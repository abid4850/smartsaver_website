from django.db import models
from django.utils.text import slugify
from django.templatetags.static import static
import os
from pathlib import Path
from django.conf import settings
import requests
from io import BytesIO
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import hashlib
import django_rq

try:
	from PIL import Image
	PIL_AVAILABLE = True
except Exception:
	PIL_AVAILABLE = False


class Product(models.Model):
	name = models.CharField(max_length=255, db_index=True)
	brand = models.CharField(max_length=120, db_index=True)
	category = models.CharField(max_length=120, db_index=True)
	description = models.TextField(blank=True)
	image = models.ImageField(upload_to="products/uploaded/%Y/%m/%d/", blank=True, null=True)
	image_url = models.URLField(max_length=500, blank=True)
	image_source = models.CharField(max_length=50, default='manual')  # api/scraped/search/fallback/manual

	@property
	def fallback_url(self) -> str:
		"""Return a URL that generates a placeholder SVG for this product.

		This points to a lightweight view that returns an SVG image for the
		given product id. The template uses this as the final fallback.
		"""
		from django.urls import reverse
		return reverse('generate_placeholder', args=[self.id])
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]

	def __str__(self) -> str:
		return f"{self.brand} {self.name}".strip()

	@property
	def cheapest_price(self):
		cheapest = self.prices.order_by("price").first()
		return cheapest.price if cheapest else None

	@property
	def cheapest_platform(self):
		cheapest = self.prices.order_by("price").first()
		return cheapest.platform if cheapest else None

	def _local_image_name(self) -> str:
		"""Generate a deterministic local filename from image_url."""
		if not self.image_url:
			return ""
		# hash the URL to create a unique filename
		hash_suffix = hashlib.md5(self.image_url.encode()).hexdigest()[:8]
		return f"products/{self.id}_{hash_suffix}.jpg"

	def _thumbnail_name(self, size_suffix: str) -> str:
		"""Generate thumbnail filename."""
		if not self.image_url:
			return ""
		hash_suffix = hashlib.md5(self.image_url.encode()).hexdigest()[:8]
		return f"products/{self.id}_{hash_suffix}_{size_suffix}.jpg"

	def _is_placeholder_url(self, url: str) -> bool:
		if not url:
			return True
		url = url.lower()
		return "dummyimage.com" in url or "via.placeholder.com" in url or "/static/smartsaver/product-placeholder.svg" in url

	def _processed_image_exists(self) -> bool:
		local_name = self._local_image_name()
		return bool(local_name and default_storage.exists(local_name))

	def _has_uploaded_image(self) -> bool:
		return bool(self.image and hasattr(self.image, "url") and self.image.name)

	def _image_source_url(self) -> str:
		"""Return the best renderable image URL for templates."""
		if self._has_uploaded_image():
			return self.image.url

		local_name = self._local_image_name()
		if local_name and default_storage.exists(local_name):
			return f"{settings.MEDIA_URL.rstrip('/')}/{local_name}"

		if self.image_url and not self._is_placeholder_url(self.image_url):
			return self.image_url

		return "/static/smartsaver/product-placeholder.svg"

	def download_and_process_image(self):
		"""Download remote image_url and generate local thumbnails (guarded by PIL)."""
		if not self.image_url or self._is_placeholder_url(self.image_url) or not PIL_AVAILABLE:
			return

		try:
			# download image
			resp = requests.get(self.image_url, timeout=10)
			resp.raise_for_status()
			
			img_bytes = BytesIO(resp.content)
			img = Image.open(img_bytes)
			img = img.convert("RGBA") if img.mode in ("P", "RGBA") else img.convert("RGB")
			
			# save original
			local_name = self._local_image_name()
			self._save_image_variant(img, local_name, max_width=1200)
			
			# generate thumbnails
			sizes = {
				"card": (600, 400),
				"thumb": (320, 240),
			}
			for suffix, (w, h) in sizes.items():
				thumb_name = self._thumbnail_name(suffix)
				self._save_image_variant(img, thumb_name, max_width=w)
		except Exception:
			# fail silently in dev if download/process fails
			return

	def _save_image_variant(self, img: "Image.Image", filename: str, max_width: int = None):
		"""Save an image variant to media storage."""
		if not PIL_AVAILABLE:
			return
		
		# scale to max_width if needed
		if max_width and img.width > max_width:
			ratio = max_width / img.width
			new_h = int(img.height * ratio)
			img = img.resize((max_width, new_h), Image.LANCZOS)
		
		# ensure RGB mode for JPEG
		if img.mode in ("RGBA", "P", "LA"):
			bg = Image.new("RGB", img.size, (255, 255, 255))
			if img.mode == "P":
				img = img.convert("RGBA")
			bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
			img = bg
		elif img.mode != "RGB":
			img = img.convert("RGB")
		
		# save to BytesIO
		buffer = BytesIO()
		img.save(buffer, format="JPEG", quality=85, optimize=True)
		buffer.seek(0)
		
		# save to media
		default_storage.save(filename, ContentFile(buffer.read()))

	def get_image_url(self) -> str:
		"""Return local or remote image URL with proper fallback to white background placeholder."""
		return self._image_source_url()

	def get_image_srcset(self) -> str:
		"""Return responsive srcset for product images."""
		if self._has_uploaded_image():
			return f"{self.image.url} 1x"

		if not self._processed_image_exists():
			return ""
		
		srcset_parts = []
		local_name = self._local_image_name()
		
		# try to find local variants
		if local_name and default_storage.exists(local_name):
			srcset_parts.append(f"{settings.MEDIA_URL.rstrip('/')}/{local_name} 1200w")
		
		for suffix, w in (("card", 600), ("thumb", 320)):
			thumb_name = self._thumbnail_name(suffix)
			if thumb_name and default_storage.exists(thumb_name):
				srcset_parts.append(f"{settings.MEDIA_URL.rstrip('/')}/{thumb_name} {w}w")
		
		# if no local variants, fallback to original URL
		if not srcset_parts:
			return f"{self.image_url} 1200w"
		
		return ", ".join(srcset_parts)

	def save(self, *args, **kwargs):
		"""Override save to queue background download + thumbnailing when image_url changes."""
		old_url = None
		old_image_name = None
		if self.pk:
			try:
				old = Product.objects.get(pk=self.pk)
				old_url = old.image_url
				old_image_name = old.image.name if old.image else None
			except Product.DoesNotExist:
				old_url = None
				old_image_name = None
		super().save(*args, **kwargs)
		if self._has_uploaded_image() and self.image.name != old_image_name:
			return
		# queue background processing if the image_url is new/changed
		if self.image_url and self.image_url != old_url and PIL_AVAILABLE:
			try:
				queue = django_rq.get_queue('default')
				from products.tasks import process_product_image
				queue.enqueue(process_product_image, self.id)
			except Exception as e:
				# fallback: run synchronously in dev (e.g., no Redis)
				try:
					self.download_and_process_image()
				except Exception:
					pass  # don't let image processing affect save operation


