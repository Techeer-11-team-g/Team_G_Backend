"""
AI 패션 어시스턴트 - 메인 오케스트레이터
사용자 의도 파악 및 서브 에이전트 조율
"""

import json
import logging
import re
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from services import get_langchain_service, get_redis_service
from agents.schemas import INTENT_CLASSIFICATION_SCHEMA, SUPPORTED_CATEGORIES
from agents.response_builder import ResponseBuilder
from agents.sub_agents import SearchAgent, FittingAgent, CommerceAgent
from config.tracing import traced, get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

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

    @traced("orchestrator.process_message", attributes={"user_id": "user_id"})
    def process_message(
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
            intent_result = self._classify_intent(message, image, context)
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
            response = self._route_to_agent(intent_result, message, image, context)

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

    @traced("orchestrator.classify_intent")
    def _classify_intent(
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

        # 이미지 + 피팅 요청: 특별 처리 (상품 검색 후 피팅 플로우)
        if has_image and message:
            message_lower = message.lower()
            fitting_keywords = ["피팅", "입어", "착용", "가상피팅", "피팅해", "입혀"]
            if any(kw in message_lower for kw in fitting_keywords):
                return {
                    "intent": "fitting",
                    "sub_intent": "fitting_with_image",
                    "has_image": True,
                    "requires_context": False,
                    "references": {"type": "none"}
                }

        # 간단한 키워드 기반 분류 (기본)
        # 실제로는 LangChain Function Calling 사용
        intent_result = self._keyword_based_classification(message, has_image, context)

        # pending_action 처리 중이면 LLM 덮어쓰기 방지
        if intent_result.get('continue_pending'):
            intent_result['has_image'] = has_image
            return intent_result

        # LLM 기반 정교한 분류 시도
        try:
            llm_result = self._llm_classify_intent(message, context)
            if llm_result:
                intent_result.update(llm_result)
        except Exception as e:
            logger.warning(f"LLM classification fallback: {e}")
            # 키워드 기반 결과 사용

        intent_result['has_image'] = has_image
        return intent_result

    def _extract_category(self, message: str) -> Optional[str]:
        """메시지에서 카테고리 추출"""
        message_lower = message.lower()

        # 카테고리 키워드 매핑
        category_keywords = {
            'shoes': ['신발', '구두', '운동화', '스니커즈', '부츠', '로퍼', '샌들', '슬리퍼', '하이힐', '플랫슈즈', '캔버스화'],
            'top': ['상의', '티셔츠', '셔츠', '블라우스', '니트', '맨투맨', '후드', '반팔', '긴팔', '탑'],
            'bottom': ['하의', '바지', '팬츠', '청바지', '데님', '슬랙스', '조거', '반바지', '숏팬츠'],
            'outer': ['아우터', '자켓', '재킷', '코트', '점퍼', '패딩', '가디건', '집업', '야상', '트렌치'],
            'bag': ['가방', '백', '토트백', '크로스백', '숄더백', '백팩', '클러치', '에코백'],
            'hat': ['모자', '캡', '비니', '버킷햇', '베레모'],
            'skirt': ['치마', '스커트', '미니스커트', '롱스커트', '플리츠'],
            'dress': ['원피스', '드레스'],
        }

        for category, keywords in category_keywords.items():
            if any(kw in message_lower for kw in keywords):
                return category

        return None

    def _keyword_based_classification(
        self,
        message: str,
        has_image: bool,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """키워드 기반 Intent 분류 (폴백)"""
        message_lower = message.lower()

        # 0. 대기 중인 액션 확인 (ask_size 이후 사이즈 선택 등)
        pending = context.get('pending_action')
        if pending:
            pending_type = pending.get('type')

            # ask_size 후 사이즈 선택 대기 중
            size_patterns = [
                r'(?<![A-Za-z])(XS|S|M|L|XL|XXL|XXXL|FREE)(?![A-Za-z])',
                r'(\d{2,3})(?:\s*사이즈|\s*$|[^0-9])',  # 95, 100 등 + 사이즈 or 끝 or 비숫자
            ]
            has_size = any(
                re.search(pattern, message, re.IGNORECASE)
                for pattern in size_patterns
            )

            if pending_type == 'select_size_for_cart':
                if has_size or "사이즈" in message_lower:
                    return {
                        "intent": "commerce",
                        "sub_intent": "add_cart",
                        "references": {"type": "none"},
                        "continue_pending": True
                    }

            elif pending_type == 'select_size_for_direct_purchase':
                if has_size or "사이즈" in message_lower:
                    return {
                        "intent": "commerce",
                        "sub_intent": "direct_purchase",
                        "references": {"type": "none"},
                        "continue_pending": True
                    }

            # 피팅을 위한 상품 검색 확인 대기 중
            elif pending_type == 'confirm_search_for_fitting':
                confirm_keywords = ["응", "ㅇㅇ", "해줘", "찾아", "그래", "좋아", "네", "예"]
                cancel_keywords = ["아니", "괜찮", "취소", "안해", "싫어"]
                if any(kw in message_lower for kw in confirm_keywords):
                    return {
                        "intent": "fitting",
                        "sub_intent": "confirm_search_for_fitting",
                        "references": {"type": "none"},
                        "continue_pending": True
                    }
                elif any(kw in message_lower for kw in cancel_keywords):
                    return {
                        "intent": "fitting",
                        "sub_intent": "cancel_fitting",
                        "references": {"type": "none"},
                        "continue_pending": True
                    }

            # 피팅할 상품 선택 대기 중
            elif pending_type == 'select_product_for_fitting':
                # "다 해줘", "전부" -> batch_fit
                if "다 " in message_lower or "전부" in message_lower or "모든" in message_lower or "다해" in message_lower:
                    return {
                        "intent": "fitting",
                        "sub_intent": "batch_fit",
                        "references": {"type": "none"},
                        "continue_pending": True
                    }
                # "N번 해줘" -> single_fit
                refs = self._extract_references(message)
                if refs.get('type') == 'index' and refs.get('indices'):
                    return {
                        "intent": "fitting",
                        "sub_intent": "single_fit",
                        "references": refs,
                        "continue_pending": True
                    }

        # 카테고리 추출
        extracted_category = self._extract_category(message)

        # 1. 커머스 관련 (가장 구체적인 키워드, 먼저 체크)
        commerce_keywords = {
            "add_cart": ["담아", "장바구니에 담", "카트에", "장바구니로", "번 장바구니", "담을래", "담기", "카트로"],
            "view_cart": ["장바구니 보", "장바구니 확인", "뭐 담았", "담은 거", "장바구니에 뭐", "장바구니 열", "카트 보"],
            "remove_cart": ["빼", "삭제", "제거", "비워", "장바구니에서"],
            "size_recommend": ["사이즈", "치수", "몇 사이즈"],
            "checkout": ["주문", "구매", "결제", "살래", "살게", "계산"],
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

        # 4. 다시 검색 (이전 검색을 반복)
        if context.get('has_search_results') and context.get('last_search_query'):
            retry_keywords = ["다시 검색", "다시 찾아", "한번 더", "다시 보여", "재검색"]
            if any(kw in message_lower for kw in retry_keywords):
                return {
                    "intent": "search",
                    "sub_intent": "retry_search",
                    "references": {"type": "none"}
                }

        # 5. Refine 확인 (이전 검색 결과가 있는 경우)
        if context.get('has_search_results'):
            # 5-1. 이미지 분석 결과에서 필터 변경 ("신발만", "코트만 보여줘" 등)
            last_search_type = context.get('last_search_type')
            if last_search_type == 'image':
                # "~만" 패턴으로 필터 변경 의도 감지
                filter_only_patterns = ["만 보여", "만 찾아", "만 볼래", "만 보고"]
                if any(kw in message_lower for kw in filter_only_patterns):
                    return {
                        "intent": "search",
                        "sub_intent": "refine",
                        "search_params": {
                            "target_categories": [extracted_category] if extracted_category else []
                        },
                        "references": {"type": "none"}
                    }

            # 5-2. 기존 refine 키워드 (텍스트 검색용)
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
                    "search_params": {
                        "target_categories": [extracted_category] if extracted_category else []
                    },
                    "references": {"type": "none"}
                }
            return {
                "intent": "search",
                "sub_intent": "new_search",
                "search_params": {
                    "target_categories": [extracted_category] if extracted_category else []
                },
                "references": {"type": "none"}
            }

        # 6. 기본값: 이미지가 있으면 검색, 없으면 일반 검색으로 처리
        return {
            "intent": "search",
            "sub_intent": "new_search",
            "search_params": {
                "target_categories": [extracted_category] if extracted_category else []
            },
            "references": {"type": "none"}
        }

    def _extract_references(self, message: str) -> Dict[str, Any]:
        """참조 표현 추출"""
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

    def _llm_classify_intent(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """LLM 기반 Intent 분류 (LangChain Function Calling)"""
        try:
            # LangChainService의 classify_intent 사용
            llm_result = self.langchain.classify_intent(
                message=message,
                context={
                    'has_search_results': context.get('has_search_results', False),
                    'has_user_image': context.get('has_user_image', False),
                    'cart_item_count': context.get('cart_item_count', 0),
                }
            )

            if llm_result:
                logger.info(
                    f"LLM classified: {llm_result.get('intent')}/{llm_result.get('sub_intent')} "
                    f"(confidence: {llm_result.get('confidence', 0):.2f})"
                )
                return llm_result

            return None

        except Exception as e:
            logger.warning(f"LLM classification error: {e}")
            return None

    @traced("orchestrator.route_to_agent")
    def _route_to_agent(
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
            return self._handle_compound(intent_result, message, image, context)

        # 단일 의도 라우팅
        if intent == 'search':
            return self.search_agent.handle(sub_intent, message, image, context)

        elif intent == 'fitting':
            return self.fitting_agent.handle(sub_intent, context, image)

        elif intent == 'commerce':
            return self.commerce_agent.handle(sub_intent, message, context)

        elif intent == 'general':
            return self._handle_general(sub_intent, message)

        else:
            return ResponseBuilder.general_response(
                "무엇을 도와드릴까요?"
            )

    def _handle_compound(
        self,
        intent_result: Dict[str, Any],
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """복합 의도 처리 (예: "찾아서 입어봐")"""
        # TODO: 순차적 처리 구현
        # 일단 첫 번째 의도만 처리
        return self.search_agent.handle('new_search', message, image, context)

    def _handle_general(
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
                # 컨텍스트에서 카테고리/아이템타입 필터 확인
                context = self._load_context()
                category_filter = context.get('analysis_category_filter')
                item_type_filter = context.get('analysis_item_type_filter')
                is_fitting_flow = context.get('fitting_flow', False)

                # 결과 가져오기 (카테고리/아이템타입 필터 적용)
                products = self.search_agent.get_analysis_results(
                    analysis_id,
                    category_filter=category_filter,
                    item_type_filter=item_type_filter
                )

                if products:
                    context['search_results'] = products
                    context['has_search_results'] = True
                    context['current_analysis_id'] = analysis_id
                    context['analysis_pending'] = False
                    context['last_search_type'] = 'image'  # 이미지 검색 타입 저장
                    # 보여준 상품 ID 저장 (재검색 시 제외용)
                    shown_ids = [p.get('product_id') for p in products if p.get('product_id')]
                    context['shown_product_ids'] = shown_ids

                    # 피팅 플로우인 경우: 피팅할 상품 선택 요청
                    if is_fitting_flow:
                        context['pending_action'] = {
                            'type': 'select_product_for_fitting',
                            'analysis_id': analysis_id
                        }
                        context['fitting_flow'] = False  # 플로우 리셋
                        self._save_context(context)
                        return ResponseBuilder.ask_which_product_to_fit(products)

                    self._save_context(context)

                    # 필터 적용 여부에 따른 메시지
                    filter_name = item_type_filter or category_filter
                    if filter_name:
                        message = f"이미지에서 {filter_name} 관련 상품을 찾았어요:"
                    else:
                        message = "이미지 분석이 완료됐어요! 찾은 상품이에요:"

                    return ResponseBuilder.search_results(products, message)
                else:
                    # 피팅 플로우인 경우 리셋
                    if is_fitting_flow:
                        context['fitting_flow'] = False
                        context['pending_action'] = None
                        self._save_context(context)

                    # 필터 적용했는데 결과 없으면 다른 메시지
                    filter_name = item_type_filter or category_filter
                    if filter_name:
                        return ResponseBuilder.no_results(
                            f"이미지에서 {filter_name} 상품을 찾지 못했어요. 다른 조건으로 시도해보세요."
                        )
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
