from django.test import TestCase
from django.contrib.auth import get_user_model

from comparisons.models import AlternativeProduct
from comparisons.models import ProductPrice
from users.models import SavedFilter

from .models import Product
from .models import ProductNews
from django.utils import timezone


class SmartSaverEndpointsTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username="testuser",
			email="test@example.com",
			password="TestPass123",
		)

		self.main_product = Product.objects.create(
			name="Galaxy Buds Pro",
			brand="Samsung",
			category="Audio",
			description="Wireless earbuds with ANC.",
			image_url="https://images.example.com/galaxy-buds-pro.jpg",
		)
		self.alt_product = Product.objects.create(
			name="Redmi Buds 5",
			brand="Xiaomi",
			category="Audio",
			description="Budget earbuds with strong battery life.",
			image_url="https://images.example.com/redmi-buds-5.jpg",
		)

		ProductPrice.objects.create(
			product=self.main_product,
			platform="Amazon",
			price="129.99",
			product_url="https://example.com/main-amazon",
		)
		ProductPrice.objects.create(
			product=self.main_product,
			platform="eBay",
			price="119.99",
			product_url="https://example.com/main-ebay",
		)
		ProductPrice.objects.create(
			product=self.alt_product,
			platform="Amazon",
			price="69.99",
			product_url="https://example.com/alt-amazon",
		)

		AlternativeProduct.objects.create(
			main_product=self.main_product,
			alternative_product=self.alt_product,
			similarity_score="0.86",
			price_difference="50.00",
		)

		self.news = ProductNews.objects.create(
			title="Galaxy Buds Firmware Update Improves ANC",
			summary="Samsung rolls out better active noise cancellation for Galaxy Buds Pro.",
			body="Users report clearer call quality and improved suppression in busy environments.",
			image_url="https://images.example.com/news-buds.jpg",
			product=self.main_product,
			published_at=timezone.now(),
			is_published=True,
		)

	def test_search_api(self):
		response = self.client.get("/api/search/?q=galaxy")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["count"], 1)

	def test_compare_api(self):
		response = self.client.get(f"/api/compare/{self.main_product.id}/")
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload["best_deal"]["platform"], "eBay")

	def test_alternatives_api(self):
		response = self.client.get(f"/api/alternatives/{self.main_product.id}/")
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(len(payload["alternatives"]), 1)

	def test_home_page(self):
		response = self.client.get("/")
		self.assertEqual(response.status_code, 200)

	def test_results_page(self):
		response = self.client.get("/results/?q=buds")
		self.assertEqual(response.status_code, 200)

	def test_product_detail_page(self):
		response = self.client.get(f"/products/{self.main_product.id}/")
		self.assertEqual(response.status_code, 200)

	def test_results_sort_by_low_price(self):
		response = self.client.get("/results/?sort=price_low")
		self.assertEqual(response.status_code, 200)
		product_ids = [item.id for item in response.context["products"]]
		self.assertEqual(product_ids[0], self.alt_product.id)

	def test_results_price_range_filter(self):
		response = self.client.get("/results/?min_price=100&max_price=125")
		self.assertEqual(response.status_code, 200)
		product_ids = [item.id for item in response.context["products"]]
		self.assertIn(self.main_product.id, product_ids)
		self.assertNotIn(self.alt_product.id, product_ids)

	def test_seo_category_page(self):
		response = self.client.get("/category/audio/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["category"], "Audio")

	def test_autocomplete_endpoint(self):
		response = self.client.get("/api/autocomplete/?q=gal")
		self.assertEqual(response.status_code, 200)
		suggestions = response.json()["suggestions"]
		self.assertTrue(any("Galaxy" in item for item in suggestions))

	def test_save_filter_requires_login(self):
		response = self.client.post("/filters/save/", {"name": "My Filter"})
		self.assertEqual(response.status_code, 302)
		self.assertIn("/accounts/login/", response.url)

	def test_save_filter_for_authenticated_user(self):
		self.client.login(username="testuser", password="TestPass123")
		response = self.client.post(
			"/filters/save/",
			{
				"name": "Budget Audio",
				"query": "buds",
				"category": "Audio",
				"brand": "Samsung",
				"sort": "price_low",
				"min_price": "50",
				"max_price": "150",
				"next": "/results/",
			},
		)
		self.assertEqual(response.status_code, 302)
		exists = SavedFilter.objects.filter(user=self.user, name="Budget Audio").exists()
		self.assertTrue(exists)

	def test_toggle_pin_filter(self):
		self.client.login(username="testuser", password="TestPass123")
		saved = SavedFilter.objects.create(user=self.user, name="Pin Me")
		response = self.client.post(f"/filters/{saved.id}/pin/", {"next": "/results/"})
		self.assertEqual(response.status_code, 302)
		saved.refresh_from_db()
		self.assertTrue(saved.is_pinned)

	def test_saved_filter_has_share_url_in_context(self):
		self.client.login(username="testuser", password="TestPass123")
		SavedFilter.objects.create(
			user=self.user,
			name="Shareable",
			query="buds",
			category="Audio",
			brand="Samsung",
		)
		response = self.client.get("/results/")
		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.context["saved_filters"])
		self.assertIn("/results/?", response.context["saved_filters"][0].share_url)

	def test_news_list_and_detail(self):
		list_response = self.client.get("/news/")
		self.assertEqual(list_response.status_code, 200)
		detail_response = self.client.get(f"/news/{self.news.slug}/")
		self.assertEqual(detail_response.status_code, 200)

	def test_favorites_dashboard(self):
		self.client.login(username="testuser", password="TestPass123")
		SavedFilter.objects.create(user=self.user, name="Pinned One", is_pinned=True)
		response = self.client.get("/favorites/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["total_favorites"], 1)

	def test_news_detail_staff_edit_context(self):
		self.client.login(username="testuser", password="TestPass123")
		response = self.client.get(f"/news/{self.news.slug}/")
		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.context.get("edit_url"))
