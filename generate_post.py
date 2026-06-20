#!/usr/bin/env python3
"""
LayerCrafters Daily Post Generator -- v2
Outputs a JSON payload to stdout with:
  - caption           Instagram caption body (NO hashtags in caption)
  - first_comment     Hashtags only -- post as first comment on Instagram
  - facebook_copy     Caption + hashtags combined (for Facebook)
  - pinterest_copy    Keyword-rich Pinterest pin description
  - image_path        Local file path
  - image_url         CDN URL (if --upload flag used)
  - theme, product, date, weekday

Changes from v1:
  - Hashtags moved to first_comment (Instagram best practice)
  - Post-history awareness: last 7 posts injected into prompt to avoid repeating angles
  - Smart hitch cover rotation by last-used date (no index drift on errors)
  - Pinterest copy generated as separate output field
  - Sunday engagement posts use real feed Q&A format (not fake poll)
  - Log entries older than 90 days auto-archived to social_log_archive.json
  - Graceful fallback on missing product (no hard exit)
  - Uses claude-sonnet-4-6 for better copy quality
  - Seasonal context injected into prompts
"""

import os
import sys
import json
import datetime
import random
import re
import subprocess
import argparse
from pathlib import Path
from openai import OpenAI

# Config
BASE_DIR = Path("/home/ubuntu/layercrafters_social")
IMAGE_DIR = Path("/home/ubuntu/layercrafters_images")
CATALOG_PATH = IMAGE_DIR / "catalog.json"
LOG_PATH = BASE_DIR / "social_log.json"
LOG_ARCHIVE_PATH = BASE_DIR / "social_log_archive.json"
DRAFT_DIR = BASE_DIR / "drafts"
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

SHOP_URL = "https://www.etsy.com/shop/layercrafters3d"
LOG_RETENTION_DAYS = 90

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

def get_season(month):
    if month in (12, 1, 2): return "winter"
    if month in (3, 4, 5):  return "spring"
    if month in (6, 7, 8):  return "summer"
    return "fall"

def load_log():
    if LOG_PATH.exists():
        with open(LOG_PATH) as f:
            return json.load(f)
    return {"posts": [], "hitch_last_used": {}}

def save_log(log):
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

def archive_old_entries(log):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=LOG_RETENTION_DAYS)).strftime("%Y-%m-%d")
    keep = [p for p in log.get("posts", []) if p.get("date", "9999") >= cutoff]
    old  = [p for p in log.get("posts", []) if p.get("date", "9999") <  cutoff]
    if old:
        archive = {"posts": []}
        if LOG_ARCHIVE_PATH.exists():
            with open(LOG_ARCHIVE_PATH) as f:
                archive = json.load(f)
        archive["posts"].extend(old)
        with open(LOG_ARCHIVE_PATH, "w") as f:
            json.dump(archive, f, indent=2)
        log["posts"] = keep
    return log

def get_recent_post_summary(log, n=7):
    recent = log.get("posts", [])[-n:]
    if not recent:
        return "No recent posts on record."
    lines = []
    for p in recent:
        preview = p.get("caption_preview", "")[:80]
        lines.append(
            f"- {p.get('date','?')} ({p.get('weekday','?')}): "
            f"{p.get('theme','?')} -- {p.get('product','?')} -- \"{preview}\""
        )
    return "\n".join(lines)

def load_catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)

def get_product_by_slug(catalog, slug):
    for cat in catalog.values():
        for item in cat:
            if item["slug"] == slug:
                return item
    return None

def get_random_product(catalog, category, exclude_slugs=None):
    items = catalog.get(category, [])
    if exclude_slugs:
        filtered = [i for i in items if i["slug"] not in exclude_slugs]
        items = filtered if filtered else items
    return random.choice(items) if items else None

