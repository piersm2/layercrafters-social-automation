#!/usr/bin/env python3
"""
LayerCrafters Daily Social Media Automation
Runs every day at 7:00 AM Central Time.

- Generates a day-of-week-appropriate caption and hashtags using OpenAI
- Selects the correct real product image from the local library
- Publishes to Instagram via MCP
- Sends a Facebook-ready version via Gmail draft
- Logs all activity to social_log.json
"""

import os
import sys
import json
import subprocess
import datetime
import random
import re
import pytz
import requests
import shutil
from pathlib import Path
from openai import OpenAI

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
BASE_DIR        = Path("/home/ubuntu/layercrafters_social")
IMAGE_DIR       = Path("/home/ubuntu/layercrafters_images")
CATALOG_PATH    = IMAGE_DIR / "catalog.json"
LOG_PATH        = BASE_DIR / "social_log.json"
DRAFT_DIR       = BASE_DIR / "drafts"
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

CENTRAL_TZ      = pytz.timezone("America/Chicago")
SHOP_URL        = "https://www.etsy.com/shop/layercrafters3d"
GMAIL_RECIPIENT = "piersm2@gmail.com"

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

# Hitch cover rotation list (for vehicle-specific posts)
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

def pick_product_for_theme(theme, catalog, log):
    """Select the appropriate product based on today's theme."""
    if theme == "bestseller_spotlight":
        # Rotate through top hitch covers
        idx = log.get("last_hitch_index", 0) % len(HITCH_COVER_ROTATION)
        slug = HITCH_COVER_ROTATION[idx]
        log["last_hitch_index"] = idx + 1
        product = get_product_by_slug(catalog, slug)
        if not product:
            product = get_random_product(catalog, "hitch_covers")
        return product, "bestseller_spotlight"

    elif theme == "vehicle_model_specific":
        # Pick next hitch cover in rotation
        idx = log.get("last_hitch_index", 0) % len(HITCH_COVER_ROTATION)
        slug = HITCH_COVER_ROTATION[idx]
        log["last_hitch_index"] = idx + 1
        product = get_product_by_slug(catalog, slug)
        if not product:
            product = get_random_product(catalog, "hitch_covers")
        return product, "vehicle_model_specific"

    elif theme == "behind_the_scenes":
        # Use any hitch cover image for print-farm content
        product = get_random_product(catalog, "hitch_covers")
        return product, "behind_the_scenes"

    elif theme == "problem_solution":
        # Alternate between hitch covers and shop-vac
        product = get_random_product(catalog, "hitch_covers")
        return product, "problem_solution"

    elif theme == "garage_truck_lifestyle":
        product = get_random_product(catalog, "hitch_covers")
        return product, "garage_truck_lifestyle"

    elif theme == "shopvac_product":
        product = get_random_product(catalog, "shopvac")
        if not product:
            product = get_random_product(catalog, "utility")
        return product, "shopvac_product"

    elif theme == "engagement_poll":
        product = get_random_product(catalog, "hitch_covers")
        return product, "engagement_poll"

    return get_random_product(catalog, "hitch_covers"), theme

# ─────────────────────────────────────────────
# Caption Generation
# ─────────────────────────────────────────────
THEME_PROMPTS = {
    "bestseller_spotlight": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Monday — Best-Selling Hitch Cover Spotlight.
Product: {model}
Etsy listing: {listing_url}

Rules:
- Practical, direct voice. No hype. No cheesy AI language.
- 2-3 short sentences max.
- One clear benefit.
- Light call to action (link in bio, or "find it on Etsy").
- 5-8 relevant hashtags on a separate line.
- Do not make claims that are not true.
- Do not mention "officially licensed."
- Do not use more than 2 emojis total.
- Do not mention compatibility with specific vehicles unless the product name already states it.""",

    "vehicle_model_specific": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Tuesday — Vehicle/Model-Specific Post.
Product: {model} Hitch Cover
Etsy listing: {listing_url}

Rules:
- Speak directly to owners of that specific truck/vehicle.
- Practical, direct voice. No hype. No cheesy AI language.
- 2-3 short sentences max.
- One clear benefit (protects the hitch, looks clean, made in USA).
- Light call to action.
- 5-8 relevant hashtags on a separate line (include the vehicle name as a hashtag).
- Do not make claims that are not true.
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

Rules:
- Lead with the problem (dirty hitch, bare receiver, etc.).
- Follow with the solution (this product).
- Practical, direct voice. No hype.
- 2-3 short sentences max.
- Light call to action.
- 5-8 relevant hashtags on a separate line.
- Do not make claims that are not true.
- Do not use more than 2 emojis total.""",

    "garage_truck_lifestyle": """Write an Instagram caption for LayerCrafters, a small American 3D printing business.
Today is Friday — Garage/Truck Lifestyle Post.
Product: {model}
Etsy listing: {listing_url}

Rules:
- Speak to truck owners and garage/workshop enthusiasts.
- Weekend/Friday energy — practical, not hype.
- 2-3 short sentences max.
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
- One clear benefit.
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
- 5-8 relevant hashtags on a separate line.
- Do not use more than 2 emojis total.
- No political content.""",
}

