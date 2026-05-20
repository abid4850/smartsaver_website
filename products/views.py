from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from comparisons.models import AlternativeProduct
from comparisons.models import ProductPrice
from users.models import SavedFilter

from .models import Product
from .models import ProductNews
from .serializers import AlternativeProductSerializer
from .serializers import ProductPriceSerializer
from .serializers import ProductNewsSerializer
from .serializers import ProductSerializer
from django.http import HttpResponse, HttpResponseBadRequest, FileResponse
from django.shortcuts import get_object_or_404
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse
import requests
import os
import hashlib

PRODUCTS_PER_PAGE = 40
FAVORITES_PER_PAGE = 40
NEWS_PER_PAGE = 40
ALLOWED_PAGE_SIZES = (20, 40, 60)
PER_PAGE_SESSION_KEY = "preferred_per_page"



class ProductSearchAPIView(generics.ListAPIView):
	serializer_class = ProductSerializer
	filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
	filterset_fields = ["brand", "category"]
	ordering_fields = ["name", "brand", "category", "lowest_price"]
	ordering = ["name"]

	def get_queryset(self):
		queryset = Product.objects.prefetch_related("prices").annotate(lowest_price=Min("prices__price"))
		query = self.request.query_params.get("q", "").strip()
		min_price = _parse_decimal(self.request.query_params.get("min_price", "").strip())
		max_price = _parse_decimal(self.request.query_params.get("max_price", "").strip())
		brand = self.request.query_params.get("brand", "").strip()
		category = self.request.query_params.get("category", "").strip()

		if query:
			queryset = queryset.filter(
				Q(name__icontains=query)
				| Q(brand__icontains=query)
				| Q(category__icontains=query)
			)
		if brand:
			queryset = queryset.filter(brand__icontains=brand)
		if category:
			queryset = queryset.filter(category__icontains=category)
		if min_price is not None:
			queryset = queryset.filter(lowest_price__gte=min_price)
		if max_price is not None:
			queryset = queryset.filter(lowest_price__lte=max_price)
		return queryset


class ProductNewsAPIView(generics.ListAPIView):
	serializer_class = ProductNewsSerializer

	def get_queryset(self):
		queryset = ProductNews.objects.filter(is_published=True, published_at__lte=timezone.now())
		query = self.request.query_params.get("q", "").strip()
		category = self.request.query_params.get("category", "").strip()
		if query:
			queryset = queryset.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(body__icontains=query))
		if category and category in dict(ProductNews.CATEGORY_CHOICES):
			queryset = queryset.filter(news_category=category)
		return queryset.order_by("-published_at")


class ProductComparisonAPIView(APIView):
	def get(self, request, product_id):
		product = get_object_or_404(Product.objects.prefetch_related("prices"), pk=product_id)
		prices = ProductPrice.objects.filter(product=product).order_by("price", "platform")
		best_deal = prices.first()

		return Response(
			{
				"product": ProductSerializer(product).data,
				"best_deal": ProductPriceSerializer(best_deal).data if best_deal else None,
				"prices": ProductPriceSerializer(prices, many=True).data,
			}
		)


class ProductAlternativesAPIView(APIView):
	def get(self, request, product_id):
		product = get_object_or_404(Product, pk=product_id)
		alternatives = (
			AlternativeProduct.objects.select_related("alternative_product")
			.filter(main_product=product, price_difference__gt=0)
			.order_by("-price_difference", "-similarity_score")
		)

		return Response(
			{
				"product": ProductSerializer(product).data,
				"alternatives": AlternativeProductSerializer(alternatives, many=True).data,
			}
		)


