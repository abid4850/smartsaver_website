from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import urllib.parse
import urllib.request

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from comparisons.models import AlternativeProduct
from comparisons.models import ProductPrice
from deals.models import DealAlert
from products.models import Product
from products.models import ProductNews


class Command(BaseCommand):
    help = "Seed SmartSaver with a large catalog of famous products, prices, alternatives, and a demo alert."

    PLATFORM_MULTIPLIERS = {
        "Amazon": Decimal("1.00"),
        "eBay": Decimal("0.96"),
        "BestBuy": Decimal("1.02"),
        "Walmart": Decimal("0.99"),
        "AliExpress": Decimal("0.94"),
        "Target": Decimal("1.01"),
        "Newegg": Decimal("0.98"),
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--resolve-images",
            action="store_true",
            help="Resolve product images via Wikipedia/Openverse",
        )

    def _white_background_image(self, product_name):
        encoded = urllib.parse.quote_plus(product_name)
        return f"https://dummyimage.com/1200x1200/ffffff/0f172a.png&text={encoded}"

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

    def _price_for_platform(self, base_price: Decimal, platform: str) -> Decimal:
        multiplier = self.PLATFORM_MULTIPLIERS.get(platform, Decimal("1.00"))
        return (base_price * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def handle(self, *args, **options):
        resolve_images = options.get("resolve_images", False)
        products_payload = [
            {"slug": "iphone_15_pro_max", "name": "iPhone 15 Pro Max", "brand": "Apple", "category": "Smartphones", "description": "Premium iPhone with Pro camera system and titanium frame.", "base_price": "1199.00", "platforms": ["Amazon", "eBay", "BestBuy", "Target"]},
            {"slug": "iphone_15", "name": "iPhone 15", "brand": "Apple", "category": "Smartphones", "description": "Mainstream iPhone with great camera and long software support.", "base_price": "799.00", "platforms": ["Amazon", "eBay", "BestBuy", "Walmart"]},
            {"slug": "iphone_14", "name": "iPhone 14", "brand": "Apple", "category": "Smartphones", "description": "Reliable iPhone with strong performance and camera quality.", "base_price": "679.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "galaxy_s24_ultra", "name": "Galaxy S24 Ultra", "brand": "Samsung", "category": "Smartphones", "description": "Top-tier Samsung flagship with stylus and zoom camera.", "base_price": "1299.00", "platforms": ["Amazon", "eBay", "BestBuy", "Walmart"]},
            {"slug": "galaxy_s24", "name": "Galaxy S24", "brand": "Samsung", "category": "Smartphones", "description": "Compact flagship Android with AI features and bright display.", "base_price": "729.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "galaxy_z_fold5", "name": "Galaxy Z Fold5", "brand": "Samsung", "category": "Smartphones", "description": "Foldable flagship for multitasking and productivity.", "base_price": "1599.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "pixel_9_pro", "name": "Pixel 9 Pro", "brand": "Google", "category": "Smartphones", "description": "AI-powered Android phone with excellent camera pipeline.", "base_price": "999.00", "platforms": ["Amazon", "eBay", "BestBuy", "Target"]},
            {"slug": "pixel_8", "name": "Pixel 8", "brand": "Google", "category": "Smartphones", "description": "Balanced Android phone with smooth software updates.", "base_price": "589.00", "platforms": ["Amazon", "eBay", "Walmart"]},
            {"slug": "oneplus_12", "name": "OnePlus 12", "brand": "OnePlus", "category": "Smartphones", "description": "Fast flagship smartphone with high-end charging and display.", "base_price": "799.00", "platforms": ["Amazon", "eBay", "AliExpress"]},
            {"slug": "xiaomi_14_ultra", "name": "Xiaomi 14 Ultra", "brand": "Xiaomi", "category": "Smartphones", "description": "Camera-focused premium Android smartphone.", "base_price": "1099.00", "platforms": ["Amazon", "AliExpress", "eBay"]},
            {"slug": "nothing_phone_2", "name": "Nothing Phone (2)", "brand": "Nothing", "category": "Smartphones", "description": "Distinct design smartphone with clean Android experience.", "base_price": "599.00", "platforms": ["Amazon", "eBay", "Target"]},
            {"slug": "huawei_p60_pro", "name": "Huawei P60 Pro", "brand": "Huawei", "category": "Smartphones", "description": "Photography-first smartphone with premium build.", "base_price": "999.00", "platforms": ["AliExpress", "eBay", "Amazon"]},
            {"slug": "sony_xperia_1_v", "name": "Xperia 1 V", "brand": "Sony", "category": "Smartphones", "description": "Creator-friendly flagship with pro camera controls.", "base_price": "1199.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "moto_razr_50_ultra", "name": "Motorola Razr 50 Ultra", "brand": "Motorola", "category": "Smartphones", "description": "Foldable smartphone with large external screen.", "base_price": "999.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "oppo_find_x7_ultra", "name": "Oppo Find X7 Ultra", "brand": "Oppo", "category": "Smartphones", "description": "High-end camera flagship with strong battery life.", "base_price": "999.00", "platforms": ["AliExpress", "Amazon", "eBay"]},

            {"slug": "macbook_air_m3", "name": "MacBook Air M3", "brand": "Apple", "category": "Laptops", "description": "Thin and efficient laptop with excellent battery life.", "base_price": "1099.00", "platforms": ["Amazon", "BestBuy", "eBay", "Target"]},
            {"slug": "macbook_pro_14_m3", "name": "MacBook Pro 14 M3 Pro", "brand": "Apple", "category": "Laptops", "description": "Pro laptop for development and content creation.", "base_price": "1999.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "dell_xps_13", "name": "Dell XPS 13", "brand": "Dell", "category": "Laptops", "description": "Premium ultrabook with compact design and sharp display.", "base_price": "1299.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "hp_spectre_x360", "name": "HP Spectre x360", "brand": "HP", "category": "Laptops", "description": "Convertible 2-in-1 laptop for work and portability.", "base_price": "1399.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "thinkpad_x1_carbon", "name": "ThinkPad X1 Carbon", "brand": "Lenovo", "category": "Laptops", "description": "Business-class lightweight laptop with robust keyboard.", "base_price": "1699.00", "platforms": ["Amazon", "eBay", "Newegg"]},
            {"slug": "rog_zephyrus_g14", "name": "ROG Zephyrus G14", "brand": "ASUS", "category": "Laptops", "description": "Portable gaming laptop with high-performance graphics.", "base_price": "1599.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "acer_swift_x14", "name": "Acer Swift X 14", "brand": "Acer", "category": "Laptops", "description": "Creator-focused laptop with dedicated GPU.", "base_price": "1199.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "surface_laptop_6", "name": "Surface Laptop 6", "brand": "Microsoft", "category": "Laptops", "description": "Clean Windows laptop with premium build quality.", "base_price": "1299.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "msi_raider_ge78", "name": "MSI Raider GE78", "brand": "MSI", "category": "Laptops", "description": "High-end gaming laptop for enthusiasts.", "base_price": "2799.00", "platforms": ["Amazon", "Newegg", "eBay"]},
            {"slug": "razer_blade_16", "name": "Razer Blade 16", "brand": "Razer", "category": "Laptops", "description": "Premium gaming and creator laptop with strong build.", "base_price": "2999.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "galaxy_book4_pro", "name": "Galaxy Book4 Pro", "brand": "Samsung", "category": "Laptops", "description": "Sleek productivity laptop integrated with Galaxy ecosystem.", "base_price": "1499.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "framework_laptop_13", "name": "Framework Laptop 13", "brand": "Framework", "category": "Laptops", "description": "Repairable and upgradeable modular laptop.", "base_price": "1399.00", "platforms": ["Amazon", "eBay", "Newegg"]},

            {"slug": "ipad_pro_11", "name": "iPad Pro 11", "brand": "Apple", "category": "Tablets", "description": "High-performance tablet for creative and professional work.", "base_price": "999.00", "platforms": ["Amazon", "BestBuy", "eBay", "Target"]},
            {"slug": "ipad_air", "name": "iPad Air", "brand": "Apple", "category": "Tablets", "description": "Lightweight tablet for everyday productivity.", "base_price": "549.00", "platforms": ["Amazon", "eBay", "Walmart", "Target"]},
            {"slug": "galaxy_tab_s9", "name": "Galaxy Tab S9", "brand": "Samsung", "category": "Tablets", "description": "Premium Android tablet with stylus support.", "base_price": "799.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "xiaomi_pad_6", "name": "Xiaomi Pad 6", "brand": "Xiaomi", "category": "Tablets", "description": "Value tablet with strong display and speakers.", "base_price": "359.00", "platforms": ["Amazon", "AliExpress", "eBay"]},
            {"slug": "lenovo_tab_p12", "name": "Lenovo Tab P12", "brand": "Lenovo", "category": "Tablets", "description": "Large-screen tablet for media and study.", "base_price": "379.00", "platforms": ["Amazon", "Walmart", "eBay"]},
            {"slug": "surface_pro_10", "name": "Surface Pro 10", "brand": "Microsoft", "category": "Tablets", "description": "2-in-1 Windows tablet for business users.", "base_price": "1199.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "fire_max_11", "name": "Fire Max 11", "brand": "Amazon", "category": "Tablets", "description": "Affordable entertainment tablet with Alexa.", "base_price": "229.00", "platforms": ["Amazon", "eBay", "Target"]},
            {"slug": "oneplus_pad_2", "name": "OnePlus Pad 2", "brand": "OnePlus", "category": "Tablets", "description": "Performance Android tablet with smooth UI.", "base_price": "499.00", "platforms": ["Amazon", "eBay", "AliExpress"]},

            {"slug": "sony_wh1000xm5", "name": "WH-1000XM5", "brand": "Sony", "category": "Headphones", "description": "Industry-leading wireless noise-canceling headphones.", "base_price": "329.00", "platforms": ["Amazon", "eBay", "Walmart", "BestBuy"]},
            {"slug": "bose_qc_ultra", "name": "Bose QC Ultra", "brand": "Bose", "category": "Headphones", "description": "Premium ANC headphones with comfort-focused design.", "base_price": "429.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "airpods_max", "name": "AirPods Max", "brand": "Apple", "category": "Headphones", "description": "Apple over-ear headphones with spatial audio.", "base_price": "549.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "momentum_4", "name": "Momentum 4 Wireless", "brand": "Sennheiser", "category": "Headphones", "description": "High-fidelity wireless headphones with strong battery life.", "base_price": "349.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "soundcore_q45", "name": "Soundcore Q45", "brand": "Anker", "category": "Headphones", "description": "Budget-friendly ANC headphones with great value.", "base_price": "139.00", "platforms": ["Amazon", "eBay", "BestBuy", "Walmart"]},
            {"slug": "beats_studio_pro", "name": "Beats Studio Pro", "brand": "Beats", "category": "Headphones", "description": "Stylish wireless headphones tuned for mainstream sound.", "base_price": "349.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "jbl_tune_770nc", "name": "JBL Tune 770NC", "brand": "JBL", "category": "Headphones", "description": "Affordable wireless ANC headphones for everyday listening.", "base_price": "129.00", "platforms": ["Amazon", "Walmart", "eBay"]},
            {"slug": "nothing_ear_a", "name": "Nothing Ear (a)", "brand": "Nothing", "category": "Headphones", "description": "Compact earbuds with balanced sound and ANC.", "base_price": "99.00", "platforms": ["Amazon", "eBay", "AliExpress"]},

            {"slug": "apple_watch_series_9", "name": "Apple Watch Series 9", "brand": "Apple", "category": "Smartwatches", "description": "Mainstream smartwatch with advanced fitness tracking.", "base_price": "399.00", "platforms": ["Amazon", "BestBuy", "Target", "eBay"]},
            {"slug": "apple_watch_ultra_2", "name": "Apple Watch Ultra 2", "brand": "Apple", "category": "Smartwatches", "description": "Rugged premium smartwatch for outdoor users.", "base_price": "799.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "galaxy_watch6_classic", "name": "Galaxy Watch6 Classic", "brand": "Samsung", "category": "Smartwatches", "description": "Android smartwatch with rotating bezel and health features.", "base_price": "399.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "pixel_watch_2", "name": "Pixel Watch 2", "brand": "Google", "category": "Smartwatches", "description": "Wear OS smartwatch with Fitbit integration.", "base_price": "349.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "garmin_fenix_7", "name": "Garmin Fenix 7", "brand": "Garmin", "category": "Smartwatches", "description": "Outdoor multisport GPS smartwatch.", "base_price": "699.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "amazfit_gtr_4", "name": "Amazfit GTR 4", "brand": "Amazfit", "category": "Smartwatches", "description": "Long-battery smartwatch with fitness sensors.", "base_price": "199.00", "platforms": ["Amazon", "eBay", "AliExpress"]},

            {"slug": "ps5_slim", "name": "PlayStation 5 Slim", "brand": "Sony", "category": "Gaming Consoles", "description": "Current-gen console with high-performance gaming.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "Walmart", "Target"]},
            {"slug": "ps5_digital", "name": "PlayStation 5 Digital Edition", "brand": "Sony", "category": "Gaming Consoles", "description": "Diskless PlayStation 5 for digital game libraries.", "base_price": "449.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "xbox_series_x", "name": "Xbox Series X", "brand": "Microsoft", "category": "Gaming Consoles", "description": "Powerful console with 4K gaming support.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "Walmart", "Target"]},
            {"slug": "xbox_series_s", "name": "Xbox Series S", "brand": "Microsoft", "category": "Gaming Consoles", "description": "Affordable current-gen digital gaming console.", "base_price": "299.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "switch_oled", "name": "Nintendo Switch OLED", "brand": "Nintendo", "category": "Gaming Consoles", "description": "Portable and dockable console with OLED display.", "base_price": "349.00", "platforms": ["Amazon", "BestBuy", "Target", "eBay"]},
            {"slug": "steam_deck_oled", "name": "Steam Deck OLED", "brand": "Valve", "category": "Gaming Consoles", "description": "Handheld PC gaming console with OLED screen.", "base_price": "549.00", "platforms": ["Amazon", "eBay", "Newegg"]},

            {"slug": "lg_c3_oled_55", "name": "LG C3 OLED 55", "brand": "LG", "category": "TVs", "description": "Popular OLED TV with excellent gaming performance.", "base_price": "1399.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "samsung_s90c_oled_55", "name": "Samsung S90C OLED 55", "brand": "Samsung", "category": "TVs", "description": "Bright OLED TV with rich color output.", "base_price": "1499.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "sony_x90l_65", "name": "Sony Bravia X90L 65", "brand": "Sony", "category": "TVs", "description": "Balanced 4K TV with strong image processing.", "base_price": "1199.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "tcl_qm8_65", "name": "TCL QM8 65", "brand": "TCL", "category": "TVs", "description": "Value-focused mini-LED TV with high brightness.", "base_price": "999.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "hisense_u8k_65", "name": "Hisense U8K 65", "brand": "Hisense", "category": "TVs", "description": "High-value 4K mini-LED TV for home entertainment.", "base_price": "949.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "xiaomi_tv_a_pro_55", "name": "Xiaomi TV A Pro 55", "brand": "Xiaomi", "category": "TVs", "description": "Budget smart TV with modern design.", "base_price": "599.00", "platforms": ["Amazon", "AliExpress", "eBay"]},

            {"slug": "sony_a7_iv", "name": "Sony A7 IV", "brand": "Sony", "category": "Cameras", "description": "Full-frame hybrid camera for photo and video creators.", "base_price": "2499.00", "platforms": ["Amazon", "BestBuy", "eBay", "Newegg"]},
            {"slug": "canon_r6_mark_ii", "name": "Canon EOS R6 Mark II", "brand": "Canon", "category": "Cameras", "description": "Versatile full-frame camera for professional shooting.", "base_price": "2499.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "nikon_z8", "name": "Nikon Z8", "brand": "Nikon", "category": "Cameras", "description": "Flagship-level mirrorless camera for advanced users.", "base_price": "3999.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "fujifilm_xt5", "name": "Fujifilm X-T5", "brand": "Fujifilm", "category": "Cameras", "description": "High-resolution APS-C camera with classic controls.", "base_price": "1699.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "lumix_s5_ii", "name": "Panasonic Lumix S5 II", "brand": "Panasonic", "category": "Cameras", "description": "Strong video-capable full-frame mirrorless camera.", "base_price": "1999.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "gopro_hero12", "name": "GoPro HERO12 Black", "brand": "GoPro", "category": "Cameras", "description": "Durable action camera for travel and sports.", "base_price": "399.00", "platforms": ["Amazon", "BestBuy", "eBay", "Walmart"]},

            {"slug": "dyson_v15_detect", "name": "Dyson V15 Detect", "brand": "Dyson", "category": "Home Appliances", "description": "Flagship cordless vacuum with laser dust detection.", "base_price": "749.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "roomba_j7_plus", "name": "Roomba j7+", "brand": "iRobot", "category": "Home Appliances", "description": "Robot vacuum with automatic dirt disposal.", "base_price": "699.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "philips_airfryer_xxl", "name": "Philips Airfryer XXL", "brand": "Philips", "category": "Home Appliances", "description": "Large-capacity air fryer for family cooking.", "base_price": "329.00", "platforms": ["Amazon", "Walmart", "Target"]},
            {"slug": "instant_pot_duo", "name": "Instant Pot Duo 7-in-1", "brand": "Instant Pot", "category": "Home Appliances", "description": "Popular multifunction electric pressure cooker.", "base_price": "129.00", "platforms": ["Amazon", "Walmart", "Target"]},
            {"slug": "ninja_creami", "name": "Ninja Creami", "brand": "Ninja", "category": "Home Appliances", "description": "Home ice cream maker with multiple dessert modes.", "base_price": "229.00", "platforms": ["Amazon", "Walmart", "BestBuy"]},
            {"slug": "breville_barista_express", "name": "Breville Barista Express", "brand": "Breville", "category": "Home Appliances", "description": "Semi-automatic espresso machine for home baristas.", "base_price": "749.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "coway_airmega_250", "name": "Coway Airmega 250", "brand": "Coway", "category": "Home Appliances", "description": "Air purifier for medium to large spaces.", "base_price": "449.00", "platforms": ["Amazon", "Walmart", "BestBuy"]},
            {"slug": "lg_instaview_fridge", "name": "LG InstaView Refrigerator", "brand": "LG", "category": "Home Appliances", "description": "Smart refrigerator with InstaView door panel.", "base_price": "3199.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},

            {"slug": "jbl_charge_5", "name": "JBL Charge 5", "brand": "JBL", "category": "Speakers", "description": "Portable Bluetooth speaker with strong bass.", "base_price": "179.00", "platforms": ["Amazon", "Walmart", "BestBuy"]},
            {"slug": "sonos_era_300", "name": "Sonos Era 300", "brand": "Sonos", "category": "Speakers", "description": "Spatial audio smart speaker for home sound systems.", "base_price": "449.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "echo_4", "name": "Amazon Echo (4th Gen)", "brand": "Amazon", "category": "Speakers", "description": "Voice assistant smart speaker with room-filling sound.", "base_price": "99.00", "platforms": ["Amazon", "Target", "Walmart"]},
            {"slug": "nest_audio", "name": "Google Nest Audio", "brand": "Google", "category": "Speakers", "description": "Google Assistant smart speaker with balanced audio.", "base_price": "99.00", "platforms": ["Amazon", "Target", "Walmart"]},
            {"slug": "marshall_stanmore_iii", "name": "Marshall Stanmore III", "brand": "Marshall", "category": "Speakers", "description": "Iconic Bluetooth speaker with classic Marshall design.", "base_price": "379.00", "platforms": ["Amazon", "BestBuy", "eBay"]},

            {"slug": "lg_ultragear_27gp850", "name": "LG UltraGear 27GP850", "brand": "LG", "category": "Monitors", "description": "Fast 27-inch gaming monitor with high refresh rate.", "base_price": "449.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "odyssey_g7", "name": "Samsung Odyssey G7", "brand": "Samsung", "category": "Monitors", "description": "Curved gaming monitor with premium panel quality.", "base_price": "699.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "dell_u2723qe", "name": "Dell UltraSharp U2723QE", "brand": "Dell", "category": "Monitors", "description": "Professional 4K monitor with USB-C connectivity.", "base_price": "649.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "apple_studio_display", "name": "Apple Studio Display", "brand": "Apple", "category": "Monitors", "description": "Premium 5K display for Mac workflows.", "base_price": "1599.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "samsung_galaxy_a55", "name": "Galaxy A55", "brand": "Samsung", "category": "Smartphones", "description": "Mid-range smartphone with balanced specs and camera.", "base_price": "349.00", "platforms": ["Amazon", "eBay", "Walmart"]},
            {"slug": "google_pixel_fold", "name": "Pixel Fold", "brand": "Google", "category": "Smartphones", "description": "Google's first foldable with flagship camera features.", "base_price": "1799.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "lenovo_legion_pro_5i", "name": "Legion Pro 5i", "brand": "Lenovo", "category": "Laptops", "description": "High-refresh gaming laptop with powerful CPU and GPU.", "base_price": "1499.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "hp_omen_16", "name": "Omen 16", "brand": "HP", "category": "Laptops", "description": "Gaming laptop with strong thermals and fast display.", "base_price": "1199.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "asus_tuf_gaming_17", "name": "TUF Gaming 17", "brand": "ASUS", "category": "Laptops", "description": "Durable gaming laptop with high-refresh screen.", "base_price": "999.00", "platforms": ["Amazon", "Newegg", "BestBuy"]},
            {"slug": "canon_eos_r10", "name": "Canon EOS R10", "brand": "Canon", "category": "Cameras", "description": "APS-C mirrorless camera for enthusiast photographers.", "base_price": "979.00", "platforms": ["Amazon", "BestBuy", "B&H"]},
            {"slug": "panasonic_g100", "name": "Lumix G100", "brand": "Panasonic", "category": "Cameras", "description": "Compact mirrorless camera optimized for vlogging.", "base_price": "599.00", "platforms": ["Amazon", "B&H", "eBay"]},
            {"slug": "google_nest_hub_max", "name": "Nest Hub Max", "brand": "Google", "category": "Speakers", "description": "Smart display with great integration for smart homes.", "base_price": "229.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "jbl_boombox_3", "name": "JBL Boombox 3", "brand": "JBL", "category": "Speakers", "description": "Large portable Bluetooth speaker with long battery life.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "sony_ht_a7000", "name": "Sony HT-A7000", "brand": "Sony", "category": "Speakers", "description": "High-end soundbar for immersive home theater audio.", "base_price": "1499.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "lg_27gp950", "name": "LG 27GP950", "brand": "LG", "category": "Monitors", "description": "27-inch 4K high-refresh monitor for gaming and content.", "base_price": "799.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "benq_sw320", "name": "BenQ SW320", "brand": "BenQ", "category": "Monitors", "description": "Professional photo-editing monitor with wide color gamut.", "base_price": "1199.00", "platforms": ["Amazon", "B&H", "Newegg"]},
            {"slug": "google_pixel_tablet", "name": "Pixel Tablet", "brand": "Google", "category": "Tablets", "description": "Android tablet focused on media and productivity.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "amazon_echo_dot_5th", "name": "Echo Dot (5th Gen)", "brand": "Amazon", "category": "Speakers", "description": "Compact smart speaker with voice assistant.", "base_price": "49.00", "platforms": ["Amazon", "Target", "Walmart"]},
            {"slug": "nintendo_switch_lite", "name": "Nintendo Switch Lite", "brand": "Nintendo", "category": "Gaming Consoles", "description": "Handheld-only Switch for portable gaming.", "base_price": "199.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "beats_fit_pro", "name": "Beats Fit Pro", "brand": "Beats", "category": "Headphones", "description": "Sport-oriented true wireless earbuds with robust ANC.", "base_price": "199.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "samsung_galaxy_buds2_pro", "name": "Galaxy Buds2 Pro", "brand": "Samsung", "category": "Headphones", "description": "Flagship Samsung earbuds with great ANC and sound.", "base_price": "199.00", "platforms": ["Amazon", "BestBuy", "Samsung"]},
            {"slug": "samsung_galaxy_tab_a8", "name": "Galaxy Tab A8", "brand": "Samsung", "category": "Tablets", "description": "Affordable Android tablet for media and reading.", "base_price": "159.00", "platforms": ["Amazon", "Walmart", "Target"]},
            {"slug": "garmin_vivoactive_5", "name": "Garmin Vivoactive 5", "brand": "Garmin", "category": "Smartwatches", "description": "Versatile fitness-focused smartwatch with long battery.", "base_price": "279.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "samsung_galaxy_s24_fe", "name": "Galaxy S24 FE", "brand": "Samsung", "category": "Smartphones", "description": "Fan edition flagship with a strong camera and smooth display.", "base_price": "649.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "oneplus_open", "name": "OnePlus Open", "brand": "OnePlus", "category": "Smartphones", "description": "Foldable phone with a large inner display and fast performance.", "base_price": "1699.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "motorola_edge_50_pro", "name": "Motorola Edge 50 Pro", "brand": "Motorola", "category": "Smartphones", "description": "Style-focused Android phone with fast charging and solid cameras.", "base_price": "699.00", "platforms": ["Amazon", "eBay", "Walmart"]},
            {"slug": "asus_rog_ally", "name": "ROG Ally", "brand": "ASUS", "category": "Gaming Consoles", "description": "Windows handheld gaming PC with a high-refresh display.", "base_price": "649.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "lenovo_legion_go", "name": "Legion Go", "brand": "Lenovo", "category": "Gaming Consoles", "description": "Large-screen handheld gaming PC with detachable controllers.", "base_price": "699.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "dji_mini_4_pro", "name": "DJI Mini 4 Pro", "brand": "DJI", "category": "Cameras", "description": "Ultra-light drone with advanced imaging and obstacle sensing.", "base_price": "759.00", "platforms": ["Amazon", "BestBuy", "B&H"]},
            {"slug": "insta360_x4", "name": "Insta360 X4", "brand": "Insta360", "category": "Cameras", "description": "360-degree action camera for immersive capture.", "base_price": "499.00", "platforms": ["Amazon", "B&H", "eBay"]},
            {"slug": "sony_srs_xg300", "name": "Sony SRS-XG300", "brand": "Sony", "category": "Speakers", "description": "Portable party speaker with strong sound and battery life.", "base_price": "349.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "ue_epicboom", "name": "Ultimate Ears Epicboom", "brand": "Ultimate Ears", "category": "Speakers", "description": "Rugged outdoor speaker with bold sound and portability.", "base_price": "349.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "benq_mobiuz_ex2710q", "name": "BenQ MOBIUZ EX2710Q", "brand": "BenQ", "category": "Monitors", "description": "Gaming monitor with fast response and immersive audio.", "base_price": "449.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "alienware_aw3423dw", "name": "Alienware AW3423DW", "brand": "Dell", "category": "Monitors", "description": "Premium ultrawide QD-OLED gaming monitor.", "base_price": "1299.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "microsoft_surface_go_4", "name": "Surface Go 4", "brand": "Microsoft", "category": "Tablets", "description": "Compact Windows tablet for light productivity and travel.", "base_price": "579.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "amazon_fire_hd_10", "name": "Fire HD 10", "brand": "Amazon", "category": "Tablets", "description": "Affordable large-screen tablet for entertainment.", "base_price": "139.00", "platforms": ["Amazon", "Walmart", "Target"]},
            {"slug": "fitbit_sense_2", "name": "Fitbit Sense 2", "brand": "Fitbit", "category": "Smartwatches", "description": "Health-focused smartwatch with stress and sleep tracking.", "base_price": "299.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "google_pixel_8a", "name": "Pixel 8a", "brand": "Google", "category": "Smartphones", "description": "Affordable Pixel phone with flagship-style camera features.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "samsung_galaxy_z_flip6", "name": "Galaxy Z Flip6", "brand": "Samsung", "category": "Smartphones", "description": "Compact foldable with improved battery and cameras.", "base_price": "1099.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "apple_watch_se_2", "name": "Apple Watch SE 2", "brand": "Apple", "category": "Smartwatches", "description": "Affordable Apple smartwatch for everyday fitness tracking.", "base_price": "249.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "suunto_vertical", "name": "Suunto Vertical", "brand": "Suunto", "category": "Smartwatches", "description": "Rugged adventure watch with navigation and long battery life.", "base_price": "629.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "sony_xperia_10_v", "name": "Xperia 10 V", "brand": "Sony", "category": "Smartphones", "description": "Compact phone with great battery life and clean design.", "base_price": "499.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "canon_r50", "name": "Canon EOS R50", "brand": "Canon", "category": "Cameras", "description": "Compact mirrorless camera for creators and beginners.", "base_price": "679.00", "platforms": ["Amazon", "BestBuy", "B&H"]},
            {"slug": "fujifilm_xs20", "name": "Fujifilm X-S20", "brand": "Fujifilm", "category": "Cameras", "description": "Versatile APS-C camera with strong video performance.", "base_price": "1299.00", "platforms": ["Amazon", "B&H", "BestBuy"]},
            {"slug": "jbl_flip_6", "name": "JBL Flip 6", "brand": "JBL", "category": "Speakers", "description": "Portable Bluetooth speaker with IP67 durability.", "base_price": "129.00", "platforms": ["Amazon", "Walmart", "BestBuy"]},
            {"slug": "sonos_move_2", "name": "Sonos Move 2", "brand": "Sonos", "category": "Speakers", "description": "Premium portable speaker with Wi-Fi and Bluetooth.", "base_price": "449.00", "platforms": ["Amazon", "BestBuy", "Target"]},
            {"slug": "lg_oled_g3_65", "name": "LG OLED G3 65", "brand": "LG", "category": "TVs", "description": "Bright premium OLED TV designed for wall mounting.", "base_price": "2999.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "tcl_q7_65", "name": "TCL Q7 65", "brand": "TCL", "category": "TVs", "description": "High-value mini-LED TV with gaming-friendly features.", "base_price": "899.00", "platforms": ["Amazon", "BestBuy", "Walmart"]},
            {"slug": "hp_24mh", "name": "HP 24mh", "brand": "HP", "category": "Monitors", "description": "Budget IPS monitor for everyday use and office work.", "base_price": "149.00", "platforms": ["Amazon", "BestBuy", "Newegg"]},
            {"slug": "samsung_viewfinity_s9", "name": "Samsung ViewFinity S9", "brand": "Samsung", "category": "Monitors", "description": "Premium 5K monitor for creators and Mac users.", "base_price": "1299.00", "platforms": ["Amazon", "BestBuy", "eBay"]},
            {"slug": "lenovo_tab_plus", "name": "Lenovo Tab Plus", "brand": "Lenovo", "category": "Tablets", "description": "Media-focused Android tablet with kickstand design.", "base_price": "299.00", "platforms": ["Amazon", "Walmart", "BestBuy"]},

            {"slug": "tesla_model_3_performance", "name": "Tesla Model 3 Performance", "brand": "Tesla", "category": "Electric Vehicles", "description": "High-performance electric sedan with advanced autopilot features.", "base_price": "69990.00", "platforms": ["Amazon", "eBay", "Walmart"]},
            {"slug": "lucid_air_grand_touring", "name": "Lucid Air Grand Touring", "brand": "Lucid", "category": "Electric Vehicles", "description": "Luxury EV sedan with premium interior and ultra-long range.", "base_price": "95000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "porsche_taycan_4s", "name": "Porsche Taycan 4S", "brand": "Porsche", "category": "Electric Vehicles", "description": "Performance luxury EV with precision handling and premium cabin.", "base_price": "100000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},

            {"slug": "rolex_daytona_platinum", "name": "Rolex Daytona Platinum", "brand": "Rolex", "category": "Luxury Watches", "description": "Iconic high-end chronograph watch in platinum finish.", "base_price": "85000.00", "platforms": ["Amazon", "eBay", "Target"]},
            {"slug": "omega_speedmaster_moonwatch_gold", "name": "Omega Speedmaster Moonwatch Gold", "brand": "Omega", "category": "Luxury Watches", "description": "Collector-grade mechanical chronograph in precious metal.", "base_price": "42000.00", "platforms": ["Amazon", "eBay", "Target"]},
            {"slug": "tag_heuer_carrera_tourbillon", "name": "TAG Heuer Carrera Tourbillon", "brand": "TAG Heuer", "category": "Luxury Watches", "description": "Swiss tourbillon watch with racing-inspired dial design.", "base_price": "28500.00", "platforms": ["Amazon", "eBay", "BestBuy"]},

            {"slug": "red_v_raptor_xl_8k", "name": "RED V-RAPTOR XL 8K", "brand": "RED", "category": "Cinema Cameras", "description": "High-end cinema camera for studio and production workflows.", "base_price": "39995.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "arri_alexa_mini_lf_body", "name": "ARRI ALEXA Mini LF", "brand": "ARRI", "category": "Cinema Cameras", "description": "Professional large-format cinema camera body.", "base_price": "100000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "sony_venice_2", "name": "Sony VENICE 2", "brand": "Sony", "category": "Cinema Cameras", "description": "Flagship digital cinema camera used in feature film production.", "base_price": "76000.00", "platforms": ["Amazon", "eBay", "Newegg"]},

            {"slug": "naim_statement_nap_s1", "name": "Naim Statement NAP S1", "brand": "Naim", "category": "Audiophile Systems", "description": "Reference-grade amplifier system for audiophile listening rooms.", "base_price": "100000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "focal_grande_utopia_em_evo", "name": "Focal Grande Utopia EM Evo", "brand": "Focal", "category": "Audiophile Systems", "description": "Flagship floorstanding speaker system with uncompromised detail.", "base_price": "100000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
            {"slug": "mcintosh_xrt2k", "name": "McIntosh XRT2K", "brand": "McIntosh", "category": "Audiophile Systems", "description": "High-end loudspeaker array for dedicated listening environments.", "base_price": "80000.00", "platforms": ["Amazon", "eBay", "BestBuy"]},
        ]

        catalog = {}
        if resolve_images:
            self.stdout.write("Resolving product images...")
            product_image_urls = {}
            for item in products_payload:
                resolved = self._resolve_product_image(item["name"], item["brand"], item["category"])
                product_image_urls[item["slug"]] = resolved or self._white_background_image(item["name"])
        else:
            product_image_urls = {item["slug"]: self._white_background_image(item["name"]) for item in products_payload}

        for item in products_payload:
            slug = item["slug"]
            base_price = Decimal(item["base_price"])
            product, _ = Product.objects.update_or_create(
                name=item["name"],
                brand=item["brand"],
                defaults={
                    "category": item["category"],
                    "description": item["description"],
                    "image_url": product_image_urls.get(slug, self._white_background_image(item["name"])),
                },
            )
            catalog[slug] = product

            for platform in item["platforms"]:
                clean_platform = platform.replace(" ", "-").lower()
                # Generate retailer URL based on platform
                retailer_urls = {
                    "Amazon": f"https://www.amazon.com/s?k={slug.replace('_', '+')}-amazon",
                    "eBay": f"https://www.ebay.com/sch/i.html?_nkw={slug.replace('_', '+')}+ebay",
                    "BestBuy": f"https://www.bestbuy.com/site/searchpage.jsp?st={slug.replace('_', '+')}",
                    "Newegg": f"https://www.newegg.com/p/pl?d={slug.replace('_', '+')}",
                }
                product_url = retailer_urls.get(platform, f"https://{clean_platform}.com/search?q={slug}")
                ProductPrice.objects.update_or_create(
                    product=product,
                    platform=platform,
                    defaults={
                        "price": self._price_for_platform(base_price, platform),
                        "product_url": product_url,
                    },
                )

        # Rebuild alternatives to match the expanded catalog.
        AlternativeProduct.objects.all().delete()
        products_by_category = {}
        for product in catalog.values():
            products_by_category.setdefault(product.category, []).append(product)

        for category_products in products_by_category.values():
            ranked = sorted(
                [p for p in category_products if p.cheapest_price],
                key=lambda obj: obj.cheapest_price,
                reverse=True,
            )
            if len(ranked) < 2:
                continue

            for idx, main_product in enumerate(ranked[: min(5, len(ranked))]):
                cheaper_options = [
                    p for p in ranked if p.id != main_product.id and p.cheapest_price < main_product.cheapest_price
                ]
                if not cheaper_options:
                    continue
                alt_product = cheaper_options[0]
                difference = main_product.cheapest_price - alt_product.cheapest_price
                score = (Decimal("0.74") + Decimal(idx) * Decimal("0.03")).quantize(Decimal("0.01"))

                AlternativeProduct.objects.update_or_create(
                    main_product=main_product,
                    alternative_product=alt_product,
                    defaults={
                        "similarity_score": min(score, Decimal("0.96")),
                        "price_difference": difference,
                    },
                )

        user_model = get_user_model()
        demo_user, created = user_model.objects.get_or_create(
            username="demo_user",
            defaults={"email": "demo@smartsaver.local"},
        )
        if created:
            demo_user.set_password("DemoPass123")
            demo_user.save(update_fields=["password"])

        DealAlert.objects.update_or_create(
            user=demo_user,
            product=catalog.get("iphone_15") or next(iter(catalog.values())),
            defaults={"target_price": Decimal("620.00"), "is_active": True},
        )

        now = timezone.now()
        news_payload = [
            {
                "title": "Flagship Phone Prices Tighten Ahead of Seasonal Sales",
                "summary": "Retail pricing across top flagship phones has narrowed, making comparison shopping more valuable this week.",
                "body": "SmartSaver tracked multiple marketplace updates where flagship devices saw temporary discounts. Users should compare at least three platforms before purchasing.",
                "image_url": "/static/smartsaver/news-pricing.svg",
                "product_slug": "iphone_15_pro_max",
                "days_ago": 0,
                "news_category": "pricing",
            },
            {
                "title": "Premium Headphones Category Gets New Competitive Discounts",
                "summary": "Noise-canceling headphone listings from leading brands dropped across two major platforms today.",
                "body": "The category has become highly competitive, with narrower gaps between premium and value models. Buyers should check alternative suggestions for best savings.",
                "image_url": "/static/smartsaver/news-deals.svg",
                "product_slug": "sony_wh1000xm5",
                "days_ago": 1,
                "news_category": "deals",
            },
            {
                "title": "Workstation Laptop Segment Shows Wider Price Variance",
                "summary": "High-performance laptops now show larger cross-platform pricing spreads than mainstream ultrabooks.",
                "body": "SmartSaver data indicates creator and gaming laptops can vary significantly by platform promotions, making tracked comparisons especially useful.",
                "image_url": "/static/smartsaver/news-tech.svg",
                "product_slug": "razer_blade_16",
                "days_ago": 2,
                "news_category": "tech",
            },
            {
                "title": "Luxury Watch Listings Expand in Premium Marketplace Segment",
                "summary": "Premium watch category has expanded with broader availability in the $20,000 to $100,000 range.",
                "body": "SmartSaver catalog now tracks more luxury watch listings, helping users compare niche premium products with transparent pricing.",
                "image_url": "/static/smartsaver/news-launches.svg",
                "product_slug": "rolex_daytona_platinum",
                "days_ago": 3,
                "news_category": "launches",
            },
            {
                "title": "Electric Vehicle Pricing Becomes More Competitive Across Platforms",
                "summary": "EV product pages are showing stronger cross-platform differences, creating new opportunities for smarter price discovery.",
                "body": "High-value electric vehicle listings are now part of the SmartSaver product range, allowing premium-range filtering and category analysis.",
                "image_url": "/static/smartsaver/news-pricing.svg",
                "product_slug": "porsche_taycan_4s",
                "days_ago": 4,
                "news_category": "pricing",
            },
            {
                "title": "Cinema Camera Segment Added for Professional Buyers",
                "summary": "SmartSaver now includes professional cinema camera listings with price points reaching $100,000.",
                "body": "Production teams and creators can now compare premium cinema systems side-by-side and track pricing changes from multiple platforms.",
                "image_url": "/static/smartsaver/news-reviews.svg",
                "product_slug": "arri_alexa_mini_lf_body",
                "days_ago": 5,
                "news_category": "launches",
            },
        ]

        for row in news_payload:
            ProductNews.objects.update_or_create(
                title=row["title"],
                defaults={
                    "summary": row["summary"],
                    "body": row["body"],
                    "image_url": row["image_url"],
                    "news_category": row.get("news_category", "general"),
                    "product": catalog.get(row["product_slug"]),
                    "published_at": now - timedelta(days=row["days_ago"]),
                    "is_published": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(f"SmartSaver catalog ready with {len(catalog)} products."))