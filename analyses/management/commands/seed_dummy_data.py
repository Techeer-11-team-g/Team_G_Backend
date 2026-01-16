"""
더미 데이터 생성 커맨드
Usage: python manage.py seed_dummy_data
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import random

from users.models import User
from products.models import SizeCode, Product
from analyses.models import (
    UploadedImage, ImageAnalysis, DetectedObject,
    ObjectProductMapping, SelectedProduct
)
from fittings.models import UserImage, FittingImage
from orders.models import CartItem, Order, OrderItem


class Command(BaseCommand):
    help = '테스트용 더미 데이터를 생성합니다.'

    def handle(self, *args, **options):
        self.stdout.write('더미 데이터 생성을 시작합니다...\n')

        # 1. Users 생성
        self.stdout.write('1. 사용자 생성 중...')
        users = self._create_users()
        self.stdout.write(self.style.SUCCESS(f'   -> {len(users)}명 생성 완료'))

        # 2. Products 생성
        self.stdout.write('2. 상품 생성 중...')
        products = self._create_products()
        self.stdout.write(self.style.SUCCESS(f'   -> {len(products)}개 생성 완료'))

        # 3. SizeCode 생성 (Product에 연결)
        self.stdout.write('3. 사이즈 코드 생성 중...')
        size_codes = self._create_sizes(products)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(size_codes)}개 생성 완료'))

        # 4. UploadedImages 생성
        self.stdout.write('4. 업로드 이미지 생성 중...')
        uploaded_images = self._create_uploaded_images(users)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(uploaded_images)}개 생성 완료'))

        # 5. ImageAnalysis 생성
        self.stdout.write('5. 이미지 분석 생성 중...')
        analyses = self._create_image_analyses(uploaded_images)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(analyses)}개 생성 완료'))

        # 6. DetectedObjects 생성
        self.stdout.write('6. 검출 객체 생성 중...')
        detected_objects = self._create_detected_objects(uploaded_images)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(detected_objects)}개 생성 완료'))

        # 7. ObjectProductMapping 생성
        self.stdout.write('7. 객체-상품 매핑 생성 중...')
        mappings = self._create_object_product_mappings(detected_objects, products)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(mappings)}개 생성 완료'))

        # 8. SelectedProducts 생성
        self.stdout.write('8. 선택된 상품 생성 중...')
        selected_products = self._create_selected_products(products, size_codes)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(selected_products)}개 생성 완료'))

        # 9. UserImages 생성
        self.stdout.write('9. 사용자 이미지 생성 중...')
        user_images = self._create_user_images(users)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(user_images)}개 생성 완료'))

        # 10. FittingImages 생성
        self.stdout.write('10. 피팅 이미지 생성 중...')
        fitting_images = self._create_fitting_images(user_images, products)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(fitting_images)}개 생성 완료'))

        # 11. CartItems 생성
        self.stdout.write('11. 장바구니 항목 생성 중...')
        cart_items = self._create_cart_items(users, selected_products)
        self.stdout.write(self.style.SUCCESS(f'   -> {len(cart_items)}개 생성 완료'))

        # 12. Orders & OrderItems 생성
        self.stdout.write('12. 주문 및 주문 항목 생성 중...')
        orders, order_items = self._create_orders(users, selected_products)
        self.stdout.write(self.style.SUCCESS(f'   -> 주문 {len(orders)}개, 항목 {len(order_items)}개 생성 완료'))

        self.stdout.write(self.style.SUCCESS('\n모든 더미 데이터 생성이 완료되었습니다!'))

    def _create_users(self):
        users_data = [
            {'username': 'testuser1', 'email': 'test1@example.com', 'first_name': '민준', 'last_name': '김', 'phone_number': '010-1234-5678', 'address': '서울시 강남구 테헤란로 123'},
            {'username': 'testuser2', 'email': 'test2@example.com', 'first_name': '서연', 'last_name': '이', 'phone_number': '010-2345-6789', 'address': '서울시 서초구 반포대로 456'},
            {'username': 'testuser3', 'email': 'test3@example.com', 'first_name': '도윤', 'last_name': '박', 'phone_number': '010-3456-7890', 'address': '서울시 송파구 올림픽로 789'},
            {'username': 'testuser4', 'email': 'test4@example.com', 'first_name': '하은', 'last_name': '최', 'phone_number': '010-4567-8901', 'address': '서울시 마포구 홍대입구역로 101'},
            {'username': 'testuser5', 'email': 'test5@example.com', 'first_name': '지호', 'last_name': '정', 'phone_number': '010-5678-9012', 'address': '서울시 영등포구 여의대로 202'},
        ]
        users = []
        for data in users_data:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    **data,
                    'birth_date': timezone.now() - timedelta(days=random.randint(7000, 15000)),
                    'user_image_url': f'https://example.com/profiles/{data["username"]}.jpg',
                }
            )
            if created:
                user.set_password('testpass123')
                user.save()
            users.append(user)
        return users

    def _create_products(self):
        products_data = [
            {'brand_name': 'Nike', 'product_name': '에어맥스 97', 'selling_price': 199000, 'product_url': 'https://nike.com/airmax97', 'product_image_url': 'https://example.com/nike_airmax97.jpg'},
            {'brand_name': 'Adidas', 'product_name': '울트라부스트 22', 'selling_price': 229000, 'product_url': 'https://adidas.com/ultraboost22', 'product_image_url': 'https://example.com/adidas_ultraboost.jpg'},
            {'brand_name': 'Zara', 'product_name': '오버사이즈 블레이저', 'selling_price': 159000, 'product_url': 'https://zara.com/blazer', 'product_image_url': 'https://example.com/zara_blazer.jpg'},
            {'brand_name': 'H&M', 'product_name': '슬림핏 치노 팬츠', 'selling_price': 49900, 'product_url': 'https://hm.com/chino', 'product_image_url': 'https://example.com/hm_chino.jpg'},
            {'brand_name': 'Uniqlo', 'product_name': '에어리즘 코튼 티셔츠', 'selling_price': 19900, 'product_url': 'https://uniqlo.com/airism', 'product_image_url': 'https://example.com/uniqlo_airism.jpg'},
            {'brand_name': 'Gucci', 'product_name': 'GG 마몽 숄더백', 'selling_price': 2890000, 'product_url': 'https://gucci.com/marmont', 'product_image_url': 'https://example.com/gucci_marmont.jpg'},
            {'brand_name': 'Louis Vuitton', 'product_name': '네버풀 MM', 'selling_price': 2150000, 'product_url': 'https://louisvuitton.com/neverfull', 'product_image_url': 'https://example.com/lv_neverfull.jpg'},
            {'brand_name': 'Musinsa Standard', 'product_name': '릴렉스드 핏 후드', 'selling_price': 39900, 'product_url': 'https://musinsa.com/hood', 'product_image_url': 'https://example.com/musinsa_hood.jpg'},
            {'brand_name': 'Converse', 'product_name': '척 70 하이탑', 'selling_price': 95000, 'product_url': 'https://converse.com/chuck70', 'product_image_url': 'https://example.com/converse_chuck70.jpg'},
            {'brand_name': 'Levi\'s', 'product_name': '501 오리지널 핏 진', 'selling_price': 129000, 'product_url': 'https://levis.com/501', 'product_image_url': 'https://example.com/levis_501.jpg'},
        ]
        products = []
        for data in products_data:
            product, _ = Product.objects.get_or_create(
                brand_name=data['brand_name'],
                product_name=data['product_name'],
                defaults=data
            )
            products.append(product)
        return products

    def _create_sizes(self, products):
        """상품별 사이즈 코드 생성"""
        # 신발 상품 (Nike, Adidas, Converse)
        shoe_products = [p for p in products if p.brand_name in ['Nike', 'Adidas', 'Converse']]
        shoe_sizes = ['230', '240', '250', '260', '270', '280']

        # 의류 상품
        clothing_products = [p for p in products if p.brand_name in ['Zara', 'H&M', 'Uniqlo', 'Musinsa Standard', "Levi's"]]
        clothing_sizes = ['XS', 'S', 'M', 'L', 'XL', 'XXL']

        # 가방 상품
        bag_products = [p for p in products if p.brand_name in ['Gucci', 'Louis Vuitton']]
        bag_sizes = ['S', 'M', 'L']

        size_codes = []

        for product in shoe_products:
            for size in shoe_sizes:
                sc, _ = SizeCode.objects.get_or_create(
                    product=product,
                    size_value=size,
                )
                size_codes.append(sc)

        for product in clothing_products:
            for size in clothing_sizes:
                sc, _ = SizeCode.objects.get_or_create(
                    product=product,
                    size_value=size,
                )
                size_codes.append(sc)

        for product in bag_products:
            for size in bag_sizes:
                sc, _ = SizeCode.objects.get_or_create(
                    product=product,
                    size_value=size,
                )
                size_codes.append(sc)

        return size_codes

    def _create_uploaded_images(self, users):
        uploaded_images = []
        for i, user in enumerate(users):
            for j in range(2):  # 유저당 2개 이미지
                img, _ = UploadedImage.objects.get_or_create(
                    user=user,
                    uploaded_image_url=f'uploaded-images/2026/01/11/test_image_{user.id}_{j}.jpg',
                )
                uploaded_images.append(img)
        return uploaded_images

    def _create_image_analyses(self, uploaded_images):
        statuses = ['PENDING', 'RUNNING', 'DONE', 'DONE', 'DONE', 'FAILED']
        analyses = []
        for img in uploaded_images:
            analysis, _ = ImageAnalysis.objects.get_or_create(
                uploaded_image=img,
                defaults={'image_analysis_status': random.choice(statuses)}
            )
            analyses.append(analysis)
        return analyses

    def _create_detected_objects(self, uploaded_images):
        categories = ['상의', '하의', '신발', '가방', '아우터']
        detected_objects = []
        for img in uploaded_images:
            num_objects = random.randint(1, 3)
            for i in range(num_objects):
                x1 = round(random.uniform(0.1, 0.4), 2)
                y1 = round(random.uniform(0.1, 0.4), 2)
                x2 = round(x1 + random.uniform(0.2, 0.4), 2)
                y2 = round(y1 + random.uniform(0.2, 0.4), 2)

                obj, _ = DetectedObject.objects.get_or_create(
                    uploaded_image=img,
                    object_category=categories[i % len(categories)],
                    defaults={
                        'bbox_x1': x1,
                        'bbox_y1': y1,
                        'bbox_x2': min(x2, 1.0),
                        'bbox_y2': min(y2, 1.0),
                    }
                )
                detected_objects.append(obj)
        return detected_objects

    def _create_object_product_mappings(self, detected_objects, products):
        mappings = []
        for obj in detected_objects:
            # 각 검출 객체당 1-3개의 유사 상품 매핑
            num_mappings = random.randint(1, 3)
            selected_products = random.sample(products, min(num_mappings, len(products)))
            for product in selected_products:
                mapping, _ = ObjectProductMapping.objects.get_or_create(
                    detected_object=obj,
                    product=product,
                    defaults={'confidence_score': round(random.uniform(0.5, 0.95), 2)}
                )
                mappings.append(mapping)
        return mappings

    def _create_selected_products(self, products, size_codes):
        selected_products = []
        for product in products:
            # 해당 상품의 사이즈 코드 중 일부 선택
            product_sizes = [sc for sc in size_codes if sc.product_id == product.id]
            if product_sizes:
                num_sizes = min(random.randint(2, 3), len(product_sizes))
                selected_sizes = random.sample(product_sizes, num_sizes)
                for size in selected_sizes:
                    sp, _ = SelectedProduct.objects.get_or_create(
                        product=product,
                        size_code=size,
                        defaults={'selected_product_inventory': random.randint(0, 100)}
                    )
                    selected_products.append(sp)
        return selected_products

    def _create_user_images(self, users):
        user_images = []
        for user in users:
            img, _ = UserImage.objects.get_or_create(
                user=user,
                defaults={'user_image_url': f'user-images/2026/01/11/{user.username}_fullbody.jpg'}
            )
            user_images.append(img)
        return user_images

    def _create_fitting_images(self, user_images, products):
        statuses = ['PENDING', 'RUNNING', 'DONE', 'DONE', 'FAILED']
        fitting_images = []
        for user_image in user_images:
            # 유저당 1-2개 피팅 이미지
            num_fittings = random.randint(1, 2)
            selected_products = random.sample(products, min(num_fittings, len(products)))
            for product in selected_products:
                status = random.choice(statuses)
                fitting, _ = FittingImage.objects.get_or_create(
                    user_image=user_image,
                    product=product,
                    defaults={
                        'fitting_image_status': status,
                        'fitting_image_url': f'https://example.com/fittings/{user_image.user.username}_{product.id}.jpg' if status == 'DONE' else None,
                    }
                )
                fitting_images.append(fitting)
        return fitting_images

    def _create_cart_items(self, users, selected_products):
        cart_items = []
        for user in users[:3]:  # 처음 3명의 유저만
            num_items = random.randint(1, 3)
            selected = random.sample(selected_products, min(num_items, len(selected_products)))
            for sp in selected:
                item, _ = CartItem.objects.get_or_create(
                    user=user,
                    selected_product=sp,
                    defaults={'quantity': random.randint(1, 3)}
                )
                cart_items.append(item)
        return cart_items

    def _create_orders(self, users, selected_products):
        statuses = ['PENDING', 'PAID', 'PREPARING', 'SHIPPING', 'DELIVERED', 'CANCELLED']
        orders = []
        order_items = []

        for user in users[:4]:  # 처음 4명의 유저만
            num_orders = random.randint(1, 2)
            for _ in range(num_orders):
                order = Order.objects.create(
                    user=user,
                    total_price=0,
                    delivery_address=user.address or '서울시 강남구 테스트로 123',
                )
                orders.append(order)

                # 주문당 1-3개 아이템
                num_items = random.randint(1, 3)
                selected = random.sample(selected_products, min(num_items, len(selected_products)))
                total = 0

                for sp in selected:
                    quantity = random.randint(1, 2)
                    price = sp.product.selling_price

                    oi = OrderItem.objects.create(
                        order=order,
                        product_item=sp,
                        purchased_quantity=quantity,
                        price_at_order=price,
                        order_status=random.choice(statuses),
                    )
                    order_items.append(oi)
                    total += price * quantity

                order.total_price = total
                order.save()

        return orders, order_items