def home_view(request):
	featured_products = Product.objects.prefetch_related("prices").all()[:6]
	latest_news = ProductNews.objects.filter(is_published=True, published_at__lte=timezone.now()).order_by('-published_at')[:3]
	
	# Stats and FAQ for the homepage
	total_products = Product.objects.count()
	user_count = f"{(total_products // 100) + 50}K"  # Estimate based on products
	average_savings = "42%"  # Default value for homepage
	
	faqs = [
		{
			'question': 'How accurate are the prices?',
			'answer': 'Our prices update in real-time (every 6-24 hours depending on retailer) by directly scraping store websites. We show exact current prices from 100+ major retailers.'
		},
		{
			'question': 'Is SmartSaver free to use?',
			'answer': 'Yes! SmartSaver is completely free. We make money from affiliate commissions when you buy through our links, but you pay the same price.'
		},
		{
			'question': 'Which stores do you compare?',
			'answer': 'We track Amazon, Walmart, Best Buy, Newegg, Target, eBay, and 90+ other major retailers across electronics, home goods, and more.'
		},
		{
			'question': 'How do price alerts work?',
			'answer': 'Sign in, add a product to your wishlist, set your target price, and we\'ll email you instantly when it drops. You\'ll never miss a deal again.'
		},
		{
			'question': 'Can I get alternative product recommendations?',
			'answer': 'Absolutely! Our AI analyzes specs, features, and ratings to suggest similar products that might offer better value. See them on the comparison page.'
		},
		{
			'question': 'Is my data safe with SmartSaver?',
			'answer': 'We use enterprise-grade encryption. We never share your data with third parties. See our Privacy Policy for complete transparency.'
		},
	]
	
	return render(request, "home.html", {
		"featured_products": featured_products, 
		"latest_news": latest_news,
		"total_products": total_products,
		"user_count": user_count,
		"average_savings": average_savings,
		"faqs": faqs,
	})


def generate_placeholder_view(request, product_id: int):
	"""Return an SVG placeholder for the product. This does not require
	persistent storage; it returns a generated SVG response directly.
	"""
	product = get_object_or_404(Product, pk=product_id)
	brand = (product.brand or '').strip()
	initials = ''.join([p[:1] for p in brand.split()][:2]).upper() or (brand[:2].upper() if brand else 'PR')
	title = product.name or ''
	# choose a simple palette from brand name hash
	h = int(hashlib.md5((brand or '').encode('utf-8')).hexdigest()[:6], 16)
	color = f"#{(h & 0xFFFFFF):06x}"
	bg = '#ffffff'

	# Truncate title to two lines by inserting a <tspan> break if long
	max_len = 36
	if len(title) > max_len:
		first = title[:max_len].rsplit(' ', 1)[0]
		second = title[len(first):].strip()
	else:
		first = title
		second = ''

	svg = f"""
	<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>
	  <rect width='100%' height='100%' fill='{bg}' />
	  <rect x='64' y='64' width='440' height='440' rx='28' fill='{color}' opacity='0.08'/>
	  <rect x='64' y='64' width='440' height='440' rx='28' fill='#fff' stroke='#eef2ff' />
	  <text x='284' y='240' font-family='Inter,Arial' font-size='120' text-anchor='middle' fill='{color}' font-weight='800'>{initials}</text>
	  <text x='540' y='220' font-family='Inter,Arial' font-size='48' fill='#0f172a' font-weight='700'>{first}</text>
	  """
	if second:
		svg += f"\n      <text x='540' y='270' font-family='Inter,Arial' font-size='36' fill='#374151' font-weight='600'>{second}</text>\n"
	svg += "\n    </svg>"

	return HttpResponse(svg, content_type='image/svg+xml')


