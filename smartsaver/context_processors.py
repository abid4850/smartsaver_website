from django.conf import settings

def site_settings(request):
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'SmartSaver'),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
    }
