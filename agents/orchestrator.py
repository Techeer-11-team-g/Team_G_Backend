"""
AI 패션 어시스턴트 - 메인 오케스트레이터
사용자 의도 파악 및 서브 에이전트 조율
"""

import json
import logging
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from services import get_langchain_service, get_redis_service
from agents.schemas import INTENT_CLASSIFICATION_SCHEMA, SUPPORTED_CATEGORIES
from agents.response_builder import ResponseBuilder
from agents.sub_agents import SearchAgent, FittingAgent, CommerceAgent

logger = logging.getLogger(__name__)

# Redis TTL 설정 (기존 설정 활용)
TTL_SESSION = 2 * 60 * 60  # 2시간 (기존 TTL_CONVERSATION과 동일)


class MainOrchestrator:
    """
    메인 에이전트 (Orchestrator)

    역할:
    1. 사용자 입력 처리 (텍스트 + 이미지)
    2. Intent Classification (LangChain Function Calling)
    3. 서브 에이전트 라우팅
    4. 응답 생성
    5. 세션 상태 관리 (Redis)
    """

    def __init__(self, user_id: int, session_id: Optional[str] = None):
        self.user_id = user_id
        self.session_id = session_id or str(uuid.uuid4())

        # 서비스 초기화
        self.langchain = get_langchain_service()
        self.redis = get_redis_service()

        # 서브 에이전트 초기화
        self.search_agent = SearchAgent(user_id)
        self.fitting_agent = FittingAgent(user_id)
        self.commerce_agent = CommerceAgent(user_id)

    async def process_message(
        self,
        message: str,
        image: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        메시지 처리 메인 로직

        Args:
            message: 사용자 텍스트 메시지
            image: 첨부 이미지 (바이트)

        Returns:
            응답 딕셔너리 (text, type, data, suggestions)
        """
        try:
            # 1. 세션 컨텍스트 로드
            context = self._load_context()

            # 2. 입력 검증 및 정규화
            message = (message or '').strip()
            if not message and not image:
                return {
                    "session_id": self.session_id,
                    "response": ResponseBuilder.general_response(
                        "무엇을 도와드릴까요? 이미지를 보내주시거나 원하는 상품을 말씀해주세요."
                    ),
                    "context": {}
                }

            # 메시지 길이 제한 (10000자)
            if len(message) > 10000:
                message = message[:10000]

            # 3. Intent Classification
            intent_result = await self._classify_intent(message, image, context)
            context['intent_result'] = intent_result

            logger.info(
                "Intent classified",
                extra={
                    'event': 'intent_classified',
                    'user_id': self.user_id,
                    'session_id': self.session_id,
                    'intent': intent_result.get('intent'),
                    'sub_intent': intent_result.get('sub_intent'),
                }
            )

            # 4. 라우팅 및 처리
            response = await self._route_to_agent(intent_result, message, image, context)

            # 5. 대화 이력 저장
            self._save_turn(message, response.get('text', ''), context)

            # 6. 세션 상태 업데이트
            self._save_context(context)

            # 7. 응답 구성
            return {
                "session_id": self.session_id,
                "response": response,
                "context": {
                    "current_analysis_id": context.get('current_analysis_id'),
                    "has_search_results": context.get('has_search_results', False),
                    "has_user_image": context.get('has_user_image', False),
                    "cart_item_count": context.get('cart_item_count', 0),
                }
            }

        except Exception as e:
            logger.error(
                f"Orchestrator error: {e}",
                exc_info=True,
                extra={
                    'event': 'orchestrator_error',
                    'user_id': self.user_id,
                    'session_id': self.session_id,
                }
            )
            return {
                "session_id": self.session_id,
                "response": ResponseBuilder.error(
                    "system_error",
                    "죄송해요, 문제가 발생했어요. 다시 시도해주세요."
                ),
                "context": {}
            }

    async def _classify_intent(
        self,
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Intent Classification - LangChain Function Calling 활용

        기존 LangChainService를 확장하여 Intent 분류
        """
        # 이미지만 있으면 자동으로 검색 의도
        if image and not message:
            return {
                "intent": "search",
                "sub_intent": "new_search",
                "has_image": True,
                "requires_context": False,
                "references": {"type": "none"}
            }

        # 이미지 + 텍스트
        has_image = image is not None

        # 간단한 키워드 기반 분류 (기본)
        # 실제로는 LangChain Function Calling 사용
        intent_result = self._keyword_based_classification(message, has_image, context)

        # LLM 기반 정교한 분류 시도
        try:
            llm_result = await self._llm_classify_intent(message, context)
            if llm_result:
                intent_result.update(llm_result)
        except Exception as e:
            logger.warning(f"LLM classification fallback: {e}")
            # 키워드 기반 결과 사용

        intent_result['has_image'] = has_image
        return intent_result

    def _keyword_based_classification(
        self,
        message: str,
        has_image: bool,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """키워드 기반 Intent 분류 (폴백)"""
        message_lower = message.lower()

        # 1. 커머스 관련 (가장 구체적인 키워드, 먼저 체크)
        commerce_keywords = {
            "add_cart": ["담아", "장바구니에 담", "카트에"],
            "view_cart": ["장바구니 보", "장바구니 확인", "뭐 담", "담은 거", "장바구니에 뭐"],
            "remove_cart": ["빼", "삭제", "제거", "비워"],
            "size_recommend": ["사이즈", "치수", "몇 사이즈"],
            "checkout": ["주문", "구매", "결제", "살래", "살게"],
            "order_status": ["배송", "주문 내역", "주문 확인", "어디쯤"],
            "cancel_order": ["취소"]
        }

        for sub_intent, keywords in commerce_keywords.items():
            if any(kw in message_lower for kw in keywords):
                return {
                    "intent": "commerce",
                    "sub_intent": sub_intent,
                    "references": self._extract_references(message)
                }

        # 2. 피팅 관련
        fitting_keywords = ["입어", "피팅", "착용", "어떻게 보", "비교해"]
        if any(kw in message_lower for kw in fitting_keywords):
            if "비교" in message_lower or "vs" in message_lower:
                return {
                    "intent": "fitting",
                    "sub_intent": "compare_fit",
                    "references": self._extract_references(message)
                }
            if "다 " in message_lower or "전부" in message_lower or "모든" in message_lower:
                return {
                    "intent": "fitting",
                    "sub_intent": "batch_fit",
                    "references": {"type": "none"}
                }
            return {
                "intent": "fitting",
                "sub_intent": "single_fit",
                "references": self._extract_references(message)
            }

        # 3. 일반 대화
        general_keywords = {
            "greeting": ["안녕", "하이", "헬로"],
            "help": ["도와줘", "뭘 할 수", "사용법"],
            "feedback": ["고마워", "감사", "좋아", "별로"]
        }

        for sub_intent, keywords in general_keywords.items():
            if any(kw in message_lower for kw in keywords):
                return {
                    "intent": "general",
                    "sub_intent": sub_intent,
                    "references": {"type": "none"}
                }

        # 4. Refine 확인 (이전 검색 결과가 있는 경우)
        if context.get('has_search_results'):
            refine_keywords = ["다른", "대신", "말고", "색", "브랜드", "싸", "비싸", "없어", "더"]
            if any(kw in message_lower for kw in refine_keywords):
                return {
                    "intent": "search",
                    "sub_intent": "refine",
                    "references": {"type": "none"}
                }

        # 5. 검색 관련
        search_keywords = ["찾아", "보여줘", "검색", "추천", "비슷한", "어울리"]
        if any(kw in message_lower for kw in search_keywords) or has_image:
            # 크로스 카테고리 확인
            if "어울리" in message_lower and has_image:
                return {
                    "intent": "search",
                    "sub_intent": "cross_recommend",
                    "references": {"type": "none"}
                }
            return {
                "intent": "search",
                "sub_intent": "new_search",
                "references": {"type": "none"}
            }

        # 6. 기본값: 이미지가 있으면 검색, 없으면 일반 검색으로 처리
        return {
            "intent": "search",
            "sub_intent": "new_search",
            "references": {"type": "none"}
        }

    def _extract_references(self, message: str) -> Dict[str, Any]:
        """참조 표현 추출"""
        import re

        # 인덱스 참조
        index_pattern = r'(\d+)\s*번'
        indices = [int(m) for m in re.findall(index_pattern, message)]
        if indices:
            return {"type": "index", "indices": indices}

        # 시간 참조
        temporal_map = {
            "이거": "current",
            "그거": "last",
            "아까": "previous",
            "처음": "first",
            "방금": "last"
        }
        for keyword, temporal in temporal_map.items():
            if keyword in message:
                return {"type": "temporal", "temporal": temporal}

        return {"type": "none"}

    async def _llm_classify_intent(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """LLM 기반 Intent 분류 (LangChain Function Calling)"""
        try:
            # 기존 LangChainService의 Function Calling 활용
            # parse_refine_query_v2와 유사한 방식

            system_prompt = """당신은 패션 쇼핑 어시스턴트입니다.
사용자의 메시지를 분석하여 의도를 분류하세요.

가능한 의도:
- search: 상품 검색 (new_search, refine, similar, cross_recommend)
- fitting: 가상 피팅 (single_fit, batch_fit, compare_fit)
- commerce: 구매 관련 (add_cart, view_cart, size_recommend, checkout, order_status)
- general: 일반 대화 (greeting, help, feedback)

참조 표현 유형:
- index: 번호 참조 (1번, 2번)
- temporal: 시간 참조 (이거, 아까, 처음)
- attribute: 속성 참조 (빨간 거, 싼 거)
- none: 참조 없음
"""

            # LangChain으로 분류 (실제 구현 시 Function Calling 사용)
            # 여기서는 간소화

            return None  # 키워드 기반 결과 사용

        except Exception as e:
            logger.warning(f"LLM classification error: {e}")
            return None

    async def _route_to_agent(
        self,
        intent_result: Dict[str, Any],
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """서브 에이전트 라우팅"""
        intent = intent_result.get('intent', 'general')
        sub_intent = intent_result.get('sub_intent', '')

        # 복합 의도 처리
        if intent == 'compound':
            return await self._handle_compound(intent_result, message, image, context)

        # 단일 의도 라우팅
        if intent == 'search':
            return await self.search_agent.handle(sub_intent, message, image, context)

        elif intent == 'fitting':
            return await self.fitting_agent.handle(sub_intent, context)

        elif intent == 'commerce':
            return await self.commerce_agent.handle(sub_intent, message, context)

        elif intent == 'general':
            return await self._handle_general(sub_intent, message)

        else:
            return ResponseBuilder.general_response(
                "무엇을 도와드릴까요?"
            )

    async def _handle_compound(
        self,
        intent_result: Dict[str, Any],
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """복합 의도 처리 (예: "찾아서 입어봐")"""
        # TODO: 순차적 처리 구현
        # 일단 첫 번째 의도만 처리
        return await self.search_agent.handle('new_search', message, image, context)

    async def _handle_general(
        self,
        sub_intent: str,
        message: str
    ) -> Dict[str, Any]:
        """일반 대화 처리"""
        if sub_intent == 'greeting':
            return ResponseBuilder.greeting()

        elif sub_intent == 'help':
            return ResponseBuilder.help_message()

        elif sub_intent == 'feedback':
            return ResponseBuilder.general_response(
                "감사해요! 더 도와드릴 일이 있으면 말씀해주세요."
            )

        else:
            return ResponseBuilder.general_response(
                "저는 패션 쇼핑을 도와드리는 AI예요. "
                "상품 검색, 가상 피팅, 장바구니 관리 등을 도와드릴 수 있어요!"
            )

    # ============ Session Management (Redis) ============

    def _load_context(self) -> Dict[str, Any]:
        """Redis에서 세션 컨텍스트 로드"""
        try:
            key = f"agent:session:{self.session_id}"
            data = self.redis.get(key)

            if data:
                try:
                    context = json.loads(data)
                    # 필수 필드 검증 및 기본값 설정
                    context.setdefault('session_id', self.session_id)
                    context.setdefault('user_id', self.user_id)
                    context.setdefault('search_results', [])
                    context.setdefault('has_search_results', False)
                    context.setdefault('has_user_image', False)
                    context.setdefault('cart_item_count', 0)
                    return context
                except json.JSONDecodeError:
                    logger.warning(f"Corrupted session data for {self.session_id}, creating new context")
                    # 손상된 데이터는 삭제
                    self.redis.delete(key)

            # 새 세션 초기화
            return {
                "session_id": self.session_id,
                "user_id": self.user_id,
                "created_at": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "current_analysis_id": None,
                "search_results": [],
                "has_search_results": False,
                "selected_product": None,
                "has_user_image": self._check_user_image(),
                "cart_item_count": self._get_cart_count(),
            }

        except Exception as e:
            logger.warning(f"Failed to load context: {e}")
            return {
                "session_id": self.session_id,
                "user_id": self.user_id,
                "search_results": [],
                "has_search_results": False,
            }

    def _save_context(self, context: Dict[str, Any]):
        """Redis에 세션 컨텍스트 저장"""
        try:
            context['last_activity'] = datetime.now().isoformat()
            key = f"agent:session:{self.session_id}"
            self.redis.setex(key, TTL_SESSION, json.dumps(context, default=str))

        except Exception as e:
            logger.warning(f"Failed to save context: {e}")

    def _save_turn(self, user_message: str, assistant_response: str, context: Dict[str, Any]):
        """대화 턴 저장"""
        try:
            key = f"agent:session:{self.session_id}:turns"

            turn = {
                "user": user_message,
                "assistant": assistant_response,
                "timestamp": datetime.now().isoformat()
            }

            # List에 추가 (최대 20개 유지)
            self.redis.lpush(key, json.dumps(turn))
            self.redis.ltrim(key, 0, 19)
            self.redis.expire(key, TTL_SESSION)

        except Exception as e:
            logger.warning(f"Failed to save turn: {e}")

    def _check_user_image(self) -> bool:
        """사용자 전신 이미지 존재 여부"""
        try:
            from fittings.models import UserImage
            return UserImage.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).exists()
        except Exception:
            return False

    def _get_cart_count(self) -> int:
        """장바구니 아이템 수"""
        try:
            from orders.models import CartItem
            return CartItem.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).count()
        except Exception:
            return 0

    # ============ Polling Support ============

    def check_analysis_status(self, analysis_id: int) -> Dict[str, Any]:
        """분석 상태 확인 및 결과 반환"""
        from analyses.models import ImageAnalysis

        try:
            analysis = ImageAnalysis.objects.get(id=analysis_id)

            if analysis.image_analysis_status == 'DONE':
                # 결과 가져오기
                products = self.search_agent.get_analysis_results(analysis_id)

                if products:
                    context = self._load_context()
                    context['search_results'] = products
                    context['has_search_results'] = True
                    context['current_analysis_id'] = analysis_id
                    context['analysis_pending'] = False
                    self._save_context(context)

                    return ResponseBuilder.search_results(
                        products,
                        "이미지 분석이 완료됐어요! 찾은 상품이에요:"
                    )
                else:
                    return ResponseBuilder.no_results(
                        "이미지에서 상품을 찾지 못했어요. 다른 이미지로 시도해주세요."
                    )

            elif analysis.image_analysis_status == 'FAILED':
                return ResponseBuilder.error(
                    "analysis_failed",
                    "이미지 분석에 실패했어요. 다시 시도해주세요."
                )

            else:
                return ResponseBuilder.analysis_pending(analysis_id)

        except ImageAnalysis.DoesNotExist:
            return ResponseBuilder.error(
                "analysis_not_found",
                "분석 정보를 찾을 수 없어요."
            )

    def check_fitting_status(self, fitting_id: int) -> Dict[str, Any]:
        """피팅 상태 확인 및 결과 반환"""
        return self.fitting_agent.get_fitting_status(fitting_id)
