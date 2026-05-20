#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartsaver.settings")
django.setup()

from products.models import Product
from django.core.files.storage import default_storage
from django.conf import settings
import requests
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
import traceback

p = Product.objects.first()
if p:
    print(f"Product: {p.name}")
    print(f"Image URL: {p.image_url}")
    
    try:
        # Download image
        print("\nDownloading image...")
        resp = requests.get(p.image_url, timeout=10)
        resp.raise_for_status()
        print(f"Response status: {resp.status_code}")
        print(f"Response size: {len(resp.content)} bytes")
        
        # Open as PIL image
        print("\nOpening image with PIL...")
        img_bytes = BytesIO(resp.content)
        img = Image.open(img_bytes)
        print(f"Image format: {img.format}, size: {img.size}, mode: {img.mode}")
        
        # Convert image
        print("\nConverting image...")
        img = img.convert("RGBA") if img.mode in ("P", "RGBA") else img.convert("RGB")
        print(f"Converted to mode: {img.mode}")
        
        # Save to BytesIO
        print("\nSaving to BytesIO...")
        # ensure RGB mode for JPEG
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85, optimize=True)
        print(f"Buffer size: {buffer.tell()} bytes")
        buffer.seek(0)
        
        # Save to storage
        print("\nSaving to Django storage...")
        local_name = p._local_image_name()
        print(f"Target filename: {local_name}")
        result = default_storage.save(local_name, ContentFile(buffer.read()))
        print(f"Saved as: {result}")
        
        # Verify
        print("\nVerifying...")
        exists = default_storage.exists(local_name)
        print(f"File exists: {exists}")
        if exists:
            size = default_storage.size(local_name)
            print(f"File size: {size} bytes")
            
    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()