class ProductNews(models.Model):
	CATEGORY_CHOICES = [
		("launches", "Product Launches"),
		("pricing", "Price Updates"),
		("deals", "Hot Deals"),
		("tech", "Technology & Features"),
		("reviews", "Reviews & Analysis"),
		("general", "General News"),
	]
	
	title = models.CharField(max_length=220)
	slug = models.SlugField(max_length=240, unique=True, blank=True)
	summary = models.TextField()
	body = models.TextField(blank=True)
	image_url = models.URLField(blank=True, help_text="Optional: External image URL as fallback")
	image = models.ImageField(upload_to="news/%Y/%m/%d/", blank=True, help_text="Upload news image (recommended: 800x600px or wider)")
	news_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="general", db_index=True)
	product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="news_items")
	is_published = models.BooleanField(default=True)
	published_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-published_at"]

	def save(self, *args, **kwargs):
		if not self.slug:
			base_slug = slugify(self.title) or "news-item"
			slug = base_slug
			counter = 2
			while ProductNews.objects.filter(slug=slug).exclude(pk=self.pk).exists():
				slug = f"{base_slug}-{counter}"
				counter += 1
			self.slug = slug
		super().save(*args, **kwargs)

	def get_image_url(self):
		"""Return the best available image URL for the news item."""
		if self.image:
			return self.image.url
		if self.image_url:
			return self.image_url

		fallback_map = {
			"launches": "smartsaver/news-launches.svg",
			"pricing": "smartsaver/news-pricing.svg",
			"deals": "smartsaver/news-deals.svg",
			"tech": "smartsaver/news-tech.svg",
			"reviews": "smartsaver/news-reviews.svg",
			"general": "smartsaver/news-general.svg",
		}
		return static(fallback_map.get(self.news_category, "smartsaver/news-general.svg"))

	def _thumbnail_path(self, size_suffix: str) -> str:
		"""Return filesystem path for a thumbnail variant.

		size_suffix examples: 'hero', 'card', 'thumb'
		"""
		if not self.image:
			return ""
		original_path = Path(self.image.path)
		return str(original_path.with_name(f"{original_path.stem}_{size_suffix}{original_path.suffix}"))

	def _thumbnail_url(self, size_suffix: str) -> str:
		if not self.image:
			return ""
		original_url = self.image.url
		original_path = Path(self.image.name)
		thumb_name = f"{original_path.stem}_{size_suffix}{original_path.suffix}"
		return str(settings.MEDIA_URL.rstrip("/") + "/" + str(original_path.with_name(thumb_name)).lstrip("/"))

	def generate_thumbnails(self):
		"""Generate small/medium thumbnails for uploaded news images (no-op if PIL missing)."""
		if not PIL_AVAILABLE or not self.image:
			return

		sizes = {
			"hero": (1200, 800),
			"card": (600, 400),
			"thumb": (320, 240),
		}

		try:
			img_path = self.image.path
			with Image.open(img_path) as im:
				im = im.convert("RGBA") if im.mode in ("P", "RGBA") else im.convert("RGB")
				for suffix, size in sizes.items():
					out_path = self._thumbnail_path(suffix)
					dst = Image.new("RGB", size, (255, 255, 255))
					im_copy = im.copy()
					im_copy.thumbnail(size, Image.LANCZOS)
					# center image
					x = (size[0] - im_copy.width) // 2
					y = (size[1] - im_copy.height) // 2
					dst.paste(im_copy, (x, y))
					dst.save(out_path, format="JPEG", quality=85)
		except Exception:
			# Fail silently in dev if thumbnailing fails
			return

	def get_image_srcset(self) -> str:
		"""Return a srcset string for responsive image loading.

		Falls back to get_image_url when no thumbnails exist.
		"""
		if self.image:
			parts = []
			for suffix, w in (("hero", 1200), ("card", 600), ("thumb", 320)):
				url = self._thumbnail_url(suffix)
				if url:
					parts.append(f"{url} {w}w")
			if parts:
				return ", ".join(parts)
			return self.image.url

		# no uploaded image - if external URL exists, just repeat it
		if self.image_url:
			return f"{self.image_url} 1200w"
		return ""

	def __str__(self):
		return self.title