def pick_hitch_cover(catalog, log):
    last_used = log.get("hitch_last_used", {})
    def last_used_date(slug):
        return last_used.get(slug, "1970-01-01")
    slug = min(HITCH_COVER_ROTATION, key=last_used_date)
    product = get_product_by_slug(catalog, slug)
    if not product:
        recently_used = sorted(last_used, key=last_used.get, reverse=True)[:3]
        product = get_random_product(catalog, "hitch_covers", exclude_slugs=recently_used)
        slug = product["slug"] if product else None
    return product, slug

def pick_product(theme, catalog, log):
    if theme in (
        "bestseller_spotlight", "vehicle_model_specific",
        "problem_solution", "garage_truck_lifestyle",
        "engagement_poll", "behind_the_scenes",
    ):
        return pick_hitch_cover(catalog, log)
    elif theme == "shopvac_product":
        product = (
            get_random_product(catalog, "shopvac") or
            get_random_product(catalog, "utility")
        )
        return product, (product["slug"] if product else None)
    return pick_hitch_cover(catalog, log)

PRODUCT_TRUTH = """
PRODUCT TRUTH (always apply, no exceptions):
- Hitch covers are 3D-printed inserts that slide into the 2-inch or 2.5-inch receiver opening on a truck hitch.
- They fill the open hole so the hitch looks clean and finished instead of bare.
- That is ALL they do. Cosmetic/appearance product only.
- NEVER claim they protect against rust, corrosion, dirt, or physical damage.
- NEVER say officially licensed.
- NEVER invent compatibility claims.
- Accurate benefits: fills the open receiver, looks clean/finished, model-specific fit, made in the USA.
"""

CAPTION_RULES = """
OUTPUT FORMAT (follow exactly):
- Write the caption body first. No hashtags in the caption body.
- Then output a line that says exactly: HASHTAGS:
- Then output 6-10 relevant hashtags on that same line after the colon.

STYLE RULES:
- Practical, direct voice. No hype. No Elevate your openers. No cheesy AI language.
- 2-3 sentences max for the caption body.
- Maximum 2 emojis total across the entire output.
- Light CTA: link in bio or find it on Etsy -- no exclamation marks.
- Mix broad and niche hashtags. Include vehicle name when relevant.
- NEVER use the words "3D printed", "3D-printed", "3D printing", or any variation. Do not mention how the product is made. Focus on what it does and that it is made in the USA.
"""

