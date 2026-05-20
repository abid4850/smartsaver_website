import serpapi
from django.conf import settings


def get_product_image_via_serpapi(product_name: str, brand: str) -> str | None:
    """Query SerpAPI Google Images and return first valid original image URL.

    Uses the top-level `serpapi.search` helper provided by the installed package.
    Returns None if no key or no result.
    """
    api_key = getattr(settings, 'SERPAPI_KEY', '')
    if not api_key:
        return None

    query = f"{brand} {product_name} product official"
    try:
        results = serpapi.search(q=query, tbm='isch', api_key=api_key)
        # SerpResults behaves like a dict
        data = results.as_dict() if hasattr(results, 'as_dict') else dict(results)
        images = data.get('images_results') or []
        for img in images[:5]:
            url = img.get('original') or img.get('thumbnail') or img.get('source')
            if url:
                return url
    except Exception:
        return None
    return None
