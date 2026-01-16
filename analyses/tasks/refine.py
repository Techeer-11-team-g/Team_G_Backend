"""
Refine Analysis Tasks - 자연어 기반 재분석 병렬 처리.
"""

import logging

from celery import shared_task, chord

from services.redis_service import get_redis_service
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def parse_refine_query_task(
    self,
    query: str,
    available_categories: list[str],
):
    """
    LangChain을 사용하여 자연어 쿼리를 파싱하는 Celery 태스크.

    외부 API 호출: OpenAI API (LangChain)

    Args:
        query: 사용자 자연어 쿼리
        available_categories: 가용 카테고리 목록

    Returns:
        파싱된 쿼리 정보 dict
    """
    from services.langchain_service import get_langchain_service

    try:
        langchain_service = get_langchain_service(temperature=0.3)
        parsed_query = langchain_service.parse_refine_query(query, available_categories)

        logger.info(f"LangChain parsed query: {parsed_query}")
        return parsed_query

    except Exception as e:
        logger.error(f"Failed to parse query with LangChain: {e}")
        # 파싱 실패 시 기본값 반환
        return {
            'action': 'research',
            'target_categories': available_categories,
            'search_keywords': None,
            'brand_filter': None,
            'price_filter': None,
            'style_keywords': [],
        }


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_refine_analysis(
    self,
    refine_id: str,
    analysis_id: int,
    target_object_ids: list[int],
    parsed_query: dict,
):
    """
    자연어 기반 재분석 메인 태스크.
    Celery Group을 사용하여 여러 객체를 병렬 처리합니다.

    Args:
        refine_id: 재분석 작업 ID (UUID)
        analysis_id: 원본 분석 ID
        target_object_ids: 재검색 대상 DetectedObject ID 목록
        parsed_query: LangChain으로 파싱된 쿼리 정보
            - action: 'research' | 'filter' | 'change_category'
            - target_categories: 대상 카테고리 목록
            - search_keywords: 추가 검색 키워드
            - style_keywords: 스타일 키워드 목록

    Returns:
        재분석 결과
    """
    redis_service = get_redis_service()

    try:
        # 1. 상태 업데이트: RUNNING
        redis_service.set(f"refine:{refine_id}:status", "RUNNING", ttl=3600)
        redis_service.set(f"refine:{refine_id}:progress", "0", ttl=3600)
        redis_service.set(f"refine:{refine_id}:total", str(len(target_object_ids)), ttl=3600)

        logger.info(f"Starting refine analysis {refine_id} for {len(target_object_ids)} objects")

        # 2. 각 객체별 서브태스크 생성
        subtasks = []
        for obj_id in target_object_ids:
            subtasks.append(
                refine_single_object.s(
                    refine_id=refine_id,
                    detected_object_id=obj_id,
                    parsed_query=parsed_query,
                )
            )

        # 3. Celery Group으로 병렬 실행 후 결과 수집
        # chord: 병렬 실행 후 콜백 태스크 실행
        callback = refine_analysis_complete.s(refine_id=refine_id, analysis_id=analysis_id)
        job = chord(subtasks)(callback)

        logger.info(f"Refine analysis {refine_id} tasks dispatched")
        return {'refine_id': refine_id, 'status': 'DISPATCHED', 'task_count': len(subtasks)}

    except Exception as e:
        logger.error(f"Refine analysis {refine_id} failed to start: {e}")
        redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=3600)
        redis_service.set(f"refine:{refine_id}:error", str(e), ttl=3600)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def refine_single_object(
    self,
    refine_id: str,
    detected_object_id: int,
    parsed_query: dict,
):
    """
    단일 DetectedObject에 대한 재검색 태스크.
    외부 API 호출 (임베딩 생성, OpenSearch 검색)을 수행합니다.

    Args:
        refine_id: 재분석 작업 ID
        detected_object_id: DetectedObject ID
        parsed_query: 파싱된 쿼리 정보

    Returns:
        재검색 결과 (성공/실패, 매칭된 상품 수)
    """
    from analyses.models import DetectedObject, ObjectProductMapping
    from products.models import Product

    redis_service = get_redis_service()
    embedding_service = get_embedding_service()
    opensearch_service = OpenSearchService()

    try:
        # 1. DetectedObject 조회
        detected_obj = DetectedObject.objects.get(id=detected_object_id, is_deleted=False)

        # 2. 검색 텍스트 구성
        search_keywords = parsed_query.get('search_keywords')
        style_keywords = parsed_query.get('style_keywords', [])

        if search_keywords or style_keywords:
            # 텍스트 기반 검색
            search_text = ' '.join(filter(None, [
                detected_obj.object_category,
                search_keywords,
                ' '.join(style_keywords) if style_keywords else None,
            ]))
        else:
            # 기본 카테고리 기반 검색
            search_text = detected_obj.object_category

        # 3. 텍스트 임베딩 생성 (외부 API 호출)
        embedding = embedding_service.get_text_embedding(search_text)

        # 4. OpenSearch 검색 (외부 API 호출)
        category_mapping = {
            'bottom': 'pants',
            'outerwear': 'outer',
        }
        search_category = category_mapping.get(
            detected_obj.object_category, detected_obj.object_category
        )

        search_results = opensearch_service.search_similar_products_hybrid(
            embedding=embedding,
            category=search_category,
            k=5,
            search_k=50,
        )

        # 5. 기존 매핑 삭제 및 새 매핑 생성
        updated_count = 0
        if search_results:
            # 기존 매핑 soft delete
            ObjectProductMapping.objects.filter(
                detected_object=detected_obj,
                is_deleted=False
            ).update(is_deleted=True)

            # 새 매핑 생성 (Product 자동 생성 포함)
            for result in search_results:
                product_id = result.get('product_id')
                if product_id:
                    try:
                        # 1. 기존 Product 검색
                        product = Product.objects.filter(
                            product_url__endswith=f'/{product_id}'
                        ).first()

                        # 2. 없으면 OpenSearch 결과로 자동 생성
                        if not product:
                            product, created = Product.objects.update_or_create(
                                product_url=f'https://www.musinsa.com/app/goods/{product_id}',
                                defaults={
                                    'brand_name': result.get('brand', 'Unknown'),
                                    'product_name': result.get('name', 'Unknown'),
                                    'category': result.get('category', detected_obj.object_category),
                                    'selling_price': int(result.get('price', 0) or 0),
                                    'product_image_url': result.get('image_url', ''),
                                }
                            )
                            if created:
                                logger.info(f"Auto-created Product {product_id}: {result.get('name', '')[:30]}")

                        # 3. 매핑 생성
                        ObjectProductMapping.objects.create(
                            detected_object=detected_obj,
                            product=product,
                            confidence_score=result.get('score', 0.0),
                        )
                        updated_count += 1

                    except Exception as e:
                        logger.warning(f"Error creating mapping for product {product_id}: {e}")

        # 6. 진행률 업데이트
        current = redis_service.get(f"refine:{refine_id}:completed") or "0"
        redis_service.set(f"refine:{refine_id}:completed", str(int(current) + 1), ttl=3600)

        logger.info(f"Refine object {detected_object_id} completed: {updated_count} mappings created")

        return {
            'detected_object_id': detected_object_id,
            'status': 'SUCCESS',
            'mappings_created': updated_count,
        }

    except DetectedObject.DoesNotExist:
        logger.error(f"DetectedObject {detected_object_id} not found")
        return {
            'detected_object_id': detected_object_id,
            'status': 'FAILED',
            'error': 'Object not found',
        }
    except Exception as e:
        logger.error(f"Failed to refine object {detected_object_id}: {e}")
        raise self.retry(exc=e)


