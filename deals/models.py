from django.db import models
from django.conf import settings

from products.models import Product


class DealAlert(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deal_alerts")
	product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="deal_alerts")
	target_price = models.DecimalField(max_digits=10, decimal_places=2)
	created_at = models.DateTimeField(auto_now_add=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["-created_at"]
		constraints = [
			models.UniqueConstraint(fields=["user", "product"], name="unique_user_product_alert")
		]

	def __str__(self) -> str:
		return f"{self.user} alerts on {self.product} <= ${self.target_price}"
