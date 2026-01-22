"""
AI 패션 어시스턴트 - 검색 에이전트
기존 분석 파이프라인과 Refine 기능을 활용한 검색 처리
"""

import logging
import base64
from typing import Dict, Any, Optional, List

from django.core.files.uploadedfile import InMemoryUploadedFile

from services import (
    get_embedding_service,
    get_redis_service,
)
from services.opensearch_client import OpenSearchService
from agents.response_builder import ResponseBuilder
from config.tracing import traced, get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class SearchAgent:
    """
    검색 에이전트 - 기존 분석 파이프라인 활용

    핵심 연동 포인트:
    - 이미지 검색: 기존 process_image_analysis 활용
    - 텍스트 검색: OpenSearchService 직접 활용
    - Refine: 기존 parse_refine_query_task 활용 (핵심!)
    """

    # 한국어 → 영어 패션 용어 변환 (FashionCLIP은 영어 모델)
    KOREAN_TO_ENGLISH = {
        # 신발
        '구두': 'dress shoes loafers',
        '로퍼': 'loafers',
        '운동화': 'sneakers',
        '스니커즈': 'sneakers',
        '부츠': 'boots',
        '샌들': 'sandals',
        '슬리퍼': 'slippers',
        '하이힐': 'high heels',
        '플랫슈즈': 'flat shoes',
        # 상의
        '니트': 'knit sweater',
        '맨투맨': 'sweatshirt',
        '후드': 'hoodie',
        '티셔츠': 't-shirt',
        '셔츠': 'shirt',
        '블라우스': 'blouse',
        # 하의
        '청바지': 'jeans denim',
        '슬랙스': 'slacks trousers',
        '반바지': 'shorts',
        '치마': 'skirt',
        # 아우터
        '자켓': 'jacket',
        '재킷': 'jacket',
        '코트': 'coat',
        '패딩': 'puffer jacket down',
        '가디건': 'cardigan',
        '점퍼': 'jumper bomber',
        # 가방
        '백팩': 'backpack',
        '토트백': 'tote bag',
        '크로스백': 'crossbody bag',
        '숄더백': 'shoulder bag',
        # 색상
        '검은색': 'black',
        '검정': 'black',
        '흰색': 'white',
        '하얀': 'white',
        '빨간': 'red',
        '파란': 'blue',
        '녹색': 'green',
        '노란': 'yellow',
        '회색': 'gray',
        '베이지': 'beige',
        '네이비': 'navy',
        '갈색': 'brown',
    }

    def _translate_to_english(self, message: str) -> str:
        """한국어 패션 용어를 영어로 변환"""
        result = message
        for kor, eng in self.KOREAN_TO_ENGLISH.items():
            if kor in result:
                result = result.replace(kor, eng)
        return result

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.opensearch = OpenSearchService()
        self.embedding_service = get_embedding_service()
        self.redis = get_redis_service()

    @traced("search_agent.handle")
    def handle(
        self,
        sub_intent: str,
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """검색 요청 처리"""
        logger.info(
            f"SearchAgent.handle: sub_intent={sub_intent}, has_image={image is not None}, "
            f"message='{message[:30]}...', analysis_id={context.get('current_analysis_id')}"
        )
        try:
            if sub_intent == 'new_search':
                if image:
                    return self.image_search(image, message, context)
                else:
                    return self.text_search(message, context)

            elif sub_intent == 'retry_search':
                # 이전 검색 타입 확인 (이미지 vs 텍스트)
                last_search_type = context.get('last_search_type')

                if last_search_type == 'image':
                    # 이미지 분석 재검색 - 다른 상품 보여주기
                    analysis_id = context.get('current_analysis_id')
                    if analysis_id:
                        return self.retry_image_search(analysis_id, context)
                    else:
                        return ResponseBuilder.error(
                            "no_previous_search",
                            "이전 이미지 분석 기록이 없어요. 새로운 이미지를 업로드해주세요."
                        )
                else:
                    # 텍스트 검색 재검색
                    last_query = context.get('last_search_query')
                    last_search_params = context.get('last_search_params')
                    if last_query:
                        # offset 증가 (다음 5개 상품)
                        current_offset = context.get('search_offset', 0)
                        new_offset = current_offset + 5
                        context['search_offset'] = new_offset
                        # 이전 검색 조건 복원 (색상, 브랜드, 카테고리 유지)
                        if last_search_params:
                            context['intent_result'] = context.get('intent_result', {})
                            context['intent_result']['search_params'] = last_search_params
                        return self.text_search(last_query, context, is_retry=True, offset=new_offset)
                    else:
                        return ResponseBuilder.error(
                            "no_previous_search",
                            "이전 검색 기록이 없어요. 새로운 검색어를 입력해주세요."
                        )

            elif sub_intent == 'refine':
                return self.refine_search(message, context)

            elif sub_intent == 'similar':
                # 이미지가 있으면 이미지 기반 검색
                if image:
                    return self.image_search(image, message, context)
                return self.similar_search(context)

            elif sub_intent == 'cross_recommend':
                return self.cross_category_search(message, image, context)

            else:
                return self.text_search(message, context)

        except Exception as e:
            logger.error(f"SearchAgent error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "검색 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.image_search")
    def image_search(
        self,
        image: bytes,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        이미지 기반 검색 - 기존 분석 파이프라인 활용

        1. 이미지 업로드 (UploadedImage 생성)
        2. 분석 시작 (ImageAnalysis 생성)
        3. Celery Task 실행 (process_image_analysis)
        4. 결과 반환 (폴링 또는 대기)

        카테고리 필터 지원:
        - "신발만 찾아줘" → shoes만 반환
        - "상의 찾아줘" → top만 반환
        """
        from analyses.models import UploadedImage, ImageAnalysis
        from analyses.tasks.analysis import process_image_analysis
        from django.core.files.base import ContentFile
        import uuid

        try:
            # 0. 메시지에서 필터 추출
            search_params = context.get('intent_result', {}).get('search_params', {})
            target_categories = search_params.get('target_categories', [])
            category_filter = target_categories[0] if target_categories else None
            item_type_filter = search_params.get('item_type')
            pattern_filter = search_params.get('pattern')
            style_filter = search_params.get('style')
            material_filter = search_params.get('material')
            color_filter = search_params.get('color')

            logger.info(
                f"Image search: search_params={search_params}, "
                f"category={category_filter}, item_type={item_type_filter}, "
                f"pattern={pattern_filter}, style={style_filter}, material={material_filter}, color={color_filter}"
            )

            # 1. 이미지 업로드
            uploaded_image = UploadedImage.objects.create(
                user_id=self.user_id,
                uploaded_image_url=""  # GCS 업로드 후 업데이트
            )

            # 2. 분석 시작
            analysis = ImageAnalysis.objects.create(
                uploaded_image=uploaded_image,
                image_analysis_status='PENDING'
            )

            # 3. Celery Task 실행 (Base64로 전달하여 빠른 처리)
            image_b64 = base64.b64encode(image).decode('utf-8')
            process_image_analysis.delay(
                analysis_id=analysis.id,
                image_url=None,
                user_id=self.user_id,
                image_b64=image_b64
            )

            # 4. 컨텍스트 업데이트 - 새 이미지 업로드 시 이전 이미지 컨텍스트 완전 초기화
            # 새 분석 정보
            context['current_analysis_id'] = analysis.id
            context['analysis_pending'] = True
            context['last_search_type'] = 'image'

            # 이전 이미지 관련 컨텍스트 초기화
            context['shown_product_ids'] = []  # 보여준 상품 ID 초기화
            context['search_results'] = []  # 이전 검색 결과 초기화
            context['has_search_results'] = False  # 아직 결과 없음
            context['selected_product'] = None  # 선택 상품 초기화

            # 필터 초기화 (새 필터가 있으면 적용, 없으면 None)
            context['analysis_category_filter'] = category_filter
            context['analysis_item_type_filter'] = item_type_filter
            context['analysis_pattern_filter'] = pattern_filter
            context['analysis_style_filter'] = style_filter
            context['analysis_material_filter'] = material_filter
            context['analysis_color_filter'] = color_filter

            # 텍스트 검색 관련 컨텍스트도 초기화 (이미지 검색과 분리)
            context['last_search_query'] = None
            context['last_search_params'] = None
            context['search_offset'] = 0
            context['search_filters'] = None

            # 대기 중인 액션 초기화 (사이즈 선택 등)
            context['pending_action'] = None

            return ResponseBuilder.analysis_pending(analysis.id)

        except Exception as e:
            logger.error(f"Image search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "upload_error",
                "이미지 처리 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.retry_image_search")
    def retry_image_search(
        self,
        analysis_id: int,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        이미지 분석 재검색 - 이전에 보여준 상품 제외하고 다른 상품 반환
        """
        try:
            # 이전에 보여준 상품 ID 목록
            shown_product_ids = context.get('shown_product_ids', [])

            # 카테고리/아이템타입 필터 (저장된 값 사용)
            category_filter = context.get('analysis_category_filter')
            item_type_filter = context.get('analysis_item_type_filter')

            # 새로운 상품 조회 (이전 상품 제외)
            products = self.get_analysis_results(
                analysis_id,
                category_filter=category_filter,
                item_type_filter=item_type_filter,
                exclude_product_ids=shown_product_ids
            )

            if not products:
                # 더 이상 보여줄 상품이 없으면 처음부터 다시
                context['shown_product_ids'] = []
                products = self.get_analysis_results(
                    analysis_id,
                    category_filter=category_filter,
                    item_type_filter=item_type_filter
                )
                if not products:
                    return ResponseBuilder.no_results(
                        "더 이상 비슷한 상품을 찾지 못했어요. 다른 이미지로 시도해보세요."
                    )
                message = "처음부터 다시 보여드릴게요:"
            else:
                message = "다른 비슷한 상품을 찾았어요:"

            # 보여준 상품 ID 업데이트
            new_shown_ids = [p.get('product_id') for p in products if p.get('product_id')]
            context['shown_product_ids'] = shown_product_ids + new_shown_ids

            # 컨텍스트 업데이트
            context['search_results'] = products
            context['has_search_results'] = True

            logger.info(f"Image retry search: analysis_id={analysis_id}, shown={len(shown_product_ids)}, new={len(products)}")

            return ResponseBuilder.search_results(products, message)

        except Exception as e:
            logger.error(f"Retry image search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "재검색 중 문제가 발생했어요. 다시 시도해주세요."
            )

    # 한국어 → 영어 색상 매핑 (OpenSearch COLOR_KEYWORDS와 호환)
    KOREAN_TO_ENGLISH_COLOR = {
        '검은색': 'black', '검정': 'black', '블랙': 'black',
        '흰색': 'white', '하얀': 'white', '화이트': 'white',
        '회색': 'gray', '그레이': 'gray', '회색': 'grey',
        '네이비': 'navy', '남색': 'navy',
        '파란색': 'blue', '파란': 'blue', '블루': 'blue',
        '빨간색': 'red', '빨간': 'red', '레드': 'red',
        '녹색': 'green', '초록': 'green', '그린': 'green',
        '노란색': 'yellow', '노란': 'yellow', '옐로우': 'yellow',
        '분홍색': 'pink', '핑크': 'pink',
        '주황색': 'orange', '오렌지': 'orange',
        '보라색': 'purple', '퍼플': 'purple',
        '갈색': 'brown', '브라운': 'brown',
        '베이지': 'beige', '크림': 'cream',
        '카키': 'khaki', '올리브': 'khaki',
    }

    # 한국어 → 영어 패턴/문양 매핑
    KOREAN_TO_ENGLISH_PATTERN = {
        '스트라이프': 'stripe', '줄무늬': 'stripe', '세로줄': 'stripe', '가로줄': 'stripe', '스트라입': 'stripe',
        '점박이': 'polka dot', '도트': 'polka dot', '폴카도트': 'polka dot', '땡땡이': 'polka dot', '물방울': 'polka dot',
        '체크': 'check', '격자': 'check', '체크무늬': 'check', '깅엄': 'gingham', '타탄': 'tartan',
        '무지': 'solid', '솔리드': 'solid', '단색': 'solid', '민무늬': 'plain',
        '꽃무늬': 'floral', '플로럴': 'floral', '꽃': 'floral', '플라워': 'flower',
        '페이즐리': 'paisley',
        '카모': 'camo', '밀리터리': 'military', '위장': 'camo', '아미': 'army',
        '호피': 'leopard', '레오파드': 'leopard', '표범': 'leopard', '지브라': 'zebra', '얼룩말': 'zebra', '애니멀': 'animal',
        '로고': 'logo', '프린트': 'print', '그래픽': 'graphic', '레터링': 'lettering',
        '아가일': 'argyle', '마름모': 'argyle',
    }

    # 한국어 → 영어 스타일 매핑
    KOREAN_TO_ENGLISH_STYLE = {
        '캐주얼': 'casual', '편한': 'casual', '일상': 'casual', '데일리': 'daily',
        '포멀': 'formal', '정장': 'formal', '격식': 'formal', '오피스': 'office', '비즈니스': 'business',
        '스포티': 'sporty', '운동': 'sport', '액티브': 'active', '애슬레저': 'athleisure',
        '빈티지': 'vintage', '레트로': 'retro', '복고': 'retro', '구제': 'vintage',
        '미니멀': 'minimal', '심플': 'simple', '기본': 'basic', '베이직': 'basic',
        '스트릿': 'street', '힙합': 'hiphop', '유니크': 'unique',
        '클래식': 'classic', '정통': 'classic', '트래디셔널': 'traditional',
        '오버핏': 'overfit', '루즈핏': 'loose', '박시': 'boxy', '와이드': 'wide', '오버사이즈': 'oversized',
        '슬림핏': 'slim', '타이트': 'tight', '스키니': 'skinny', '피트': 'fit',
    }

    # 한국어 → 영어 소재 매핑
    KOREAN_TO_ENGLISH_MATERIAL = {
        '데님': 'denim', '청': 'denim',
        '가죽': 'leather', '레더': 'leather', '소가죽': 'leather', '양가죽': 'leather',
        '니트': 'knit', '울': 'wool', '양모': 'wool', '캐시미어': 'cashmere',
        '면': 'cotton', '코튼': 'cotton', '순면': 'cotton',
        '린넨': 'linen', '마': 'linen', '마직': 'linen',
        '벨벳': 'velvet', '벨루어': 'velour',
        '코듀로이': 'corduroy', '골덴': 'corduroy',
        '퍼': 'fur', '털': 'fur', '무스탕': 'shearling', '양털': 'fleece', '플리스': 'fleece',
        '스웨이드': 'suede',
        '나일론': 'nylon', '폴리': 'polyester', '폴리에스터': 'polyester',
        '실크': 'silk', '비단': 'silk', '새틴': 'satin',
        '트위드': 'tweed',
        '저지': 'jersey',
    }

    def _normalize_color(self, color: str) -> str:
        """한국어 색상을 영어로 정규화"""
        if not color:
            return None
        color_lower = color.lower().strip()
        # 이미 영어면 그대로 반환
        if color_lower in ['black', 'white', 'gray', 'grey', 'navy', 'blue', 'red',
                           'green', 'yellow', 'pink', 'orange', 'purple', 'brown',
                           'beige', 'cream', 'khaki']:
            return color_lower
        # 한국어 → 영어 변환
        return self.KOREAN_TO_ENGLISH_COLOR.get(color_lower, color_lower)

    def _normalize_pattern(self, pattern: str) -> str:
        """한국어 패턴을 영어로 정규화"""
        if not pattern:
            return None
        pattern_lower = pattern.lower().strip()
        # 이미 영어면 그대로 반환
        if pattern_lower in ['stripe', 'polka dot', 'check', 'solid', 'floral', 'paisley',
                             'camo', 'leopard', 'zebra', 'animal', 'graphic', 'argyle', 'plain']:
            return pattern_lower
        # 한국어 → 영어 변환
        return self.KOREAN_TO_ENGLISH_PATTERN.get(pattern_lower, pattern_lower)

    def _normalize_style(self, style: str) -> str:
        """한국어 스타일을 영어로 정규화"""
        if not style:
            return None
        style_lower = style.lower().strip()
        # 이미 영어면 그대로 반환
        if style_lower in ['casual', 'formal', 'sporty', 'vintage', 'minimal', 'street',
                           'classic', 'overfit', 'slim', 'basic', 'office']:
            return style_lower
        # 한국어 → 영어 변환
        return self.KOREAN_TO_ENGLISH_STYLE.get(style_lower, style_lower)

    def _normalize_material(self, material: str) -> str:
        """한국어 소재를 영어로 정규화"""
        if not material:
            return None
        material_lower = material.lower().strip()
        # 이미 영어면 그대로 반환
        if material_lower in ['denim', 'leather', 'wool', 'cotton', 'linen', 'velvet',
                              'corduroy', 'fur', 'suede', 'polyester', 'silk', 'knit', 'fleece']:
            return material_lower
        # 한국어 → 영어 변환
        return self.KOREAN_TO_ENGLISH_MATERIAL.get(material_lower, material_lower)

    def _filter_results_by_keywords(
        self,
        results: List[Dict[str, Any]],
        pattern: Optional[str] = None,
        style: Optional[str] = None,
        material: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        검색 결과를 패턴/스타일/소재 키워드로 필터링

        상품명에 해당 키워드가 포함된 결과만 반환
        """
        if not pattern and not style and not material:
            return results

        # 키워드 → 검색어 매핑 (한글/영문 모두 포함)
        PATTERN_KEYWORDS = {
            'stripe': ['스트라이프', 'stripe', '줄무늬', '줄'],
            'polka_dot': ['도트', 'dot', '점박이', '땡땡이', '물방울'],
            'polka dot': ['도트', 'dot', '점박이', '땡땡이', '물방울'],
            'check': ['체크', 'check', '격자', '깅엄', 'gingham'],
            'solid': ['무지', 'solid', '단색', 'plain'],
            'floral': ['플로럴', 'floral', '꽃무늬', '꽃', 'flower'],
            'paisley': ['페이즐리', 'paisley'],
            'camo': ['카모', 'camo', '밀리터리', 'military', '위장', '아미'],
            'animal': ['호피', 'leopard', '지브라', 'zebra', '애니멀', 'animal'],
            'leopard': ['호피', 'leopard', '레오파드'],
            'graphic': ['그래픽', 'graphic', '프린트', 'print', '로고', 'logo', '레터링'],
            'argyle': ['아가일', 'argyle', '마름모'],
        }

        STYLE_KEYWORDS = {
            'casual': ['캐주얼', 'casual', '데일리', 'daily'],
            'formal': ['포멀', 'formal', '정장', '오피스', 'office', '비즈니스'],
            'sporty': ['스포티', 'sporty', '스포츠', 'sport', '애슬레저', 'athleisure'],
            'vintage': ['빈티지', 'vintage', '레트로', 'retro', '복고', '구제'],
            'minimal': ['미니멀', 'minimal', '심플', 'simple', '베이직', 'basic'],
            'street': ['스트릿', 'street', '힙합', '유니크'],
            'classic': ['클래식', 'classic', '트래디셔널'],
            'overfit': ['오버핏', 'overfit', '오버사이즈', 'oversized', '루즈', 'loose', '박시', 'boxy', '와이드', 'wide'],
            'slim': ['슬림', 'slim', '스키니', 'skinny', '타이트', 'tight', '피트', 'fit'],
        }

        MATERIAL_KEYWORDS = {
            'denim': ['데님', 'denim', '청바지', '청'],
            'leather': ['가죽', 'leather', '레더'],
            'wool': ['울', 'wool', '니트', 'knit', '양모', '캐시미어', 'cashmere'],
            'cotton': ['코튼', 'cotton', '면', '순면'],
            'linen': ['린넨', 'linen', '마'],
            'velvet': ['벨벳', 'velvet', '벨루어'],
            'corduroy': ['코듀로이', 'corduroy', '골덴'],
            'fur': ['퍼', 'fur', '털', '무스탕', '양털', 'fleece', '플리스'],
            'suede': ['스웨이드', 'suede'],
            'polyester': ['폴리', 'polyester', '나일론', 'nylon'],
            'silk': ['실크', 'silk', '새틴', 'satin'],
            'knit': ['니트', 'knit', '울', 'wool'],
            'fleece': ['플리스', 'fleece', '양털'],
        }

        def matches_keywords(product_name: str, filter_value: str, keyword_map: dict) -> bool:
            """상품명에 키워드가 포함되어 있는지 확인"""
            if not filter_value:
                return True
            keywords = keyword_map.get(filter_value.lower(), [filter_value])
            product_name_lower = product_name.lower()
            return any(kw.lower() in product_name_lower for kw in keywords)

        filtered = []
        for result in results:
            product_name = result.get('product_name', '') or ''

            # 모든 필터 조건 체크
            if pattern and not matches_keywords(product_name, pattern, PATTERN_KEYWORDS):
                continue
            if style and not matches_keywords(product_name, style, STYLE_KEYWORDS):
                continue
            if material and not matches_keywords(product_name, material, MATERIAL_KEYWORDS):
                continue

            filtered.append(result)

        logger.info(
            f"Keyword filter: pattern={pattern}, style={style}, material={material}, "
            f"before={len(results)}, after={len(filtered)}"
        )

        return filtered

    @traced("search_agent.text_search")
    def text_search(
        self,
        message: str,
        context: Dict[str, Any],
        is_retry: bool = False,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        텍스트 기반 검색 - OpenSearch 직접 활용

        1. 검색 조건 파싱
        2. 텍스트 임베딩 생성
        3. OpenSearch 하이브리드 검색
        """
        try:
            # 1. 검색 조건 추출 (컨텍스트에서)
            search_params = context.get('intent_result', {}).get('search_params', {})

            # 2. 텍스트 임베딩 생성 (한국어 → 영어 변환)
            translated_query = self._translate_to_english(message)

            # 3. 카테고리, 브랜드, 색상, 패턴, 스타일, 소재 추출
            categories = search_params.get('target_categories', [])
            category = categories[0] if categories else None
            brand = search_params.get('brand')
            color = self._normalize_color(search_params.get('color'))
            pattern = self._normalize_pattern(search_params.get('pattern'))
            style = self._normalize_style(search_params.get('style'))
            material = self._normalize_material(search_params.get('material'))

            # 모든 필터를 검색 쿼리에 포함 (임베딩 품질 향상)
            search_query_parts = []
            if brand:
                search_query_parts.append(brand)
            if color:
                search_query_parts.append(color)
            if pattern:
                search_query_parts.append(pattern)
            if style:
                search_query_parts.append(style)
            if material:
                search_query_parts.append(material)
            search_query_parts.append(translated_query)
            search_query = ' '.join(search_query_parts)

            text_embedding = self.embedding_service.get_text_embedding(search_query)

            logger.info(
                f"Text search: message='{message}' -> query='{search_query}', "
                f"category={category}, brand={brand}, color={color}, "
                f"pattern={pattern}, style={style}, material={material}, is_retry={is_retry}"
            )

            # 4. OpenSearch 검색 (브랜드/색상 필터 지원)
            # 더 많은 후보를 가져와서 다양한 결과 제공
            if (brand or color) and category:
                # 브랜드/색상 + 카테고리 필터링
                results = self.opensearch.search_brand_vector_color(
                    embedding=text_embedding,
                    category=category,
                    brand=brand,
                    color=color,
                    k=100,        # 더 많은 결과 반환 (30 → 100)
                    search_k=500  # 더 많은 후보 검색 (100 → 500)
                )
            elif category:
                results = self.opensearch.search_similar_products_hybrid(
                    embedding=text_embedding,
                    category=category,
                    k=100,        # 30 → 100
                    search_k=500  # 100 → 500
                )
            else:
                # 카테고리 미지정 시 벡터 유사도 기반 전체 검색
                results = self.opensearch.search_by_vector(
                    embedding=text_embedding,
                    k=100  # 30 → 100
                )

            if not results:
                return ResponseBuilder.no_results(
                    "조건에 맞는 상품을 찾지 못했어요. 조건을 바꿔서 다시 찾아볼까요?"
                )

            # 5. 패턴/스타일/소재 키워드 필터링 (상품명 기반)
            if pattern or style or material:
                results = self._filter_results_by_keywords(results, pattern, style, material)
                if not results:
                    filter_desc = ', '.join(filter(None, [pattern, style, material]))
                    return ResponseBuilder.no_results(
                        f"'{filter_desc}' 조건에 맞는 상품을 찾지 못했어요. 다른 조건으로 찾아볼까요?"
                    )

            # 6. offset 적용하여 결과 슬라이싱
            sliced_results = results[offset:offset + 5]

            # 더 이상 결과가 없으면 처음으로 돌아가기
            if not sliced_results:
                context['search_offset'] = 0  # offset 리셋
                sliced_results = results[:5]
                result_message = f"'{message}' 검색 결과를 처음부터 다시 보여드릴게요:"
            elif is_retry:
                page_num = (offset // 5) + 1
                result_message = f"'{message}' 검색 결과 ({page_num}페이지):"
            else:
                result_message = f"'{message}'로 검색한 결과예요:"

            # 6. 결과 정규화 및 컨텍스트 업데이트
            normalized_results = self._normalize_search_results(sliced_results)
            context['search_results'] = normalized_results
            context['has_search_results'] = True
            context['search_filters'] = search_params

            # 7. 이전 검색 쿼리 및 조건 저장 (새 검색일 때만)
            if not is_retry:
                context['last_search_query'] = message
                context['last_search_params'] = search_params  # 색상, 브랜드, 카테고리 저장
                context['last_search_type'] = 'text'  # 텍스트 검색 타입 저장
                context['search_offset'] = 0  # 새 검색 시 offset 리셋

                # 이전 이미지 분석 컨텍스트 초기화 (텍스트 검색으로 전환)
                context['current_analysis_id'] = None
                context['analysis_pending'] = False
                context['analysis_category_filter'] = None
                context['analysis_item_type_filter'] = None
                context['shown_product_ids'] = []
                context['selected_product'] = None
                context['pending_action'] = None

            return ResponseBuilder.search_results(
                normalized_results,
                result_message,
                search_params.get('understood_intent')
            )

        except Exception as e:
            logger.error(f"Text search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "검색 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.refine_search")
    def refine_search(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        자연어 재분석 / 필터 변경

        세 가지 모드 지원:
        1. 이미지 분석 결과 필터 변경: 같은 analysis_id, 필터만 변경
           예: "신발만 보여줘", "코트만 찾아줘"
        2. 텍스트 검색 조건 변경: 이전 검색 조건 + 새 필터 병합
           예: "나이키 운동화" → "빨간색으로" = "나이키 빨간색 운동화"
        3. 기존 parse_refine_query 활용 (이미지 분석 컨텍스트)
        """
        analysis_id = context.get('current_analysis_id')
        last_search_type = context.get('last_search_type')

        logger.info(
            f"Refine search: analysis_id={analysis_id}, last_search_type={last_search_type}, "
            f"has_search_results={context.get('has_search_results')}"
        )

        # 이미지 분석 결과가 있는 경우 - 필터만 변경
        if analysis_id and last_search_type == 'image':
            # 요청된 카테고리가 이미지 분석 결과에 있는지 확인
            search_params = context.get('intent_result', {}).get('search_params', {})
            target_categories = search_params.get('target_categories', [])
            requested_category = target_categories[0] if target_categories else None

            # 카테고리가 없거나, 이미지에 해당 카테고리가 있으면 이미지 refine
            if not requested_category or self._category_exists_in_analysis(analysis_id, requested_category):
                result = self._refine_image_filter(analysis_id, message, context)

                # 결과가 0개면 텍스트 검색으로 폴백
                if result.get('type') == 'no_results':
                    logger.info("Image refine returned 0 results, falling back to text search")
                    return self.text_search(message, context)

                return result
            else:
                # 이미지에 해당 카테고리가 없으면 텍스트 검색으로 전환
                logger.info(
                    f"Category '{requested_category}' not found in analysis {analysis_id}, "
                    "switching to text search"
                )
                return self.text_search(message, context)

        # 텍스트 검색 컨텍스트가 있는 경우 - 이전 검색 조건과 병합
        if last_search_type == 'text' and context.get('last_search_params'):
            return self._refine_text_search(message, context)

        # 컨텍스트 없는 경우 - 새 텍스트 검색으로 처리
        if not analysis_id:
            logger.info("Refine search: No context, falling back to new text search")
            return self.text_search(message, context)

        # 기존 refine 로직 (이미지 분석 컨텍스트가 있지만 image 타입이 아닌 경우)
        try:
            from analyses.tasks.refine import parse_refine_query_task

            result = parse_refine_query_task.apply(
                args=[
                    message,
                    ['top', 'bottom', 'outer', 'shoes', 'bag', 'hat', 'skirt'],
                    analysis_id,
                    True  # use_v2
                ]
            ).get(timeout=30)

            from analyses.models import ObjectProductMapping

            mappings = list(ObjectProductMapping.objects.filter(
                detected_object__uploaded_image__analyses__id=analysis_id,
                is_deleted=False
            ).select_related(
                'product'
            ).order_by('-confidence_score')[:5])

            products = [self._mapping_to_product(m) for m in mappings]

            if not products:
                return ResponseBuilder.no_results(
                    f"'{message}' 조건에 맞는 상품을 찾지 못했어요."
                )

            context['search_results'] = products
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                products,
                f"'{message}' 조건으로 다시 찾았어요:"
            )

        except Exception as e:
            logger.error(f"Refine search error: {e}", exc_info=True)
            return self.text_search(message, context)

    @traced("search_agent.refine_image_filter")
    def _refine_image_filter(
        self,
        analysis_id: int,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        이미지 분석 결과에서 필터만 변경 (refine)

        같은 analysis_id를 유지하면서:
        - 카테고리, 아이템 타입, 패턴, 스타일, 소재 필터 업데이트
        - shown_product_ids 리셋
        - 새 필터로 결과 반환
        """
        try:
            # 1. 메시지에서 새 필터 추출
            search_params = context.get('intent_result', {}).get('search_params', {})
            target_categories = search_params.get('target_categories', [])
            new_category_filter = target_categories[0] if target_categories else None
            new_item_type_filter = search_params.get('item_type')
            new_pattern_filter = search_params.get('pattern')
            new_style_filter = search_params.get('style')
            new_material_filter = search_params.get('material')
            new_color_filter = search_params.get('color')

            # 메시지에서 직접 필터 추출 (LLM 분류가 누락된 경우 대비)
            message_lower = message.lower()

            if not new_category_filter and not new_item_type_filter:
                new_category_filter, new_item_type_filter = self._extract_filter_from_message(message)

            # 패턴/스타일/소재/색상 직접 추출
            if not new_pattern_filter:
                for kor, eng in self.KOREAN_TO_ENGLISH_PATTERN.items():
                    if kor in message_lower:
                        new_pattern_filter = eng
                        break

            if not new_style_filter:
                for kor, eng in self.KOREAN_TO_ENGLISH_STYLE.items():
                    if kor in message_lower:
                        new_style_filter = eng
                        break

            if not new_material_filter:
                for kor, eng in self.KOREAN_TO_ENGLISH_MATERIAL.items():
                    if kor in message_lower:
                        new_material_filter = eng
                        break

            if not new_color_filter:
                for kor, eng in self.KOREAN_TO_ENGLISH_COLOR.items():
                    if kor in message_lower:
                        new_color_filter = eng
                        break

            # 필터가 하나도 없으면 다른 상품 보여주기
            has_any_filter = any([
                new_category_filter, new_item_type_filter, new_pattern_filter,
                new_style_filter, new_material_filter, new_color_filter
            ])
            if not has_any_filter:
                return self.retry_image_search(analysis_id, context)

            # 2. 컨텍스트 필터 업데이트
            if new_category_filter:
                context['analysis_category_filter'] = new_category_filter
            if new_item_type_filter:
                context['analysis_item_type_filter'] = new_item_type_filter
            if new_pattern_filter:
                context['analysis_pattern_filter'] = new_pattern_filter
            if new_style_filter:
                context['analysis_style_filter'] = new_style_filter
            if new_material_filter:
                context['analysis_material_filter'] = new_material_filter
            if new_color_filter:
                context['analysis_color_filter'] = new_color_filter

            # 3. shown_product_ids 리셋 (새 필터이므로 처음부터)
            context['shown_product_ids'] = []

            # 적용할 필터들
            filter_parts = list(filter(None, [
                new_pattern_filter, new_style_filter, new_material_filter,
                new_color_filter, new_item_type_filter, new_category_filter
            ]))

            logger.info(
                f"Refine image filter: analysis_id={analysis_id}, "
                f"category={new_category_filter}, item_type={new_item_type_filter}, "
                f"pattern={new_pattern_filter}, style={new_style_filter}, "
                f"material={new_material_filter}, color={new_color_filter}"
            )

            # 4. 새 필터로 결과 조회
            products = self.get_analysis_results(
                analysis_id,
                category_filter=new_category_filter or context.get('analysis_category_filter'),
                item_type_filter=new_item_type_filter or context.get('analysis_item_type_filter')
            )

            # 5. 패턴/스타일/소재/색상 키워드 필터링
            pattern = self._normalize_pattern(new_pattern_filter or context.get('analysis_pattern_filter'))
            style = self._normalize_style(new_style_filter or context.get('analysis_style_filter'))
            material = self._normalize_material(new_material_filter or context.get('analysis_material_filter'))
            color = self._normalize_color(new_color_filter or context.get('analysis_color_filter'))

            if pattern or style or material or color:
                # 색상도 키워드 필터링에 추가
                filtered_products = []
                for p in products:
                    product_name = (p.get('product_name', '') or '').lower()
                    match = True

                    if pattern:
                        pattern_keywords = self.KOREAN_TO_ENGLISH_PATTERN.get(pattern, [pattern])
                        if isinstance(pattern_keywords, str):
                            pattern_keywords = [pattern_keywords, pattern]
                        if not any(kw.lower() in product_name for kw in pattern_keywords):
                            match = False

                    if style and match:
                        style_keywords = self.KOREAN_TO_ENGLISH_STYLE.get(style, [style])
                        if isinstance(style_keywords, str):
                            style_keywords = [style_keywords, style]
                        if not any(kw.lower() in product_name for kw in style_keywords):
                            match = False

                    if material and match:
                        material_keywords = self.KOREAN_TO_ENGLISH_MATERIAL.get(material, [material])
                        if isinstance(material_keywords, str):
                            material_keywords = [material_keywords, material]
                        if not any(kw.lower() in product_name for kw in material_keywords):
                            match = False

                    if color and match:
                        color_keywords = self.KOREAN_TO_ENGLISH_COLOR.get(color, [color])
                        if isinstance(color_keywords, str):
                            color_keywords = [color_keywords, color]
                        if not any(kw.lower() in product_name for kw in color_keywords):
                            match = False

                    if match:
                        filtered_products.append(p)

                products = filtered_products
                logger.info(f"Image filter keyword filtering: {len(filtered_products)} results after filtering")

            if not products:
                filter_name = ', '.join(filter_parts) if filter_parts else '지정한 조건'
                return ResponseBuilder.no_results(
                    f"이미지에서 {filter_name} 관련 상품을 찾지 못했어요. 다른 조건으로 시도해보세요."
                )

            # 6. 컨텍스트 업데이트
            shown_ids = [p.get('product_id') for p in products if p.get('product_id')]
            context['shown_product_ids'] = shown_ids
            context['search_results'] = products
            context['has_search_results'] = True

            filter_name = ', '.join(filter_parts[:2]) if filter_parts else '지정한 조건'  # 최대 2개까지 표시
            return ResponseBuilder.search_results(
                products,
                f"이미지에서 {filter_name} 관련 상품이에요:"
            )

        except Exception as e:
            logger.error(f"Refine image filter error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "refine_error",
                "필터 적용 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.refine_text_search")
    def _refine_text_search(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        텍스트 검색 조건 변경 (이전 검색 조건 + 새 필터 병합)

        예시:
        - "나이키 운동화 찾아줘" → "빨간색으로 찾아줘"
          = 이전 조건(brand=nike, category=shoes) + 새 조건(color=red)
        - "검은색 코트 찾아줘" → "다른 브랜드로" → "무신사"
          = 이전 조건 유지 + 새 조건 병합
        """
        try:
            # 1. 이전 검색 조건 가져오기
            last_params = context.get('last_search_params', {})
            last_query = context.get('last_search_query', '')

            # 2. 새 메시지에서 추출된 조건 가져오기
            new_params = context.get('intent_result', {}).get('search_params', {})

            # 3. 이전 조건과 새 조건 병합 (새 조건이 우선)
            merged_params = last_params.copy()

            # 새 조건 병합 (None이 아닌 값만)
            if new_params.get('target_categories'):
                merged_params['target_categories'] = new_params['target_categories']
            if new_params.get('color'):
                merged_params['color'] = new_params['color']
            if new_params.get('brand'):
                merged_params['brand'] = new_params['brand']
            if new_params.get('item_type'):
                merged_params['item_type'] = new_params['item_type']
            if new_params.get('pattern'):
                merged_params['pattern'] = new_params['pattern']
            if new_params.get('style'):
                merged_params['style'] = new_params['style']
            if new_params.get('material'):
                merged_params['material'] = new_params['material']

            # 4. 메시지에서 직접 필터 추출 (LLM이 놓친 경우 대비)
            message_lower = message.lower()

            # 색상 추출
            for kor_color, eng_color in self.KOREAN_TO_ENGLISH_COLOR.items():
                if kor_color in message_lower:
                    merged_params['color'] = eng_color
                    break

            # 브랜드 추출 (주요 브랜드)
            BRAND_KEYWORDS = {
                'nike': ['나이키', 'nike'],
                'adidas': ['아디다스', 'adidas'],
                'newbalance': ['뉴발란스', 'new balance', '뉴발'],
                'converse': ['컨버스', 'converse'],
                'vans': ['반스', 'vans'],
                'zara': ['자라', 'zara'],
                'uniqlo': ['유니클로', 'uniqlo'],
                'musinsa': ['무신사', 'musinsa'],
            }
            for brand, keywords in BRAND_KEYWORDS.items():
                if any(kw in message_lower for kw in keywords):
                    merged_params['brand'] = brand
                    break

            # 패턴 추출
            for kor_pattern, eng_pattern in self.KOREAN_TO_ENGLISH_PATTERN.items():
                if kor_pattern in message_lower:
                    merged_params['pattern'] = eng_pattern
                    break

            # 스타일 추출
            for kor_style, eng_style in self.KOREAN_TO_ENGLISH_STYLE.items():
                if kor_style in message_lower:
                    merged_params['style'] = eng_style
                    break

            # 소재 추출
            for kor_material, eng_material in self.KOREAN_TO_ENGLISH_MATERIAL.items():
                if kor_material in message_lower:
                    merged_params['material'] = eng_material
                    break

            logger.info(
                f"Refine text search: last_query='{last_query}', "
                f"last_params={last_params}, new_params={new_params}, "
                f"merged_params={merged_params}"
            )

            # 5. 병합된 조건으로 검색
            # context의 intent_result에 병합된 params 설정
            context['intent_result'] = context.get('intent_result', {})
            context['intent_result']['search_params'] = merged_params

            # 6. 검색 쿼리 구성 (이전 쿼리 + 새 조건)
            # 이전 쿼리에서 조건 키워드 추출하여 재사용
            search_query = last_query

            # 새로 추가된 필터 표시용
            filter_desc_parts = []
            if merged_params.get('color') and merged_params.get('color') != last_params.get('color'):
                filter_desc_parts.append(merged_params['color'])
            if merged_params.get('brand') and merged_params.get('brand') != last_params.get('brand'):
                filter_desc_parts.append(merged_params['brand'])
            if merged_params.get('pattern') and merged_params.get('pattern') != last_params.get('pattern'):
                filter_desc_parts.append(merged_params['pattern'])
            if merged_params.get('style') and merged_params.get('style') != last_params.get('style'):
                filter_desc_parts.append(merged_params['style'])
            if merged_params.get('material') and merged_params.get('material') != last_params.get('material'):
                filter_desc_parts.append(merged_params['material'])

            # 7. 텍스트 검색 실행
            # 필터 추출 및 정규화
            categories = merged_params.get('target_categories', [])
            category = categories[0] if categories else None
            brand = merged_params.get('brand')
            color = self._normalize_color(merged_params.get('color'))
            pattern = self._normalize_pattern(merged_params.get('pattern'))
            style = self._normalize_style(merged_params.get('style'))
            material = self._normalize_material(merged_params.get('material'))

            # 임베딩 쿼리 구성 (모든 필터 포함)
            query_parts = []
            if brand:
                query_parts.append(brand)
            if color:
                query_parts.append(color)
            if pattern:
                query_parts.append(pattern)
            if style:
                query_parts.append(style)
            if material:
                query_parts.append(material)
            query_parts.append(self._translate_to_english(last_query))
            search_query_for_embedding = ' '.join(query_parts)

            text_embedding = self.embedding_service.get_text_embedding(search_query_for_embedding)

            # 8. OpenSearch 검색
            if (brand or color) and category:
                results = self.opensearch.search_brand_vector_color(
                    embedding=text_embedding,
                    category=category,
                    brand=brand,
                    color=color,
                    k=100,
                    search_k=500
                )
            elif category:
                results = self.opensearch.search_similar_products_hybrid(
                    embedding=text_embedding,
                    category=category,
                    k=100,
                    search_k=500
                )
            else:
                results = self.opensearch.search_by_vector(
                    embedding=text_embedding,
                    k=100
                )

            if not results:
                # 결과 0개: 이전 조건 없이 새 검색으로 폴백
                logger.info("Text refine returned 0 results with merged params, trying new search")
                # 컨텍스트를 초기화하고 새 텍스트 검색
                context['last_search_params'] = None
                context['last_search_query'] = None
                return self.text_search(message, context)

            # 9. 패턴/스타일/소재 키워드 필터링
            if pattern or style or material:
                results = self._filter_results_by_keywords(results, pattern, style, material)
                if not results:
                    # 필터링 후 0개: 필터 없이 다시 시도
                    logger.info("Text refine returned 0 results after keyword filter, trying without filter")
                    context['last_search_params'] = None
                    context['last_search_query'] = None
                    return self.text_search(message, context)

            # 10. 결과 반환
            normalized_results = self._normalize_search_results(results[:5])
            context['search_results'] = normalized_results
            context['has_search_results'] = True
            context['last_search_params'] = merged_params  # 병합된 조건 저장
            # last_search_query는 원래 검색어 유지

            # 결과 메시지 구성
            if filter_desc_parts:
                result_message = f"'{last_query}'에서 {', '.join(filter_desc_parts)} 조건으로 다시 찾았어요:"
            else:
                result_message = f"'{last_query}' 조건을 변경해서 찾았어요:"

            return ResponseBuilder.search_results(normalized_results, result_message)

        except Exception as e:
            logger.error(f"Refine text search error: {e}", exc_info=True)
            # 에러 시 새 검색으로 fallback
            return self.text_search(message, context)

    def _extract_filter_from_message(self, message: str) -> tuple:
        """
        메시지에서 카테고리/아이템 타입 필터 추출

        Returns:
            (category_filter, item_type_filter) 튜플
        """
        message_lower = message.lower()

        # 카테고리 키워드 매핑
        CATEGORY_KEYWORDS = {
            'shoes': ['신발', '구두', '운동화', '스니커즈', '부츠', '로퍼', '샌들', '슬리퍼'],
            'top': ['상의', '티셔츠', '셔츠', '니트', '맨투맨', '후드', '블라우스'],
            'bottom': ['하의', '바지', '팬츠', '청바지', '슬랙스', '반바지'],
            'outer': ['아우터', '자켓', '재킷', '코트', '점퍼', '패딩', '가디건'],
            'bag': ['가방', '백', '토트백', '크로스백', '백팩'],
        }

        # 아이템 타입 키워드 (ITEM_TYPE_KEYWORDS 재사용)
        ITEM_TYPE_EXTRACT = {
            'coat': ['코트', '트렌치'],
            'padding': ['패딩', '다운', '푸퍼'],
            'jacket': ['자켓', '재킷', '블레이저'],
            'sneakers': ['운동화', '스니커즈'],
            'loafers': ['구두', '로퍼'],
            'boots': ['부츠', '워커'],
        }

        # 아이템 타입 먼저 체크 (더 구체적)
        for item_type, keywords in ITEM_TYPE_EXTRACT.items():
            if any(kw in message_lower for kw in keywords):
                return None, item_type

        # 카테고리 체크
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in message_lower for kw in keywords):
                return category, None

        return None, None

    def _get_available_categories_in_analysis(self, analysis_id: int) -> List[str]:
        """
        이미지 분석 결과에서 검출된 카테고리 목록 조회

        Args:
            analysis_id: 분석 ID

        Returns:
            검출된 카테고리 목록 (예: ['shoes', 'top', 'outer'])
        """
        from analyses.models import DetectedObject

        try:
            categories = DetectedObject.objects.filter(
                uploaded_image__analyses__id=analysis_id
            ).values_list('object_category', flat=True).distinct()

            return list(categories)
        except Exception as e:
            logger.error(f"Error getting available categories: {e}")
            return []

    def _category_exists_in_analysis(self, analysis_id: int, category: str) -> bool:
        """
        이미지 분석 결과에 해당 카테고리가 있는지 확인

        Args:
            analysis_id: 분석 ID
            category: 확인할 카테고리

        Returns:
            카테고리 존재 여부
        """
        # 카테고리 매핑 (사용자 입력 → DB 카테고리)
        CATEGORY_MAPPING = {
            'shoes': ['shoes'],
            'top': ['top'],
            'bottom': ['bottom'],
            'pants': ['bottom'],
            'outer': ['outerwear'],
            'outerwear': ['outerwear'],
            'bag': ['bag'],
            'hat': ['hat'],
            'dress': ['dress'],
            'skirt': ['skirt', 'dress'],
        }

        available = self._get_available_categories_in_analysis(analysis_id)
        target_categories = CATEGORY_MAPPING.get(category, [category])

        exists = any(cat in available for cat in target_categories)
        logger.info(
            f"Category check: {category} → {target_categories}, "
            f"available={available}, exists={exists}"
        )
        return exists

    @traced("search_agent.similar_search")
    def similar_search(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """현재 선택 상품과 유사한 상품 검색"""
        selected = context.get('selected_product')
        if not selected:
            results = context.get('search_results', [])
            if results:
                selected = results[0]
            else:
                return ResponseBuilder.ask_search_first()

        try:
            # 선택 상품의 임베딩으로 유사 검색
            from products.models import Product

            product = Product.objects.get(id=selected.get('product_id'))

            # 상품의 임베딩으로 유사 상품 검색
            # 기존 상품의 이미지로 임베딩 생성하거나 저장된 임베딩 사용
            text_query = f"{product.brand_name} {product.product_name}"
            embedding = self.embedding_service.get_text_embedding(text_query)

            results = self.opensearch.search_similar_products_hybrid(
                embedding=embedding,
                category=product.category,
                k=10
            )

            # 선택 상품 제외 및 정규화
            results = [r for r in results if r.get('product_id') != product.id]
            normalized_results = self._normalize_search_results(results[:5])

            if not normalized_results:
                return ResponseBuilder.no_results("비슷한 상품을 찾지 못했어요.")

            context['search_results'] = normalized_results
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                normalized_results,
                f"{selected.get('product_name', '선택한 상품')}과 비슷한 상품이에요:"
            )

        except Exception as e:
            logger.error(f"Similar search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "비슷한 상품을 찾는 중 문제가 발생했어요."
            )

    @traced("search_agent.cross_category_search")
    def cross_category_search(
        self,
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        크로스 카테고리 추천
        예: 셔츠 이미지 + "어울리는 바지 찾아줘"
        """
        try:
            # 이미지가 있으면 먼저 분석
            if image:
                # 이미지 분석하여 속성 추출
                from services import get_gpt4v_service
                gpt4v = get_gpt4v_service()

                # Base64 인코딩
                image_b64 = base64.b64encode(image).decode('utf-8')

                # 속성 추출 (간소화)
                attributes = {
                    "color": "white",  # 실제로는 Claude Vision으로 추출
                    "style": "casual"
                }

                context['source_attributes'] = attributes

            # 대상 카테고리 추출
            search_params = context.get('intent_result', {}).get('search_params', {})
            target_categories = search_params.get('target_categories', ['bottom'])

            # 크로스 카테고리 검색 - 텍스트 임베딩 사용
            text_embedding = self.embedding_service.get_text_embedding(message)
            target_category = target_categories[0] if target_categories else 'bottom'

            results = self.opensearch.search_similar_products_hybrid(
                embedding=text_embedding,
                category=target_category,
                k=30
            )

            if not results:
                return ResponseBuilder.no_results()

            # 결과 정규화 및 컨텍스트 업데이트
            normalized_results = self._normalize_search_results(results[:5])
            context['search_results'] = normalized_results
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                normalized_results,
                "어울리는 상품을 찾았어요:"
            )

        except Exception as e:
            logger.error(f"Cross category search error: {e}", exc_info=True)
            return self.text_search(message, context)

    def _mapping_to_product(self, mapping, include_bbox: bool = False) -> Dict[str, Any]:
        """ObjectProductMapping을 product dict로 변환"""
        product = mapping.product
        detected_obj = mapping.detected_object

        result = {
            'product_id': product.id,
            'brand_name': product.brand_name,
            'product_name': product.product_name,
            'selling_price': product.selling_price,
            'image_url': product.product_image_url,
            'product_url': product.product_url,
            'category': product.category,
            'confidence_score': mapping.confidence_score,
            # 사이즈 정보 (selected_product_id 포함)
            'sizes': self._get_sizes_with_selected_product(product.id)
        }

        # 이미지 분석 결과일 때만 bbox 포함
        if include_bbox and detected_obj:
            result['detected_object_id'] = detected_obj.id
            result['bbox'] = {
                'x1': round(detected_obj.bbox_x1, 4),
                'y1': round(detected_obj.bbox_y1, 4),
                'x2': round(detected_obj.bbox_x2, 4),
                'y2': round(detected_obj.bbox_y2, 4),
            }

        return result

    def _normalize_search_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """OpenSearch 결과를 표준 포맷으로 변환"""
        normalized = []
        for r in results:
            product_id = r.get('product_id') or r.get('itemId')
            normalized.append({
                'product_id': product_id,
                'brand_name': r.get('brand_name') or r.get('brand', ''),
                'product_name': r.get('product_name') or r.get('name', ''),
                'selling_price': r.get('selling_price') or r.get('price', 0),
                'image_url': r.get('image_url') or r.get('imageUrl', ''),
                'product_url': r.get('product_url') or r.get('productUrl', ''),
                'category': r.get('category', ''),
                'score': r.get('score', 0),
                'sizes': self._get_sizes_with_selected_product(product_id),
            })
        return normalized

    def _get_sizes_with_selected_product(self, product_id) -> List[Dict[str, Any]]:
        """상품의 사이즈별 selected_product_id 조회"""
        from products.models import SizeCode
        from analyses.models import SelectedProduct

        if not product_id:
            return []

        # SizeCode 조회
        size_codes = SizeCode.objects.filter(
            product_id=product_id,
            is_deleted=False
        )

        sizes = []
        for sc in size_codes:
            # SelectedProduct 조회 또는 생성
            selected_product, _ = SelectedProduct.objects.get_or_create(
                product_id=product_id,
                size_code=sc,
                defaults={'selected_product_inventory': 0}
            )
            sizes.append({
                'size': sc.size_value,
                'size_code_id': sc.id,
                'selected_product_id': selected_product.id
            })

        return sizes

    # 아이템 타입별 키워드 매핑 (상품명에서 검색)
    ITEM_TYPE_KEYWORDS = {
        # outer
        'coat': ['코트', 'coat', '트렌치', 'trench'],
        'padding': ['패딩', 'padding', '다운', 'down', '푸퍼', 'puffer'],
        'jacket': ['자켓', 'jacket', '재킷', '블레이저', 'blazer'],
        'cardigan': ['가디건', 'cardigan'],
        'jumper': ['점퍼', 'jumper', '바람막이', '윈드', 'wind'],
        # shoes
        'sneakers': ['스니커즈', 'sneakers', '운동화', '러닝', 'running'],
        'loafers': ['로퍼', 'loafer', '구두', '드레스슈즈', 'dress shoes', '옥스퍼드', 'oxford'],
        'boots': ['부츠', 'boots', '워커', 'walker'],
        'sandals': ['샌들', 'sandal'],
        'slippers': ['슬리퍼', 'slipper', '슬라이드', 'slide'],
        # top
        'tshirt': ['티셔츠', 't-shirt', 'tshirt', '반팔'],
        'shirt': ['셔츠', 'shirt', '블라우스', 'blouse'],
        'knit': ['니트', 'knit', '스웨터', 'sweater'],
        'hoodie': ['후드', 'hoodie', '후디'],
        'sweatshirt': ['맨투맨', 'sweatshirt', '스웻'],
        # bottom
        'jeans': ['청바지', 'jeans', '데님', 'denim'],
        'slacks': ['슬랙스', 'slacks', '정장바지', '드레스팬츠'],
        'jogger': ['조거', 'jogger', '트레이닝', 'training'],
        'shorts': ['반바지', 'shorts', '숏팬츠', '숏츠'],
    }

    def get_analysis_results(
        self,
        analysis_id: int,
        category_filter: Optional[str] = None,
        item_type_filter: Optional[str] = None,
        exclude_product_ids: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """
        분석 결과 조회 - 각 detected_object별로 최고 매칭 상품 반환

        여러 객체가 탐지된 경우 (예: shoes, pants, outerwear)
        각 객체별로 가장 매칭 점수가 높은 상품을 반환합니다.

        Args:
            analysis_id: 분석 ID
            category_filter: 카테고리 필터 (예: 'shoes', 'top', 'bottom')
            item_type_filter: 아이템 타입 필터 (예: 'coat', 'sneakers')
                             지정 시 해당 키워드가 상품명에 포함된 것만 반환
            exclude_product_ids: 제외할 상품 ID 목록 (재검색 시 이전 상품 제외)
        """
        from analyses.models import ObjectProductMapping
        from django.db.models import Max

        # 카테고리 매핑 (사용자 입력 → DB 카테고리)
        # DB values: ['bottom', 'shoes', 'top', 'bag', 'outerwear', 'hat']
        CATEGORY_MAPPING = {
            'shoes': ['shoes'],
            'top': ['top'],  # 상의 = 티셔츠, 셔츠, 니트 등 (아우터 제외)
            'bottom': ['bottom'],
            'pants': ['bottom'],
            'outer': ['outerwear'],  # 아우터 = 자켓, 코트, 패딩 등
            'outerwear': ['outerwear'],
            'bag': ['bag'],
            'hat': ['hat'],
            'dress': ['dress'],
            'skirt': ['skirt', 'dress'],
        }

        # 아이템 타입 → 카테고리 매핑 (item_type만 지정된 경우)
        ITEM_TYPE_TO_CATEGORY = {
            'coat': 'outer', 'padding': 'outer', 'jacket': 'outer',
            'cardigan': 'outer', 'jumper': 'outer',
            'sneakers': 'shoes', 'loafers': 'shoes', 'boots': 'shoes',
            'sandals': 'shoes', 'slippers': 'shoes',
            'tshirt': 'top', 'shirt': 'top', 'knit': 'top',
            'hoodie': 'top', 'sweatshirt': 'top',
            'jeans': 'pants', 'slacks': 'pants', 'jogger': 'pants', 'shorts': 'pants',
        }

        # item_type이 있으면 자동으로 category 설정
        if item_type_filter and not category_filter:
            category_filter = ITEM_TYPE_TO_CATEGORY.get(item_type_filter)

        # 1. 모든 매핑 조회
        queryset = ObjectProductMapping.objects.filter(
            detected_object__uploaded_image__analyses__id=analysis_id,
            is_deleted=False
        ).select_related('product', 'detected_object')

        # 카테고리 필터 적용
        if category_filter:
            allowed_categories = CATEGORY_MAPPING.get(category_filter, [category_filter])
            queryset = queryset.filter(
                detected_object__object_category__in=allowed_categories
            )
            logger.info(f"Filtering analysis results by category: {category_filter} -> {allowed_categories}")

        all_mappings = queryset.order_by('-confidence_score')

        # 2. detected_object별로 그룹화하여 최고 점수 상품 선택
        seen_objects = set()
        results = []
        exclude_ids = set(exclude_product_ids or [])

        # 아이템 타입 키워드
        item_keywords = self.ITEM_TYPE_KEYWORDS.get(item_type_filter, []) if item_type_filter else []

        for mapping in all_mappings:
            obj_id = mapping.detected_object_id
            product = mapping.product

            # 제외 상품 스킵 (재검색 시 이전에 보여준 상품)
            if product.id in exclude_ids:
                continue

            if obj_id not in seen_objects:
                product_name = (product.product_name or '').lower()

                # 아이템 타입 필터 적용 (키워드 매칭)
                if item_keywords:
                    if not any(kw.lower() in product_name for kw in item_keywords):
                        continue  # 키워드 매칭 안 되면 스킵

                seen_objects.add(obj_id)
                results.append(self._mapping_to_product(mapping, include_bbox=True))

            # 최대 5개까지
            if len(results) >= 5:
                break

        if item_type_filter:
            logger.info(f"Item type filter '{item_type_filter}' applied: {len(results)} results")

        return results
