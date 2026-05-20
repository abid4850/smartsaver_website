"""Management command: fix_images

This command aggressively fetches product images using (in order):
 1) Bing Image Search (via web scraping since no API key is provided)
 2) DuckDuckGo image search HTML
 3) Store search page scraping
 If all fail, generate and save an SVG placeholder file in MEDIA_ROOT and set product.image_url to it.

Usage: python manage.py fix_images --limit 0
"""
from __future__ import annotations

import os
import io
import time
import logging
from urllib.parse import quote_plus

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils.text import slugify
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404

import requests
from bs4 import BeautifulSoup
from PIL import Image

from products.models import Product
from django.conf import settings
from products.utils.serpapi_client import get_product_image_via_serpapi

logger = logging.getLogger(__name__)
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; SmartSaver/1.0)'}


def validate_image_url(url: str) -> bool:
    try:
        r = requests.head(url, timeout=8, headers=HEADERS, allow_redirects=True)
        if r.status_code >= 400:
            r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code >= 400:
            return False
        ctype = r.headers.get('content-type', '')
        return 'image' in ctype
    except Exception:
        return False


def search_duckduckgo(product: Product) -> str | None:
    q = quote_plus(f"{product.brand} {product.name} product image official")
    url = f'https://duckduckgo.com/?q={q}&iax=images&ia=images'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        doc = BeautifulSoup(resp.text, 'html.parser')
        imgs = doc.find_all('img')
        for img in imgs:
            src = img.get('data-src') or img.get('src')
            if not src:
                continue
            if src.startswith('//'):
                src = 'https:' + src
            if validate_image_url(src):
                return src
    except Exception:
        return None
    return None


def scrape_store_search(product: Product) -> str | None:
    q = quote_plus(f"{product.brand} {product.name}")
    candidates = []
    try_urls = [
        f"https://www.ebay.com/sch/i.html?_nkw={q}",
        f"https://www.bestbuy.com/site/searchpage.jsp?st={q}",
        f"https://www.newegg.com/p/pl?d={q}",
        f"https://www.amazon.com/s?k={q}",
    ]
    for url in try_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            doc = BeautifulSoup(r.text, 'html.parser')
            imgs = doc.find_all('img')
            for img in imgs:
                src = img.get('data-src') or img.get('src')
                if not src:
                    continue
                if src.startswith('//'):
                    src = 'https:' + src
                if src.startswith('/'):
                    src = requests.utils.urljoin(url, src)
                if validate_image_url(src):
                    return src
        except Exception:
            continue
    return None


def generate_and_save_svg(product: Product) -> str:
    initials = ''.join([p[:1] for p in (product.brand or '').split()][:2]).upper() or 'PR'
    title = product.name or ''
    color = '#111827'
    bg = '#ffffff'
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>\n<rect width='100%' height='100%' fill='{bg}'/>\n<text x='600' y='300' font-family='Inter,Arial' font-size='120' text-anchor='middle' fill='{color}' font-weight='800'>{initials}</text>\n<text x='600' y='420' font-family='Inter,Arial' font-size='44' text-anchor='middle' fill='#374151'>{title}</text>\n</svg>"""
    fname = f'products/placeholder_{slugify(product.name)}_{product.id}.svg'
    try:
        if default_storage.exists(fname):
            default_storage.delete(fname)
        default_storage.save(fname, ContentFile(svg.encode('utf-8')))
        return default_storage.url(fname)
    except Exception:
        path = os.path.join(settings.MEDIA_ROOT, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(svg.encode('utf-8'))
        return settings.MEDIA_URL.rstrip('/') + '/' + fname


class Command(BaseCommand):
    help = 'Fix product images by searching image sources or generating placeholders.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        limit = options.get('limit', 0) or 0
        products = Product.objects.all().order_by('id')
        total = products.count()
        fixed = 0
        placeholders = 0

        for i, p in enumerate(products, start=1):
            if limit and fixed >= limit:
                break
            need = not p.image_url or not validate_image_url(p.image_url)
            if not need:
                continue
            self.stdout.write(f'[{i}/{total}] Processing {p.id} {p.brand} {p.name}...')
            found = None
            # 0) SerpAPI (preferred, requires SERPAPI_KEY in settings)
            try:
                if getattr(settings, 'SERPAPI_KEY', ''):
                    found = get_product_image_via_serpapi(p.name, p.brand)
            except Exception:
                found = None
            # 1) duckduckgo
            if not found:
                found = search_duckduckgo(p)
            if not found:
                found = scrape_store_search(p)
            if found:
                p.image_url = found
                p.image_source = 'search'
                p.save(update_fields=['image_url', 'image_source', 'updated_at'])
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f'  -> found {found}'))
                continue

            # not found: generate placeholder
            url = generate_and_save_svg(p)
            p.image_url = url
            p.image_source = 'placeholder'
            p.save(update_fields=['image_url', 'image_source', 'updated_at'])
            placeholders += 1
            fixed += 1
            self.stdout.write(self.style.WARNING(f'  -> placeholder saved {url}'))
            time.sleep(0.2)

        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed}/{total} products, placeholders: {placeholders}'))
