#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartsaver.settings")
django.setup()

from products.models import Product
from django.core.files.storage import default_storage
from django.conf import settings

print(f"MEDIA_ROOT: {settings.MEDIA_ROOT}")
print(f"MEDIA_URL: {settings.MEDIA_URL}")

p = Product.objects.first()
if p:
    print(f"\nProduct: {p.name}")
    print(f"Image URL: {p.image_url}")
    local_name = p._local_image_name()
    print(f"Local image name: {local_name}")
    if local_name:
        exists = default_storage.exists(local_name)
        print(f"File exists: {exists}")
        if exists:
            print(f"File size: {default_storage.size(local_name)} bytes")
            print(f"File URL: {default_storage.url(local_name)}")
