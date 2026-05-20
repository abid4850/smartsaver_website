import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartsaver.settings')
import django
django.setup()
from products.tasks import process_product_image

print('Starting process_product_image(139)')
process_product_image(139)
print('Finished')
