#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartsaver.settings")
django.setup()

from products.models import Product
from django.core.files.storage import default_storage
from django.conf import settings

p = Product.objects.first()
if p:
    print(f"Product: {p.name}")
    print(f"\nImage URL variants:")
    print(f"Original: {p.get_image_url()}")
    print(f"\nSrcset: {p.get_image_srcset()}")
    
    # Check for each thumbnail
    for suffix in ["card", "thumb"]:
        thumb_name = p._thumbnail_name(suffix)
        exists = default_storage.exists(thumb_name)
        print(f"\n{suffix} ({thumb_name}): exists={exists}")
        if exists:
            print(f"  Size: {default_storage.size(thumb_name)} bytes")
            print(f"  URL: {default_storage.url(thumb_name)}")
