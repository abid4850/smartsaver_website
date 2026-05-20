from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError

from comparisons.models import ProductPrice
from products.models import Product


class Command(BaseCommand):
    help = (
        "Automatically add more products with marketplace prices "
        "(Amazon/eBay/BestBuy/Newegg/etc.)."
    )

    MARKET_ALIASES = {
        "amazon": "Amazon",
        "amzon": "Amazon",
        "ebay": "eBay",
        "eboy": "eBay",
        "bestbuy": "BestBuy",
        "best buy": "BestBuy",
        "bustbuy": "BestBuy",
        "newegg": "Newegg",
        "newsage": "Newegg",
        "walmart": "Walmart",
        "target": "Target",
        "aliexpress": "AliExpress",
        "ali express": "AliExpress",
    }

    URL_PATTERNS = {
        "Amazon": "https://www.amazon.com/s?k={query}",
        "eBay": "https://www.ebay.com/sch/i.html?_nkw={query}",
        "BestBuy": "https://www.bestbuy.com/site/searchpage.jsp?st={query}",
        "Newegg": "https://www.newegg.com/p/pl?d={query}",
        "Walmart": "https://www.walmart.com/search?q={query}",
        "Target": "https://www.target.com/s?searchTerm={query}",
        "AliExpress": "https://www.aliexpress.com/w/wholesale-{query}.html",
    }

    PRODUCT_CATALOG = [
        {"name": "iPhone 16 Pro", "brand": "Apple", "category": "Smartphones", "base_price": "1099.00", "markets": ["Amazon", "eBay", "BestBuy"]},
        {"name": "Galaxy S25 Ultra", "brand": "Samsung", "category": "Smartphones", "base_price": "1299.00", "markets": ["Amazon", "eBay", "BestBuy", "Newegg"]},
        {"name": "Pixel 10 Pro", "brand": "Google", "category": "Smartphones", "base_price": "999.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "OnePlus 13", "brand": "OnePlus", "category": "Smartphones", "base_price": "899.00", "markets": ["Amazon", "eBay", "AliExpress"]},
        {"name": "Xiaomi 15 Pro", "brand": "Xiaomi", "category": "Smartphones", "base_price": "949.00", "markets": ["Amazon", "AliExpress", "eBay"]},
        {"name": "Nothing Phone 3", "brand": "Nothing", "category": "Smartphones", "base_price": "649.00", "markets": ["Amazon", "eBay", "BestBuy"]},

        {"name": "MacBook Pro 16 M4", "brand": "Apple", "category": "Laptops", "base_price": "2699.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Dell XPS 14", "brand": "Dell", "category": "Laptops", "base_price": "1799.00", "markets": ["Amazon", "BestBuy", "Newegg"]},
        {"name": "HP Omen Transcend 14", "brand": "HP", "category": "Laptops", "base_price": "1699.00", "markets": ["Amazon", "BestBuy", "Newegg"]},
        {"name": "Lenovo Yoga Pro 9i", "brand": "Lenovo", "category": "Laptops", "base_price": "1899.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "ASUS ProArt P16", "brand": "ASUS", "category": "Laptops", "base_price": "2199.00", "markets": ["Amazon", "BestBuy", "Newegg"]},
        {"name": "Acer Predator Helios Neo 16", "brand": "Acer", "category": "Laptops", "base_price": "1499.00", "markets": ["Amazon", "BestBuy", "Newegg"]},

        {"name": "iPad Mini 7", "brand": "Apple", "category": "Tablets", "base_price": "599.00", "markets": ["Amazon", "BestBuy", "Target", "eBay"]},
        {"name": "Galaxy Tab S10+", "brand": "Samsung", "category": "Tablets", "base_price": "1099.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "OnePlus Pad 3", "brand": "OnePlus", "category": "Tablets", "base_price": "549.00", "markets": ["Amazon", "eBay", "AliExpress"]},
        {"name": "Lenovo Tab Extreme 2", "brand": "Lenovo", "category": "Tablets", "base_price": "799.00", "markets": ["Amazon", "BestBuy", "Walmart"]},

        {"name": "Sony WH-1000XM6", "brand": "Sony", "category": "Headphones", "base_price": "399.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Bose QuietComfort Ultra Earbuds 2", "brand": "Bose", "category": "Headphones", "base_price": "329.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Sennheiser Momentum 5", "brand": "Sennheiser", "category": "Headphones", "base_price": "449.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Anker Soundcore Liberty 5", "brand": "Anker", "category": "Headphones", "base_price": "149.00", "markets": ["Amazon", "eBay", "Walmart"]},

        {"name": "Apple Watch Series 11", "brand": "Apple", "category": "Smartwatches", "base_price": "449.00", "markets": ["Amazon", "BestBuy", "Target", "eBay"]},
        {"name": "Garmin Fenix 8", "brand": "Garmin", "category": "Smartwatches", "base_price": "899.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Galaxy Watch 8 Pro", "brand": "Samsung", "category": "Smartwatches", "base_price": "499.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Pixel Watch 4", "brand": "Google", "category": "Smartwatches", "base_price": "399.00", "markets": ["Amazon", "BestBuy", "eBay"]},

        {"name": "NVIDIA GeForce RTX 5090", "brand": "NVIDIA", "category": "PC Components", "base_price": "1999.00", "markets": ["Amazon", "Newegg", "eBay", "BestBuy"]},
        {"name": "AMD Ryzen 9 9950X3D", "brand": "AMD", "category": "PC Components", "base_price": "799.00", "markets": ["Amazon", "Newegg", "BestBuy"]},
        {"name": "Intel Core Ultra 9 285K", "brand": "Intel", "category": "PC Components", "base_price": "699.00", "markets": ["Amazon", "Newegg", "BestBuy"]},
        {"name": "Samsung 990 Pro 4TB", "brand": "Samsung", "category": "PC Components", "base_price": "369.00", "markets": ["Amazon", "Newegg", "BestBuy", "eBay"]},

        {"name": "LG OLED C5 65", "brand": "LG", "category": "TVs", "base_price": "2499.00", "markets": ["Amazon", "BestBuy", "Walmart"]},
        {"name": "Samsung S95D OLED 65", "brand": "Samsung", "category": "TVs", "base_price": "2799.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Sony Bravia 9 75", "brand": "Sony", "category": "TVs", "base_price": "4499.00", "markets": ["Amazon", "BestBuy", "Walmart"]},

        {"name": "Canon EOS R5 Mark II", "brand": "Canon", "category": "Cameras", "base_price": "4299.00", "markets": ["Amazon", "eBay", "BestBuy", "Newegg"]},
        {"name": "Nikon Z6 III", "brand": "Nikon", "category": "Cameras", "base_price": "2499.00", "markets": ["Amazon", "BestBuy", "eBay"]},
        {"name": "Fujifilm X100VI", "brand": "Fujifilm", "category": "Cameras", "base_price": "1599.00", "markets": ["Amazon", "eBay", "BestBuy"]},

        {"name": "PlayStation 5 Pro", "brand": "Sony", "category": "Gaming Consoles", "base_price": "699.00", "markets": ["Amazon", "BestBuy", "Target", "Walmart"]},
        {"name": "Nintendo Switch 2", "brand": "Nintendo", "category": "Gaming Consoles", "base_price": "449.00", "markets": ["Amazon", "BestBuy", "Target", "eBay"]},
        {"name": "Xbox Series X 2TB", "brand": "Microsoft", "category": "Gaming Consoles", "base_price": "649.00", "markets": ["Amazon", "BestBuy", "Walmart"]},
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--markets",
            type=str,
            default="amazon,ebay,bestbuy,newegg",
            help="Comma-separated marketplaces (supports aliases like amzon, eboy, bustbuy, newsage)",
        )
        parser.add_argument(
            "--count-per-market",
            type=int,
            default=8,
            help="Max products to add per selected marketplace (0 = all available)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be added without writing to the database",
        )

    def handle(self, *args, **options):
        requested_markets = self._normalize_markets(options["markets"])
        count_per_market = options["count_per_market"]
        dry_run = options["dry_run"]

        if count_per_market < 0:
            raise CommandError("--count-per-market cannot be negative")

        if not requested_markets:
            raise CommandError("No valid marketplaces provided")

        selected_products = self._pick_products(requested_markets, count_per_market)
        if not selected_products:
            self.stdout.write(self.style.WARNING("No products matched the selected marketplaces."))
            return

        created_products = 0
        updated_products = 0
        created_prices = 0
        updated_prices = 0

        for item in selected_products:
            defaults = {
                "category": item["category"],
                "description": (
                    f"Auto-added product for marketplace comparison across "
                    f"{', '.join(item['markets'])}."
                ),
                "image_source": "fallback",
            }

            if dry_run:
                self.stdout.write(f"[DRY] product: {item['brand']} {item['name']}")
                for market in item["markets"]:
                    if market in requested_markets:
                        price = self._price_for_market(Decimal(item["base_price"]), market, item["name"])
                        self.stdout.write(f"[DRY]   {market}: ${price}")
                continue

            product = Product.objects.filter(name=item["name"], brand=item["brand"]).first()
            if product:
                Product.objects.filter(pk=product.pk).update(
                    category=defaults["category"],
                    description=defaults["description"],
                    image_source=defaults["image_source"],
                    image_url=self._white_image(item["name"]),
                )
                product.refresh_from_db(fields=["id", "name", "brand"])
                updated_products += 1
            else:
                product = Product.objects.create(
                    name=item["name"],
                    brand=item["brand"],
                    category=defaults["category"],
                    description=defaults["description"],
                    image_source=defaults["image_source"],
                )
                Product.objects.filter(pk=product.pk).update(image_url=self._white_image(item["name"]))
                created_products += 1

            for market in item["markets"]:
                if market not in requested_markets:
                    continue
                price = self._price_for_market(Decimal(item["base_price"]), market, item["name"])
                product_url = self._market_url(market, item["name"], item["brand"])

                _, price_created = ProductPrice.objects.update_or_create(
                    product=product,
                    platform=market,
                    defaults={"price": price, "product_url": product_url},
                )
                if price_created:
                    created_prices += 1
                else:
                    updated_prices += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Auto import complete. "
                f"Products created={created_products}, updated={updated_products}; "
                f"Prices created={created_prices}, updated={updated_prices}."
            )
        )

    def _normalize_markets(self, raw_value: str) -> list[str]:
        normalized = []
        for token in raw_value.split(","):
            key = token.strip().lower()
            if not key:
                continue
            canonical = self.MARKET_ALIASES.get(key)
            if canonical and canonical not in normalized:
                normalized.append(canonical)
        return normalized

    def _pick_products(self, markets: list[str], count_per_market: int) -> list[dict]:
        selected: list[dict] = []
        selected_names: set[str] = set()

        for market in markets:
            matching = [item for item in self.PRODUCT_CATALOG if market in item["markets"]]
            limit = len(matching) if count_per_market == 0 else min(count_per_market, len(matching))
            picked = 0
            for item in matching:
                key = f"{item['brand']}::{item['name']}"
                if key in selected_names:
                    continue
                selected.append(item)
                selected_names.add(key)
                picked += 1
                if picked >= limit:
                    break

        return selected

    def _price_for_market(self, base_price: Decimal, market: str, name: str) -> Decimal:
        # Deterministic price spread so repeated runs remain stable.
        seed = f"{market}:{name}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()
        offset = (int(digest[:4], 16) % 13) - 6  # -6..+6
        factor = Decimal("1") + (Decimal(offset) / Decimal("100"))
        return (base_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _market_url(self, market: str, name: str, brand: str) -> str:
        query = "+".join(f"{brand} {name}".lower().split())
        pattern = self.URL_PATTERNS.get(market)
        if pattern:
            return pattern.format(query=query)
        return f"https://www.google.com/search?q={query}"

    def _white_image(self, product_name: str) -> str:
        safe = "+".join(product_name.split())
        return f"https://dummyimage.com/1200x1200/ffffff/0f172a.png&text={safe}"
