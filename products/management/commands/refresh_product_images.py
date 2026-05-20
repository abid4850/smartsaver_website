import json
import re
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand
from django.utils import timezone

from products.models import Product


class Command(BaseCommand):
    help = "Resolve product images via Wikipedia/Openverse and update image_url."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of products to process",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Resolve images even when a non-placeholder image_url exists",
        )
        parser.add_argument(
            "--process",
            action="store_true",
            help="Download and generate thumbnails after updating image_url",
        )

    def _fetch_json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _tokenize(self, text):
        return {token for token in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(token) > 1}

    def _score_match(self, name, brand, candidate_title):
        name_tokens = self._tokenize(name)
        brand_tokens = self._tokenize(brand)
        title_tokens = self._tokenize(candidate_title)

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

        # Weight name overlap highest, then brand, then numeric tokens.
        return overlap * 2 + brand_hits * 3 + numeric_score * 2

    def _candidate_queries(self, name, brand, category):
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

        deduped = []
        for query in candidates:
            query = " ".join(query.split())
            if query and query not in deduped:
                deduped.append(query)
        return deduped

    def _best_wikipedia_image(self, name, brand, category):
        best_url = ""
        best_score = 0
        candidates = self._candidate_queries(name, brand, category)

        for query in candidates:
            search_url = (
                "https://en.wikipedia.org/w/rest.php/v1/search/title?q="
                + urllib.parse.quote(query)
                + "&limit=5"
            )
            try:
                data = self._fetch_json(search_url)
            except Exception:
                continue

            pages = data.get("pages") or []
            for page in pages:
                title = page.get("title")
                if not title:
                    continue

                score = self._score_match(name, brand, title)
                if score < 4:
                    continue

                summary_url = (
                    "https://en.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(title.replace(" ", "_"))
                )
                try:
                    summary = self._fetch_json(summary_url)
                except Exception:
                    continue

                image_url = (
                    summary.get("originalimage", {}).get("source")
                    or summary.get("thumbnail", {}).get("source")
                )
                if not image_url:
                    continue

                if ".svg" in image_url.lower() or "vector" in image_url.lower():
                    continue

                if score > best_score:
                    best_score = score
                    best_url = image_url

        return best_url

    def _best_commons_image(self, name, brand, category):
        best_url = ""
        best_score = 0
        candidates = self._candidate_queries(name, brand, category)

        for query in candidates:
            search_url = (
                "https://commons.wikimedia.org/w/api.php?action=query&list=search&srnamespace=6"
                + "&srlimit=5&format=json&srsearch="
                + urllib.parse.quote(query)
            )
            try:
                data = self._fetch_json(search_url)
            except Exception:
                continue

            results = data.get("query", {}).get("search") or []
            for result in results:
                title = result.get("title")
                if not title:
                    continue

                score = self._score_match(name, brand, title)
                if score < 4:
                    continue

                info_url = (
                    "https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url"
                    + "&format=json&titles="
                    + urllib.parse.quote(title)
                )
                try:
                    info = self._fetch_json(info_url)
                except Exception:
                    continue

                pages = info.get("query", {}).get("pages", {})
                for page in pages.values():
                    imageinfo = page.get("imageinfo", [])
                    if not imageinfo:
                        continue
                    image_url = imageinfo[0].get("url")
                    if not image_url:
                        continue
                    if ".svg" in image_url.lower() or "vector" in image_url.lower():
                        continue
                    if score > best_score:
                        best_score = score
                        best_url = image_url

        return best_url

    def _best_openverse_image(self, name, brand, category):
        best_url = ""
        best_score = 0
        candidates = self._candidate_queries(name, brand, category)

        for query in candidates:
            openverse_url = (
                "https://api.openverse.org/v1/images/?q="
                + urllib.parse.quote(query)
                + "&page_size=15"
            )
            try:
                data = self._fetch_json(openverse_url)
            except Exception:
                continue

            results = data.get("results") or []
            for result in results:
                title = (result.get("title") or "")
                score = self._score_match(name, brand, title)
                if score < 4:
                    continue
                image_url = result.get("url") or result.get("thumbnail") or ""
                if not image_url:
                    continue
                if score > best_score:
                    best_score = score
                    best_url = image_url

        return best_url

    def _resolve_product_image(self, name, brand, category):
        image_url = self._best_wikipedia_image(name, brand, category)
        if image_url:
            return image_url

        image_url = self._best_commons_image(name, brand, category)
        if image_url:
            return image_url

        return self._best_openverse_image(name, brand, category)

    def _is_placeholder(self, url):
        if not url:
            return True
        url = url.lower()
        return "dummyimage.com" in url or "via.placeholder.com" in url

    def handle(self, *args, **options):
        limit = options.get("limit")
        force = options.get("force")
        do_process = options.get("process")

        products = Product.objects.order_by("id")
        if limit:
            products = products[:limit]

        total = products.count()
        updated = 0
        skipped = 0
        failed = 0

        self.stdout.write(f"Resolving images for {total} products...")

        for idx, product in enumerate(products, 1):
            if not force and product.image_url and not self._is_placeholder(product.image_url):
                skipped += 1
                continue

            resolved = self._resolve_product_image(product.name, product.brand, product.category)
            if not resolved:
                failed += 1
                self.stdout.write(f"[{idx}/{total}] No match for {product.name}")
                continue

            Product.objects.filter(pk=product.pk).update(
                image_url=resolved,
                updated_at=timezone.now(),
            )
            product.image_url = resolved
            updated += 1

            if do_process:
                product.download_and_process_image()

            self.stdout.write(f"[{idx}/{total}] OK {product.name}")

        self.stdout.write(
            f"Done: {updated} updated, {skipped} skipped, {failed} no-match"
        )
