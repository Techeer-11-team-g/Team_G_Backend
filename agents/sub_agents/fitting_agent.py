"""
AI 패션 어시스턴트 - 피팅 에이전트
기존 피팅 시스템을 활용한 가상 피팅 처리
"""

import logging
from typing import Dict, Any, Optional, List

from agents.response_builder import ResponseBuilder

logger = logging.getLogger(__name__)


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

    async def handle(
        self,
        sub_intent: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """피팅 요청 처리"""
        try:
            # 전제조건 확인
            prereq_check = await self._check_prerequisites(context)
            if prereq_check:
                return prereq_check

            if sub_intent == 'single_fit':
                return await self.single_fitting(context)

            elif sub_intent == 'batch_fit':
                return await self.batch_fitting(context)

            elif sub_intent == 'compare_fit':
                return await self.compare_fitting(context)

            else:
                return await self.single_fitting(context)

        except Exception as e:
            logger.error(f"FittingAgent error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "fitting_error",
                "피팅 처리 중 문제가 발생했어요. 다시 시도해주세요."
            )

    async def _check_prerequisites(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

    async def single_fitting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        단일 피팅 - 기존 API 활용

        1. 선택된 상품 확인 (또는 인덱스로 선택)
        2. 캐시 확인 (이미 피팅된 결과 있는지)
        3. 피팅 요청 (FittingImage 생성)
        4. Celery Task 실행 (process_fitting_task)
        """
        from fittings.models import FittingImage
        from fittings.tasks import process_fitting_task

        # 1. 선택된 상품 확인
        selected = context.get('selected_product')
        if not selected:
            # 검색 결과에서 선택
            products = context.get('search_results', [])
            if len(products) == 1:
                selected = products[0]
            elif len(products) > 1:
                # 인덱스 참조 확인
                refs = context.get('intent_result', {}).get('references', {})
                indices = refs.get('indices', [])
                # 유효한 인덱스 범위 확인 (1 ~ len(products))
                if indices and 1 <= indices[0] <= len(products):
                    selected = products[indices[0] - 1]
                else:
                    return ResponseBuilder.ask_selection(
                        "어떤 상품을 피팅해볼까요?",
                        products
                    )
            else:
                return ResponseBuilder.ask_search_first()

        # 2. 사용자 이미지
        user_image = context.get('user_image')
        if not user_image:
            from fittings.models import UserImage
            user_image = UserImage.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).order_by('-created_at').first()

            if not user_image:
                return ResponseBuilder.ask_user_image()

        product_id = selected.get('product_id') or selected.get('id')

        # 3. 캐시 확인
        existing = FittingImage.objects.filter(
            user_image=user_image,
            product_id=product_id,
            fitting_image_status='DONE',
            is_deleted=False
        ).first()

        if existing:
            # 캐시된 결과 반환
            return ResponseBuilder.fitting_result(
                existing.fitting_image_url,
                selected
            )

        # 4. 새 피팅 생성
        fitting = FittingImage.objects.create(
            user_image=user_image,
            product_id=product_id,
            fitting_image_status='PENDING'
        )

        # 5. Celery Task 실행
        process_fitting_task.delay(fitting.id)

        # 컨텍스트 업데이트
        context['current_fitting_id'] = fitting.id
        context['fitting_pending'] = True
        context['selected_product'] = selected

        return ResponseBuilder.fitting_pending(fitting.id, selected)

    async def batch_fitting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        배치 피팅 - 여러 상품 동시 피팅

        검색 결과 전체 또는 선택된 상품들을 병렬로 피팅
        """
        from fittings.models import FittingImage
        from fittings.tasks import process_fitting_task

        products = context.get('search_results', [])
        if not products:
            return ResponseBuilder.ask_search_first()

        user_image = context.get('user_image')
        if not user_image:
            from fittings.models import UserImage
            user_image = UserImage.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).order_by('-created_at').first()

            if not user_image:
                return ResponseBuilder.ask_user_image()

        # 인덱스 참조가 있으면 해당 상품만
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        if indices:
            # 유효한 인덱스만 필터링 (1 ~ len(products))
            products = [products[i-1] for i in indices if 1 <= i <= len(products)]
            if not products:
                # 모든 인덱스가 유효하지 않으면 원래 결과 사용
                products = context.get('search_results', [])[:5]

        # 최대 5개까지 피팅
        products = products[:5]
        fitting_ids = []

        for product in products:
            product_id = product.get('product_id') or product.get('id')

            # 캐시 확인
            existing = FittingImage.objects.filter(
                user_image=user_image,
                product_id=product_id,
                fitting_image_status='DONE',
                is_deleted=False
            ).first()

            if existing:
                fitting_ids.append(existing.id)
            else:
                # 새 피팅 생성
                fitting = FittingImage.objects.create(
                    user_image=user_image,
                    product_id=product_id,
                    fitting_image_status='PENDING'
                )
                process_fitting_task.delay(fitting.id)
                fitting_ids.append(fitting.id)

        # 컨텍스트 업데이트
        context['fitting_ids'] = fitting_ids
        context['batch_fitting_pending'] = True

        return ResponseBuilder.batch_fitting_pending(fitting_ids, len(fitting_ids))

    async def compare_fitting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """비교 피팅 - 2개 상품 비교"""
        # 배치 피팅과 동일하지만 최대 2개
        products = context.get('search_results', [])
        if len(products) < 2:
            return ResponseBuilder.error(
                "not_enough_products",
                "비교하려면 최소 2개 상품이 필요해요."
            )

        # 인덱스 참조 확인
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        if len(indices) >= 2:
            products = [products[i-1] for i in indices[:2] if i <= len(products)]
        else:
            products = products[:2]

        context['search_results'] = products
        return await self.batch_fitting(context)

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