THEME_PROMPTS = {
    "bestseller_spotlight": """{product_truth}
Today is Monday -- Bestseller Spotlight.
Product: {model}
Etsy listing: {listing_url}
Season: {season}
Write an Instagram caption spotlighting this as a top seller. Lead with what makes it popular -- the clean, finished look it gives a specific truck model. Do not lead with a question.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "vehicle_model_specific": """{product_truth}
Today is Tuesday -- Vehicle/Model-Specific Post.
Product: {model} Hitch Cover
Etsy listing: {listing_url}
Season: {season}
Speak directly to owners of this specific truck. Make it feel like it was made for them -- because it was.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "behind_the_scenes": """{product_truth}
Today is Wednesday -- Behind-the-Scenes.
Season: {season}
Do NOT promote a specific product today. Focus on the LayerCrafters print farm -- machines running, parts coming off the bed, the small-business maker reality. Authentic, not polished.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "problem_solution": """{product_truth}
Today is Thursday -- Problem/Solution.
Product: {model}
Etsy listing: {listing_url}
Lead with the real problem: the open receiver hole looks unfinished and bare when the hitch is not in use.
Follow with the solution: this insert fills it and the hitch looks clean.
Keep it simple. No drama.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "garage_truck_lifestyle": """{product_truth}
Today is Friday -- Garage/Truck Lifestyle.
Product: {model}
Etsy listing: {listing_url}
Season: {season}
Friday energy -- speak to truck owners and garage people who care about the details. Weekend tone. Make it feel like something a truck guy would actually say, not a marketing line.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "shopvac_product": """{product_truth}
Today is Saturday -- Shop-Vac / Dust Collection Product.
Product: {model}
Etsy listing: {listing_url}
Speak to woodworkers, makers, and workshop people. Describe only what this product actually does. Do not invent benefits.
{caption_rules}
Recent posts (avoid repeating these angles or phrases):
{recent_posts}""",

    "engagement_poll": """{product_truth}
Today is Sunday -- Engagement Post.
This is a FEED POST, not a Story. There is no poll feature. Write a direct question that invites real comments.
Good formats: Ford or Chevy -- go. / What is actually in your truck bed right now? / Which model should we do next?
Do NOT mention a specific product or Etsy link. No sales pitch today.
Rules:
- One direct question. One sentence of setup at most.
- Truck/garage/maker community focused.
- Maximum 2 emojis total.
- Then output: HASHTAGS: followed by 6-8 community-focused hashtags.
Recent posts (avoid repeating these questions or angles):
{recent_posts}""",
}

PINTEREST_PROMPT = """{product_truth}
Write a Pinterest pin description for this LayerCrafters product.
Product: {model}
Etsy listing: {listing_url}
Pinterest descriptions are keyword-rich and informative -- discovery text, not Instagram captions.
Include: what the product is, which truck it fits, that it is made in the USA, relevant keywords woven naturally. Do not use the words 3D printed or 3D printing.
End with the Etsy listing URL on its own line.
Length: 2-3 sentences + URL. No hashtags. No emojis. No hype. No protection claims."""


def parse_caption_and_hashtags(raw):
    raw = re.sub(r'^\*{0,2}Caption:\*{0,2}\s*', '', raw, flags=re.IGNORECASE).strip()
    if re.search(r'HASHTAGS:', raw, re.IGNORECASE):
        parts = re.split(r'HASHTAGS:\s*', raw, flags=re.IGNORECASE, maxsplit=1)
        return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
    lines = raw.strip().split("\n")
    hash_lines, body_lines, in_hashtags = [], [], False
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("#") or (in_hashtags and stripped.startswith("#")):
            hash_lines.insert(0, stripped)
            in_hashtags = True
        else:
            body_lines.insert(0, stripped)
            in_hashtags = False
    return "\n".join(l for l in body_lines if l).strip(), " ".join(hash_lines).strip()


def get_now():
    try:
        import pytz
        return datetime.datetime.now(pytz.timezone("America/Chicago"))
    except ImportError:
        return datetime.datetime.utcnow() - datetime.timedelta(hours=5)


def generate_caption(theme, product, log):
    client = OpenAI()
    model_name  = product["model"] if product else "LayerCrafters Hitch Cover"
    listing_url = product.get("listing_url", SHOP_URL) if product else SHOP_URL
    prompt = THEME_PROMPTS.get(theme, THEME_PROMPTS["bestseller_spotlight"]).format(
        model=model_name, listing_url=listing_url, season=get_season(get_now().month),
        recent_posts=get_recent_post_summary(log),
        product_truth=PRODUCT_TRUTH, caption_rules=CAPTION_RULES,
    )
    response = client.chat.completions.create(
        model="claude-sonnet-4-6",
        messages=[
            {"role": "system", "content": "You are a social media copywriter for LayerCrafters, a small American 3D printing business. Write practical, direct copy. No hype. No AI language. Follow the output format exactly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8, max_tokens=500,
    )
    return parse_caption_and_hashtags(response.choices[0].message.content.strip())


def generate_pinterest_copy(product):
    if not product:
        return ""
    client = OpenAI()
    prompt = PINTEREST_PROMPT.format(
        model=product["model"],
        listing_url=product.get("listing_url", SHOP_URL),
        product_truth=PRODUCT_TRUTH,
    )
    response = client.chat.completions.create(
        model="claude-sonnet-4-6",
        messages=[
            {"role": "system", "content": "You write Pinterest pin descriptions. Keyword-rich, informative, no hype."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6, max_tokens=200,
    )
    return response.choices[0].message.content.strip()


def prepare_image_for_instagram(image_path):
    from PIL import Image as _Image
    img = _Image.open(image_path)
    w, h = img.size
    ratio = w / h
    if 0.8 <= ratio <= 1.91:
        return image_path
    target_ratio = 4 / 5
    new_w, new_h = w, int(w / target_ratio)
    if new_h > h:
        new_h, new_w = h, int(h * target_ratio)
    left, top = (w - new_w) // 2, (h - new_h) // 2
    cropped = img.crop((left, top, left + new_w, top + new_h))
    out_path = re.sub(r'\.(jpg|jpeg|png)$', r'_ig.\1', str(image_path), flags=re.IGNORECASE)
    cropped.save(out_path, "JPEG", quality=92)
    return out_path


def upload_image(image_path):
    image_path = prepare_image_for_instagram(image_path)
    result = subprocess.run(["manus-upload-file", str(image_path)], capture_output=True, text=True, timeout=120)
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
        if line.strip().startswith("https://"):
            return line.strip()
    raise RuntimeError(f"Could not parse upload URL from output: {output[:500]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--log-result", type=str)
    args = parser.parse_args()

    if args.log_result:
        try:
            result_data = json.loads(args.log_result)
            log = load_log()
            if log.get("posts"):
                log["posts"][-1].update(result_data)
                save_log(log)
                print(json.dumps({"status": "logged", "updated": log["posts"][-1]}))
            else:
                print(json.dumps({"status": "no_posts_to_update"}))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
        return

    now       = get_now()
    today_str = now.strftime("%Y-%m-%d")
    theme     = WEEKLY_THEME[now.weekday()]
    catalog   = load_catalog()
    log       = archive_old_entries(load_log())

    product, slug = pick_product(theme, catalog, log)
    if not product:
        product = get_random_product(catalog, "hitch_covers")
        slug = product["slug"] if product else None
        if not product:
            print(json.dumps({"error": "No products available in catalog"}), file=sys.stderr)
            sys.exit(1)

    if slug and theme != "shopvac_product":
        log.setdefault("hitch_last_used", {})[slug] = today_str

    caption_body, hashtags = generate_caption(theme, product, log)

    pinterest_copy = ""
    if theme not in ("engagement_poll", "behind_the_scenes"):
        try:
            pinterest_copy = generate_pinterest_copy(product)
        except Exception:
            pass

    facebook_copy = f"{caption_body}\n\n{hashtags}" if hashtags else caption_body

    draft_path = str(DRAFT_DIR / f"{today_str}_{theme}.txt")
    with open(draft_path, "w") as f:
        f.write(f"Date: {today_str}\nTheme: {theme}\nProduct: {product['model']}\n\n")
        f.write(f"=== INSTAGRAM CAPTION ===\n{caption_body}\n\n")
        f.write(f"=== FIRST COMMENT (hashtags) ===\n{hashtags}\n\n")
        f.write(f"=== FACEBOOK COPY ===\n{facebook_copy}\n\n")
        if pinterest_copy:
            f.write(f"=== PINTEREST COPY ===\n{pinterest_copy}\n")

    payload = {
        "date": today_str, "weekday": now.strftime("%A"), "theme": theme,
        "product": product["model"], "slug": product["slug"], "category": product["category"],
        "image_path": product["image_path"], "listing_url": product.get("listing_url", SHOP_URL),
        "caption": caption_body, "first_comment": hashtags,
        "facebook_copy": facebook_copy, "pinterest_copy": pinterest_copy,
        "draft_path": draft_path,
        "instagram_status": "pending", "facebook_email_status": "pending", "pinterest_email_status": "pending",
    }

    if args.upload:
        try:
            payload["image_url"] = upload_image(product["image_path"])
        except Exception as e:
            payload["upload_error"] = str(e)

    log.setdefault("posts", []).append({
        "date": today_str, "timestamp": now.isoformat(), "weekday": now.strftime("%A"),
        "theme": theme, "product": product["model"], "slug": product["slug"],
        "image_path": product["image_path"], "caption_preview": caption_body[:200],
        "instagram_status": "pending", "facebook_email_status": "pending",
        "pinterest_email_status": "pending", "draft_path": draft_path,
    })
    save_log(log)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
