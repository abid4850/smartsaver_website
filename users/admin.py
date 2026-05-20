from django.contrib import admin

from .models import SavedFilter


@admin.register(SavedFilter)
class SavedFilterAdmin(admin.ModelAdmin):
	list_display = ("name", "user", "is_pinned", "category", "brand", "updated_at")
	search_fields = ("name", "user__username", "query", "category", "brand")
	list_filter = ("is_pinned", "sort", "category", "brand")
