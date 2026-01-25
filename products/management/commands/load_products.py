import json
from django.core.management.base import BaseCommand
from django.db import transaction
from products.models import Product, SizeCode


class Command(BaseCommand):
    help = 'Load products from JSONL file into database (bulk insert)'

    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            type=str,
            help='Path to the JSONL file containing product data'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing products before loading'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Batch size for bulk insert (default: 1000)'
        )

    def handle(self, *args, **options):
        file_path = options['file_path']
        batch_size = options['batch_size']

        if options['clear']:
            self.stdout.write('Clearing existing products...')
            SizeCode.objects.all().delete()
            Product.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared all products'))

        self.stdout.write(f'Loading products from {file_path} (batch_size={batch_size})...')

        products_batch = []
        sizes_data = []  # [(product_url, size_value), ...]
        total_count = 0
        error_count = 0

        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    product = Product(
                        brand_name=data.get('brand', ''),
                        product_name=data.get('productName', ''),
                        category=data.get('category', 'free'),
                        product_url=data.get('productUrl', ''),
                        selling_price=int(data.get('price', 0)),
                        product_image_url=data.get('imageUrl', ''),
                    )
                    products_batch.append(product)

                    # Store size info for later
                    sizes = data.get('sizes', '')
                    if sizes:
                        product_url = data.get('productUrl', '')
                        for size_value in sizes.split(','):
                            size_value = size_value.strip()
                            if size_value:
                                sizes_data.append((product_url, size_value))

                    # Bulk insert when batch is full
                    if len(products_batch) >= batch_size:
                        self._bulk_insert(products_batch, sizes_data)
                        total_count += len(products_batch)
                        self.stdout.write(f'Inserted {total_count} products...')
                        products_batch = []
                        sizes_data = []

                except json.JSONDecodeError as e:
                    error_count += 1
                    if error_count <= 10:
                        self.stdout.write(
                            self.style.ERROR(f'Line {line_num}: JSON error - {e}')
                        )
                except Exception as e:
                    error_count += 1
                    if error_count <= 10:
                        self.stdout.write(
                            self.style.ERROR(f'Line {line_num}: Error - {e}')
                        )

        # Insert remaining products
        if products_batch:
            self._bulk_insert(products_batch, sizes_data)
            total_count += len(products_batch)

        self.stdout.write(self.style.SUCCESS(
            f'\nDone! Total inserted: {total_count}, Errors: {error_count}'
        ))

    @transaction.atomic
    def _bulk_insert(self, products_batch, sizes_data):
        # Bulk create products
        Product.objects.bulk_create(products_batch, ignore_conflicts=True)

        # Create sizes
        if sizes_data:
            # Get product IDs by URL
            urls = list(set(url for url, _ in sizes_data))
            url_to_product = {
                p.product_url: p
                for p in Product.objects.filter(product_url__in=urls)
            }

            size_objects = []
            for product_url, size_value in sizes_data:
                product = url_to_product.get(product_url)
                if product:
                    size_objects.append(SizeCode(
                        product=product,
                        size_value=size_value
                    ))

            if size_objects:
                SizeCode.objects.bulk_create(size_objects, ignore_conflicts=True)
