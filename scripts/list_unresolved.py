import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartsaver.settings')
import django
django.setup()
from products.models import Product
from products.management.commands.seed_data import Command
cmd = Command()

unresolved = []
for p in Product.objects.all():
    try:
        img = cmd._resolve_product_image(p.name, p.brand, p.category)
    except Exception:
        img = ''
    if not img:
        unresolved.append(p.slug)

for s in unresolved:
    print(s)