@shared_task
def refine_analysis_complete(
    results: list[dict],
    refine_id: str,
    analysis_id: int,
):
    """
    모든 객체 재검색이 완료된 후 호출되는 콜백 태스크.
    최종 상태를 업데이트하고 결과를 집계합니다.

    Args:
        results: 각 서브태스크의 결과 목록
        refine_id: 재분석 작업 ID
        analysis_id: 원본 분석 ID

    Returns:
        최종 결과 요약
    """
    redis_service = get_redis_service()

    try:
        # 결과 집계
        success_count = sum(1 for r in results if r.get('status') == 'SUCCESS')
        failed_count = sum(1 for r in results if r.get('status') == 'FAILED')
        total_mappings = sum(r.get('mappings_created', 0) for r in results)

        # 최종 상태 업데이트
        redis_service.set(f"refine:{refine_id}:status", "DONE", ttl=3600)
        redis_service.set(f"refine:{refine_id}:success_count", str(success_count), ttl=3600)
        redis_service.set(f"refine:{refine_id}:failed_count", str(failed_count), ttl=3600)
        redis_service.set(f"refine:{refine_id}:total_mappings", str(total_mappings), ttl=3600)

        logger.info(
            f"Refine analysis {refine_id} completed: "
            f"{success_count} success, {failed_count} failed, {total_mappings} mappings"
        )

        return {
            'refine_id': refine_id,
            'analysis_id': analysis_id,
            'status': 'DONE',
            'success_count': success_count,
            'failed_count': failed_count,
            'total_mappings': total_mappings,
        }

    except Exception as e:
        logger.error(f"Failed to complete refine analysis {refine_id}: {e}")
        redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=3600)
        redis_service.set(f"refine:{refine_id}:error", str(e), ttl=3600)
        return {
            'refine_id': refine_id,
            'status': 'FAILED',
            'error': str(e),
        }
