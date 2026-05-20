from django.db import models
from products.models import Product


class ProductPrice(models.Model):
	product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
	platform = models.CharField(max_length=100)
	price = models.DecimalField(max_digits=10, decimal_places=2)
	product_url = models.URLField()
	last_updated = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["price"]
		constraints = [
			models.UniqueConstraint(fields=["product", "platform"], name="unique_product_platform_price")
		]

	def __str__(self) -> str:
		return f"{self.product} @ {self.platform} - ${self.price}"


class AlternativeProduct(models.Model):
	main_product = models.ForeignKey(
		Product,
		on_delete=models.CASCADE,
		related_name="main_product_alternatives",
	)
	alternative_product = models.ForeignKey(
		Product,
		on_delete=models.CASCADE,
		related_name="alternative_product_matches",
	)
	similarity_score = models.DecimalField(max_digits=5, decimal_places=2)
	price_difference = models.DecimalField(max_digits=10, decimal_places=2)

	class Meta:
		ordering = ["-price_difference", "-similarity_score"]
		constraints = [
			models.UniqueConstraint(
				fields=["main_product", "alternative_product"],
				name="unique_alternative_pair",
			)
		]

	def __str__(self) -> str:
		return f"{self.main_product} -> {self.alternative_product}"
