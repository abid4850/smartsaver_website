from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from products.models import Product


class Command(BaseCommand):
    help = "Import curated product images from a directory into Product.image."

    def add_arguments(self, parser):
        parser.add_argument(
            "source_dir",
            type=str,
            help="Directory containing curated product image files",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing uploaded images",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        force = options["force"]

        if not source_dir.exists() or not source_dir.is_dir():
            raise CommandError(f"Source directory not found: {source_dir}")

        image_files = [
            path for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]

        if not image_files:
            self.stdout.write(self.style.WARNING("No image files found in source directory."))
            return

        products = list(Product.objects.all())
        by_id = {str(product.id): product for product in products}
        by_slug = {self._slugify_product_name(product.name): product for product in products}
        by_name = {self._slugify_product_name(product.name): product for product in products}

        imported = 0
        skipped = 0
        unmatched = []

        for image_path in image_files:
            stem = image_path.stem
            key = self._slugify_product_name(stem)

            product = by_id.get(stem) or by_slug.get(key) or by_name.get(key)
            if not product:
                unmatched.append(image_path.name)
                continue

            if product.image and not force:
                skipped += 1
                continue

            with image_path.open("rb") as image_file:
                product.image.save(image_path.name, File(image_file), save=True)
                imported += 1

        self.stdout.write(self.style.SUCCESS(f"Imported {imported} images, skipped {skipped}."))
        if unmatched:
            self.stdout.write(self.style.WARNING("Unmatched files:"))
            for filename in unmatched:
                self.stdout.write(f" - {filename}")

    def _slugify_product_name(self, value: str) -> str:
        return "".join(ch.lower() for ch in value if ch.isalnum())
