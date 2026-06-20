#!/usr/bin/env python3
"""
LayerCrafters Daily Post Generator
Outputs a JSON payload to stdout with:
  - caption (ready to publish)
  - image_path (local file path)
  - image_url (after upload, if --upload flag used)
  - theme, product, date, weekday

The Manus scheduled task agent reads this output and:
1. Uploads the image via manus-upload-file
2. Publishes to Instagram via MCP create_instagram
3. Sends Facebook-ready email via Gmail MCP gmail_send_messages
4. Logs the result
"""

import os
import sys
import json
import datetime
import random
import re
import subprocess
from pathlib import Path
from openai import OpenAI

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
BASE_DIR     = Path("/home/ubuntu/layercrafters_social")
IMAGE_DIR    = Path("/home/ubuntu/layercrafters_images")
CATALOG_PATH = IMAGE_DIR / "catalog.json"
LOG_PATH     = BASE_DIR / "social_log.json"
DRAFT_DIR    = BASE_DIR / "drafts"
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

SHOP_URL     = "https://www.etsy.com/shop/layercrafters3d"

# Weekly content rotation (0=Mon … 6=Sun)
WEEKLY_THEME = {
    0: "bestseller_spotlight",
    1: "vehicle_model_specific",
    2: "behind_the_scenes",
    3: "problem_solution",
    4: "garage_truck_lifestyle",
    5: "shopvac_product",
    6: "engagement_poll",
}

HITCH_COVER_ROTATION = [
    "ford_tremor", "ford_ranger", "ford_bronco", "ford_raptor_r",
    "chevy_trail_boss", "chevy_zr2", "chevy_rst",
    "gmc_at4", "gmc_denali", "dodge_trx", "z71",
    "f150_off_road", "ford_explorer_st",
]

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def load_catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)

def load_log():
    if LOG_PATH.exists():
        with open(LOG_PATH) as f:
            return json.load(f)
    return {"posts": [], "last_hitch_index": 0}

def save_log(log):
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

def get_product_by_slug(catalog, slug):
    for cat in catalog.values():
        for item in cat:
            if item["slug"] == slug:
                return item
    return None

def get_random_product(catalog, category):
    items = catalog.get(category, [])
    return random.choice(items) if items else None

def pick_product(theme, catalog, log):
    if theme in ("bestseller_spotlight", "vehicle_model_specific",
                 "behind_the_scenes", "problem_solution", "garage_truck_lifestyle"):
        idx = log.get("last_hitch_index", 0) % len(HITCH_COVER_ROTATION)
        slug = HITCH_COVER_ROTATION[idx]
        log["last_hitch_index"] = idx + 1
        product = get_product_by_slug(catalog, slug) or get_random_product(catalog, "hitch_covers")
        return product
    elif theme == "shopvac_product":
        return get_random_product(catalog, "shopvac") or get_random_product(catalog, "utility")
    elif theme == "engagement_poll":
        return get_random_product(catalog, "hitch_covers")
    return get_random_product(catalog, "hitch_covers")

# ─────────────────────────────────────────────
# Caption Generation
# ─────────────────────────────────────────────
# PRODUCT TRUTH: Hitch covers insert into the receiver opening and fill it so it looks clean and finished.
# They do NOT protect against rust, corrosion, or physical damage. Do NOT claim any protective function.
# Accurate benefits: fills the open receiver, looks clean/finished, model-specific fit, 3D printed in the USA.

