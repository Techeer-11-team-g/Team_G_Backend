"""
Hybrid Reranker Service - 하이브리드 리랭킹 서비스.

Claude Vision 리랭킹 대신 임베딩 기반 로컬 리랭킹으로 속도 개선.
- 코사인 유사도 (visual_similarity)
- OpenSearch 점수 정규화 (normalized_os_score)
- 속성 매칭 보너스 (brand/color)
"""

import logging
from typing import Optional

import numpy as np

from .base import SingletonMeta

logger = logging.getLogger(__name__)


class RerankerConfig:
    """리랭킹 가중치 설정."""
    VISUAL_WEIGHT = 0.50      # 시각적 유사도 (코사인)
    OPENSEARCH_WEIGHT = 0.30  # k-NN 점수
    ATTRIBUTE_WEIGHT = 0.20   # 브랜드/색상 매칭


class HybridReranker(metaclass=SingletonMeta):
    """
    하이브리드 리랭킹 서비스.

    코사인 유사도 + OpenSearch 점수 + 속성 매칭으로
    검색 결과를 재정렬합니다.
    """

    def __init__(
        self,
        visual_weight: float = RerankerConfig.VISUAL_WEIGHT,
        opensearch_weight: float = RerankerConfig.OPENSEARCH_WEIGHT,
        attribute_weight: float = RerankerConfig.ATTRIBUTE_WEIGHT,
    ):
        self.visual_weight = visual_weight
        self.opensearch_weight = opensearch_weight
        self.attribute_weight = attribute_weight

    def rerank(
        self,
        query_embedding: list[float],
        candidates: list[dict],
        attributes: Optional[object] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        검색 결과 리랭킹.

        Args:
            query_embedding: 쿼리 이미지 임베딩 (512차원)
            candidates: OpenSearch 검색 결과 리스트
                각 항목에 'embedding', 'score', 'brand' 필드 필요
            attributes: 추출된 속성 객체 (color, brand 등)
            top_k: 반환할 결과 수

        Returns:
            리랭킹된 결과 리스트 (combined_score 포함)
        """
        if not candidates:
            return []

        if not query_embedding:
            logger.warning("No query embedding provided, returning original order")
            return candidates[:top_k]

        # 쿼리 임베딩 numpy 배열로 변환
        query_vec = np.array(query_embedding)
        query_norm = np.linalg.norm(query_vec)

        if query_norm == 0:
            logger.warning("Query embedding norm is zero, returning original order")
            return candidates[:top_k]

        # OpenSearch 점수 정규화를 위한 min/max 계산
        os_scores = [c.get('score', 0) for c in candidates]
        os_min = min(os_scores) if os_scores else 0
        os_max = max(os_scores) if os_scores else 1
        os_range = os_max - os_min if os_max != os_min else 1

        # 속성 추출
        detected_brand = (attributes.brand or '').lower() if attributes else ''
        detected_color = (attributes.color or '').lower() if attributes else ''
        detected_secondary = (attributes.secondary_color or '').lower() if attributes else ''

        scored_candidates = []

        for candidate in candidates:
            # 1. 코사인 유사도 계산
            product_embedding = candidate.get('embedding')
            if product_embedding:
                product_vec = np.array(product_embedding)
                product_norm = np.linalg.norm(product_vec)
                if product_norm > 0:
                    visual_similarity = float(np.dot(query_vec, product_vec) / (query_norm * product_norm))
                else:
                    visual_similarity = 0.0
            else:
                # 임베딩 없는 경우 기본값
                visual_similarity = 0.5

            # 2. OpenSearch 점수 정규화 (0-1)
            os_score = candidate.get('score', 0)
            normalized_os_score = (os_score - os_min) / os_range

            # 3. 속성 매칭 보너스
            attribute_bonus = self._calculate_attribute_bonus(
                candidate=candidate,
                detected_brand=detected_brand,
                detected_color=detected_color,
                detected_secondary=detected_secondary,
            )

            # 4. 가중 합산
            combined_score = (
                self.visual_weight * visual_similarity +
                self.opensearch_weight * normalized_os_score +
                self.attribute_weight * attribute_bonus
            )

            # 결과에 점수 추가
            scored_candidate = candidate.copy()
            scored_candidate['combined_score'] = combined_score
            scored_candidate['visual_similarity'] = visual_similarity
            scored_candidate['normalized_os_score'] = normalized_os_score
            scored_candidate['attribute_bonus'] = attribute_bonus

            scored_candidates.append(scored_candidate)

        # 5. 점수순 정렬
        scored_candidates.sort(key=lambda x: x['combined_score'], reverse=True)

        logger.info(
            f"Hybrid reranking: {len(candidates)} candidates → top {top_k}, "
            f"top score: {scored_candidates[0]['combined_score']:.4f}" if scored_candidates else ""
        )

        return scored_candidates[:top_k]

    def _calculate_attribute_bonus(
        self,
        candidate: dict,
        detected_brand: str,
        detected_color: str,
        detected_secondary: str,
    ) -> float:
        """
        속성 매칭 보너스 계산.

        Args:
            candidate: 후보 상품
            detected_brand: 검출된 브랜드 (소문자)
            detected_color: 검출된 주요 색상 (소문자)
            detected_secondary: 검출된 보조 색상 (소문자)

        Returns:
            0.0 ~ 1.0 사이의 보너스 점수
        """
        bonus = 0.0

        product_brand = (candidate.get('brand') or '').lower()
        product_name = (candidate.get('name') or '').lower()

        # 브랜드 매칭 (0.5점)
        if detected_brand:
            if detected_brand in product_brand or detected_brand in product_name:
                bonus += 0.5

        # 색상 매칭 (0.5점)
        if detected_color or detected_secondary:
            # 상품명에서 색상 체크
            color_match = False
            if detected_color and detected_color in product_name:
                color_match = True
            if detected_secondary and detected_secondary in product_name:
                color_match = True

            if color_match:
                bonus += 0.5

        return bonus


# Singleton getter
_hybrid_reranker: Optional[HybridReranker] = None


def get_hybrid_reranker() -> HybridReranker:
    """HybridReranker 싱글톤 인스턴스 반환."""
    global _hybrid_reranker
    if _hybrid_reranker is None:
        _hybrid_reranker = HybridReranker()
    return _hybrid_reranker
