"""
find_exact_images.py

Usage:
  python scripts/find_exact_images.py --sample samples/arri_alexa.jpg --pages pages.txt --out matches

This script crawls a list of pages, downloads images, and matches them against a sample
using perceptual hash (pHash) and optional CLIP-like embeddings (if sentence-transformers
is installed). It is defensive: if embeddings are unavailable it still runs pHash matching.

Place sample images in `samples/` and a newline-separated list of pages in `pages.txt`.
"""
from __future__ import annotations
import os
import io
import sys
import argparse
import time
from urllib.parse import urljoin
from typing import List, Tuple

try:
    from PIL import Image
except Exception as e:
    print("Pillow is required. Install with: pip install pillow")
    raise

try:
    import imagehash
except Exception:
    print("imagehash is required. Install with: pip install ImageHash")
    raise

import requests
from bs4 import BeautifulSoup
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except Exception:
    EMBEDDING_AVAILABLE = False


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ImageFinder/1.0)"}


def download_image(url: str, timeout: int = 12) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def crawl_page_for_images(page_url: str, max_images: int = 200) -> List[str]:
    try:
        r = requests.get(page_url, timeout=10, headers=HEADERS)
        r.raise_for_status()
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    imgs: List[str] = []
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
        if not src:
            continue
        full = urljoin(page_url, src)
        imgs.append(full)
        if len(imgs) >= max_images:
            break
    return imgs


def compute_phash(img: Image.Image) -> imagehash.ImageHash:
    return imagehash.phash(img)


def hamming_dist(h1: imagehash.ImageHash, h2: imagehash.ImageHash) -> int:
    return int(h1 - h2)


class Embedder:
    def __init__(self):
        self.model = None
        if EMBEDDING_AVAILABLE:
            try:
                # Use a lightweight CLIP-like model via sentence-transformers if available
                self.model = SentenceTransformer("clip-ViT-B-32")
            except Exception:
                try:
                    self.model = SentenceTransformer("all-MiniLM-L6-v2")
                except Exception:
                    self.model = None

    def embed_pil(self, pil_img: Image.Image) -> np.ndarray | None:
        if not self.model:
            return None
        try:
            # sentence-transformers supports PIL input for some models
            emb = self.model.encode(pil_img, convert_to_numpy=True, show_progress_bar=False)
            return np.array(emb, dtype=float)
        except Exception:
            return None


def find_matches(sample_path: str, pages: List[str], out_dir: str = "matches", top_k: int = 30) -> List[Tuple[str, int, float]]:
    os.makedirs(out_dir, exist_ok=True)
    sample = Image.open(sample_path).convert("RGB")
    sample_ph = compute_phash(sample)

    embedder = Embedder()
    sample_emb = embedder.embed_pil(sample) if embedder.model else None

    results: List[Tuple[str, int, float]] = []

    for page in pages:
        print(f"Crawling: {page}")
        try:
            img_urls = crawl_page_for_images(page)
        except Exception:
            img_urls = []
        for url in img_urls:
            img = download_image(url)
            if img is None:
                continue
            try:
                ph = compute_phash(img)
            except Exception:
                continue
            dist = hamming_dist(sample_ph, ph)
            sim = -1.0
            if sample_emb is not None:
                emb = embedder.embed_pil(img)
                if emb is not None:
                    sim = float(np.dot(sample_emb, emb) / (np.linalg.norm(sample_emb) * np.linalg.norm(emb) + 1e-9))
            results.append((url, dist, sim))

    # Sort: exact phash first (dist), then higher similarity
    results.sort(key=lambda r: (r[1], -r[2]))

    # Save top_k images
    saved = 0
    for i, (url, dist, sim) in enumerate(results[:top_k]):
        img = download_image(url)
        if img is None:
            continue
        fname = f"{i:02d}_d{dist}_s{int(sim*1000) if sim>-0.5 else 0}.jpg"
        path = os.path.join(out_dir, fname)
        try:
            img.save(path, quality=90)
            saved += 1
        except Exception:
            continue

    print(f"Saved {saved} images to {out_dir}")
    return results


def read_pages_file(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip() and not l.strip().startswith("#")]
            return lines
    except Exception:
        return []


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True, help="Path to sample image")
    parser.add_argument("--pages", required=True, help="Path to newline-separated pages file")
    parser.add_argument("--out", default="matches", help="Output directory to save matches")
    parser.add_argument("--top", type=int, default=30, help="How many top matches to save")
    args = parser.parse_args(argv)

    pages = read_pages_file(args.pages)
    if not pages:
        print("No pages to crawl. Provide a pages file with URLs, one per line.")
        return 2
    if not os.path.exists(args.sample):
        print("Sample image not found:", args.sample)
        return 3

    find_matches(args.sample, pages, out_dir=args.out, top_k=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
