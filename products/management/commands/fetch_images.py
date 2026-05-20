"""Management command: fetch_images

Attempts to populate or repair `Product.image_url` using multiple strategies in priority order:
 1. Store API (if API keys configured) - stubbed adapters
 2. Scrape store search result pages for image thumbnails
 3. Bing Image Search API (requires BING_SEARCH_API_KEY env var)
 4. Generate styled SVG fallback saved to media storage

The command validates candidate URLs and writes `image_url` and `image_source` on success.

Usage: python manage.py fetch_images [--limit N] [--dry-run]
"""
from __future__ import annotations

import io
import os
import sys
import time
import logging
from urllib.parse import quote_plus

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils.text import slugify
from django.db import transaction

import requests
from bs4 import BeautifulSoup
from PIL import Image

from products.models import Product

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SmartSaverImageFetcher/1.0)"}


def is_valid_image_url(url: str, timeout: int = 8) -> bool:
    try:
        # Some hosts reject HEAD; try HEAD first then GET small bytes
        resp = requests.head(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
        if resp.status_code >= 400 or 'image' not in (resp.headers.get('content-type') or ''):
            # fallback to GET
            resp = requests.get(url, timeout=timeout, headers=HEADERS, stream=True)
        if resp.status_code >= 400:
            return False
        ctype = (resp.headers.get('content-type') or '')
        if 'image' not in ctype:
            return False
        # Read a bit and try to open with PIL
        data = resp.content if hasattr(resp, 'content') else resp.raw.read(4096)
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            # Some hosts may require full download; assume OK if content-type image/*
            return True
        return True
    except Exception:
        return False


def fetch_from_store_api(product: Product) -> str | None:
    # Stubbed adapters. Real implementations require API keys and SDKs.
    store = (product.store or '').lower()
    q = f"{product.brand} {product.name}".strip()
    # Example: check environment for keys
    # Implementations should be added here for Amazon PA-API, eBay Browse API, BestBuy, Newegg
    # For now, return None to indicate not found
    return None


def scrape_store_search(product: Product) -> str | None:
    """Attempt to scrape product image from common store search pages."""
    q = quote_plus(f"{product.brand} {product.name}")
    candidates = []

    store = (product.store or '').lower()
    try_urls = []
    # Add store-specific search pages we can scrape
    if 'ebay' in store:
        try_urls.append(f"https://www.ebay.com/sch/i.html?_nkw={q}")
    if 'best' in store or 'bestbuy' in store:
        try_urls.append(f"https://www.bestbuy.com/site/searchpage.jsp?st={q}")
    if 'newegg' in store:
        try_urls.append(f"https://www.newegg.com/p/pl?d={q}")
    if 'amazon' in store:
        try_urls.append(f"https://www.amazon.com/s?k={q}")

    # Generic fallback: DuckDuckGo image search HTML
    try_urls.append(f"https://duckduckgo.com/?q={q}&iax=images&ia=images")

    for url in try_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            doc = BeautifulSoup(resp.text, 'html.parser')
            # Look for image tags
            imgs = doc.find_all('img')
            for img in imgs:
                src = img.get('data-src') or img.get('src') or img.get('data-original')
                if not src:
                    continue
                if src.startswith('//'):
                    src = 'https:' + src
                if src.startswith('/'):  # relative
                    base = '{uri.scheme}://{uri.netloc}'.format(uri=requests.utils.urlparse(url))
                    src = base + src
                if is_valid_image_url(src):
                    return src
        except Exception:
            continue
    return None


def image_search_api(product: Product) -> str | None:
    # Use Bing Image Search if BING_SEARCH_API_KEY is set
    key = os.environ.get('BING_SEARCH_API_KEY')
    if not key:
        return None
    q = f"{product.brand} {product.name} product image official"
    endpoint = 'https://api.bing.microsoft.com/v7.0/images/search'
    try:
        r = requests.get(endpoint, params={'q': q, 'count': 5}, headers={'Ocp-Apim-Subscription-Key': key}, timeout=8)
        r.raise_for_status()
        data = r.json()
        for item in data.get('value', [])[:5]:
            content_url = item.get('contentUrl')
            if content_url and is_valid_image_url(content_url):
                return content_url
    except Exception:
        return None
    return None


def generate_svg_fallback(product: Product) -> str:
    """Generate a simple SVG image with brand initials and product name, save to media storage, return relative URL."""
    initials = (product.initials if hasattr(product, 'initials') and product.initials else ''.join([p[:1] for p in product.brand.split()][:2])).upper()
    title = product.name
    color = '#111827'
    bg = '#f3f4f6'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800">
  <rect width="100%" height="100%" fill="{bg}"/>
  <g transform="translate(80,120)">
    <rect x="0" y="0" width="360" height="360" rx="28" fill="#ffffff" stroke="#e6eef7" stroke-width="2" />
    <text x="180" y="210" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="120" fill="{color}" font-weight="800">{initials}</text>
  </g>
  <text x="520" y="220" font-family="Inter, Arial, sans-serif" font-size="48" fill="#0f172a" font-weight="700">{title}</text>
  </svg>'''

    fname = f"products/generated_{slugify(product.name)}_{product.id}.svg"
    content = ContentFile(svg.encode('utf-8'))
    storage = settings.DEFAULT_FILE_STORAGE
    try:
        # Use default_storage to save
        from django.core.files.storage import default_storage
        if default_storage.exists(fname):
            default_storage.delete(fname)
        default_storage.save(fname, content)
        url = default_storage.url(fname)
        return url
    except Exception:
        # fallback: write to MEDIA_ROOT directly
        path = os.path.join(settings.MEDIA_ROOT, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(svg.encode('utf-8'))
        return settings.MEDIA_URL.rstrip('/') + '/' + fname


class Command(BaseCommand):
    help = 'Fetch or repair product images using APIs, scraping, image search, or generate SVG fallback.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0, help='Limit number of products to process')
        parser.add_argument('--dry-run', action='store_true', help='Do not write changes to database')

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']

        qs = Product.objects.all()
        # Prefer products with empty image_url or with placeholders
        qs = qs.order_by('id')
        count = 0
        for product in qs:
            if limit and count >= limit:
                break
            need = False
            if not product.image_url:
                need = True
            else:
                # Validate existing URL
                try:
                    if not is_valid_image_url(product.image_url):
                        need = True
                except Exception:
                    need = True

            if not need:
                continue

            self.stdout.write(f"Processing Product #{product.id}: {product.brand} {product.name}")
            found = None
            source = None

            # 1) Try store API
            try:
                found = fetch_from_store_api(product)
                if found:
                    source = 'api'
            except Exception as e:
                logger.exception('store api failed')

            # 2) Scrape store search
            if not found:
                try:
                    found = scrape_store_search(product)
                    if found:
                        source = 'scraped'
                except Exception:
                    found = None

            # 3) Image search API
            if not found:
                try:
                    found = image_search_api(product)
                    if found:
                        source = 'search'
                except Exception:
                    found = None

            # 4) Fallback generate SVG
            if not found:
                try:
                    found = generate_svg_fallback(product)
                    source = 'fallback'
                except Exception:
                    found = None

            if found:
                self.stdout.write(f"  -> Found image ({source}): {found}")
                if not dry_run:
                    try:
                        with transaction.atomic():
                            product.image_url = found
                            product.image_source = source
                            product.save(update_fields=['image_url', 'image_source', 'updated_at'])
                    except Exception:
                        logger.exception('failed to save product image')
            else:
                self.stdout.write("  -> No image found; skipping")

            count += 1
            # brief sleep to be polite
            time.sleep(0.3)

        self.stdout.write(self.style.SUCCESS('done'))
