from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.conf import settings

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

from products.models import Product


class Command(BaseCommand):
    help = "Generate clean white-background placeholder images for products without resolved photos."

    CATEGORY_TINTS = {
        "smartphones": ((224, 242, 254), (2, 132, 199)),
        "laptops": ((240, 249, 255), (59, 130, 246)),
        "tablets": ((245, 243, 255), (99, 102, 241)),
        "headphones": ((255, 247, 237), (249, 115, 22)),
        "smartwatches": ((236, 253, 245), (16, 185, 129)),
        "cameras": ((250, 245, 255), (168, 85, 247)),
        "cinema cameras": ((255, 241, 242), (225, 29, 72)),
        "electric vehicles": ((240, 253, 250), (14, 165, 233)),
        "luxury watches": ((255, 251, 235), (217, 119, 6)),
        "audiophile systems": ((248, 250, 252), (71, 85, 105)),
        "tv": ((240, 249, 255), (37, 99, 235)),
    }

    CATEGORY_ICONS = {
        "smartphones": "phone",
        "laptops": "laptop",
        "tablets": "tablet",
        "headphones": "headphones",
        "smartwatches": "watch",
        "cameras": "camera",
        "cinema cameras": "camera",
        "electric vehicles": "car",
        "luxury watches": "watch",
        "audiophile systems": "speaker",
        "tv": "display",
    }

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
            help="Regenerate placeholder images even when a local file already exists",
        )

    def handle(self, *args, **options):
        if not PIL_AVAILABLE:
            self.stderr.write("Pillow is not available.")
            return

        limit = options.get("limit")
        force = options.get("force", False)
        products = Product.objects.order_by("id")
        if limit:
            products = products[:limit]

        media_root = Path(settings.MEDIA_ROOT)
        created = 0
        skipped = 0

        for product in products:
            local_name = product._local_image_name()
            if product.image_url and not product._is_placeholder_url(product.image_url):
                skipped += 1
                continue

            if local_name and product._processed_image_exists() and not force:
                skipped += 1
                continue

            if not local_name:
                skipped += 1
                continue

            placeholder_path = media_root / local_name
            placeholder_path.parent.mkdir(parents=True, exist_ok=True)

            category_key = (product.category or "").strip().lower()
            tint = self.CATEGORY_TINTS.get(category_key, ((240, 248, 255), (14, 165, 233)))
            bg_color, accent_color = tint
            icon_type = self.CATEGORY_ICONS.get(category_key, "product")

            image = Image.new("RGB", (1200, 1200), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((60, 60, 1140, 1140), radius=40, fill=bg_color, outline=(219, 234, 254), width=6)

            # top accent strip for category identity
            draw.rounded_rectangle((90, 90, 1110, 190), radius=28, fill=accent_color)

            # soft product pedestal to make it feel more like a real marketplace thumbnail
            draw.ellipse((290, 770, 910, 1010), fill=(255, 255, 255), outline=(191, 219, 254), width=4)

            try:
                title_font = ImageFont.truetype("arial.ttf", 26)
                initials_font = ImageFont.truetype("arial.ttf", 72)
            except Exception:
                title_font = ImageFont.load_default()
                initials_font = ImageFont.load_default()

            initials = "".join(part[0] for part in product.name.split()[:2] if part)
            initials = initials.upper()[:2] or "PS"

            badge_box = (470, 235, 730, 495)
            draw.rounded_rectangle(badge_box, radius=52, fill=(255, 255, 255), outline=(255, 255, 255), width=0)
            draw.rounded_rectangle((badge_box[0] + 10, badge_box[1] + 10, badge_box[2] - 10, badge_box[3] - 10), radius=42, outline=accent_color, width=8)

            initials_bbox = draw.textbbox((0, 0), initials, font=initials_font)
            initials_w = initials_bbox[2] - initials_bbox[0]
            initials_h = initials_bbox[3] - initials_bbox[1]
            draw.text((600 - initials_w / 2, 365 - initials_h / 2), initials, font=initials_font, fill=accent_color)

            # category icon drawn as a minimal silhouette so the card feels photographic rather than text-heavy
            self._draw_category_icon(draw, icon_type, accent_color)

            def center_text(y, text, font, fill):
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                x = (1200 - text_width) / 2
                draw.text((x, y), text, font=font, fill=fill)

            # a very small label keeps the art clean while still giving the card identity if needed
            center_text(895, product.category, title_font, (100, 116, 139))

            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=92, optimize=True)
            buffer.seek(0)
            placeholder_path.write_bytes(buffer.read())
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} placeholder images, skipped {skipped}."))

    def _draw_category_icon(self, draw, icon_type, accent_color):
        """Draw a clean category silhouette in the center of the tile."""
        if icon_type == "phone":
            draw.rounded_rectangle((500, 285, 700, 600), radius=34, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.rectangle((560, 327, 640, 342), fill=accent_color)
            draw.ellipse((582, 562, 618, 598), fill=accent_color)
            draw.rectangle((520, 410, 680, 540), fill=(235, 245, 255))
        elif icon_type == "laptop":
            draw.rounded_rectangle((400, 300, 800, 545), radius=24, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.rectangle((375, 545, 825, 575), outline=accent_color, width=10, fill=(255, 255, 255))
            draw.rectangle((515, 332, 685, 510), fill=(235, 245, 255), outline=None)
            draw.rounded_rectangle((535, 350, 665, 475), radius=14, fill=(255, 255, 255))
        elif icon_type == "tablet":
            draw.rounded_rectangle((455, 270, 745, 595), radius=30, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.ellipse((592, 560, 608, 576), fill=accent_color)
            draw.rounded_rectangle((490, 315, 710, 530), radius=18, fill=(245, 247, 255))
        elif icon_type == "headphones":
            draw.arc((432, 260, 768, 555), start=200, end=340, fill=accent_color, width=12)
            draw.rounded_rectangle((410, 420, 485, 565), radius=26, fill=(255, 255, 255), outline=accent_color, width=8)
            draw.rounded_rectangle((715, 420, 790, 565), radius=26, fill=(255, 255, 255), outline=accent_color, width=8)
            draw.arc((470, 315, 730, 520), start=210, end=330, fill=(214, 226, 239), width=8)
        elif icon_type == "watch":
            draw.rounded_rectangle((512, 255, 688, 315), radius=24, fill=(255, 255, 255), outline=accent_color, width=8)
            draw.rounded_rectangle((525, 315, 675, 545), radius=32, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.rounded_rectangle((512, 545, 688, 605), radius=24, fill=(255, 255, 255), outline=accent_color, width=8)
            draw.ellipse((556, 350, 644, 438), outline=accent_color, width=8)
            draw.ellipse((570, 364, 630, 424), fill=(245, 247, 250))
        elif icon_type == "camera":
            draw.rounded_rectangle((385, 315, 815, 575), radius=36, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.ellipse((495, 355, 705, 565), outline=accent_color, width=12)
            draw.ellipse((565, 425, 635, 495), fill=accent_color)
            draw.rounded_rectangle((445, 275, 585, 332), radius=16, fill=(255, 255, 255), outline=accent_color, width=8)
            draw.rectangle((520, 390, 680, 540), fill=(245, 247, 252))
        elif icon_type == "car":
            draw.arc((340, 330, 860, 660), start=180, end=360, fill=accent_color, width=12)
            draw.rounded_rectangle((425, 430, 775, 565), radius=48, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.ellipse((460, 550, 555, 645), outline=accent_color, width=12)
            draw.ellipse((645, 550, 740, 645), outline=accent_color, width=12)
            draw.rounded_rectangle((500, 445, 700, 520), radius=26, fill=(240, 250, 253))
        elif icon_type == "speaker":
            draw.rounded_rectangle((485, 275, 715, 610), radius=34, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.ellipse((540, 340, 660, 460), outline=accent_color, width=10)
            draw.ellipse((565, 480, 635, 550), outline=accent_color, width=8)
            draw.rectangle((525, 315, 675, 595), fill=(248, 250, 252))
        else:
            draw.rounded_rectangle((470, 300, 730, 580), radius=30, outline=accent_color, width=10, fill=(255, 255, 255))
            draw.line((520, 360, 680, 500), fill=accent_color, width=10)
            draw.line((680, 360, 520, 500), fill=accent_color, width=10)
            draw.rectangle((520, 390, 680, 500), fill=(245, 247, 250))
