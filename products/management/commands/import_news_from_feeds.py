from __future__ import annotations

import re
from defusedxml import ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from products.models import Product
from products.models import ProductNews
from products.utils.web_image_resolver import resolve_page_image


class Command(BaseCommand):
    help = "Import recent tech/news stories from public RSS feeds and attach web images."

    FEEDS = [
        {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "Engadget", "url": "https://www.engadget.com/rss.xml"},
        {"name": "CNET", "url": "https://www.cnet.com/rss/news/"},
    ]

    HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SmartSaverNewsSync/1.0)"}

    def add_arguments(self, parser):
        parser.add_argument(
            "--feeds",
            type=str,
            default="",
            help="Comma-separated feed names to import (default: all configured feeds)",
        )
        parser.add_argument(
            "--limit-per-feed",
            type=int,
            default=5,
            help="Maximum number of stories to import per feed",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview imports without writing to the database",
        )

    def handle(self, *args, **options):
        limit_per_feed = max(options["limit_per_feed"], 0)
        dry_run = options["dry_run"]
        selected_feeds = self._selected_feeds(options["feeds"])

        if not selected_feeds:
            self.stdout.write(self.style.WARNING("No feeds selected."))
            return

        created = 0
        updated = 0
        skipped = 0

        for feed in selected_feeds:
            entries = self._load_feed_entries(feed["url"])
            if not entries:
                self.stdout.write(self.style.WARNING(f"No entries found for {feed['name']}."))
                continue

            for entry in entries[:limit_per_feed or len(entries)]:
                title = entry["title"].strip()
                if not title:
                    skipped += 1
                    continue

                summary = entry["summary"].strip() or title
                link = entry["link"].strip()
                published_at = self._parse_datetime(entry.get("published"))
                news_category = self._classify_story(title, summary)
                image_url = resolve_page_image(link, query=title, category=news_category) if link else ""
                product = self._match_product(title, summary)

                slug_base = slugify(f"{feed['name']} {title}") or "news-item"
                slug = slug_base
                counter = 2
                while ProductNews.objects.filter(slug=slug).exists() and not dry_run:
                    slug = f"{slug_base}-{counter}"
                    counter += 1

                body_parts = [summary]
                if link:
                    body_parts.append(f"Source: {link}")
                body = "\n\n".join(body_parts)

                if dry_run:
                    self.stdout.write(
                        f"[DRY] {feed['name']}: {title} | {news_category} | "
                        f"image={'yes' if image_url else 'no'}"
                    )
                    continue

                news_item, was_created = ProductNews.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "title": title,
                        "summary": summary,
                        "body": body,
                        "image_url": image_url,
                        "news_category": news_category,
                        "product": product,
                        "is_published": True,
                        "published_at": published_at,
                    },
                )

                if was_created:
                    created += 1
                else:
                    updated += 1

                self.stdout.write(f"Imported: {news_item.title}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"News sync complete. created={created}, updated={updated}, skipped={skipped}."
            )
        )

    def _selected_feeds(self, raw_value: str) -> list[dict[str, str]]:
        if not raw_value.strip():
            return self.FEEDS

        requested = {token.strip().lower() for token in raw_value.split(",") if token.strip()}
        return [
            feed
            for feed in self.FEEDS
            if feed["name"].lower() in requested or feed["url"].lower() in requested
        ]

    def _load_feed_entries(self, feed_url: str) -> list[dict[str, str]]:
        response = requests.get(feed_url, headers=self.HEADERS, timeout=15)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall(".//item") or root.findall(".//{*}entry")
        entries: list[dict[str, str]] = []

        for item in items:
            title = self._tag_text(item, "title")
            summary = self._tag_text(item, "description") or self._tag_text(item, "summary")
            if not summary:
                content = self._tag_text(item, "content")
                summary = re.sub(r"<[^>]+>", "", content)

            link = self._tag_link(item)
            published = (
                self._tag_text(item, "pubDate")
                or self._tag_text(item, "published")
                or self._tag_text(item, "updated")
            )

            entries.append(
                {
                    "title": title or "",
                    "summary": summary or "",
                    "link": link or "",
                    "published": published or "",
                }
            )

        return entries

    def _tag_text(self, item, tag_name: str) -> str:
        tag = item.find(tag_name) or item.find(f"{{*}}{tag_name}")
        if tag is None:
            return ""
        text = tag.text or ""
        return re.sub(r"<[^>]+>", " ", text).strip()

    def _tag_link(self, item) -> str:
        link_tag = item.find("link") or item.find("{*}link")
        if not link_tag:
            return ""
        return link_tag.attrib.get("href") or (link_tag.text or "").strip()

    def _parse_datetime(self, value: str) -> datetime:
        if not value:
            return timezone.now()

        try:
            parsed = parsedate_to_datetime(value)
        except Exception:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return timezone.now()

        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def _classify_story(self, title: str, summary: str) -> str:
        text = f"{title} {summary}".lower()

        if any(token in text for token in ("launch", "announces", "introduces", "unveils", "debut")):
            return "launches"
        if any(token in text for token in ("price", "pricing", "sale", "deal", "discount", "save")):
            return "deals"
        if any(token in text for token in ("review", "hands-on", "analysis", "benchmark")):
            return "reviews"
        if any(token in text for token in ("update", "software", "chip", "camera", "battery", "display", "ai")):
            return "tech"
        return "general"

    def _match_product(self, title: str, summary: str):
        text = f"{title} {summary}".lower()
        best_product = None
        best_score = 0

        for product in Product.objects.all().only("id", "name", "brand", "category"):
            score = 0
            name_tokens = self._tokenize(product.name)
            title_tokens = self._tokenize(title)
            summary_tokens = self._tokenize(summary)
            brand_tokens = self._tokenize(product.brand)

            if product.brand.lower() in text:
                score += 3

            score += len(name_tokens & title_tokens) * 2
            score += len(name_tokens & summary_tokens)
            score += len(brand_tokens & title_tokens) * 3

            if score > best_score:
                best_score = score
                best_product = product

        return best_product if best_score >= 4 else None

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(token) > 1}