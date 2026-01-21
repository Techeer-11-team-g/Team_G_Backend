"""
상품명 매칭 유틸리티

검색 결과에서 사용자 메시지를 기반으로 상품을 찾는 공통 로직.
CommerceAgent, FittingAgent 등에서 공유하여 사용.
"""

import logging
import re
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


class ProductMatcher:
    """
    상품명/브랜드명 매칭 유틸리티

    사용법:
        matcher = ProductMatcher()
        product = matcher.find_best_match(message, products)
        products = matcher.find_all_matches(message, products)
    """

    # 공통 불용어 (모든 에이전트에서 사용)
    COMMON_STOPWORDS = {
        # 일반 지시어
        '해줘', '보여줘', '줘', '좀', '것', '거', '이거', '그거', '저거',
        '주세요', '해주세요', '봐줘', '해봐', '볼래', '할래',
        # 대명사/조사
        '이', '그', '저', '을', '를', '의', '가', '은', '는', '에',
    }

    # 커머스 관련 불용어
    COMMERCE_STOPWORDS = {
        '담아', '담아줘', '담기', '담을래', '담아주세요',
        '주문', '구매', '사줘', '살래', '살게', '사고싶어', '살거야',
        '장바구니', '카트', '결제', '계산',
    }

    # 피팅 관련 불용어
    FITTING_STOPWORDS = {
        '피팅', '입어', '입어봐', '착용', '가상피팅', '피팅해', '입혀',
        '비교', '비교해', '비교해봐',
    }

    # 사이즈 관련 불용어 (사이즈는 상품명 매칭에서 제외)
    SIZE_STOPWORDS = {
        'xs', 's', 'm', 'l', 'xl', 'xxl', 'xxxl', 'free',
        '사이즈', '치수', '호', '인치',
    }

    # 브랜드 키워드 (한글-영어 매핑)
    BRAND_ALIASES = {
        '나이키': ['nike', '나이키'],
        '아디다스': ['adidas', '아디다스'],
        '뉴발란스': ['new balance', 'newbalance', '뉴발란스', '뉴발'],
        '컨버스': ['converse', '컨버스'],
        '반스': ['vans', '반스'],
        '푸마': ['puma', '푸마'],
        '휠라': ['fila', '휠라'],
        '자라': ['zara', '자라'],
        '유니클로': ['uniqlo', '유니클로'],
        '무신사': ['musinsa', '무신사', '무신사스탠다드'],
        '커버낫': ['covernat', '커버낫'],
        '디스커버리': ['discovery', '디스커버리'],
        '내셔널지오그래픽': ['national geographic', '내셔널지오그래픽', '내셔널'],
    }

    def __init__(
        self,
        include_commerce_stopwords: bool = True,
        include_fitting_stopwords: bool = True,
        min_word_length: int = 2,
        min_score_threshold: int = 2,
        extra_stopwords: Optional[set] = None
    ):
        """
        Args:
            include_commerce_stopwords: 커머스 관련 불용어 포함 여부
            include_fitting_stopwords: 피팅 관련 불용어 포함 여부
            min_word_length: 검색어로 사용할 최소 단어 길이
            min_score_threshold: 매칭으로 인정할 최소 점수 (기본값 2로 상향)
            extra_stopwords: 추가 불용어 셋
        """
        self.min_word_length = min_word_length
        self.min_score_threshold = min_score_threshold

        # 불용어 통합
        self.stopwords = self.COMMON_STOPWORDS.copy()
        self.stopwords.update(self.SIZE_STOPWORDS)

        if include_commerce_stopwords:
            self.stopwords.update(self.COMMERCE_STOPWORDS)
        if include_fitting_stopwords:
            self.stopwords.update(self.FITTING_STOPWORDS)
        if extra_stopwords:
            self.stopwords.update(extra_stopwords)

    def find_best_match(
        self,
        message: str,
        products: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        메시지에서 가장 잘 매칭되는 단일 상품 반환

        Args:
            message: 사용자 메시지
            products: 검색 결과 상품 리스트

        Returns:
            매칭된 상품 또는 None
        """
        if not products:
            return None

        scored_products = self._score_products(message, products)

        if not scored_products:
            logger.debug(f"No product match found for message: '{message[:50]}...'")
            return None

        # 최고 점수 상품 반환
        best_product, best_score = scored_products[0]

        if best_score >= self.min_score_threshold:
            product_name = best_product.get('product_name') or ''
            logger.info(
                f"Product matched: '{product_name[:30]}' "
                f"(score: {best_score}) for message: '{message[:30]}...'"
            )
            return best_product

        logger.debug(
            f"Best match score ({best_score}) below threshold ({self.min_score_threshold}) "
            f"for message: '{message[:50]}...'"
        )
        return None

    def find_all_matches(
        self,
        message: str,
        products: List[Dict[str, Any]],
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        메시지에서 매칭되는 모든 상품 반환 (배치 피팅용)

        Args:
            message: 사용자 메시지
            products: 검색 결과 상품 리스트
            max_results: 최대 반환 개수

        Returns:
            매칭된 상품 리스트 (점수 순 정렬)
        """
        if not products:
            return []

        scored_products = self._score_products(message, products)

        # 최소 점수 이상인 상품만 반환
        matched = [
            product for product, score in scored_products
            if score >= self.min_score_threshold
        ]

        if matched:
            logger.info(f"Found {len(matched)} matching products for message: '{message[:30]}...'")

        return matched[:max_results]

    def _score_products(
        self,
        message: str,
        products: List[Dict[str, Any]]
    ) -> List[Tuple[Dict[str, Any], int]]:
        """
        각 상품에 대해 매칭 점수 계산

        Returns:
            (상품, 점수) 튜플 리스트 (점수 내림차순 정렬)
        """
        # 검색어 추출
        search_words = self._extract_search_words(message)

        if not search_words:
            return []

        scored = []

        for product in products:
            score = self._calculate_match_score(search_words, product)
            if score > 0:
                scored.append((product, score))

        # 점수 내림차순 정렬
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored

    def _extract_search_words(self, message: str) -> List[str]:
        """
        메시지에서 검색에 사용할 단어 추출

        불용어 제거, 최소 길이 필터링, 정규화 적용
        """
        message_lower = message.lower()

        # 숫자+번 패턴 제거 (인덱스 참조)
        message_lower = re.sub(r'\d+\s*번', '', message_lower)

        # 사이즈 패턴 제거 (XL, 95 등)
        message_lower = re.sub(r'\b(xs|s|m|l|xl|xxl|xxxl|free)\b', '', message_lower, flags=re.IGNORECASE)
        message_lower = re.sub(r'\b\d{2,3}\s*(사이즈|호)?\b', '', message_lower)

        # 단어 분리
        words = message_lower.split()

        # 불용어 제거 및 최소 길이 필터링
        search_words = [
            word for word in words
            if word not in self.stopwords and len(word) >= self.min_word_length
        ]

        return search_words

    def _calculate_match_score(
        self,
        search_words: List[str],
        product: Dict[str, Any]
    ) -> int:
        """
        단일 상품에 대한 매칭 점수 계산

        점수 체계:
        - 상품명 완전 단어 매칭: +3점
        - 상품명 부분 매칭: +2점
        - 브랜드명 매칭: +2점 (한글-영어 변환 지원)
        """
        product_name = (product.get('product_name') or '').lower()
        brand_name = (product.get('brand_name') or '').lower()

        score = 0

        for word in search_words:
            # 브랜드 별칭 확인 (한글-영어 매핑)
            brand_aliases = self._get_brand_aliases(word)

            # 상품명 매칭
            if word in product_name:
                # 완전 단어 매칭 (공백으로 구분된 단어)
                if re.search(rf'\b{re.escape(word)}\b', product_name):
                    score += 3
                else:
                    score += 2

            # 브랜드명 매칭 (별칭 포함)
            if word in brand_name:
                score += 2
            elif brand_aliases:
                for alias in brand_aliases:
                    if alias in brand_name:
                        score += 2
                        break

        return score

    def _get_brand_aliases(self, word: str) -> List[str]:
        """
        브랜드 단어에 대한 별칭 반환 (한글 ↔ 영어)
        """
        for key, aliases in self.BRAND_ALIASES.items():
            if word == key or word in aliases:
                return aliases
        return []


# 편의 함수 (기존 코드와의 호환성)
def find_product_by_name(
    message: str,
    products: List[Dict[str, Any]],
    context: str = 'general'
) -> Optional[Dict[str, Any]]:
    """
    레거시 호환 함수 - ProductMatcher 사용

    Args:
        message: 사용자 메시지
        products: 상품 리스트
        context: 'commerce', 'fitting', 'general' 중 하나
    """
    include_commerce = context in ('commerce', 'general')
    include_fitting = context in ('fitting', 'general')

    matcher = ProductMatcher(
        include_commerce_stopwords=include_commerce,
        include_fitting_stopwords=include_fitting
    )

    return matcher.find_best_match(message, products)


def find_products_by_name(
    message: str,
    products: List[Dict[str, Any]],
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """
    레거시 호환 함수 - 다중 상품 매칭
    """
    matcher = ProductMatcher()
    return matcher.find_all_matches(message, products, max_results)
