from django.contrib import admin

from .models import AlternativeProduct
from .models import ProductPrice


@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
	list_display = ("product", "platform", "price", "last_updated")
	search_fields = ("product__name", "platform")
	list_filter = ("platform",)


@admin.register(AlternativeProduct)
class AlternativeProductAdmin(admin.ModelAdmin):
	list_display = ("main_product", "alternative_product", "similarity_score", "price_difference")
	search_fields = ("main_product__name", "alternative_product__name")