def generate_caption(theme, product):
    client = OpenAI()

    model_name = product["model"] if product else "LayerCrafters Hitch Cover"
    listing_url = product.get("listing_url", SHOP_URL) if product else SHOP_URL

    prompt_template = THEME_PROMPTS.get(theme, THEME_PROMPTS["bestseller_spotlight"])
    prompt = prompt_template.format(model=model_name, listing_url=listing_url)

    response = client.chat.completions.create(
        model="claude-haiku-4-5",
        messages=[
            {"role": "system", "content": "You are a social media copywriter for LayerCrafters, a small American 3D printing business. Write practical, direct copy with no hype and no cheesy AI language."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=400,
    )
    return response.choices[0].message.content.strip()

# ─────────────────────────────────────────────
# Instagram Publishing via MCP
# ─────────────────────────────────────────────
def upload_image_for_instagram(image_path):
    """Upload image to S3 and return public URL."""
    result = subprocess.run(
        ["manus-upload-file", str(image_path)],
        capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"Upload failed: {output}")
    # Parse CDN URL from output — format: "CDN URL: https://..."
    for line in output.split("\n"):
        line = line.strip()
        if "CDN URL:" in line:
            url = line.split("CDN URL:", 1)[1].strip()
            if url.startswith("http"):
                return url
        if line.startswith("https://files.manuscdn.com") or line.startswith("https://cdn."):
            return line
    # Fallback: any https line
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("https://"):
            return line
    raise RuntimeError(f"Could not parse upload URL from: {output[:500]}")

def publish_to_instagram(image_url, caption):
    """Publish image post to Instagram via MCP."""
    payload = json.dumps({
        "type": "post",
        "caption": caption,
        "media": [{"type": "image", "media_url": image_url}]
    })
    result = subprocess.run(
        ["manus-mcp-cli", "tool", "call", "create_instagram",
         "--server", "instagram",
         "--input", payload],
        capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"Instagram publish failed: {output}")
    return output

# ─────────────────────────────────────────────
# Gmail — Facebook-Ready Draft
# ─────────────────────────────────────────────
def send_facebook_draft_email(caption, image_path, theme, product, today_str):
    """Send a Gmail with the Facebook-ready post content."""
    model_name = product["model"] if product else "LayerCrafters"
    listing_url = product.get("listing_url", SHOP_URL) if product else SHOP_URL

    subject = f"LayerCrafters Facebook Post - {today_str} ({theme.replace('_', ' ').title()})"
    body = (
        f"LayerCrafters Daily Social Post\n"
        f"Date: {today_str}\n"
        f"Theme: {theme.replace('_', ' ').title()}\n"
        f"Product: {model_name}\n\n"
        f"CAPTION (ready to paste into Facebook):\n"
        f"{caption}\n\n"
        f"PRODUCT LINK:\n"
        f"{listing_url}\n\n"
        f"IMAGE FILE:\n"
        f"{image_path}\n\n"
        f"Note: Instagram post published automatically at 7:00 AM Central.\n"
        f"Facebook: Copy caption above and attach the product image manually."
    )

    payload = json.dumps({
        "messages": [{
            "to": [GMAIL_RECIPIENT],
            "subject": subject,
            "content": body
        }]
    })
    result = subprocess.run(
        ["manus-mcp-cli", "tool", "call", "gmail_send_messages",
         "--server", "gmail",
         "--input", payload],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"Gmail send failed: {output}")
    return output

# ─────────────────────────────────────────────
# Weekly Sunday Report
# ─────────────────────────────────────────────
def send_weekly_report(log):
    """Send Sunday night weekly summary email."""
    now_ct = datetime.datetime.now(CENTRAL_TZ)
    week_start = (now_ct - datetime.timedelta(days=6)).strftime("%b %d")
    week_end = now_ct.strftime("%b %d, %Y")

    # Get this week's posts
    cutoff = (now_ct - datetime.timedelta(days=7)).isoformat()
    week_posts = [p for p in log.get("posts", []) if p.get("timestamp", "") >= cutoff]

    # Build summary
    post_lines = []
    for p in week_posts:
        post_lines.append(
            f"  {p.get('date','?')} | {p.get('theme','?').replace('_',' ').title()} | "
            f"{p.get('product','?')} | Instagram: {p.get('instagram_status','?')}"
        )
    posts_text = "\n".join(post_lines) if post_lines else "  No posts recorded this week."

    # Theme performance (simple count)
    theme_counts = {}
    for p in week_posts:
        t = p.get("theme", "unknown")
        theme_counts[t] = theme_counts.get(t, 0) + 1
    theme_text = "\n".join(f"  {t.replace('_',' ').title()}: {c} post(s)" for t, c in theme_counts.items()) or "  No data."

    subject = f"LayerCrafters Weekly Social Report — {week_start}–{week_end}"
    body = f"""LayerCrafters Weekly Social Media Report
Week: {week_start} – {week_end}

─────────────────────────────────────────
1. POSTS PUBLISHED THIS WEEK
─────────────────────────────────────────
{posts_text}

─────────────────────────────────────────
2. BEST-PERFORMING POST
─────────────────────────────────────────
Check Instagram Insights for engagement data.
(Automation does not yet pull live metrics — review manually in the Instagram app.)

─────────────────────────────────────────
3. FOLLOWER / ENGAGEMENT CHANGES
─────────────────────────────────────────
Review Instagram Insights > Audience tab for follower changes.
Review post reach and engagement in the Professional Dashboard.

─────────────────────────────────────────
4. PRODUCT THEMES THIS WEEK
─────────────────────────────────────────
{theme_text}

─────────────────────────────────────────
5. RECOMMENDED CONTENT DIRECTION — NEXT WEEK
─────────────────────────────────────────
- Continue hitch cover rotation (50% of posts).
- If shop-vac posts underperformed, test a different angle (workshop setup vs. product close-up).
- If engagement post (Sunday) got replies, follow up on Monday with related content.
- Consider adding a customer review screenshot post if new 5-star reviews came in this week.

─────────────────────────────────────────
Automation Status: Active | Next post: Tomorrow 7:00 AM Central
─────────────────────────────────────────
"""

    payload = json.dumps({
        "messages": [{
            "to": [GMAIL_RECIPIENT],
            "subject": subject,
            "content": body
        }]
    })
    result = subprocess.run(
        ["manus-mcp-cli", "tool", "call", "gmail_send_messages",
         "--server", "gmail",
         "--input", payload],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"WARNING: Weekly report email failed: {output}")
    else:
        print("Weekly report sent.")

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    now_ct = datetime.datetime.now(CENTRAL_TZ)
    today_str = now_ct.strftime("%Y-%m-%d")
    weekday  = now_ct.weekday()  # 0=Mon, 6=Sun
    theme    = WEEKLY_THEME[weekday]

    print(f"[{today_str}] LayerCrafters Daily Social Post")
    print(f"  Day: {now_ct.strftime('%A')} | Theme: {theme}")

    # Load catalog and log
    catalog = load_catalog()
    log = load_log()

    # Pick product
    product, theme = pick_product_for_theme(theme, catalog, log)
    if not product:
        print("ERROR: No product found for today's theme.")
        sys.exit(1)

    print(f"  Product: {product['model']}")
    print(f"  Image: {product['image_path']}")

    # Generate caption
    print("  Generating caption...")
    try:
        caption = generate_caption(theme, product)
        print(f"  Caption preview: {caption[:120]}...")
    except Exception as e:
        print(f"  ERROR generating caption: {e}")
        sys.exit(1)

    # Save draft locally
    draft_path = DRAFT_DIR / f"{today_str}_{theme}.txt"
    with open(draft_path, "w") as f:
        f.write(f"Date: {today_str}\nTheme: {theme}\nProduct: {product['model']}\n\n{caption}")

    # Upload image and publish to Instagram
    instagram_status = "skipped"
    try:
        print("  Uploading image...")
        image_url = upload_image_for_instagram(product["image_path"])
        print(f"  Image URL: {image_url}")

        print("  Publishing to Instagram...")
        ig_result = publish_to_instagram(image_url, caption)
        instagram_status = "published"
        print(f"  Instagram: {ig_result[:200]}")
    except Exception as e:
        instagram_status = f"error: {e}"
        print(f"  Instagram ERROR: {e}")

    # Send Facebook-ready email
    fb_status = "skipped"
    try:
        print("  Sending Facebook draft email...")
        send_facebook_draft_email(caption, product["image_path"], theme, product, today_str)
        fb_status = "sent"
        print("  Facebook email: sent")
    except Exception as e:
        fb_status = f"error: {e}"
        print(f"  Facebook email ERROR: {e}")

    # Log the post
    post_record = {
        "date": today_str,
        "timestamp": now_ct.isoformat(),
        "weekday": now_ct.strftime("%A"),
        "theme": theme,
        "product": product["model"],
        "slug": product["slug"],
        "image_path": product["image_path"],
        "caption_preview": caption[:200],
        "instagram_status": instagram_status,
        "facebook_email_status": fb_status,
        "draft_path": str(draft_path),
    }
    log.setdefault("posts", []).append(post_record)
    save_log(log)

    print(f"\n  Done. Instagram: {instagram_status} | Facebook email: {fb_status}")

    # Sunday night: send weekly report
    if weekday == 6:
        print("  Sunday — sending weekly report...")
        send_weekly_report(log)

if __name__ == "__main__":
    main()
