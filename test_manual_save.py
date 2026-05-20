#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartsaver.settings")
django.setup()

from products.models import Product
from django.core.files.storage import default_storage
import requests
from io import BytesIO
from PIL import Image

p = Product.objects.first()
if p:
    print(f"Testing download_and_process_image for: {p.name}")
    
    # Manual test
    resp = requests.get(p.image_url, timeout=10)
    resp.raise_for_status()
    
    img_bytes = BytesIO(resp.content)
    img = Image.open(img_bytes)
    print(f"Original image size: {img.size}")
    img = img.convert("RGBA") if img.mode in ("P", "RGBA") else img.convert("RGB")
    
    # Test saving original
    print("\nSaving original...")
    local_name = p._local_image_name()
    p._save_image_variant(img, local_name, max_width=1200)
    exists = default_storage.exists(local_name)
    print(f"Original saved: {exists}")
    if exists:
        print(f"Size: {default_storage.size(local_name)} bytes")
    
    # Test saving card thumbnail
    print("\nSaving card thumbnail...")
    thumb_name = p._thumbnail_name("card")
    p._save_image_variant(img, thumb_name, max_width=600)
    exists = default_storage.exists(thumb_name)
    print(f"Card thumbnail saved: {exists}")
    if exists:
        print(f"Size: {default_storage.size(thumb_name)} bytes")
    
    # Test saving thumb thumbnail
    print("\nSaving thumb thumbnail...")
    thumb_name = p._thumbnail_name("thumb")
    p._save_image_variant(img, thumb_name, max_width=320)
    exists = default_storage.exists(thumb_name)
    print(f"Thumb thumbnail saved: {exists}")
    if exists:
        print(f"Size: {default_storage.size(thumb_name)} bytes")
