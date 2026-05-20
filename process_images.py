#!/usr/bin/env python
"""
Script to manually process images for all products
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartsaver.settings')
django.setup()

from products.models import Product
from products.tasks import process_product_image

# Process products with image_url
products = Product.objects.filter(image_url__isnull=False).exclude(image_url='')[:5]
print(f"Processing {len(products)} products...")

for i, product in enumerate(products, 1):
    try:
        print(f"[{i}] Processing {product.name}... ", end='', flush=True)
        process_product_image(product.id)
        print("✓ OK")
    except Exception as e:
        print(f"✗ Error: {e}")

print("Done!")