def image_proxy_view(request):
	"""Simple proxy to fetch and return an external image. Use sparingly.

	Accepts a `url` query parameter. Returns 400 if missing or invalid.
	"""
	url = request.GET.get('url')
	if not url:
		return HttpResponseBadRequest('missing url')
	# Basic safety: only allow http(s)
	if not url.lower().startswith(('http://', 'https://')):
		return HttpResponseBadRequest('invalid url')
	try:
		resp = requests.get(url, stream=True, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (compatible; SmartSaver/1.0)'} )
		resp.raise_for_status()
		content_type = resp.headers.get('content-type', 'application/octet-stream')
		return HttpResponse(resp.content, content_type=content_type)
	except Exception as e:
		return HttpResponseBadRequest('fetch failed')


def autocomplete_api(request):
	query = request.GET.get("q", "").strip()
	if len(query) < 2:
		return JsonResponse({"suggestions": []})

	product_names = list(
		Product.objects.filter(name__icontains=query)
		.order_by("name")
		.values_list("name", flat=True)
		.distinct()[:8]
	)
	brands = list(
		Product.objects.filter(brand__icontains=query)
		.order_by("brand")
		.values_list("brand", flat=True)
		.distinct()[:4]
	)
	categories = list(
		Product.objects.filter(category__icontains=query)
		.order_by("category")
		.values_list("category", flat=True)
		.distinct()[:4]
	)

	suggestions = []
	seen = set()
	for value in [*product_names, *brands, *categories]:
		normalized = value.lower()
		if normalized in seen:
			continue
		seen.add(normalized)
		suggestions.append(value)
		if len(suggestions) >= 10:
			break

	return JsonResponse({"suggestions": suggestions})


def _parse_decimal(value):
	if not value:
		return None
	try:
		return Decimal(value)
	except InvalidOperation:
		return None


def _parse_page_size(request, default_size):
	if (request.GET.get("reset_per_page") or "").strip() == "1":
		request.session.pop(PER_PAGE_SESSION_KEY, None)
		return default_size

	raw_value = (request.GET.get("per_page") or "").strip()
	if raw_value:
		try:
			page_size = int(raw_value)
		except ValueError:
			page_size = default_size
		if page_size in ALLOWED_PAGE_SIZES:
			request.session[PER_PAGE_SESSION_KEY] = page_size
			return page_size

	session_value = request.session.get(PER_PAGE_SESSION_KEY)
	if session_value in ALLOWED_PAGE_SIZES:
		return session_value

	return default_size


def _resolve_category_from_slug(category_slug):
	all_categories = Product.objects.order_by().values_list("category", flat=True).distinct()
	for item in all_categories:
		if slugify(item) == category_slug:
			return item
	return ""


def _build_results_context(request, forced_category=""):
	query = request.GET.get("q", "").strip()
	category = forced_category.strip() if forced_category else request.GET.get("category", "").strip()
	brand = request.GET.get("brand", "").strip()
	sort = request.GET.get("sort", "name_asc").strip()
	per_page = _parse_page_size(request, PRODUCTS_PER_PAGE)
	min_price = _parse_decimal(request.GET.get("min_price", "").strip())
	max_price = _parse_decimal(request.GET.get("max_price", "").strip())

	price_bounds = ProductPrice.objects.aggregate(global_min=Min("price"), global_max=Max("price"))
	price_floor = int(price_bounds["global_min"] or 0)
	price_ceiling = max(int(price_bounds["global_max"] or 0), 100000)

	if min_price is None:
		min_price = Decimal(price_floor)
	if max_price is None:
		max_price = Decimal(price_ceiling)
	min_price = max(min_price, Decimal("0"))
	max_price = min(max_price, Decimal(price_ceiling))
	if min_price > max_price:
		min_price, max_price = max_price, min_price

	base_products = Product.objects.prefetch_related("prices").annotate(lowest_price=Min("prices__price"))
	if query:
		base_products = base_products.filter(
			Q(name__icontains=query)
			| Q(brand__icontains=query)
			| Q(category__icontains=query)
		)
	if brand:
		base_products = base_products.filter(brand__icontains=brand)
	base_products = base_products.filter(lowest_price__gte=min_price, lowest_price__lte=max_price)

	category_counts_rows = (
		base_products.values("category")
		.annotate(total=Count("id"))
		.order_by("category")
	)
	category_counts = {row["category"]: row["total"] for row in category_counts_rows}
	category_totals = [
		{
			"name": row["category"],
			"count": row["total"],
			"slug": slugify(row["category"]),
		}
		for row in category_counts_rows
	]
	all_categories_total = sum(item["count"] for item in category_totals)

	products = base_products
	if category:
		products = products.filter(category__icontains=category)

	if sort == "price_low":
		products = products.order_by("lowest_price", "name")
	elif sort == "price_high":
		products = products.order_by("-lowest_price", "name")
	elif sort == "name_desc":
		products = products.order_by("-name")
	else:
		products = products.order_by("name")

	paginator = Paginator(products, per_page)
	page_obj = paginator.get_page(request.GET.get("page"))

	query_params = request.GET.copy()
	query_params["category"] = category
	if "page" in query_params:
		query_params.pop("page")
	pagination_query = query_params.urlencode()
	if pagination_query:
		pagination_query = f"&{pagination_query}"

	popular_categories = list(category_counts.keys())
	if not popular_categories:
		popular_categories = list(
			Product.objects.order_by().values_list("category", flat=True).distinct().order_by("category")
		)
	popular_brands = list(
		Product.objects.order_by().values_list("brand", flat=True).distinct().order_by("brand")
	)

	saved_filters = []
	if request.user.is_authenticated:
		raw_filters = SavedFilter.objects.filter(user=request.user)[:12]
		for saved in raw_filters:
			query_data = {
				"q": saved.query,
				"category": saved.category,
				"brand": saved.brand,
				"sort": saved.sort,
				"min_price": saved.min_price,
				"max_price": saved.max_price,
			}
			query_string = urlencode(query_data)
			saved.share_url = f"/results/?{query_string}"
			saved_filters.append(saved)

	return {
		"query": query,
		"category": category,
		"brand": brand,
		"sort": sort,
		"per_page": per_page,
		"allowed_page_sizes": ALLOWED_PAGE_SIZES,
		"min_price": int(min_price),
		"max_price": int(max_price),
		"price_floor": price_floor,
		"price_ceiling": price_ceiling,
		"products": page_obj.object_list,
		"page_obj": page_obj,
		"paginator": paginator,
		"pagination_query": pagination_query,
		"total_results": paginator.count,
		"all_categories_total": all_categories_total,
		"category_counts": category_counts,
		"category_totals": category_totals,
		"popular_categories": popular_categories,
		"popular_brands": popular_brands,
		"saved_filters": saved_filters,
	}


def _saved_filter_share_url(saved_filter):
	query_data = {
		"q": saved_filter.query,
		"category": saved_filter.category,
		"brand": saved_filter.brand,
		"sort": saved_filter.sort,
		"min_price": saved_filter.min_price,
		"max_price": saved_filter.max_price,
	}
	return f"/results/?{urlencode(query_data)}"


@login_required
def favorites_view(request):
	query = request.GET.get("q", "").strip()
	per_page = _parse_page_size(request, FAVORITES_PER_PAGE)
	favorites_qs = SavedFilter.objects.filter(user=request.user, is_pinned=True)
	
	if query:
		favorites_qs = favorites_qs.filter(Q(name__icontains=query) | Q(query__icontains=query))
	
	paginator = Paginator(favorites_qs, per_page)
	page_obj = paginator.get_page(request.GET.get("page"))
	favorites = list(page_obj.object_list)
	for saved in favorites:
		saved.share_url = _saved_filter_share_url(saved)

	query_params = request.GET.copy()
	if "page" in query_params:
		query_params.pop("page")
	pagination_query = query_params.urlencode()
	if pagination_query:
		pagination_query = f"&{pagination_query}"

	return render(
		request,
		"favorites.html",
		{
			"favorites": favorites,
			"total_favorites": paginator.count,
			"query": query,
			"per_page": per_page,
			"allowed_page_sizes": ALLOWED_PAGE_SIZES,
			"page_obj": page_obj,
			"paginator": paginator,
			"pagination_query": pagination_query,
		},
	)


def results_view(request):
	context = _build_results_context(request)
	return render(request, "results.html", context)


def category_results_view(request, category_slug):
	resolved_category = _resolve_category_from_slug(category_slug)
	if not resolved_category:
		raise Http404("Category not found")

	context = _build_results_context(request, forced_category=resolved_category)
	return render(request, "results.html", context)


@login_required
@require_POST
def save_filter_view(request):
	name = request.POST.get("name", "").strip()
	query = request.POST.get("query", "").strip()
	category = request.POST.get("category", "").strip()
	brand = request.POST.get("brand", "").strip()
	sort = request.POST.get("sort", "name_asc").strip() or "name_asc"
	min_price = _parse_decimal(request.POST.get("min_price", "").strip())
	max_price = _parse_decimal(request.POST.get("max_price", "").strip())

	if min_price is None:
		min_price = Decimal("0")
	if max_price is None:
		max_price = Decimal("100000")

	if not name:
		label_seed = query or category or brand or "Smart Filter"
		name = f"{label_seed} ({sort})"

	SavedFilter.objects.update_or_create(
		user=request.user,
		name=name,
		defaults={
			"query": query,
			"category": category,
			"brand": brand,
			"sort": sort,
			"min_price": min_price,
			"max_price": max_price,
		},
	)
	messages.success(request, "Filter saved to your account.")
	return redirect(request.POST.get("next") or "/results/")


@login_required
@require_POST
def delete_filter_view(request, filter_id):
	deleted_count, _ = SavedFilter.objects.filter(user=request.user, id=filter_id).delete()
	if deleted_count:
		messages.success(request, "Saved filter removed.")
	else:
		messages.error(request, "Saved filter not found.")
	return redirect(request.POST.get("next") or "/results/")


@login_required
@require_POST
def toggle_pin_filter_view(request, filter_id):
	filter_obj = get_object_or_404(SavedFilter, user=request.user, id=filter_id)
	filter_obj.is_pinned = not filter_obj.is_pinned
	filter_obj.save(update_fields=["is_pinned", "updated_at"])
	message = "Filter pinned to top." if filter_obj.is_pinned else "Filter unpinned."
	messages.success(request, message)
	return redirect(request.POST.get("next") or "/results/")


def news_list_view(request):
	query = request.GET.get("q", "").strip()
	category = request.GET.get("category", "").strip()
	per_page = _parse_page_size(request, NEWS_PER_PAGE)
	news_items = ProductNews.objects.filter(is_published=True, published_at__lte=timezone.now())
	if query:
		news_items = news_items.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(body__icontains=query))
	
	if category and category in dict(ProductNews.CATEGORY_CHOICES):
		news_items = news_items.filter(news_category=category)
	
	# Get all categories with counts for filtering UI
	all_categories = (
		ProductNews.objects
		.filter(is_published=True, published_at__lte=timezone.now())
		.values_list("news_category", flat=True)
		.distinct()
	)
	category_data = [
		{
			"value": cat,
			"label": dict(ProductNews.CATEGORY_CHOICES).get(cat, cat),
			"count": ProductNews.objects.filter(is_published=True, news_category=cat, published_at__lte=timezone.now()).count(),
		}
		for cat in all_categories
	]
	
	paginator = Paginator(news_items, per_page)
	page_obj = paginator.get_page(request.GET.get("page"))
	return render(
		request,
		"news_list.html",
		{
			"news_items": page_obj.object_list,
			"page_obj": page_obj,
			"paginator": paginator,
			"per_page": per_page,
			"allowed_page_sizes": ALLOWED_PAGE_SIZES,
			"categories": category_data,
			"selected_category": category,
			"query": query,
		},
	)


def news_detail_view(request, slug):
	news_item = get_object_or_404(
		ProductNews,
		slug=slug,
		is_published=True,
		published_at__lte=timezone.now(),
	)
	related_news = ProductNews.objects.filter(is_published=True, published_at__lte=timezone.now()).exclude(id=news_item.id)[:3]
	edit_url = None
	if request.user.is_staff:
		edit_url = f"/admin/products/productnews/{news_item.id}/change/"
	return render(
		request,
		"news_detail.html",
		{"news_item": news_item, "related_news": related_news, "edit_url": edit_url},
	)


def product_detail_view(request, product_id):
	product = get_object_or_404(Product.objects.prefetch_related("prices"), pk=product_id)
	prices = ProductPrice.objects.filter(product=product).order_by("price", "platform")
	best_deal = prices.first()
	alternatives = (
		AlternativeProduct.objects.select_related("alternative_product")
		.filter(main_product=product, price_difference__gt=0)
		.order_by("-price_difference", "-similarity_score")
	)

	context = {
		"product": product,
		"prices": prices,
		"best_deal": best_deal,
		"alternatives": alternatives,
	}
	return render(request, "product_detail.html", context)