THEME_PROMPTS = {
    "bestseller_spotlight": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Monday — Best-Selling Hitch Cover Spotlight.
Product: {model}
Etsy listing: {listing_url}

What the product actually is: A 3D-printed insert that slides into the 2-inch or 2.5-inch receiver opening on a truck hitch. It fills the open hole so the hitch looks clean and finished instead of bare. That is all it does — it is a cosmetic/appearance product, not a protective one.

Rules:
- Practical, direct voice. No hype. No cheesy AI language.
- 2-3 short sentences max.
- Focus only on accurate benefits: fills the receiver opening, looks clean and finished, model-specific design, made in the USA.
- NEVER claim it protects against rust, corrosion, dirt, or damage. It does not do any of those things.
- Light call to action (link in bio, or "find it on Etsy").
- 5-8 relevant hashtags on a separate line.
- Do not mention "officially licensed."
- Do not use more than 2 emojis total.""",

    "vehicle_model_specific": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Tuesday — Vehicle/Model-Specific Post.
Product: {model} Hitch Cover
Etsy listing: {listing_url}

What the product actually is: A 3D-printed insert that slides into the receiver opening on a truck hitch. It fills the open hole so the hitch looks clean and finished. Cosmetic product only — it does not protect against rust, corrosion, or damage.

Rules:
- Speak directly to owners of that specific truck/vehicle.
- Practical, direct voice. No hype. No cheesy AI language.
- 2-3 short sentences max.
- Accurate benefits only: fills the open receiver, looks clean and finished, designed for that specific model, made in the USA.
- NEVER say it protects, guards, shields, or prevents rust or corrosion.
- Light call to action.
- 5-8 relevant hashtags on a separate line (include the vehicle name as a hashtag).
- Do not mention "officially licensed."
- Do not use more than 2 emojis total.""",

    "behind_the_scenes": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Wednesday — Behind-the-Scenes 3D Printing.
Context: Show the print farm in action, printing hitch covers and accessories.

Rules:
- Authentic, maker-business tone.
- Talk about the process, not just the product.
- 2-3 short sentences max.
- Light call to action (shop link in bio).
- 5-8 relevant hashtags on a separate line.
- Do not use more than 2 emojis total.
- No fake hype.""",

    "problem_solution": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Thursday — Problem/Solution Post.
Product: {model}
Etsy listing: {listing_url}

What the product actually is: A 3D-printed insert that slides into the receiver opening on a truck hitch. It fills the open hole so the hitch looks clean and finished instead of bare. Cosmetic product only.

The real problem to lead with: The open receiver hole on a truck hitch looks unfinished and bare when not in use. The solution: this insert fills it and gives it a clean, finished look.

Rules:
- Lead with the problem (bare/open receiver looks unfinished).
- Follow with the solution (this insert fills it and looks clean).
- Practical, direct voice. No hype.
- 2-3 short sentences max.
- NEVER claim it protects against rust, corrosion, dirt, or damage. It is cosmetic only.
- Light call to action.
- 5-8 relevant hashtags on a separate line.
- Do not use more than 2 emojis total.""",

    "garage_truck_lifestyle": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Friday — Garage/Truck Lifestyle Post.
Product: {model}
Etsy listing: {listing_url}

What the product actually is: A 3D-printed insert that slides into the receiver opening on a truck hitch. Fills the open hole so the hitch looks clean and finished. Cosmetic product — does not protect against rust, corrosion, or damage.

Rules:
- Speak to truck owners and garage/workshop enthusiasts.
- Weekend/Friday energy — practical, not hype.
- 2-3 short sentences max.
- Accurate benefits only: fills the receiver opening, looks clean, model-specific design, made in the USA.
- NEVER claim it protects, guards, or prevents anything.
- Light call to action.
- 5-8 relevant hashtags on a separate line.
- Do not use more than 2 emojis total.""",

    "shopvac_product": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Saturday — Shop-Vac / Dust Collection Product.
Product: {model}
Etsy listing: {listing_url}

Rules:
- Speak to woodworkers, makers, and workshop owners.
- Practical, direct voice. No hype.
- 2-3 short sentences max.
- Only describe what the product actually does — do not invent benefits.
- Light call to action.
- 5-8 relevant hashtags on a separate line.
- Do not make claims that are not true.
- Do not use more than 2 emojis total.""",

    "engagement_poll": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Sunday — Engagement/Poll Post.
Context: Ask followers a question related to trucks, garages, or 3D printing.
Example questions: "Ford or Chevy?" / "What's in your garage?" / "Which hitch cover is your favorite?"

Rules:
- Ask one simple, direct question.
- Keep it truck/garage/maker focused.
- 2-3 short sentences max.
- No sales pitch needed today.
- Do not make any product claims.
- 5-8 relevant hashtags on a separate line.
- Do not use more than 2 emojis total.
- No political content.""",
}

def generate_caption(theme, product):
    client = OpenAI()
    model_name  = product["model"] if product else "LayerCrafters Hitch Cover"
    listing_url = product.get("listing_url", SHOP_URL) if product else SHOP_URL
    prompt = THEME_PROMPTS.get(theme, THEME_PROMPTS["bestseller_spotlight"]).format(
        model=model_name, listing_url=listing_url
    )
    response = client.chat.completions.create(
        model="claude-haiku-4-5",
        messages=[
            {"role": "system", "content": "You are a social media copywriter for LayerCrafters, a small American 3D printing business. Write practical, direct copy with no hype and no cheesy AI language."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=400,
    )
    raw = response.choices[0].message.content.strip()
    # Strip any AI label artifacts the model may prepend (e.g. "**Caption:**", "Caption:")
    import re as _re
    raw = _re.sub(r'^\*{0,2}Caption:\*{0,2}\s*', '', raw, flags=_re.IGNORECASE).strip()
    return raw

# ─────────────────────────────────────────────
# Upload helper (optional --upload flag)
# ─────────────────────────────────────────────
def prepare_image_for_instagram(image_path):
    """Ensure image aspect ratio is within Instagram's supported range (4:5 to 1.91:1).
    If outside range, center-crop to 4:5 portrait. Returns path to use for upload."""
    from PIL import Image as _Image
    img = _Image.open(image_path)
    w, h = img.size
    ratio = w / h
    # Instagram supports 0.8 (4:5) to 1.91:1
    if 0.8 <= ratio <= 1.91:
        return image_path  # already valid
    # Crop to 4:5 portrait (safest universal ratio)
    target_ratio = 4 / 5
    new_w = w
    new_h = int(new_w / target_ratio)
    if new_h > h:
        new_h = h
        new_w = int(new_h * target_ratio)
    left = (w - new_w) // 2
    top = (h - new_h) // 2
    cropped = img.crop((left, top, left + new_w, top + new_h))
    out_path = str(image_path).replace('.jpg', '_ig.jpg').replace('.png', '_ig.png')
    cropped.save(out_path, 'JPEG', quality=92)
    return out_path

def upload_image(image_path):
    image_path = prepare_image_for_instagram(image_path)
    result = subprocess.run(
        ["manus-upload-file", str(image_path)],
        capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr
    for line in output.split("\n"):
        line = line.strip()
        if "CDN URL:" in line:
            url = line.split("CDN URL:", 1)[1].strip()
            if url.startswith("http"):
                return url
        if line.startswith("https://files.manuscdn.com") or line.startswith("https://cdn."):
            return line
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("https://"):
            return line
    raise RuntimeError(f"Could not parse upload URL from: {output[:500]}")

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help="Also upload image and include CDN URL")
    parser.add_argument("--log-result", type=str, help="JSON string with instagram_status and fb_status to log")
    args = parser.parse_args()

    # If logging a result from a previous run
    if args.log_result:
        try:
            result_data = json.loads(args.log_result)
            log = load_log()
            if log.get("posts"):
                last = log["posts"][-1]
                last.update(result_data)
                save_log(log)
                print(json.dumps({"status": "logged", "updated": last}))
            else:
                print(json.dumps({"status": "no_posts_to_update"}))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
        return

    # Determine today's theme
    try:
        import pytz
        tz = pytz.timezone("America/Chicago")
        now = datetime.datetime.now(tz)
    except ImportError:
        now = datetime.datetime.utcnow() - datetime.timedelta(hours=5)  # CST fallback

    today_str = now.strftime("%Y-%m-%d")
    weekday   = now.weekday()
    theme     = WEEKLY_THEME[weekday]

    # Load catalog and log
    catalog = load_catalog()
    log     = load_log()

    # Pick product
    product = pick_product(theme, catalog, log)
    if not product:
        print(json.dumps({"error": "No product found for theme: " + theme}), file=sys.stderr)
        sys.exit(1)

    # Generate caption
    caption = generate_caption(theme, product)

    # Save draft
    draft_path = str(DRAFT_DIR / f"{today_str}_{theme}.txt")
    with open(draft_path, "w") as f:
        f.write(f"Date: {today_str}\nTheme: {theme}\nProduct: {product['model']}\n\n{caption}")

    # Build output payload
    payload = {
        "date":        today_str,
        "weekday":     now.strftime("%A"),
        "theme":       theme,
        "product":     product["model"],
        "slug":        product["slug"],
        "category":    product["category"],
        "image_path":  product["image_path"],
        "listing_url": product.get("listing_url", SHOP_URL),
        "caption":     caption,
        "draft_path":  draft_path,
        "instagram_status": "pending",
        "facebook_email_status": "pending",
    }

    # Optionally upload image
    if args.upload:
        try:
            image_url = upload_image(product["image_path"])
            payload["image_url"] = image_url
        except Exception as e:
            payload["upload_error"] = str(e)

    # Log the pending post
    log.setdefault("posts", []).append({
        "date":      today_str,
        "timestamp": now.isoformat(),
        "weekday":   now.strftime("%A"),
        "theme":     theme,
        "product":   product["model"],
        "slug":      product["slug"],
        "image_path": product["image_path"],
        "caption_preview": caption[:200],
        "instagram_status": "pending",
        "facebook_email_status": "pending",
        "draft_path": draft_path,
    })
    save_log(log)

    # Output JSON for the agent
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
