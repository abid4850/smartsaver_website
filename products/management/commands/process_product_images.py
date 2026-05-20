from django.core.management.base import BaseCommand
from products.models import Product


class Command(BaseCommand):
    help = "Download and generate thumbnails for product images"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of products to process"
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=10,
            help="Process products in batches (default 10)"
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reprocess images even if local files already exist",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        batch_size = options.get("batch", 10)
        force = options.get("force", False)
        
        products = Product.objects.filter(image_url__isnull=False, image_url__gt="")
        if limit:
            products = products[:limit]
        
        total = products.count()
        self.stdout.write(f"Processing {total} products...")
        
        processed = 0
        failed = 0
        skipped = 0
        
        for idx, product in enumerate(products, 1):
            try:
                if product._is_placeholder_url(product.image_url):
                    skipped += 1
                    self.stdout.write(f"[{idx}/{total}] SKIP {product.name} (placeholder image)")
                    continue
                # check if local image already exists
                local_name = product._local_image_name()
                from django.core.files.storage import default_storage
                if local_name and default_storage.exists(local_name) and not force:
                    skipped += 1
                    self.stdout.write(f"[{idx}/{total}] SKIP {product.name} (local exists)")
                    continue
                
                # download and process
                self.stdout.write(f"[{idx}/{total}] Processing {product.name}...")
                product.download_and_process_image()
                processed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{idx}/{total}] OK {product.name}"
                    )
                )
            except Exception as e:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"[{idx}/{total}] FAIL {product.name}: {str(e)}"
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {processed} processed, {skipped} skipped, {failed} failed"
            )
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {processed} processed, {skipped} skipped, {failed} failed"
            )
        )
