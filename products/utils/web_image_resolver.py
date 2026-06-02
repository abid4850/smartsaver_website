from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote, urljoin

import requests

from .serpapi_client import get_product_image_via_serpapi

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SmartSaver/1.0)"}


def _is_placeholder_url(url: str | None) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return any(
        marker in lowered
        for marker in (
            "dummyimage.com",
            "via.placeholder.com",
            "placeholder",
            "/static/smartsaver/product-placeholder.svg",
            "/static/smartsaver/news-general.svg",
        )
    )


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(unescape(value).split())


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(token) > 1}


def _score_match(name: str, brand: str, candidate_title: str) -> int:
    name_tokens = _tokenize(name)
    brand_tokens = _tokenize(brand)
    title_tokens = _tokenize(candidate_title)

    if not title_tokens:
        return 0

    numeric_tokens = {token for token in name_tokens if any(ch.isdigit() for ch in token)}
    numeric_score = len(numeric_tokens & title_tokens)
    if numeric_tokens and numeric_score == 0:
        return 0

    overlap = len(name_tokens & title_tokens)
    brand_hits = len(brand_tokens & title_tokens)
    if overlap == 0:
        return 0

    return overlap * 2 + brand_hits * 3 + numeric_score * 2


def _candidate_queries(name: str, brand: str, category: str) -> list[str]:
    cleaned_name = re.sub(r"\([^)]*\)", " ", name)
    cleaned_name = re.sub(r"[^A-Za-z0-9]+", " ", cleaned_name).strip()
    compact_name = re.sub(r"[^A-Za-z0-9]+", "", cleaned_name)
    category_hint = category.rstrip("s").lower()

    candidates = [
        cleaned_name,
        f"{cleaned_name} {brand}",
        f"{brand} {cleaned_name}",
        f"{cleaned_name} {category_hint}",
        f"{brand} {category_hint}",
        f"{compact_name} {category_hint}",
    ]
    if compact_name and compact_name != cleaned_name:
        candidates.append(compact_name)

    deduped: list[str] = []
    for query in candidates:
        query = " ".join(query.split())
        if query and query not in deduped:
            deduped.append(query)
    return deduped


def _fetch_json(url: str) -> dict:
    response = requests.get(url, headers=HEADERS, timeout=12)
    response.raise_for_status()
    return response.json()


def _best_wikipedia_image(name: str, brand: str, category: str) -> str:
    best_url = ""
    best_score = 0
    for query in _candidate_queries(name, brand, category):
        search_url = "https://en.wikipedia.org/w/rest.php/v1/search/title?q=" + quote(query) + "&limit=5"
        try:
            data = _fetch_json(search_url)
        except Exception:
            continue

        for page in data.get("pages") or []:
            title = page.get("title")
            if not title:
                continue

            score = _score_match(name, brand, title)
            if score < 4:
                continue

            summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"))
            try:
                summary = _fetch_json(summary_url)
            except Exception:
                continue

            image_url = summary.get("originalimage", {}).get("source") or summary.get("thumbnail", {}).get("source")
            if not image_url or ".svg" in image_url.lower() or "vector" in image_url.lower():
                continue

            if score > best_score:
                best_score = score
                best_url = image_url
    return best_url


def _best_commons_image(name: str, brand: str, category: str) -> str:
    best_url = ""
    best_score = 0
    for query in _candidate_queries(name, brand, category):
        search_url = (
            "https://commons.wikimedia.org/w/api.php?action=query&list=search&srnamespace=6"
            + "&srlimit=5&format=json&srsearch="
            + quote(query)
        )
        try:
            data = _fetch_json(search_url)
        except Exception:
            continue

        for result in data.get("query", {}).get("search") or []:
            title = result.get("title")
            if not title:
                continue

            score = _score_match(name, brand, title)
            if score < 4:
                continue

            info_url = (
                "https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url"
                + "&format=json&titles="
                + quote(title)
            )
            try:
                info = _fetch_json(info_url)
            except Exception:
                continue

            for page in info.get("query", {}).get("pages", {}).values():
                for image_info in page.get("imageinfo", []):
                    image_url = image_info.get("url")
                    if not image_url or ".svg" in image_url.lower() or "vector" in image_url.lower():
                        continue
                    if score > best_score:
                        best_score = score
                        best_url = image_url
    return best_url


