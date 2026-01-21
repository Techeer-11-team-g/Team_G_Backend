"""
AI 패션 어시스턴트 - Intent Classification 스키마
LangChain Function Calling을 위한 스키마 정의
"""

# Intent 분류 스키마
INTENT_CLASSIFICATION_SCHEMA = {
    "name": "classify_intent",
    "description": "사용자 메시지의 의도를 분류하고 필요한 파라미터를 추출합니다",
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["search", "fitting", "commerce", "general", "compound"],
                "description": "주요 의도: search(검색), fitting(피팅), commerce(구매), general(일반), compound(복합)"
            },
            "sub_intent": {
                "type": "string",
                "enum": [
                    # search
                    "new_search", "refine", "similar", "cross_recommend",
                    # fitting
                    "single_fit", "batch_fit", "compare_fit",
                    # commerce
                    "add_cart", "view_cart", "remove_cart", "update_cart",
                    "size_recommend", "checkout", "order_status", "cancel_order",
                    # general
                    "greeting", "help", "feedback", "out_of_scope"
                ],
                "description": "세부 의도"
            },
            "references": {
                "type": "object",
                "description": "참조 표현 해석 결과",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["index", "attribute", "temporal", "state", "none"],
                        "description": "참조 유형"
                    },
                    "indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "인덱스 참조 (1번, 2번 등)"
                    },
                    "attribute": {
                        "type": "string",
                        "description": "속성 참조 (빨간 거, 싼 거 등)"
                    },
                    "temporal": {
                        "type": "string",
                        "enum": ["current", "last", "first", "previous"],
                        "description": "시간 참조 (이거, 아까, 처음 등)"
                    }
                }
            },
            "has_image": {
                "type": "boolean",
                "description": "이미지 첨부 여부"
            },
            "requires_context": {
                "type": "boolean",
                "description": "이전 컨텍스트 필요 여부"
            },
            "search_params": {
                "type": "object",
                "description": "검색 파라미터",
                "properties": {
                    "target_categories": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["top", "bottom", "outer", "shoes", "bag", "hat", "skirt"]
                        },
                        "description": "대상 카테고리"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["research", "filter", "change_style"],
                        "description": "검색 액션"
                    },
                    "color_filter": {
                        "type": "string",
                        "description": "색상 필터"
                    },
                    "pattern_filter": {
                        "type": "string",
                        "enum": ["solid", "stripe", "check", "floral", "dot", "graphic", "animal"],
                        "description": "패턴 필터"
                    },
                    "style_vibe": {
                        "type": "string",
                        "enum": ["casual", "formal", "sporty", "minimal", "street", "vintage", "romantic"],
                        "description": "스타일 필터"
                    },
                    "brand_filter": {
                        "type": "string",
                        "description": "브랜드 필터"
                    },
                    "material_filter": {
                        "type": "string",
                        "enum": ["leather", "denim", "cotton", "linen", "wool", "silk", "synthetic"],
                        "description": "소재 필터"
                    },
                    "fit_filter": {
                        "type": "string",
                        "enum": ["slim", "regular", "oversized", "loose"],
                        "description": "핏 필터"
                    },
                    "sleeve_length": {
                        "type": "string",
                        "enum": ["long_sleeve", "short_sleeve", "sleeveless"],
                        "description": "소매 기장"
                    },
                    "pants_length": {
                        "type": "string",
                        "enum": ["long", "shorts", "cropped"],
                        "description": "바지 기장"
                    },
                    "price_sort": {
                        "type": "string",
                        "enum": ["lowest", "highest"],
                        "description": "가격 정렬"
                    },
                    "search_keywords": {
                        "type": "string",
                        "description": "추가 검색 키워드"
                    }
                }
            },
            "commerce_params": {
                "type": "object",
                "description": "커머스 파라미터",
                "properties": {
                    "size": {
                        "type": "string",
                        "description": "사이즈"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "수량"
                    },
                    "body_info": {
                        "type": "object",
                        "properties": {
                            "height": {"type": "integer"},
                            "weight": {"type": "integer"}
                        }
                    }
                }
            }
        },
        "required": ["intent", "sub_intent"]
    }
}

# 지원 카테고리
SUPPORTED_CATEGORIES = ["top", "bottom", "outer", "shoes", "bag", "hat", "skirt"]

# 지원 색상
SUPPORTED_COLORS = [
    "black", "white", "gray", "navy", "blue", "red", "pink",
    "green", "yellow", "orange", "purple", "brown", "beige", "ivory"
]

# Intent별 트리거 키워드
INTENT_KEYWORDS = {
    "search": ["찾아", "보여", "검색", "추천", "비슷한", "어울리는", "있어?", "없어?"],
    "fitting": ["입어", "피팅", "착용", "어떻게 보여", "비교", "vs"],
    "commerce": ["담아", "장바구니", "사이즈", "주문", "구매", "결제", "배송"],
    "general": ["안녕", "도와", "뭐해", "할 수 있어", "고마워"]
}

# 참조 표현 패턴
REFERENCE_PATTERNS = {
    "index": ["1번", "2번", "3번", "첫번째", "두번째", "세번째", "마지막"],
    "temporal": ["이거", "그거", "아까", "방금", "처음", "전에"],
    "attribute": ["빨간", "파란", "검은", "흰", "싼", "비싼"]
}
