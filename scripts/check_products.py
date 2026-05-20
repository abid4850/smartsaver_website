import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartsaver.settings')
import django
django.setup()
from products.models import Product
prods = Product.objects.all()
print('count', prods.count())
# list sample of slugs added
for p in prods.order_by('id')[:10]:
    print(p.slug)
print('---')
for p in prods.order_by('-id')[:15]:
    print(p.slug)
