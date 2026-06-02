from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.core.files.base import ContentFile
from products.models import ProductNews
from io import BytesIO
import textwrap

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


class Command(BaseCommand):
    help = "Generate simple placeholder images for ProductNews items missing an image"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Limit number of items to process (0 = all)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without saving files")

    def handle(self, *args, **options):
        if not PIL_AVAILABLE:
            self.stderr.write("Pillow is not available. Install pillow to generate images.")
            return

        limit = options.get("limit") or 0
        dry_run = options.get("dry_run")

        qs = ProductNews.objects.filter(is_published=True).order_by("published_at")
        # only items without uploaded image
        qs = qs.filter(image__isnull=True)
        if limit > 0:
            qs = qs[:limit]

        # Try to pick a reasonable fallback font
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except Exception:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        count = 0
        for item in qs:
            title = (item.title or "News").strip()
            date = item.published_at or timezone.now()
            filename = f"news/{date.year}/{date:%m}/{date:%d}/{item.slug}_placeholder.jpg"

            # build a simple image
            w, h = 1200, 800
            img = Image.new("RGB", (w, h), (255, 255, 255))
            draw = ImageDraw.Draw(img)

            # category badge
            badge_text = (item.news_category or "general").upper()
            badge_w, badge_h = draw.textsize(badge_text, font=font)
            badge_pad = 18
            rect_w = badge_w + badge_pad * 2
            rect_h = badge_h + badge_pad
            draw.rectangle([(48, 48), (48 + rect_w, 48 + rect_h)], fill=(3, 105, 161))
            draw.text((48 + badge_pad, 48 + (badge_pad // 2)), badge_text, fill=(255, 255, 255), font=font)

            # title text wrap
            lines = textwrap.wrap(title, width=28)
            y = 160
            title_font = font
            for line in lines[:6]:
                draw.text((80, y), line, fill=(15, 23, 42), font=title_font)
                y += 64

            # small footer
            footer = "SmartSaver"
            draw.text((80, h - 80), footer, fill=(100, 116, 139), font=font)

            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)

            if dry_run:
                self.stdout.write(f"[DRY] Would create {filename} for {item.slug}")
            else:
                try:
                    item.image.save(filename.split('/')[-1], ContentFile(buffer.read()), save=True)
                    # generate thumbnails if model supports it
                    try:
                        item.generate_thumbnails()
                    except Exception:
                        import logging
                        logging.exception("generate_thumbnails failed for %s", item.slug)
                    self.stdout.write(f"Created placeholder for: {item.slug} -> {filename}")
                    count += 1
                except Exception as e:
                    self.stderr.write(f"Failed to save image for {item.slug}: {e}")

        self.stdout.write(f"Done. Processed {count} items.")
