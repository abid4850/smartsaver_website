from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Product, ProductNews

class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'

    def items(self):
        return ['home', 'results', 'news_list']

    def location(self, item):
        return reverse(item)

class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Product.objects.all()

    def location(self, obj):
        return reverse('product_detail', args=[obj.id])

class NewsSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return ProductNews.objects.filter(is_published=True)

    def location(self, obj):
        return reverse('news_detail', args=[obj.slug])
