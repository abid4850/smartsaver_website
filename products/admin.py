from django.contrib import admin
from django.utils.html import format_html

from .models import Product
from .models import ProductNews


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ("name", "brand", "category", "get_image_status")
	search_fields = ("name", "brand", "category")
	list_filter = ("category", "brand")
	actions = ["reprocess_images"]
	readonly_fields = ("get_image_preview",)
	fields = (
		"name",
		"brand",
		"category",
		"description",
		"image",
		"get_image_preview",
		"image_url",
	)

	def get_image_status(self, obj):
		if obj._has_uploaded_image():
			return "✓ Uploaded"
		if obj._processed_image_exists():
			return "✓ Local"
		if obj.image_url:
			return "✓ Remote"
		return "No image"
	get_image_status.short_description = "Image"

	def get_image_preview(self, obj):
		url = obj.get_image_url()
		if not url:
			return "No image"
		return format_html(
			'<img src="{}" style="max-width: 280px; max-height: 280px; object-fit: contain; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 8px;" />',
			url,
		)
	get_image_preview.short_description = "Image Preview"

	def reprocess_images(self, request, queryset):
		"""Admin action to queue image reprocessing for selected products."""
		import logging
		import django_rq
		from products.tasks import process_product_image
		
		logger = logging.getLogger(__name__)
		queue = None
		use_sync = False
		
		# Try to get the queue, fallback to sync if Redis unavailable
		try:
			queue = django_rq.get_queue('default')
		except Exception as e:
			logger.warning(f"Could not connect to Redis queue: {e}. Falling back to synchronous processing.")
			use_sync = True
		
		count = 0
		filtered_products = queryset.filter(image_url__isnull=False, image_url__gt="")
		
		for product in filtered_products:
			try:
				if product._has_uploaded_image():
					count += 1
					logger.info(f"✓ Uploaded image already present for product {product.id}")
					continue
				if use_sync:
					# Fallback to synchronous processing
					product.download_and_process_image()
					logger.info(f"✓ Processed image for product {product.id} (sync mode)")
				else:
					# Queue task via django-rq
					queue.enqueue(process_product_image, product.id)
					logger.info(f"✓ Queued product {product.id} for image processing")
				count += 1
			except Exception as e:
				logger.error(f"Error processing product {product.id}: {e}")
				pass
		
		self.message_user(request, f"Queued {count} product(s) for image reprocessing.")
	
	reprocess_images.short_description = "Reprocess images (queue thumbnails)"


@admin.register(ProductNews)
class ProductNewsAdmin(admin.ModelAdmin):
	list_display = ("title", "news_category", "published_at", "is_published", "get_image_status")
	search_fields = ("title", "summary", "body", "product__name")
	list_filter = ("is_published", "news_category", "published_at", "created_at")
	prepopulated_fields = {"slug": ("title",)}
	readonly_fields = ("created_at", "updated_at", "get_image_preview")
	fields = (
		"title",
		"slug",
		"summary",
		"body",
		"image",
		"get_image_preview",
		"image_url",
		"news_category",
		"product",
		"is_published",
		"published_at",
		"created_at",
		"updated_at",
	)
	ordering = ("-published_at",)
	date_hierarchy = "published_at"

	def get_image_status(self, obj):
		if obj.image:
			return "✓ Uploaded"
		elif obj.image_url:
			return "✓ External URL"
		return "No image"
	get_image_status.short_description = "Image"

	def get_image_preview(self, obj):
		if not obj.image and not obj.image_url:
			return "No image attached or URL provided"
		img_url = obj.get_image_url()
		return f'<img src="{img_url}" style="max-width: 300px; max-height: 200px; border-radius: 8px;" />'
	get_image_preview.short_description = "Image Preview"
	get_image_preview.allow_tags = True
