"""
Background tasks for product image processing using django-rq.
"""
import logging

logger = logging.getLogger(__name__)


def process_product_image(product_id):
	"""
	Background task to download and generate thumbnails for a product image.
	
	Called by Product.save() when image_url changes.
	Runs in RQ worker process.
	"""
	from products.models import Product
	
	try:
		product = Product.objects.get(id=product_id)
		product.download_and_process_image()
		logger.info(f"✓ Processed image for product {product.id} ({product.name})")
	except Product.DoesNotExist:
		logger.warning(f"Product {product_id} not found")
	except Exception as e:
		logger.error(f"Error processing image for product {product_id}: {str(e)}")
