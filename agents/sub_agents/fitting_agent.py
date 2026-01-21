"""
AI 패션 어시스턴트 - 피팅 에이전트
기존 피팅 시스템을 활용한 가상 피팅 처리
"""

import logging
import base64
from typing import Dict, Any, Optional, List

from agents.response_builder import ResponseBuilder
from agents.utils import ProductMatcher
from config.tracing import traced, get_tracer
from products.models import Product

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class FittingAgent:
    """
    피팅 에이전트 - 기존 피팅 API 활용

    핵심 연동 포인트:
    - UserImage 모델: 사용자 전신 이미지
    - FittingImage 모델: 피팅 결과
    - process_fitting_task: Celery 태스크
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        # 피팅 컨텍스트용 ProductMatcher (피팅 불용어 활성화)
        self._product_matcher = ProductMatcher(
            include_commerce_stopwords=True,  # 커머스도 포함 (복합 요청 대응)
            include_fitting_stopwords=True,
            min_score_threshold=2  # 최소 2점 이상 매칭 필요
        )

    @traced("fitting_agent.handle")
    def handle(
        self,
        sub_intent: str,
        context: Dict[str, Any],
        image: Optional[bytes] = None,
        message: str = ''
    ) -> Dict[str, Any]:
        """피팅 요청 처리"""
        try:
            # 이미지 + 피팅 요청: 상품 검색 먼저 필요
            if sub_intent == 'fitting_with_image':
                return self.handle_fitting_with_image(image, context)

            # 상품 검색 확인 응답
            elif sub_intent == 'confirm_search_for_fitting':
                return self.start_search_for_fitting(context)

            # 피팅 취소
            elif sub_intent == 'cancel_fitting':
                context['pending_action'] = None
                return ResponseBuilder.general_response(
                    "알겠어요! 다른 것을 도와드릴까요?"
                )

            # 기존 피팅 로직
            # 전제조건 확인
            prereq_check = self._check_prerequisites(context)
            if prereq_check:
                return prereq_check

            if sub_intent == 'single_fit':
                return self.single_fitting(context, message)

            elif sub_intent == 'batch_fit':
                return self.batch_fitting(context, message)

            elif sub_intent == 'compare_fit':
                return self.compare_fitting(context, message)

            else:
                return self.single_fitting(context, message)

        except Exception as e:
            logger.error(f"FittingAgent error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "fitting_error",
                "피팅 처리 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("fitting_agent.handle_fitting_with_image")
    def handle_fitting_with_image(
        self,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        이미지 + 피팅 요청 처리

        플로우:
        1. 이미지가 있으면 -> 상품 검색 확인 요청
        2. 사용자 확인 후 -> 이미지 분석 시작
        3. 분석 완료 후 -> 피팅할 상품 선택 요청
        """
        if not image:
            return ResponseBuilder.error(
                "no_image",
                "피팅할 이미지가 없어요. 이미지를 업로드해주세요."
            )

        # 이미지를 컨텍스트에 저장 (나중에 분석용)
        context['fitting_source_image'] = base64.b64encode(image).decode('utf-8')

        # pending_action 설정: 상품 검색 확인 대기
        context['pending_action'] = {
            'type': 'confirm_search_for_fitting',
            'has_image': True
        }

        return ResponseBuilder.ask_search_for_fitting()

    @traced("fitting_agent.start_search_for_fitting")
    def start_search_for_fitting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        피팅을 위한 이미지 분석 시작
        """
        from analyses.models import UploadedImage, ImageAnalysis
        from analyses.tasks.analysis import process_image_analysis

        # 저장된 이미지 가져오기
        image_b64 = context.get('fitting_source_image')
        if not image_b64:
            return ResponseBuilder.error(
                "no_image",
                "이미지 정보가 없어요. 다시 이미지를 업로드해주세요."
            )

        try:
            # 1. 이미지 업로드
            uploaded_image = UploadedImage.objects.create(
                user_id=self.user_id,
                uploaded_image_url=""
            )

            # 2. 분석 시작
            analysis = ImageAnalysis.objects.create(
                uploaded_image=uploaded_image,
                image_analysis_status='PENDING'
            )

            # 3. Celery Task 실행
            process_image_analysis.delay(
                analysis_id=analysis.id,
                image_url=None,
                user_id=self.user_id,
                image_b64=image_b64
            )

            # 4. 컨텍스트 업데이트
            context['current_analysis_id'] = analysis.id
            context['analysis_pending'] = True
            context['last_search_type'] = 'image'
            context['fitting_flow'] = True  # 피팅 플로우임을 표시

            # pending_action 업데이트: 분석 완료 후 상품 선택 대기
            context['pending_action'] = {
                'type': 'select_product_for_fitting',
                'analysis_id': analysis.id
            }

            # 저장된 이미지 데이터 제거 (메모리 절약)
            context.pop('fitting_source_image', None)

            return ResponseBuilder.analysis_pending_for_fitting(analysis.id)

        except Exception as e:
            logger.error(f"Start search for fitting error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "analysis_error",
                "이미지 분석 시작에 실패했어요. 다시 시도해주세요."
            )

    def _check_prerequisites(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """전제조건 확인"""
        # 1. 검색 결과 확인
        if not context.get('has_search_results') and not context.get('search_results'):
            return ResponseBuilder.ask_search_first()

        # 2. 사용자 이미지 확인
        from fittings.models import UserImage

        user_image = UserImage.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ).order_by('-created_at').first()

        if not user_image:
            return ResponseBuilder.ask_user_image()

        # 컨텍스트에 저장
        context['user_image'] = user_image
        context['has_user_image'] = True

        return None

    def _resolve_product(self, product_info: Dict[str, Any]) -> Optional[Product]:
        """
        검색 결과의 상품 정보를 로컬 Product로 변환

        검색 결과는 외부 API(Musinsa)의 product_id를 사용하지만,
        FittingImage는 로컬 Product FK를 참조하므로 변환이 필요.

        Args:
            product_info: 검색 결과의 상품 정보 (product_url 포함)

        Returns:
            로컬 Product 또는 None
        """
        product_url = product_info.get('product_url')
        if not product_url:
            return None

        return Product.objects.filter(
            product_url=product_url,
            is_deleted=False
        ).first()

    @traced("fitting_agent.single_fitting")
    def single_fitting(self, context: Dict[str, Any], message: str = '') -> Dict[str, Any]:
        """
        단일 피팅 - 기존 API 활용

        1. 선택된 상품 확인 (인덱스 또는 상품명으로 선택)
        2. 캐시 확인 (이미 피팅된 결과 있는지)
        3. 피팅 요청 (FittingImage 생성)
        4. Celery Task 실행 (process_fitting_task)
        """
        from fittings.models import FittingImage, UserImage
        from fittings.tasks import process_fitting_task

        # 1. 선택된 상품 확인
        products = context.get('search_results', [])
        selected = self._select_product_from_context(message, context)

        if not selected:
            if not products:
                return ResponseBuilder.ask_search_first()
            elif len(products) == 1:
                selected = products[0]
            else:
                return ResponseBuilder.ask_selection(
                    "어떤 상품을 피팅해볼까요?",
                    products
                )

        # 2. 사용자 이미지
        user_image = context.get('user_image')
        if not user_image:
            user_image = UserImage.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).order_by('-created_at').first()
            if not user_image:
                return ResponseBuilder.ask_user_image()

        # 3. 로컬 Product 조회 (외부 product_id → 로컬 Product)
        local_product = self._resolve_product(selected)
        if not local_product:
            return ResponseBuilder.error(
                "product_not_found",
                "해당 상품 정보를 찾을 수 없어요. 다른 상품을 선택해주세요."
            )

        # 4. 캐시 확인
        existing = FittingImage.objects.filter(
            user_image=user_image,
            product=local_product,
            fitting_image_status='DONE',
            is_deleted=False
        ).first()

        if existing:
            # 캐시된 결과 반환
            return ResponseBuilder.fitting_result(
                existing.fitting_image_url,
                selected
            )

        # 5. 새 피팅 생성
        fitting = FittingImage.objects.create(
            user_image=user_image,
            product=local_product,
            fitting_image_status='PENDING'
        )

        # 6. Celery Task 실행
        process_fitting_task.delay(fitting.id)

        # 컨텍스트 업데이트
        context['current_fitting_id'] = fitting.id
        context['fitting_pending'] = True
        context['selected_product'] = selected

        return ResponseBuilder.fitting_pending(fitting.id, selected)

    @traced("fitting_agent.batch_fitting")
    def batch_fitting(self, context: Dict[str, Any], message: str = '') -> Dict[str, Any]:
        """
        배치 피팅 - 여러 상품 동시 피팅

        검색 결과 전체 또는 선택된 상품들을 병렬로 피팅
        """
        from fittings.models import FittingImage, UserImage
        from fittings.tasks import process_fitting_task

        products = context.get('search_results', [])
        if not products:
            return ResponseBuilder.ask_search_first()

        user_image = context.get('user_image')
        if not user_image:
            user_image = UserImage.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).order_by('-created_at').first()
            if not user_image:
                return ResponseBuilder.ask_user_image()

        # 1-1. 인덱스 참조가 있으면 해당 상품만
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        if indices:
            # 유효한 인덱스만 필터링 (1 ~ len(products))
            products = [products[i-1] for i in indices if 1 <= i <= len(products)]
            if not products:
                # 모든 인덱스가 유효하지 않으면 원래 결과 사용
                products = context.get('search_results', [])[:5]
        # 1-2. 인덱스 없으면 상품명/브랜드명으로 매칭 시도
        elif message:
            matched = self._product_matcher.find_all_matches(message, products, max_results=5)
            if matched:
                products = matched

        # 최대 5개까지 피팅
        products = products[:5]
        fitting_ids = []

        for product_info in products:
            # 로컬 Product 조회
            local_product = self._resolve_product(product_info)
            if not local_product:
                logger.warning(f"Product not found for URL: {product_info.get('product_url')}")
                continue

            # 캐시 확인
            existing = FittingImage.objects.filter(
                user_image=user_image,
                product=local_product,
                fitting_image_status='DONE',
                is_deleted=False
            ).first()

            if existing:
                fitting_ids.append(existing.id)
            else:
                # 새 피팅 생성
                fitting = FittingImage.objects.create(
                    user_image=user_image,
                    product=local_product,
                    fitting_image_status='PENDING'
                )
                process_fitting_task.delay(fitting.id)
                fitting_ids.append(fitting.id)

        # 컨텍스트 업데이트
        context['fitting_ids'] = fitting_ids
        context['batch_fitting_pending'] = True

        return ResponseBuilder.batch_fitting_pending(fitting_ids, len(fitting_ids))

    def compare_fitting(self, context: Dict[str, Any], message: str = '') -> Dict[str, Any]:
        """비교 피팅 - 2개 상품 비교"""
        # 배치 피팅과 동일하지만 최대 2개
        products = context.get('search_results', [])
        if len(products) < 2:
            return ResponseBuilder.error(
                "not_enough_products",
                "비교하려면 최소 2개 상품이 필요해요."
            )

        # 1-1. 인덱스 참조 확인
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        if len(indices) >= 2:
            # 유효한 인덱스만 필터링 (1 ~ len(products))
            products = [products[i-1] for i in indices[:2] if 1 <= i <= len(products)]
        # 1-2. 인덱스 없으면 상품명/브랜드명으로 매칭 시도
        elif message:
            matched = self._product_matcher.find_all_matches(message, products, max_results=2)
            if len(matched) >= 2:
                products = matched[:2]
            else:
                products = products[:2]
        else:
            products = products[:2]

        context['search_results'] = products
        return self.batch_fitting(context, message)

    def get_fitting_status(self, fitting_id: int) -> Dict[str, Any]:
        """피팅 상태 조회"""
        from fittings.models import FittingImage

        try:
            fitting = FittingImage.objects.select_related('product').get(id=fitting_id)

            if fitting.fitting_image_status == 'DONE':
                product = {
                    'product_id': fitting.product.id,
                    'brand_name': fitting.product.brand_name,
                    'product_name': fitting.product.product_name,
                    'selling_price': fitting.product.selling_price,
                }
                return ResponseBuilder.fitting_result(
                    fitting.fitting_image_url,
                    product
                )
            elif fitting.fitting_image_status == 'FAILED':
                return ResponseBuilder.error(
                    "fitting_failed",
                    "피팅 처리에 실패했어요. 다시 시도해주세요."
                )
            else:
                return ResponseBuilder.fitting_pending(
                    fitting.id,
                    {
                        'product_id': fitting.product.id,
                        'product_name': fitting.product.product_name,
                    }
                )
        except FittingImage.DoesNotExist:
            return ResponseBuilder.error(
                "fitting_not_found",
                "피팅 정보를 찾을 수 없어요."
            )

    def _select_product_from_context(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        컨텍스트에서 상품 선택 (인덱스 > 상품명 매칭 > 이전 선택 순서)

        우선순위:
        1. 이전에 선택된 상품 (selected_product)
        2. 인덱스 참조 (예: "1번 피팅해줘")
        3. 상품명/브랜드명 매칭 (예: "나이키 셔츠 입어봐")

        Args:
            message: 사용자 메시지
            context: 세션 컨텍스트

        Returns:
            선택된 상품 또는 None
        """
        # 1. 이전에 선택된 상품 확인
        selected = context.get('selected_product')
        if selected:
            return selected

        products = context.get('search_results', [])
        if not products:
            return None

        # 2. 인덱스 참조 확인
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])

        # 인덱스 유효 범위: 1 ~ len(products)
        if indices and 1 <= indices[0] <= len(products):
            logger.debug(f"Product selected by index: {indices[0]}")
            return products[indices[0] - 1]

        # 3. 상품명/브랜드명으로 매칭 시도
        if message:
            matched = self._product_matcher.find_best_match(message, products)
            if matched:
                return matched

        return None
