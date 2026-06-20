# LayerCrafters Social Media Automation

Automated daily social media posting system for [LayerCrafters](https://layercrafters3d.com) — a 3D printing business selling vehicle, garage, and workshop accessories on Etsy, Amazon, and Shopify.

## What It Does

- Runs daily at **7:00 AM Central Time** via Manus scheduled task
- Generates an on-brand caption using AI (Claude via Manus LLM proxy)
- Selects a real product image from the local image library (no AI-generated images)
- Publishes directly to **Instagram** via MCP connector
- Sends a **Facebook-ready draft** to piersm2@gmail.com for manual posting
- Logs every post to `social_log.json`
- Sends a **weekly summary report** every Sunday night

## Weekly Content Rotation

| Day | Theme |
| :-- | :---- |
| Monday | Bestseller Spotlight |
| Tuesday | Vehicle Model Specific |
| Wednesday | Behind-the-Scenes 3D Printing |
| Thursday | Problem / Solution |
| Friday | Garage / Truck Lifestyle |
| Saturday | Shop-Vac / Dust Collection Product |
| Sunday | Poll / Engagement Post |

## Hitch Cover Model Rotation

Ford Tremor → Ford Ranger → Ford Bronco → Ford Raptor R → Chevy Trail Boss → Chevy ZR2 → Chevy RST → GMC AT4 → GMC Denali → Dodge TRX → Z71 → F150 Off Road → Ford Explorer ST → 2-inch receiver → 2.5-inch receiver

## Key Files

| File | Purpose |
| :--- | :------ |
| `generate_post.py` | Main script — content generation, image selection, upload, logging |
| `daily_post.py` | Earlier iteration (superseded by generate_post.py) |
| `schedule_playbook.txt` | Instructions stored in the Manus scheduled task |
| `social_log.json` | Running log of every post published |
| `drafts/` | Per-day draft text files |

## Brand Rules (Enforced in Prompts)

- Hitch covers are **cosmetic only** — they fill the open receiver hole and improve appearance
- No protection, rust, corrosion, or weatherproofing claims
- No "officially licensed" language
- No false compatibility claims
- No AI-generated images — real product photos only
- Practical, direct voice — no hype, no cheesy AI language

## Image Library

Product images are stored in `/home/ubuntu/layercrafters_images/` (not tracked in this repo — sourced from Etsy listings).

```
layercrafters_images/
├── hitch_covers/       # 13 model-specific hitch cover images
├── shopvac/            # Shop-vac and dust collection accessories
├── utility/            # Razor blade holders, diffusers, etc.
├── behind_scenes/      # Print farm / behind-the-scenes images
└── catalog.json        # Product metadata and listing URLs
```

## Dependencies

- Python 3.11+
- `openai` (Manus proxy, pre-configured)
- `pillow` (image aspect ratio correction)
- `pytz` (timezone handling)
- Manus MCP connectors: `instagram`, `gmail`

## Running Manually

```bash
# Generate post + upload image
python3 generate_post.py --upload

# Log a result after publishing
python3 generate_post.py --log-result '{"instagram_status": "published", "instagram_permalink": "https://..."}'
```

## Notes

- The script auto-crops images to 4:5 portrait ratio if they fall outside Instagram's supported aspect ratio range (0.8–1.91)
- The AI model used is `claude-haiku-4-5` via the Manus OpenAI-compatible proxy
- MCP tool calls (`create_instagram`, `gmail_send_messages`) must be invoked via `manus-mcp-cli` from the shell — they cannot be called from within a Python subprocess
