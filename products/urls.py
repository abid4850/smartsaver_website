from django.urls import path
from django.views.generic import TemplateView
from . import views

from .views import ProductAlternativesAPIView
from .views import ProductComparisonAPIView
from .views import ProductNewsAPIView
from .views import ProductSearchAPIView
from .views import autocomplete_api
from .views import category_results_view
from .views import delete_filter_view
from .views import home_view
from .views import news_detail_view
from .views import news_list_view
from .views import favorites_view
from .views import product_detail_view
from .views import results_view
from .views import save_filter_view
from .views import toggle_pin_filter_view

urlpatterns = [
    path("", home_view, name="home"),
    path("deals/promo/", TemplateView.as_view(template_name="promotional_deals.html"), name="promotional_deals"),
    path("results/", results_view, name="results"),
    path("favorites/", favorites_view, name="favorites"),
    path("news/", news_list_view, name="news_list"),
    path("news/<slug:slug>/", news_detail_view, name="news_detail"),
    path("category/<slug:category_slug>/", category_results_view, name="results_by_category"),
    path("products/<int:product_id>/", product_detail_view, name="product_detail"),
    path('generate-placeholder/<int:product_id>/', views.generate_placeholder_view, name='generate_placeholder'),
    path('image-proxy/', views.image_proxy_view, name='image_proxy'),
    path("api/search/", ProductSearchAPIView.as_view(), name="api_search"),
    path("api/news/", ProductNewsAPIView.as_view(), name="api_news"),
    path("api/autocomplete/", autocomplete_api, name="api_autocomplete"),
    path("api/compare/<int:product_id>/", ProductComparisonAPIView.as_view(), name="api_compare"),
    path(
        "api/alternatives/<int:product_id>/",
        ProductAlternativesAPIView.as_view(),
        name="api_alternatives",
    ),
    path("filters/save/", save_filter_view, name="save_filter"),
    path("filters/<int:filter_id>/delete/", delete_filter_view, name="delete_filter"),
    path("filters/<int:filter_id>/pin/", toggle_pin_filter_view, name="toggle_pin_filter"),
]