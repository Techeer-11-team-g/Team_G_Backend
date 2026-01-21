"""
AI 패션 어시스턴트 - 응답 생성기
일관된 응답 포맷을 생성합니다
"""

from typing import List, Dict, Any, Optional


class ResponseBuilder:
    """에이전트 응답 포맷 생성"""

    @staticmethod
    def search_results(
        products: List[Dict],
        message: Optional[str] = None,
        understood_intent: Optional[str] = None
    ) -> Dict[str, Any]:
        """검색 결과 응답"""
        if not products:
            return ResponseBuilder.no_results()

        text_lines = [message or "찾은 상품이에요:"]
        for i, p in enumerate(products[:5], 1):
            brand = p.get('brand_name', '') or ''
            name = p.get('product_name', '') or ''
            price = p.get('selling_price', 0) or 0
            display_name = f"{brand} {name}".strip() or f"상품 {i}"
            text_lines.append(
                f"\n{i}. {display_name} - ₩{price:,}"
            )

        text_lines.append("\n\n피팅해서 확인해볼까요?")

        # 상품 데이터 구성 (bbox 있으면 이미지 분석 결과)
        formatted_products = []
        for i, p in enumerate(products[:5], 1):
            product_data = {
                "index": i,
                "product_id": p.get('product_id') or p.get('id'),
                "brand_name": p.get('brand_name', ''),
                "product_name": p.get('product_name', ''),
                "selling_price": p.get('selling_price', 0),
                "image_url": p.get('product_image_url') or p.get('image_url', ''),
                "product_url": p.get('product_url', ''),
                "sizes": p.get('sizes', [])
            }
            # 이미지 분석 결과일 때만 bbox 포함
            if p.get('bbox'):
                product_data['bbox'] = p.get('bbox')
                product_data['detected_object_id'] = p.get('detected_object_id')
            formatted_products.append(product_data)

        return {
            "text": "".join(text_lines),
            "type": "search_results",
            "data": {
                "products": formatted_products,
                "total_count": len(products),
                "understood_intent": understood_intent
            },
            "suggestions": [
                {"label": "피팅해볼까요?", "action": "fitting"},
                {"label": "장바구니에 담기", "action": "add_cart"},
                {"label": "다른 조건으로", "action": "refine"}
            ]
        }

    @staticmethod
    def no_results(suggestion: Optional[str] = None) -> Dict[str, Any]:
        """검색 결과 없음"""
        return {
            "text": suggestion or "조건에 맞는 상품을 찾지 못했어요. 다른 조건으로 찾아볼까요?",
            "type": "no_results",
            "data": {},
            "suggestions": [
                {"label": "조건 완화", "action": "refine"},
                {"label": "다른 카테고리", "action": "search"}
            ]
        }

    @staticmethod
    def fitting_pending(fitting_id: int, product: Dict) -> Dict[str, Any]:
        """피팅 대기 중"""
        return {
            "text": f"{product.get('product_name', '상품')} 피팅 중이에요... 잠시만 기다려주세요!",
            "type": "fitting_pending",
            "data": {
                "fitting_id": fitting_id,
                "product": product,
                "status_url": f"/api/v1/fitting-images/{fitting_id}/status"
            },
            "suggestions": []
        }

    @staticmethod
    def fitting_result(
        fitting_url: str,
        product: Dict,
        color_match_score: Optional[int] = None
    ) -> Dict[str, Any]:
        """피팅 결과"""
        text = f"{product.get('product_name', '상품')} 피팅 결과예요!"
        if color_match_score:
            text += f"\n컬러 매칭 점수: {color_match_score}/100"

        return {
            "text": text,
            "type": "fitting_result",
            "data": {
                "fitting_image_url": fitting_url,
                "product": product,
                "color_match_score": color_match_score
            },
            "suggestions": [
                {"label": "장바구니에 담기", "action": "add_cart"},
                {"label": "다른 상품 피팅", "action": "fitting"},
                {"label": "주문하기", "action": "checkout"}
            ]
        }

    @staticmethod
    def batch_fitting_pending(fitting_ids: List[int], count: int) -> Dict[str, Any]:
        """배치 피팅 대기 중"""
        return {
            "text": f"{count}개 상품 피팅 중이에요... 완료되면 알려드릴게요!",
            "type": "batch_fitting_pending",
            "data": {
                "fitting_ids": fitting_ids,
                "count": count
            },
            "suggestions": []
        }

    @staticmethod
    def cart_added(product: Dict, size: str, quantity: int) -> Dict[str, Any]:
        """장바구니 추가 완료"""
        return {
            "text": f"장바구니에 담았어요!\n\n"
                    f"- {product.get('brand_name', '')} {product.get('product_name', '')}\n"
                    f"- 사이즈: {size}\n"
                    f"- 수량: {quantity}개\n"
                    f"- 가격: ₩{product.get('selling_price', 0):,}",
            "type": "cart_added",
            "data": {
                "product": product,
                "size": size,
                "quantity": quantity
            },
            "suggestions": [
                {"label": "장바구니 보기", "action": "view_cart"},
                {"label": "주문하기", "action": "checkout"},
                {"label": "더 쇼핑하기", "action": "search"}
            ]
        }

    @staticmethod
    def cart_list(items: List[Dict], total_price: int) -> Dict[str, Any]:
        """장바구니 목록"""
        if not items:
            return {
                "text": "장바구니가 비어있어요. 상품을 찾아볼까요?",
                "type": "cart_empty",
                "data": {},
                "suggestions": [{"label": "상품 검색", "action": "search"}]
            }

        text_lines = ["장바구니 목록이에요:\n"]
        for i, item in enumerate(items, 1):
            product = item.get('product', {})
            text_lines.append(
                f"\n{i}. {product.get('brand_name', '')} {product.get('product_name', '')} "
                f"({item.get('size', 'FREE')}) × {item.get('quantity', 1)} - "
                f"₩{product.get('selling_price', 0) * item.get('quantity', 1):,}"
            )

        text_lines.append(f"\n\n합계: ₩{total_price:,}")

        return {
            "text": "".join(text_lines),
            "type": "cart_list",
            "data": {
                "items": items,
                "total_price": total_price,
                "item_count": len(items)
            },
            "suggestions": [
                {"label": "주문하기", "action": "checkout"},
                {"label": "더 쇼핑하기", "action": "search"}
            ]
        }

    @staticmethod
    def order_created(order_id: int, total_price: int, items_count: int) -> Dict[str, Any]:
        """주문 생성 완료"""
        return {
            "text": f"주문이 완료되었어요!\n\n"
                    f"- 주문번호: #{order_id}\n"
                    f"- 상품 수: {items_count}개\n"
                    f"- 결제 금액: ₩{total_price:,}\n\n"
                    f"결제 페이지로 이동합니다.",
            "type": "order_created",
            "data": {
                "order_id": order_id,
                "total_price": total_price,
                "items_count": items_count
            },
            "suggestions": [
                {"label": "주문 내역 보기", "action": "order_status"}
            ]
        }

    @staticmethod
    def size_recommendation(
        recommended_size: str,
        available_sizes: List[str],
        confidence: Optional[int] = None,
        product: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """사이즈 추천"""
        text = f"{recommended_size} 사이즈를 추천드려요!"
        if confidence:
            text += f" (신뢰도: {confidence}%)"

        if available_sizes:
            text += f"\n\n사용 가능한 사이즈: {', '.join(available_sizes)}"

        return {
            "text": text,
            "type": "size_recommendation",
            "data": {
                "recommended_size": recommended_size,
                "available_sizes": available_sizes,
                "confidence": confidence,
                "product": product
            },
            "suggestions": [
                {"label": f"{recommended_size}로 담기", "action": "add_cart"},
                {"label": "다른 사이즈", "action": "size_recommend"}
            ]
        }

    @staticmethod
    def ask_selection(message: str, options: List[Dict]) -> Dict[str, Any]:
        """선택 요청"""
        text_lines = [message]
        for i, opt in enumerate(options[:5], 1):
            text_lines.append(
                f"\n{i}. {opt.get('brand_name', '')} {opt.get('product_name', '')}"
            )

        return {
            "text": "".join(text_lines),
            "type": "ask_selection",
            "data": {
                "options": options[:5]
            },
            "suggestions": [
                {"label": f"{i}번", "action": f"select_{i}"}
                for i in range(1, min(len(options) + 1, 6))
            ]
        }

    @staticmethod
    def ask_size(message: str, sizes: List[str]) -> Dict[str, Any]:
        """사이즈 선택 요청"""
        return {
            "text": f"{message}\n사이즈: {', '.join(sizes)}",
            "type": "ask_size",
            "data": {
                "available_sizes": sizes
            },
            "suggestions": [
                {"label": size, "action": f"size_{size}"}
                for size in sizes[:5]
            ]
        }

    @staticmethod
    def invalid_size(requested_size: str, available_sizes: List[str]) -> Dict[str, Any]:
        """존재하지 않는 사이즈 요청 시 응답"""
        return {
            "text": f"'{requested_size}' 사이즈는 해당 상품에 없어요.\n"
                    f"선택 가능한 사이즈: {', '.join(available_sizes)}",
            "type": "ask_size",
            "data": {
                "available_sizes": available_sizes,
                "requested_size": requested_size
            },
            "suggestions": [
                {"label": size, "action": f"size_{size}"}
                for size in available_sizes[:5]
            ]
        }

    @staticmethod
    def ask_body_info() -> Dict[str, Any]:
        """신체 정보 요청"""
        return {
            "text": "사이즈 추천을 위해 키와 몸무게를 알려주시겠어요?\n"
                    "(예: 175cm 70kg)",
            "type": "ask_body_info",
            "data": {},
            "suggestions": []
        }

    @staticmethod
    def ask_user_image() -> Dict[str, Any]:
        """전신 이미지 요청"""
        return {
            "text": "피팅을 위해 전신 사진이 필요해요. 사진을 등록해주시겠어요?",
            "type": "ask_user_image",
            "data": {},
            "suggestions": [
                {"label": "전신 사진 등록", "action": "upload_user_image"}
            ]
        }

    @staticmethod
    def ask_search_first() -> Dict[str, Any]:
        """검색 먼저 요청"""
        return {
            "text": "먼저 상품을 찾아볼까요? 어떤 옷을 찾으시나요?",
            "type": "ask_search_first",
            "data": {},
            "suggestions": [
                {"label": "상의 검색", "action": "search_top"},
                {"label": "하의 검색", "action": "search_bottom"},
                {"label": "아우터 검색", "action": "search_outer"}
            ]
        }

    @staticmethod
    def general_response(text: str) -> Dict[str, Any]:
        """일반 응답"""
        return {
            "text": text,
            "type": "general",
            "data": {},
            "suggestions": [
                {"label": "상품 검색", "action": "search"},
                {"label": "장바구니 보기", "action": "view_cart"}
            ]
        }

    @staticmethod
    def greeting() -> Dict[str, Any]:
        """인사 응답"""
        return {
            "text": "안녕하세요!\n"
                    "이미지를 보내주시면 비슷한 상품을 찾아드려요.\n"
                    "텍스트로 원하시는 상품을 말씀해주셔도 돼요!\n\n"
                    "무엇을 도와드릴까요?",
            "type": "greeting",
            "data": {},
            "suggestions": [
                {"label": "상품 검색", "action": "search"},
                {"label": "사용법 안내", "action": "help"}
            ]
        }

    @staticmethod
    def help_message() -> Dict[str, Any]:
        """도움말"""
        return {
            "text": "이렇게 사용할 수 있어요:\n\n"
                    "🔍 검색\n"
                    "- 이미지를 보내면 비슷한 상품을 찾아요\n"
                    "- \"검은색 자켓 찾아줘\"처럼 말해도 돼요\n\n"
                    "👔 피팅\n"
                    "- \"입어볼래\", \"1번 피팅해줘\"\n\n"
                    "🛒 구매\n"
                    "- \"담아줘\", \"장바구니 보여줘\"\n"
                    "- \"사이즈 뭐가 좋아?\"\n\n"
                    "무엇을 도와드릴까요?",
            "type": "help",
            "data": {},
            "suggestions": [
                {"label": "상품 검색", "action": "search"},
                {"label": "장바구니", "action": "view_cart"}
            ]
        }

    @staticmethod
    def error(
        error_type: str,
        message: str,
        suggestions: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """오류 응답"""
        return {
            "text": message,
            "type": "error",
            "data": {
                "error_type": error_type
            },
            "suggestions": suggestions or [
                {"label": "다시 시도", "action": "retry"}
            ]
        }

    @staticmethod
    def analysis_pending(analysis_id: int) -> Dict[str, Any]:
        """분석 대기 중"""
        return {
            "text": "이미지를 분석 중이에요... 잠시만 기다려주세요!",
            "type": "analysis_pending",
            "data": {
                "analysis_id": analysis_id,
                "status_url": f"/api/v1/analyses/{analysis_id}/status"
            },
            "suggestions": []
        }

    @staticmethod
    def ask_search_for_fitting() -> Dict[str, Any]:
        """피팅을 위한 상품 검색 확인"""
        return {
            "text": "가상피팅을 하기 위해선 상품 정보가 필요해요. 이미지에서 상품을 먼저 찾아볼까요?",
            "type": "ask_confirm",
            "data": {
                "confirm_type": "search_for_fitting"
            },
            "suggestions": [
                {"label": "응, 찾아줘", "action": "confirm_search"},
                {"label": "아니, 괜찮아", "action": "cancel"}
            ]
        }

    @staticmethod
    def ask_which_product_to_fit(products: List[Dict]) -> Dict[str, Any]:
        """피팅할 상품 선택 요청"""
        text_lines = ["어떤 상품을 가상피팅 해볼까요?\n"]
        for i, p in enumerate(products[:5], 1):
            brand = p.get('brand_name', '') or ''
            name = p.get('product_name', '') or ''
            display_name = f"{brand} {name}".strip() or f"상품 {i}"
            text_lines.append(f"\n{i}. {display_name}")

        text_lines.append("\n\n\"다 해줘\" 또는 \"1번 해줘\"처럼 말씀해주세요!")

        formatted_products = []
        for i, p in enumerate(products[:5], 1):
            formatted_products.append({
                "index": i,
                "product_id": p.get('product_id') or p.get('id'),
                "brand_name": p.get('brand_name', ''),
                "product_name": p.get('product_name', ''),
                "image_url": p.get('product_image_url') or p.get('image_url', ''),
            })

        return {
            "text": "".join(text_lines),
            "type": "ask_product_for_fitting",
            "data": {
                "products": formatted_products
            },
            "suggestions": [
                {"label": "다 해줘", "action": "batch_fit"},
                {"label": "1번 해줘", "action": "fit_1"},
                {"label": "2번 해줘", "action": "fit_2"}
            ]
        }

    @staticmethod
    def analysis_pending_for_fitting(analysis_id: int) -> Dict[str, Any]:
        """피팅을 위한 이미지 분석 대기 중"""
        return {
            "text": "이미지를 분석 중이에요... 완료되면 피팅할 상품을 선택할 수 있어요!",
            "type": "analysis_pending_for_fitting",
            "data": {
                "analysis_id": analysis_id,
                "status_url": f"/api/v1/analyses/{analysis_id}/status",
                "next_action": "select_product_for_fitting"
            },
            "suggestions": []
        }
