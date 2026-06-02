"""
URL configuration for smartsaver project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from products.sitemaps import StaticViewSitemap, ProductSitemap, NewsSitemap
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    # legacy admin alias: /admin/blog -> redirect to product news admin
    path('admin/blog', RedirectView.as_view(url='/admin/products/productnews/')),
    path('admin/blog/', RedirectView.as_view(url='/admin/products/productnews/')),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('users/', include('users.urls')),
    path('', include('products.urls')),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
    path('sitemap.xml', sitemap, {'sitemaps': {
        'static': StaticViewSitemap(),
        'products': ProductSitemap(),
        'news': NewsSitemap(),
    }}, name='django.contrib.sitemaps.views.sitemap'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
