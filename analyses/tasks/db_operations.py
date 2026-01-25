"""
Database Operations - DB 저장/조회 유틸리티.

이 모듈은 분석 결과의 데이터베이스 작업을 담당합니다:
- 분석 상태 업데이트
- 결과 저장 (bulk_create 최적화)
- 메트릭 업데이트

Usage:
    from analyses.tasks.db_operations import (
        update_analysis_status_db,
        save_analysis_results,
    )
"""

import logging
from typing import Optional

from analyses.tasks.image_processing import normalize_result_bbox
from services.metrics import (
    ANALYSIS_TOTAL,
    ANALYSES_COMPLETED_TOTAL,
    PRODUCT_MATCHES_TOTAL,
)


logger = logging.getLogger(__name__)


def update_analysis_status_db(analysis_id: str, status: str) -> bool:
    """
    DB의 ImageAnalysis 상태 업데이트.

    Args:
        analysis_id: 분석 ID
        status: 새 상태 ('PENDING', 'RUNNING', 'DONE', 'FAILED')

    Returns:
        성공 여부
    """
    from analyses.models import ImageAnalysis

    try:
        analysis = ImageAnalysis.objects.get(id=analysis_id)
        analysis.image_analysis_status = status
        analysis.save(update_fields=['image_analysis_status', 'updated_at'])
        logger.info(f"Set analysis {analysis_id} status to {status}")
        return True
    except ImageAnalysis.DoesNotExist:
        logger.error(f"ImageAnalysis {analysis_id} not found for status update")
        return False


