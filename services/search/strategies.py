"""
OpenSearch 검색 전략 모듈.

다양한 검색 전략을 제공합니다:
- search_similar_products: 기본 필터 기반 검색
- search_similar_products_hybrid: 벡터 검색 후 카테고리 필터
- search_by_vector: 순수 벡터 유사도 검색
- search_with_attributes: 속성(브랜드/색상) 기반 검색
- search_vector_then_filter: 벡터 먼저 → 필터 적용
- search_brand_vector_color: 브랜드 → 벡터 → 색상 필터
"""

import logging

import numpy as np

from services.metrics import record_api_call
from .client import get_client
from .utils import (
    get_related_categories,
    get_conflicting_colors,
    get_color_keywords,
    get_item_type_config,
    parse_search_result,
    ITEM_TYPE_KEYWORDS,
)

logger = logging.getLogger(__name__)


class SearchStrategies:
    """
    OpenSearch 검색 전략 클래스.

    다양한 검색 전략을 메서드로 제공합니다.
    """

    def __init__(self):
        self.client = get_client()

    def search_similar_products(
        self,
        embedding: list[float],
        k: int = 5,
        category: str = None,
        brand: str = None,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        필터 기반 유사 상품 검색.

        Args:
            embedding: 쿼리 임베딩 벡터
            k: 반환할 결과 수
            category: 카테고리 필터
            brand: 브랜드 필터
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        must_clauses = []

        if category:
            must_clauses.append({'term': {'category': category}})
        if brand:
            must_clauses.append({'term': {'brand': brand}})

        if must_clauses:
            query = {
                'size': k,
                'query': {
                    'bool': {
                        'must': must_clauses,
                        'filter': {
                            'knn': {
                                'image_vector': {
                                    'vector': embedding,
                                    'k': k * 2,
                                }
                            }
                        }
                    }
                }
            }
        else:
            query = {
                'size': k,
                'query': {
                    'knn': {
                        'image_vector': {
                            'vector': embedding,
                            'k': k,
                        }
                    }
                }
            }

        response = self.client.search(index=index_name, body=query)

        results = []
        for hit in response['hits']['hits']:
            results.append({
                'product_id': hit['_source'].get('itemId'),
                'score': hit['_score'],
                'category': hit['_source'].get('category'),
                'brand': hit['_source'].get('brand'),
                'name': hit['_source'].get('productName'),
                'image_url': hit['_source'].get('imageUrl'),
                'price': hit['_source'].get('price'),
                'product_url': hit['_source'].get('productUrl'),
            })

        return results

    def search_similar_products_hybrid(
        self,
        embedding: list[float],
        category: str,
        k: int = 5,
        search_k: int = 100,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        하이브리드 검색: 벡터 유사도 → 카테고리 필터.

        Args:
            embedding: 쿼리 임베딩 벡터
            category: 필터링할 카테고리
            k: 반환할 결과 수
            search_k: 필터링 전 검색할 후보 수
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        query = {
            'size': search_k,
            '_source': [
                'itemId', 'category', 'brand', 'productName', 'imageUrl', 'price', 'productUrl',
                'attributes.colors', 'attributes.pattern', 'attributes.style_vibe',
                'attributes.sleeve_length', 'attributes.pants_length', 'attributes.outer_length',
                'attributes.materials'
            ],
            'query': {
                'knn': {
                    'image_vector': {
                        'vector': embedding,
                        'k': search_k,
                    }
                }
            }
        }

        response = self.client.search(index=index_name, body=query)

        related_categories = get_related_categories(category)

        results = []
        for hit in response['hits']['hits']:
            product_category = hit['_source'].get('category')
            if product_category in related_categories:
                results.append(parse_search_result(hit))
                if len(results) >= k:
                    break

        return results

    def search_by_vector(
        self,
        embedding: list[float],
        k: int = 30,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        순수 벡터 유사도 검색 (필터 없음).

        Args:
            embedding: 쿼리 임베딩 벡터
            k: 반환할 결과 수
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        query = {
            'size': k,
            '_source': [
                'itemId', 'category', 'brand', 'productName', 'imageUrl', 'price', 'productUrl',
                'attributes.colors', 'attributes.pattern', 'attributes.style_vibe',
            ],
            'query': {
                'knn': {
                    'image_vector': {
                        'vector': embedding,
                        'k': k,
                    }
                }
            }
        }

        response = self.client.search(index=index_name, body=query)

        results = []
        for hit in response['hits']['hits']:
            src = hit['_source']
            attributes = src.get('attributes', {})

            results.append({
                'product_id': src.get('itemId'),
                'score': hit['_score'],
                'category': src.get('category'),
                'brand': src.get('brand'),
                'name': src.get('productName'),
                'image_url': src.get('imageUrl'),
                'price': src.get('price'),
                'product_url': src.get('productUrl'),
                'colors': attributes.get('colors', []),
                'pattern': attributes.get('pattern'),
                'style_vibe': attributes.get('style_vibe'),
            })

        return results

    def search_with_attributes(
        self,
        embedding: list[float],
        category: str,
        brand: str = None,
        color: str = None,
        secondary_color: str = None,
        item_type: str = None,
        k: int = 5,
        search_k: int = 100,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        속성 기반 검색: 브랜드/색상 필터 + 벡터 유사도.

        Args:
            embedding: 쿼리 임베딩 벡터
            category: 대상 카테고리
            brand: 브랜드명 (선택)
            color: 주요 색상 (선택)
            secondary_color: 보조 색상 (선택)
            item_type: 아이템 타입 (선택)
            k: 반환할 결과 수
            search_k: 검색할 후보 수
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        related_categories = get_related_categories(category)
        normalized_brand = brand.lower().strip() if brand else None
        normalized_color = color.lower().strip() if color else None
        normalized_secondary = secondary_color.lower().strip() if secondary_color else None

        attribute_results = []
        if normalized_brand or normalized_color or normalized_secondary:
            must_clauses = []

            # 브랜드 조건
            if normalized_brand:
                must_clauses.append({
                    'bool': {
                        'should': [
                            {'wildcard': {'brand': f'*{normalized_brand}*'}},
                            {'match': {'productName': normalized_brand}}
                        ]
                    }
                })

            # 색상 조건
            search_colors = []
            if normalized_color:
                search_colors.append(normalized_color)
            if normalized_secondary and normalized_secondary != normalized_color:
                search_colors.append(normalized_secondary)

            if search_colors:
                color_clause = {
                    'bool': {
                        'should': [{'term': {'attributes.colors': c}} for c in search_colors],
                        'minimum_should_match': 1
                    }
                }
                must_clauses.append(color_clause)

            # 아이템 타입 제외 조건
            normalized_item_type = item_type.lower().strip() if item_type else None
            if normalized_item_type and normalized_item_type in ITEM_TYPE_KEYWORDS:
                exclude_keywords = ITEM_TYPE_KEYWORDS[normalized_item_type].get('exclude', [])
                if exclude_keywords:
                    must_clauses.append({
                        'bool': {
                            'must_not': [{'match_phrase': {'productName': kw}} for kw in exclude_keywords]
                        }
                    })

            # 속성 필터 쿼리
            filter_query = {
                'size': search_k,
                '_source': ['itemId', 'category', 'brand', 'productName', 'imageUrl', 'price', 'productUrl', 'image_vector'],
                'query': {
                    'bool': {
                        'must': must_clauses,
                        'filter': [
                            {'terms': {'category': related_categories}}
                        ]
                    }
                }
            }

            try:
                with record_api_call('opensearch'):
                    attr_response = self.client.search(index=index_name, body=filter_query)

                filter_desc = []
                if normalized_brand:
                    filter_desc.append(f"brand='{brand}'")
                if normalized_color or normalized_secondary:
                    colors = [c for c in [normalized_color, normalized_secondary] if c]
                    filter_desc.append(f"colors={colors}")
                logger.info(f"Attribute filter ({', '.join(filter_desc)}) + category '{category}' returned {len(attr_response['hits']['hits'])} products")

                # 벡터 유사도 계산 후 정렬
                candidates = []
                query_vec = np.array(embedding)
                query_norm = np.linalg.norm(query_vec)

                for hit in attr_response['hits']['hits']:
                    product_vec = hit['_source'].get('image_vector')
                    if product_vec:
                        product_vec = np.array(product_vec)
                        similarity = np.dot(query_vec, product_vec) / (query_norm * np.linalg.norm(product_vec))
                    else:
                        similarity = 0.0

                    candidates.append({
                        'product_id': hit['_source'].get('itemId'),
                        'score': float(similarity),
                        'category': hit['_source'].get('category'),
                        'brand': hit['_source'].get('brand'),
                        'name': hit['_source'].get('productName'),
                        'image_url': hit['_source'].get('imageUrl'),
                        'price': hit['_source'].get('price'),
                        'product_url': hit['_source'].get('productUrl'),
                    })

                attribute_results = sorted(candidates, key=lambda x: x['score'], reverse=True)
                if attribute_results:
                    logger.info(f"Re-ranked by vector similarity, top score: {attribute_results[0]['score']:.4f}")

            except Exception as e:
                logger.warning(f"Attribute + vector query failed: {e}")

        # 벡터 유사도 검색 (브랜드 필터 없이)
        vector_query = {
            'size': search_k,
            'query': {
                'knn': {
                    'image_vector': {
                        'vector': embedding,
                        'k': search_k,
                    }
                }
            }
        }

        with record_api_call('opensearch'):
            vector_response = self.client.search(index=index_name, body=vector_query)

        vector_results = []
        for hit in vector_response['hits']['hits']:
            product_category = hit['_source'].get('category')
            if product_category in related_categories:
                vector_results.append({
                    'product_id': hit['_source'].get('itemId'),
                    'score': hit['_score'],
                    'category': product_category,
                    'brand': hit['_source'].get('brand'),
                    'name': hit['_source'].get('productName'),
                    'image_url': hit['_source'].get('imageUrl'),
                    'price': hit['_source'].get('price'),
                    'product_url': hit['_source'].get('productUrl'),
                })

        # 결과 병합: 속성 매칭 결과 우선
        results = []
        seen_ids = set()

        if attribute_results:
            logger.info(f"Attribute filter matched {len(attribute_results)} products in DB")
            for item in attribute_results:
                if item['product_id'] not in seen_ids:
                    results.append(item)
                    seen_ids.add(item['product_id'])
                    if len(results) >= k:
                        break

        if len(results) < k:
            for item in vector_results:
                if item['product_id'] not in seen_ids:
                    results.append(item)
                    seen_ids.add(item['product_id'])
                    if len(results) >= k:
                        break

        return results

    def search_vector_then_filter(
        self,
        embedding: list[float],
        category: str,
        brand: str = None,
        color: str = None,
        secondary_color: str = None,
        item_type: str = None,
        k: int = 5,
        search_k: int = 400,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        벡터 유사도 먼저 → 브랜드/색상 필터.

        Args:
            embedding: 쿼리 임베딩 벡터
            category: 대상 카테고리
            brand: 브랜드명 (선택)
            color: 주요 색상 (선택)
            secondary_color: 보조 색상 (선택)
            item_type: 아이템 타입 (선택)
            k: 반환할 결과 수
            search_k: 검색할 후보 수
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        related_categories = get_related_categories(category)
        normalized_brand = brand.lower().strip() if brand else None
        normalized_color = color.lower().strip() if color else None
        normalized_secondary = secondary_color.lower().strip() if secondary_color else None
        normalized_item_type = item_type.lower().strip() if item_type else None

        # 검색할 색상 목록
        search_colors = []
        if normalized_color:
            search_colors.append(normalized_color)
        if normalized_secondary and normalized_secondary != normalized_color:
            search_colors.append(normalized_secondary)

        # 아이템 타입 제외 키워드
        exclude_item_types = get_item_type_config(normalized_item_type).get('exclude', [])

        # k-NN 벡터 유사도 검색
        vector_query = {
            'size': search_k,
            '_source': ['itemId', 'category', 'brand', 'productName', 'imageUrl', 'price', 'productUrl', 'attributes.colors'],
            'query': {
                'knn': {
                    'image_vector': {
                        'vector': embedding,
                        'k': search_k,
                    }
                }
            }
        }

        vector_response = self.client.search(index=index_name, body=vector_query)
        logger.info(f"k-NN returned {len(vector_response['hits']['hits'])} candidates")

        # 결과 필터링 및 부스팅
        results = []
        boosted_results = []

        for hit in vector_response['hits']['hits']:
            src = hit['_source']
            product_category = src.get('category')
            product_brand = (src.get('brand') or '').lower()
            product_name = (src.get('productName') or '').lower()
            product_colors = src.get('attributes', {}).get('colors', [])

            # 카테고리 필터
            if product_category not in related_categories:
                continue

            # 아이템 타입 제외
            if exclude_item_types:
                has_exclude = any(exc.lower() in product_name for exc in exclude_item_types)
                if has_exclude:
                    continue

            result_item = {
                'product_id': src.get('itemId'),
                'score': hit['_score'],
                'category': product_category,
                'brand': src.get('brand'),
                'name': src.get('productName'),
                'image_url': src.get('imageUrl'),
                'price': src.get('price'),
                'product_url': src.get('productUrl'),
            }

            # 브랜드/색상 매칭 체크
            brand_match = normalized_brand and (normalized_brand in product_brand or normalized_brand in product_name)
            color_match = search_colors and any(c in product_colors for c in search_colors)

            # 우선순위: 브랜드+색상 > 브랜드만 > 색상만 > 나머지
            if brand_match and color_match:
                result_item['_priority'] = 3
                boosted_results.append(result_item)
            elif brand_match:
                result_item['_priority'] = 2
                boosted_results.append(result_item)
            elif color_match:
                result_item['_priority'] = 1
                boosted_results.append(result_item)
            else:
                result_item['_priority'] = 0
                results.append(result_item)

        # 부스트된 결과 우선순위 정렬
        boosted_results.sort(key=lambda x: (-x['_priority'], -x['score']))
        final_results = boosted_results + results

        # _priority 필드 제거
        for item in final_results:
            item.pop('_priority', None)

        logger.info(f"Vector→Filter: {len(boosted_results)} boosted (brand/color), {len(results)} others")
        return final_results[:k]

    def search_brand_vector_color(
        self,
        embedding: list[float],
        category: str,
        brand: str = None,
        color: str = None,
        item_type: str = None,
        k: int = 5,
        search_k: int = 100,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        브랜드 → 벡터 유사도 → 색상 필터.

        Args:
            embedding: 쿼리 임베딩 벡터
            category: 대상 카테고리
            brand: 브랜드명 (선택)
            color: 색상 (선택)
            item_type: 아이템 타입 (선택)
            k: 반환할 결과 수
            search_k: 검색할 후보 수
            index_name: 검색할 인덱스

        Returns:
            매칭 상품 리스트
        """
        related_categories = get_related_categories(category)
        normalized_brand = brand.lower().strip() if brand else None
        normalized_color = color.lower().strip() if color else None
        normalized_item_type = item_type.lower().strip() if item_type else None

        # Step 1: 브랜드 + 카테고리로 필터
        must_clauses = []

        if normalized_brand:
            must_clauses.append({
                'bool': {
                    'should': [
                        {'wildcard': {'brand': f'*{normalized_brand}*'}},
                        {'match': {'productName': normalized_brand}}
                    ]
                }
            })

        # 아이템 타입 제외
        must_not_clauses = []
        if normalized_item_type and normalized_item_type in ITEM_TYPE_KEYWORDS:
            exclude_keywords = ITEM_TYPE_KEYWORDS[normalized_item_type].get('exclude', [])
            for kw in exclude_keywords:
                must_not_clauses.append({'match_phrase': {'productName': kw}})

        filter_query = {
            'size': search_k,
            '_source': ['itemId', 'category', 'brand', 'productName', 'imageUrl', 'price', 'productUrl', 'image_vector'],
            'query': {
                'bool': {
                    'must': must_clauses if must_clauses else [{'match_all': {}}],
                    'must_not': must_not_clauses,
                    'filter': [
                        {'terms': {'category': related_categories}}
                    ]
                }
            }
        }

        response = self.client.search(index=index_name, body=filter_query)
        logger.info(f"Step 1 - Brand filter (brand={brand}): {len(response['hits']['hits'])} products")

        # Step 2: 벡터 유사도로 정렬
        candidates = []
        query_vec = np.array(embedding)
        query_norm = np.linalg.norm(query_vec)

        for hit in response['hits']['hits']:
            src = hit['_source']
            product_vec = src.get('image_vector')
            if product_vec:
                product_vec = np.array(product_vec)
                similarity = np.dot(query_vec, product_vec) / (query_norm * np.linalg.norm(product_vec))
            else:
                similarity = 0.0

            candidates.append({
                'product_id': src.get('itemId'),
                'score': float(similarity),
                'category': src.get('category'),
                'brand': src.get('brand'),
                'name': src.get('productName'),
                'image_url': src.get('imageUrl'),
                'price': src.get('price'),
                'product_url': src.get('productUrl'),
            })

        # 벡터 유사도 순 정렬
        candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)
        if candidates:
            logger.info(f"Step 2 - Vector sorted, top score: {candidates[0]['score']:.4f}")

        # Step 3: 색상 필터 (후처리)
        if normalized_color:
            color_keywords = get_color_keywords(normalized_color)
            exclude_colors = get_conflicting_colors(normalized_color)

            filtered = []
            for item in candidates:
                product_name = (item.get('name') or '').lower()

                # 색상 매칭 체크
                color_match = any(kw.lower() in product_name for kw in color_keywords)
                if not color_match:
                    continue

                # 충돌 색상 제외
                if exclude_colors:
                    has_conflict = any(exc.lower() in product_name for exc in exclude_colors)
                    if has_conflict:
                        continue

                filtered.append(item)

            logger.info(f"Step 3 - Color filter (color={color}): {len(filtered)} products")
            return filtered[:k]
        else:
            return candidates[:k]
