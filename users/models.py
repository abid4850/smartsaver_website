from django.db import models
from django.conf import settings


class SavedFilter(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_filters")
	name = models.CharField(max_length=120)
	query = models.CharField(max_length=255, blank=True)
	category = models.CharField(max_length=120, blank=True)
	brand = models.CharField(max_length=120, blank=True)
	sort = models.CharField(max_length=32, default="name_asc")
	min_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	max_price = models.DecimalField(max_digits=10, decimal_places=2, default=5000)
	is_pinned = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-is_pinned", "-updated_at"]
		constraints = [
			models.UniqueConstraint(fields=["user", "name"], name="unique_saved_filter_name_per_user")
		]

	def __str__(self):
		return f"{self.user} - {self.name}"


class NewsletterSubscription(models.Model):
	email = models.EmailField(unique=True, db_index=True)
	is_subscribed = models.BooleanField(default=True)
	verification_token = models.CharField(max_length=64, blank=True, null=True)
	is_verified = models.BooleanField(default=False)
	subscribed_at = models.DateTimeField(auto_now_add=True)
	unsubscribed_at = models.DateTimeField(null=True, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-subscribed_at"]

	def __str__(self):
		return f"{self.email} ({self.get_status()})"

	def get_status(self):
		if not self.is_subscribed:
			return "Unsubscribed"
		elif not self.is_verified:
			return "Pending Verification"
		return "Active"