def save_analysis_results(
    analysis_id: str,
    results: list[dict],
    user_id: Optional[int],
) -> bool:
    """
    분석 결과를 MySQL에 bulk 저장.

    최적화된 저장 프로세스 (트랜잭션 + 최소 쿼리):
    1. 트랜잭션 내에서 모든 작업 수행
    2. DetectedObject bulk_create
    3. Product 조회/생성 (단일 쿼리)
    4. ObjectProductMapping bulk_create

    Args:
        analysis_id: 분석 ID
        results: 처리된 결과 리스트
        user_id: 사용자 ID (optional)

    Returns:
        성공 여부
    """
    from django.db import transaction
    from analyses.models import ImageAnalysis, DetectedObject, ObjectProductMapping
    from products.models import Product

    try:
        with transaction.atomic():
            analysis = ImageAnalysis.objects.select_related('uploaded_image').get(id=analysis_id)
            uploaded_image = analysis.uploaded_image

            # 1단계: DetectedObject bulk_create (ID 반환 활용)
            detected_objects_data = []
            for result in results:
                normalized_bbox = normalize_result_bbox(result.get('bbox', {}))
                detected_objects_data.append(DetectedObject(
                    uploaded_image=uploaded_image,
                    object_category=result.get('category', 'unknown'),
                    bbox_x1=normalized_bbox['x1'],
                    bbox_y1=normalized_bbox['y1'],
                    bbox_x2=normalized_bbox['x2'],
                    bbox_y2=normalized_bbox['y2'],
                    cropped_image_url=result.get('cropped_image_url'),
                ))

            # bulk_create with update_conflicts to get IDs back (Django 4.1+)
            created_objects = DetectedObject.objects.bulk_create(detected_objects_data)
            logger.info(f"Bulk created {len(created_objects)} DetectedObjects")

            # 2단계: 모든 product_id 수집 + match 정보 매핑
            all_product_ids = set()
            for result in results:
                for match in result.get('matches', []):
                    pid = match.get('product_id')
                    if pid:
                        all_product_ids.add(str(pid))

            if not all_product_ids:
                # 매핑할 상품 없음
                analysis.image_analysis_status = ImageAnalysis.Status.DONE
                analysis.save(update_fields=['image_analysis_status', 'updated_at'])
                return True

            # 3단계: Product 조회/생성 (단일 쿼리로 최적화)
            # product_id로 직접 조회 (URL 파싱 대신)
            product_urls = []
            for pid in all_product_ids:
                product_urls.append(f"https://www.musinsa.com/products/{pid}")
                product_urls.append(f"https://www.musinsa.com/app/goods/{pid}")

            existing_products = {}
            for product in Product.objects.filter(product_url__in=product_urls):
                pid = product.product_url.rstrip('/').split('/')[-1]
                if pid not in existing_products or '/products/' in product.product_url:
                    existing_products[pid] = product

            # 4단계: 없는 Product 일괄 생성
            new_products_data = []
            new_product_ids = []
            for result in results:
                for match in result.get('matches', []):
                    pid = str(match.get('product_id', ''))
                    if pid and pid not in existing_products and pid not in new_product_ids:
                        new_products_data.append(Product(
                            product_url=f"https://www.musinsa.com/app/goods/{pid}",
                            brand_name=match.get('brand', 'Unknown') or 'Unknown',
                            product_name=match.get('name', 'Unknown') or 'Unknown',
                            category=result.get('category', 'unknown'),
                            selling_price=int(match.get('price', 0) or 0),
                            product_image_url=match.get('image_url', '') or '',
                        ))
                        new_product_ids.append(pid)

            if new_products_data:
                created_products = Product.objects.bulk_create(
                    new_products_data, ignore_conflicts=True
                )
                # bulk_create 결과에서 ID 있는 것만 사용
                for product, pid in zip(created_products, new_product_ids):
                    if product.id:
                        existing_products[pid] = product
                    else:
                        # ignore_conflicts로 인해 ID 없는 경우 다시 조회
                        pass

                # 새로 생성된 Product 중 ID 없는 것 조회 (ignore_conflicts 케이스)
                missing_pids = [pid for pid in new_product_ids if pid not in existing_products]
                if missing_pids:
                    missing_urls = [f"https://www.musinsa.com/app/goods/{pid}" for pid in missing_pids]
                    for product in Product.objects.filter(product_url__in=missing_urls):
                        pid = product.product_url.rstrip('/').split('/')[-1]
                        existing_products[pid] = product

                logger.info(f"Bulk created {len(new_products_data)} new Products")

            # 5단계: ObjectProductMapping bulk_create
            mappings_data = []
            for obj, result in zip(created_objects, results):
                for match in result.get('matches', []):
                    pid = str(match.get('product_id', ''))
                    product = existing_products.get(pid)
                    if product:
                        mappings_data.append(ObjectProductMapping(
                            detected_object=obj,
                            product=product,
                            confidence_score=match.get('score', 0.0),
                        ))

            if mappings_data:
                ObjectProductMapping.objects.bulk_create(mappings_data)
                logger.info(f"Bulk created {len(mappings_data)} ObjectProductMappings")

            # 상태 업데이트
            analysis.image_analysis_status = ImageAnalysis.Status.DONE
            analysis.save(update_fields=['image_analysis_status', 'updated_at'])

        logger.info(f"Successfully saved {len(results)} results for analysis {analysis_id}")
        return True

    except ImageAnalysis.DoesNotExist:
        logger.error(f"ImageAnalysis {analysis_id} not found")
        return False
    except Exception as e:
        logger.error(f"Failed to save analysis results: {e}")
        raise


def update_metrics_on_success(valid_results: list[dict]) -> None:
    """
    분석 성공 시 메트릭 업데이트.

    Args:
        valid_results: 유효한 분석 결과 리스트
    """
    ANALYSIS_TOTAL.labels(status='success').inc()
    ANALYSES_COMPLETED_TOTAL.inc()

    for result in valid_results:
        category = result.get('category', 'unknown')
        match_count = len(result.get('matches', []))
        for _ in range(match_count):
            PRODUCT_MATCHES_TOTAL.labels(category=category).inc()


def update_metrics_on_failure() -> None:
    """분석 실패 시 메트릭 업데이트."""
    ANALYSIS_TOTAL.labels(status='failed').inc()
