from django.contrib import admin

from .models import DealAlert


@admin.register(DealAlert)
class DealAlertAdmin(admin.ModelAdmin):
	list_display = ("user", "product", "target_price", "is_active", "created_at")
	search_fields = ("user__username", "product__name")
	list_filter = ("is_active",)
