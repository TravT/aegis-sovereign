#!/usr/bin/env python3
"""
Corpus & Multimodal Asset Ingestion Script for Aegis Sovereign Appliance Benchmark.
Downloads:
1. Lewis Carroll's Alice's Adventures in Wonderland text from Project Gutenberg.
2. High-resolution public domain John Tenniel illustrations (Gutenberg #114).
3. Converts GIF illustrations to clean PNGs and writes an image metadata manifest.
"""

import io
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from PIL import Image

CORPUS_URL = "https://www.gutenberg.org/files/11/11-0.txt"
BASE_IMG_URL = "https://www.gutenberg.org/files/114/114-h/images/"

BENCHMARK_DIR = Path(__file__).resolve().parent
DATA_DIR = BENCHMARK_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"

# Target Tenniel illustrations including mandatory ones and query targets
TARGET_IMAGES = [
    {
        "file": "alice01a.gif",
        "title": "Frontispiece: King and Queen Inspecting Tart",
        "description": "King and Queen of Hearts on throne inspecting tart in courtroom with White Rabbit herald",
        "chapter": 11,
        "tags": ["courtroom", "king of hearts", "queen of hearts", "tarts", "herald", "trial"]
    },
    {
        "file": "alice02a.gif",
        "title": "White Rabbit Checking Pocket Watch",
        "description": "White Rabbit wearing waistcoat looking at pocket watch while hurrying past Alice",
        "chapter": 1,
        "tags": ["white rabbit", "waistcoat", "pocket watch", "rabbit hole", "hurrying"]
    },
    {
        "file": "alice04a.gif",
        "title": "Alice with Drink Me Bottle",
        "description": "Alice holding and examining the glass bottle with printed label DRINK ME",
        "chapter": 1,
        "tags": ["alice", "drink me", "bottle", "table", "shrink"]
    },
    {
        "file": "alice11a.gif",
        "title": "Alice Cramped in the White Rabbit's House",
        "description": "Alice grown giant, cramped inside the White Rabbit's house with an arm out the window and leg up the chimney",
        "chapter": 4,
        "tags": ["alice", "white rabbit house", "giant", "cramped", "window", "growth"]
    },
    {
        "file": "alice15a.gif",
        "title": "Caterpillar on Mushroom Smoking Hookah",
        "description": "Caterpillar sitting atop a large mushroom smoking a long hookah pipe looking at Alice",
        "chapter": 5,
        "tags": ["caterpillar", "mushroom", "smoking pipe", "hookah", "advice"]
    },
    {
        "file": "alice21a.gif",
        "title": "Duchess Kitchen with Cook, Baby, and Cheshire Cat",
        "description": "Cook stirring pepper cauldron, Duchess nursing screaming baby, Cheshire Cat grinning on hearth",
        "chapter": 6,
        "tags": ["duchess", "kitchen", "cook", "pepper", "cheshire cat", "baby", "pig"]
    },
    {
        "file": "alice24a.gif",
        "title": "Cheshire Cat in Tree Fading to Smile",
        "description": "Cheshire Cat perching on a bough of a tree smiling mysteriously as its body fades",
        "chapter": 6,
        "tags": ["cheshire cat", "tree", "grin", "smiling cat", "branch", "fading"]
    },
    {
        "file": "alice25a.gif",
        "title": "The Mad Tea Party",
        "description": "The Mad Hatter, March Hare, and Dormouse crowded together having tea under a tree with Alice",
        "chapter": 7,
        "tags": ["mad hatter", "march hare", "dormouse", "mad tea party", "tea table", "cups"]
    },
    {
        "file": "alice29a.gif",
        "title": "Queen of Hearts Shouting 'Off With Her Head!'",
        "description": "Furious Queen of Hearts shouting 'Off with her head!' and pointing finger at Alice in croquet ground",
        "chapter": 8,
        "tags": ["queen of hearts", "off with her head", "croquet ground", "cards", "king of hearts"]
    }
]


def download_text():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    alice_path = DATA_DIR / "alice.txt"
    if alice_path.exists() and alice_path.stat().st_size > 10000:
        print(f"[Corpus] {alice_path} already exists ({alice_path.stat().st_size} bytes).")
        return alice_path

    print(f"[Corpus] Downloading {CORPUS_URL}...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AegisBenchmark/1.0"}
    req = urllib.request.Request(CORPUS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8-sig", errors="ignore")

    # Clean Gutenberg preamble and license trailer if present
    start_match = re.search(r"\*\*\* START OF THE PROJECT GUTENBERG EBOOK.*?\*\*\*", content)
    end_match = re.search(r"\*\*\* END OF THE PROJECT GUTENBERG EBOOK.*?\*\*\*", content)

    if start_match and end_match:
        content = content[start_match.end():end_match.start()].strip()
    elif start_match:
        content = content[start_match.end():].strip()

    with open(alice_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[Corpus] Saved clean book text to {alice_path} ({len(content)} characters).")
    return alice_path


def download_images():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AegisBenchmark/1.0"}
    manifest = []

    print(f"[Images] Ingesting {len(TARGET_IMAGES)} Tenniel illustrations...")
    for item in TARGET_IMAGES:
        gif_name = item["file"]
        stem = Path(gif_name).stem
        png_name = f"{stem}.png"
        png_path = IMAGES_DIR / png_name
        
        img_url = f"{BASE_IMG_URL}{gif_name}"
        try:
            req = urllib.request.Request(img_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()

            # Open with Pillow and convert to clean RGB PNG
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            img.save(png_path, "PNG", optimize=True)

            meta = {
                "id": stem,
                "file_name": png_name,
                "path": str(png_path),
                "title": item["title"],
                "description": item["description"],
                "chapter": item["chapter"],
                "tags": item["tags"],
                "width": img.width,
                "height": img.height,
                "source_url": img_url
            }
            manifest.append(meta)
            print(f"  -> Converted {gif_name} -> {png_name} ({img.width}x{img.height})")
        except Exception as e:
            print(f"  [ERROR] Failed to fetch/convert {gif_name}: {e}")

    manifest_path = IMAGES_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[Images] Saved image manifest to {manifest_path} ({len(manifest)} images).")
    return manifest


if __name__ == "__main__":
    download_text()
    download_images()
