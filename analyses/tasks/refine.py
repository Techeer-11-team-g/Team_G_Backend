"""
Refine Analysis Tasks - 자연어 기반 재분석 병렬 처리.
"""

import logging
import requests
import numpy as np
from io import BytesIO
from PIL import Image

from celery import shared_task, chord

from services.redis_service import get_redis_service
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService

logger = logging.getLogger(__name__)


def _download_and_crop_image(image_url: str, bbox_x1: float, bbox_y1: float, bbox_x2: float, bbox_y2: float) -> Image.Image:
    """
    이미지 URL에서 다운로드 후 바운딩 박스로 크롭.

    Args:
        image_url: 원본 이미지 URL
        bbox_x1, bbox_y1, bbox_x2, bbox_y2: 바운딩 박스 좌표 (normalized 0-1)

    Returns:
        크롭된 PIL Image
    """
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()

    img = Image.open(BytesIO(response.content))
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # 바운딩 박스 좌표 변환 (normalized → pixels)
    w, h = img.size
    left = int(bbox_x1 * w)
    top = int(bbox_y1 * h)
    right = int(bbox_x2 * w)
    bottom = int(bbox_y2 * h)

    # 여유 마진 추가 (10%)
    margin_x = int((right - left) * 0.1)
    margin_y = int((bottom - top) * 0.1)

    left = max(0, left - margin_x)
    top = max(0, top - margin_y)
    right = min(w, right + margin_x)
    bottom = min(h, bottom + margin_y)

    cropped = img.crop((left, top, right, bottom))
    return cropped


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
        refine_id: 재분석 작업 ID (UUID) - DB에 저장되지 않는 Redis 임시 키 (작업 추적용)
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
        # (Redis 임시 저장: 작업 상태 추적용, 1시간 후 만료)
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
        # (Redis 임시 저장: 실패 상태 기록)
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

        # 2. 파싱된 쿼리에서 필터 정보 추출
        search_keywords = parsed_query.get('search_keywords')  # 자연어 검색 키워드
        style_keywords = parsed_query.get('style_keywords') or []  # 스타일 키워드 리스트
        color_filter = parsed_query.get('color_filter')
        pattern_filter = parsed_query.get('pattern_filter')
        style_vibe = parsed_query.get('style_vibe')
        sleeve_length = parsed_query.get('sleeve_length')
        pants_length = parsed_query.get('pants_length')
        outer_length = parsed_query.get('outer_length')
        material_filter = parsed_query.get('material_filter')
        brand_filter = parsed_query.get('brand_filter')
        price_sort = parsed_query.get('price_sort')

        # 3. 이미지 임베딩 생성 (크롭된 이미지 사용)
        image_embedding = None
        try:
            # 원본 이미지에서 바운딩 박스로 크롭
            uploaded_image = detected_obj.uploaded_image
            # GCS URL 또는 로컬 파일 경로
            if hasattr(uploaded_image, 'uploaded_image_url') and uploaded_image.uploaded_image_url:
                image_url = uploaded_image.uploaded_image_url.url
            else:
                image_url = None

            # bbox 좌표 확인
            has_bbox = (
                detected_obj.bbox_x1 > 0 or detected_obj.bbox_y1 > 0 or
                detected_obj.bbox_x2 > 0 or detected_obj.bbox_y2 > 0
            )

            if image_url and has_bbox:
                cropped_img = _download_and_crop_image(
                    image_url,
                    detected_obj.bbox_x1,
                    detected_obj.bbox_y1,
                    detected_obj.bbox_x2,
                    detected_obj.bbox_y2,
                )
                # PIL Image를 bytes로 변환
                img_byte_arr = BytesIO()
                cropped_img.save(img_byte_arr, format='JPEG')
                img_bytes = img_byte_arr.getvalue()
                image_embedding = embedding_service.get_image_embedding(img_bytes)
                logger.info(f"Generated image embedding for object {detected_object_id}")
            else:
                logger.warning(f"No image URL or bbox for object {detected_object_id}")
        except Exception as e:
            logger.warning(f"Failed to generate image embedding: {e}")

        # 4. 텍스트 임베딩 생성 - 상세한 설명으로 구성
        text_embedding = None
        has_attribute_change = (search_keywords or style_keywords or color_filter or
                                pattern_filter or style_vibe or sleeve_length or
                                pants_length or outer_length or material_filter)
        if has_attribute_change:
            # FashionCLIP에 최적화된 상세 설명 생성
            # 예: "black long sleeve cotton casual top" 또는 "brown wool long formal outer"
            description_parts = []

            # 색상
            if color_filter:
                description_parts.append(color_filter)

            # 소재
            if material_filter:
                description_parts.append(material_filter)

            # 패턴
            if pattern_filter:
                if pattern_filter != 'solid':
                    description_parts.append(pattern_filter)

            # 길이 (카테고리에 맞게)
            if sleeve_length:
                description_parts.append(sleeve_length.replace('_', ' '))
            if pants_length:
                if pants_length == 'shorts':
                    description_parts.append('short')
                else:
                    description_parts.append(pants_length)
            if outer_length:
                description_parts.append(outer_length)

            # 스타일
            if style_vibe:
                description_parts.append(style_vibe)

            # 스타일 키워드 (리스트)
            if style_keywords:
                description_parts.extend(style_keywords)

            # 자연어 검색 키워드 (가장 중요 - 사용자가 직접 입력한 내용)
            if search_keywords:
                description_parts.append(search_keywords)

            # 카테고리
            category_names = {
                'top': 'top shirt',
                'pants': 'pants trousers',
                'outer': 'jacket coat outerwear',
                'shoes': 'shoes sneakers',
                'bag': 'bag',
            }
            category_desc = category_names.get(detected_obj.object_category, detected_obj.object_category)
            description_parts.append(category_desc)

            search_text = ' '.join(description_parts)
            text_embedding = embedding_service.get_text_embedding(search_text)
            logger.info(f"Generated detailed text embedding: '{search_text}'")

        # 5. 임베딩 결합 - 요청 유형에 따라 비중 조절
        # - 속성 변경 요청 (색상, 패턴, 스타일 등): 텍스트 80% + 이미지 20% (모양만 참고)
        # - 단순 재검색 (비슷한 거 찾아줘): 이미지 100%
        if has_attribute_change and text_embedding is not None:
            if image_embedding is not None:
                # 속성 변경: 텍스트 중심 (80%) + 이미지 형태 참고 (20%)
                image_arr = np.array(image_embedding)
                text_arr = np.array(text_embedding)
                combined = 0.5 * image_arr + 0.5 * text_arr
                combined = combined / np.linalg.norm(combined)
                embedding = combined.tolist()
                logger.info(f"Attribute change: text 80% + image 20%")
            else:
                # 이미지 없으면 텍스트만
                embedding = text_embedding
                logger.info(f"Attribute change: text only (no image)")
        elif image_embedding is not None:
            # 단순 재검색: 이미지만 사용
            embedding = image_embedding
            logger.info(f"Simple research: image only")
        elif text_embedding is not None:
            embedding = text_embedding
            logger.info(f"Fallback: text only")
        else:
            # 폴백: 카테고리 텍스트 임베딩
            embedding = embedding_service.get_text_embedding(detected_obj.object_category)
            logger.info(f"Fallback: category text embedding")

        # 6. OpenSearch 검색 (외부 API 호출)
        category_mapping = {
            'bottom': 'pants',
            'outerwear': 'outer',
        }
        search_category = category_mapping.get(
            detected_obj.object_category, detected_obj.object_category
        )

        # 검색 실행: 유사도 먼저 → 필터 나중 방식
        # 1. 먼저 벡터 유사도로 많은 후보 검색 (50개)
        search_results = opensearch_service.search_similar_products_hybrid(
            embedding=embedding,
            category=search_category,
            k=50,
            search_k=100,
        )
        logger.info(f"Vector search returned {len(search_results)} candidates")

        # 2. 속성 필터로 후처리
        has_attribute_filters = (color_filter or brand_filter or pattern_filter or style_vibe or
                                 sleeve_length or pants_length or outer_length or material_filter)
        if has_attribute_filters and search_results:
            filtered_results = []
            for result in search_results:
                # OpenSearch 결과에서 속성 정보 가져오기
                product_id = result.get('product_id')
                if not product_id:
                    continue

                # 각 필터 조건 확인
                matches = True

                # 색상 필터
                if color_filter:
                    product_colors = result.get('colors', []) or []
                    if isinstance(product_colors, str):
                        product_colors = [product_colors]
                    if color_filter.lower() not in [c.lower() for c in product_colors]:
                        matches = False

                # 브랜드 필터
                if brand_filter and matches:
                    product_brand = (result.get('brand') or '').lower()
                    if brand_filter.lower() not in product_brand:
                        matches = False

                # 패턴 필터
                if pattern_filter and matches:
                    product_pattern = (result.get('pattern') or '').lower()
                    if pattern_filter.lower() != product_pattern:
                        matches = False

                # 스타일 필터
                if style_vibe and matches:
                    product_style = (result.get('style_vibe') or '').lower()
                    if style_vibe.lower() != product_style:
                        matches = False

                # 소매 길이 필터
                if sleeve_length and matches:
                    product_sleeve = (result.get('sleeve_length') or '').lower()
                    if sleeve_length.lower() != product_sleeve:
                        matches = False

                # 소재 필터
                if material_filter and matches:
                    product_materials = result.get('materials', []) or []
                    if isinstance(product_materials, str):
                        product_materials = [product_materials]
                    if material_filter.lower() not in [m.lower() for m in product_materials]:
                        matches = False

                if matches:
                    filtered_results.append(result)

            logger.info(f"After attribute filtering: {len(filtered_results)} results")
            search_results = filtered_results[:5]  # 상위 5개
        else:
            search_results = search_results[:5]

        # 7. 가격 정렬 적용
        if price_sort and search_results:
            reverse = (price_sort == 'highest')
            search_results = sorted(
                search_results,
                key=lambda x: int(x.get('price', 0) or 0),
                reverse=reverse
            )

        # 8. 기존 매핑 삭제 및 새 매핑 생성
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

        # 9. 진행률 업데이트
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