def _best_openverse_image(name: str, brand: str, category: str) -> str:
    best_url = ""
    best_score = 0
    for query in _candidate_queries(name, brand, category):
        openverse_url = "https://api.openverse.org/v1/images/?q=" + quote(query) + "&page_size=15"
        try:
            data = _fetch_json(openverse_url)
        except Exception:
            continue

        for result in data.get("results") or []:
            title = result.get("title") or ""
            score = _score_match(name, brand, title)
            if score < 4:
                continue
            image_url = result.get("url") or result.get("thumbnail") or ""
            if image_url and score > best_score:
                best_score = score
                best_url = image_url
    return best_url


def resolve_product_image(name: str, brand: str, category: str = "") -> str:
    image_url = get_product_image_via_serpapi(name, brand)
    if image_url and not _is_placeholder_url(image_url):
        return image_url

    image_url = _best_wikipedia_image(name, brand, category)
    if image_url:
        return image_url

    image_url = _best_commons_image(name, brand, category)
    if image_url:
        return image_url

    return _best_openverse_image(name, brand, category)


def fetch_page_metadata(page_url: str) -> dict[str, str]:
    response = requests.get(page_url, headers=HEADERS, timeout=12)
    response.raise_for_status()

    html = response.text
    metadata = {"title": "", "description": "", "image_url": "", "canonical_url": page_url}

    def read_meta(*names: str) -> str:
        pattern = re.compile(
            r'<meta[^>]+(?:property|name)=["\'](?:' + "|".join(re.escape(name) for name in names) + r')["\'][^>]+content=["\']([^"\']+)["\']',
            re.I,
        )
        match = pattern.search(html)
        return unescape(match.group(1)).strip() if match else ""

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    metadata["title"] = read_meta("og:title", "twitter:title") or (_strip_tags(title_match.group(1)) if title_match else "")
    metadata["description"] = read_meta("og:description", "description", "twitter:description")
    image_url = read_meta("og:image", "twitter:image", "twitter:image:src")
    if image_url:
        metadata["image_url"] = urljoin(page_url, image_url)

    canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
    if canonical_match:
        metadata["canonical_url"] = urljoin(page_url, canonical_match.group(1))

    if not metadata["description"]:
        paragraph_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.I | re.S)
        if paragraph_match:
            metadata["description"] = _strip_tags(paragraph_match.group(1))

    if not metadata["image_url"]:
        for script_match in re.finditer(r'<script[^>]+type=["\'][^"\']*ld\+json[^"\']*["\'][^>]*>(.*?)</script>', html, re.I | re.S):
            raw_value = script_match.group(1).strip()
            if not raw_value:
                continue
            try:
                payload = json.loads(raw_value)
            except Exception:
                continue

            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                image_value = candidate.get("image")
                if isinstance(image_value, dict):
                    image_value = image_value.get("url") or image_value.get("contentUrl")
                if isinstance(image_value, list) and image_value:
                    image_value = image_value[0]
                if isinstance(image_value, str) and image_value:
                    metadata["image_url"] = urljoin(page_url, image_value)
                    break
            if metadata["image_url"]:
                break

    return metadata


def resolve_page_image(page_url: str, query: str = "", category: str = "") -> str:
    try:
        metadata = fetch_page_metadata(page_url)
    except Exception:
        metadata = {}

    image_url = metadata.get("image_url") or ""
    if image_url and not _is_placeholder_url(image_url):
        return image_url

    search_term = query or metadata.get("title") or page_url
    if search_term:
        image_url = resolve_product_image(search_term, "", category)
        if image_url and not _is_placeholder_url(image_url):
            return image_url

    return ""