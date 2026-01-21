"""
OpenSearch client configuration.
"""

from opensearchpy import OpenSearch
from django.conf import settings

from services.metrics import record_api_call


def get_opensearch_client() -> OpenSearch:
    """
    Create and return an OpenSearch client instance.

    Returns:
        OpenSearch: Configured OpenSearch client
    """
    client = OpenSearch(
        hosts=[{
            'host': settings.OPENSEARCH_HOST,
            'port': int(settings.OPENSEARCH_PORT),
        }],
        http_auth=(settings.OPENSEARCH_USER, settings.OPENSEARCH_PASSWORD),
        use_ssl=settings.OPENSEARCH_USE_SSL,
        verify_certs=False,
        ssl_show_warn=False,
    )
    return client


# Singleton instance
_client = None


def get_client() -> OpenSearch:
    """
    Get or create OpenSearch client singleton.

    Returns:
        OpenSearch: Singleton OpenSearch client
    """
    global _client
    if _client is None:
        _client = get_opensearch_client()
    return _client


class OpenSearchService:
    """OpenSearch service for common operations."""

    # Default k-NN settings
    KNN_INDEX_SETTINGS = {
        'settings': {
            'index': {
                'knn': True,
                'knn.algo_param.ef_search': 100,
            },
            'number_of_shards': 1,
            'number_of_replicas': 0,
        },
        'mappings': {
            'properties': {
                'product_id': {'type': 'keyword'},
                'embedding': {
                    'type': 'knn_vector',
                    'dimension': 512,  # CLIP clip-vit-base-patch32
                    'method': {
                        'name': 'hnsw',
                        'space_type': 'cosinesimil',
                        'engine': 'nmslib',
                        'parameters': {
                            'ef_construction': 128,
                            'm': 16,
                        }
                    }
                },
                'category': {'type': 'keyword'},
                'brand': {'type': 'keyword'},
                'created_at': {'type': 'date'},
            }
        }
    }

    def __init__(self):
        self.client = get_client()

    def create_index(self, index_name: str, body: dict = None) -> dict:
        """Create an index."""
        if not self.client.indices.exists(index=index_name):
            return self.client.indices.create(index=index_name, body=body or {})
        return {'acknowledged': True, 'already_exists': True}

    def index_document(self, index_name: str, document: dict, doc_id: str = None) -> dict:
        """Index a document."""
        return self.client.index(
            index=index_name,
            body=document,
            id=doc_id,
            refresh=True,
        )

    def search(self, index_name: str, query: dict) -> dict:
        """Search documents."""
        return self.client.search(index=index_name, body=query)

    def delete_document(self, index_name: str, doc_id: str) -> dict:
        """Delete a document."""
        return self.client.delete(index=index_name, id=doc_id, refresh=True)

    def create_knn_index(self, index_name: str = 'products') -> dict:
        """
        Create a k-NN enabled index for product embeddings.

        Args:
            index_name: Name of the index to create

        Returns:
            Index creation result
        """
        if not self.client.indices.exists(index=index_name):
            return self.client.indices.create(
                index=index_name,
                body=self.KNN_INDEX_SETTINGS,
            )
        return {'acknowledged': True, 'already_exists': True}

    def index_product(
        self,
        product_id: str,
        embedding: list[float],
        category: str = None,
        brand: str = None,
        index_name: str = 'musinsa_products',
    ) -> dict:
        """
        Index a product with its embedding.

        Args:
            product_id: Product ID from MySQL
            embedding: Vector embedding
            category: Product category
            brand: Product brand
            index_name: Index name

        Returns:
            Index result
        """
        document = {
            'product_id': product_id,
            'embedding': embedding,
            'category': category,
            'brand': brand,
            'created_at': None,  # Will use current timestamp
        }
        return self.client.index(
            index=index_name,
            body=document,
            id=product_id,
            refresh=True,
        )

    def vector_search(self, index_name: str, vector: list, k: int = 10, field: str = 'embedding') -> dict:
        """
        Perform k-NN vector search.

        Args:
            index_name: Index to search
            vector: Query vector
            k: Number of results
            field: Vector field name

        Returns:
            Search results
        """
        query = {
            'size': k,
            'query': {
                'knn': {
                    field: {
                        'vector': vector,
                        'k': k,
                    }
                }
            }
        }
        return self.client.search(index=index_name, body=query)

    def search_similar_products(
        self,
        embedding: list[float],
        k: int = 5,
        category: str = None,
        brand: str = None,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        Search for similar products with optional filters.

        Args:
            embedding: Query embedding vector
            k: Number of results to return
            category: Filter by category
            brand: Filter by brand
            index_name: Index to search

        Returns:
            List of matching products with scores
        """
        # Build query with optional filters
        must_clauses = []

        if category:
            must_clauses.append({'term': {'category': category}})
        if brand:
            must_clauses.append({'term': {'brand': brand}})

        if must_clauses:
            # Combined k-NN + filter query
            query = {
                'size': k,
                'query': {
                    'bool': {
                        'must': must_clauses,
                        'filter': {
                            'knn': {
                                'image_vector': {
                                    'vector': embedding,
                                    'k': k * 2,  # Get more candidates before filtering
                                }
                            }
                        }
                    }
                }
            }
        else:
            # Pure k-NN query
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

    # Related categories that can be matched together
    # 정확도를 위해 각 카테고리는 자기 자신만 매칭
    RELATED_CATEGORIES = {
        'top': ['top'],
        'outer': ['outer'],
        'pants': ['pants'],
        'bottom': ['pants'],  # bottom은 pants로 매핑
        'dress': ['dress'],
        'skirt': ['dress'],  # skirt는 dress로 매핑
        'shoes': ['shoes'],
        'bag': ['bag'],
        'hat': ['hat'],
    }

    def search_similar_products_hybrid(
        self,
        embedding: list[float],
        category: str,
        k: int = 5,
        search_k: int = 100,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        하이브리드 검색: 순수 벡터 유사도로 넓게 검색 후 카테고리 필터링.

        벡터 유사도가 높으면서 + 같은/관련 카테고리인 상품을 찾음.

        Args:
            embedding: Query embedding vector
            category: Target category to filter
            k: Number of results to return
            search_k: Number of candidates to search before filtering (default 100)
            index_name: Index to search

        Returns:
            List of matching products with scores
        """
        # 1. 카테고리 필터 없이 넓게 검색 (순수 벡터 유사도)
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

        # 2. 관련 카테고리 목록 가져오기
        related_categories = self.RELATED_CATEGORIES.get(category, [category])

        # 3. 결과에서 같은/관련 카테고리만 필터링
        results = []
        all_results = []  # 카테고리 무관 전체 결과 (fallback용)

        for hit in response['hits']['hits']:
            src = hit['_source']
            product_category = src.get('category')
            attributes = src.get('attributes', {})

            result_item = {
                'product_id': src.get('itemId'),
                'score': hit['_score'],
                'category': product_category,
                'brand': src.get('brand'),
                'name': src.get('productName'),
                'image_url': src.get('imageUrl'),
                'price': src.get('price'),
                'product_url': src.get('productUrl'),
                # 속성 필드 추가
                'colors': attributes.get('colors', []),
                'pattern': attributes.get('pattern'),
                'style_vibe': attributes.get('style_vibe'),
                'sleeve_length': attributes.get('sleeve_length'),
                'pants_length': attributes.get('pants_length'),
                'outer_length': attributes.get('outer_length'),
                'materials': attributes.get('materials', []),
            }

            all_results.append(result_item)

            if product_category in related_categories:
                results.append(result_item)
                if len(results) >= k:
                    break

        # 4. 카테고리 필터 결과만 반환 (관련없는 상품으로 채우지 않음)
        # 정확도 > 결과 수
        return results

    def search_by_vector(
        self,
        embedding: list[float],
        k: int = 30,
        index_name: str = 'musinsa_products',
    ) -> list[dict]:
        """
        순수 벡터 유사도 검색 (카테고리 필터 없음).

        카테고리를 모를 때 사용합니다.

        Args:
            embedding: Query embedding vector
            k: Number of results to return
            index_name: Index to search

        Returns:
            List of matching products with scores
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

    # 충돌 색상 매핑 (black 검색 시 white 제외 등)
    CONFLICTING_COLORS = {
        'black': ['화이트', 'white', '흰'],
        'white': ['블랙', 'black', '검정'],
        'navy': ['화이트', 'white'],
        'navy blue': ['화이트', 'white'],
        'blue': ['레드', 'red', '핑크', 'pink'],
        'red': ['블루', 'blue', '그린', 'green'],
    }

    def _get_conflicting_colors(self, color: str) -> list:
        """Get colors to exclude when searching for a specific color."""
        if not color:
            return []
        return self.CONFLICTING_COLORS.get(color.lower(), [])

    # 색상 키워드 매핑 (GPT-4V 출력 → 한글/영문 검색어)
    COLOR_KEYWORDS = {
        'black': ['블랙', 'black', '검정', '검은'],
        'white': ['화이트', 'white', '흰', '백색', '아이보리', 'ivory'],
        'navy': ['네이비', 'navy', '남색'],
        'navy blue': ['네이비', 'navy', '남색', '인디고', 'indigo', '블루', 'blue', '로얄', 'royal'],
        'blue': ['블루', 'blue', '파랑', '파란'],
        'red': ['레드', 'red', '빨강', '빨간'],
        'green': ['그린', 'green', '녹색', '초록'],
        'yellow': ['옐로우', 'yellow', '노랑', '노란'],
        'pink': ['핑크', 'pink', '분홍'],
        'orange': ['오렌지', 'orange', '주황'],
        'purple': ['퍼플', 'purple', '보라'],
        'brown': ['브라운', 'brown', '갈색'],
        'gray': ['그레이', 'gray', 'grey', '회색'],
        'grey': ['그레이', 'gray', 'grey', '회색'],
        'beige': ['베이지', 'beige', '크림', 'cream'],
        'khaki': ['카키', 'khaki', '올리브', 'olive'],
        'dark brown': ['다크브라운', 'dark brown', '진갈색', '브라운'],
        'light blue': ['라이트블루', 'light blue', '스카이', 'sky', '연청'],
    }

    # 아이템 타입별 검색 키워드 및 제외 키워드
    ITEM_TYPE_KEYWORDS = {
        'sneakers': {
            'include': ['스니커즈', 'sneaker', '운동화'],
            'exclude': ['슬리퍼', '슬라이드', 'slide', '샌들', 'sandal', '로퍼', 'loafer',
                       '아딜렛', 'adilette', '뮬', 'mule', '클로그', 'clog', '슈퍼노바',
                       '아디폼', 'adiform', '아디케인', 'adikane']
        },
        'shoes': {  # Haiku가 반환하는 일반적인 값 - sneakers와 동일하게 처리
            'include': ['스니커즈', 'sneaker', '운동화'],
            'exclude': ['슬리퍼', '슬라이드', 'slide', '샌들', 'sandal', '로퍼', 'loafer',
                       '아딜렛', 'adilette', '뮬', 'mule', '클로그', 'clog', '슈퍼노바',
                       '아디폼', 'adiform', '아디케인', 'adikane']
        },
        'slides': {
            'include': ['슬라이드', 'slide', '슬리퍼'],
            'exclude': ['스니커즈', 'sneaker', '운동화', '부츠']
        },
        'boots': {
            'include': ['부츠', 'boots', '워커'],
            'exclude': ['스니커즈', '슬리퍼', '샌들']
        },
        'loafers': {
            'include': ['로퍼', 'loafer'],
            'exclude': ['스니커즈', '슬리퍼', '부츠']
        },
        'track jacket': {
            'include': ['트랙', 'track', '져지', 'jersey'],
            'exclude': ['셔츠', '티셔츠']
        },
        'jacket': {  # Haiku가 반환하는 일반적인 값
            'include': ['자켓', 'jacket', '트랙', 'track'],
            'exclude': ['셔츠', '티셔츠', '팬츠', 'pants']
        },
        'hoodie': {
            'include': ['후드', 'hoodie', '후디'],
            'exclude': ['셔츠', '자켓']
        },
    }

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

        GPT-4V로 추출한 브랜드/색상으로 OpenSearch에서 직접 필터링.

        Args:
            embedding: Query embedding vector
            category: Target category
            brand: Brand name detected by GPT-4V (optional)
            color: Primary color detected by GPT-4V (optional)
            secondary_color: Secondary color detected by GPT-4V (optional)
            k: Number of results to return
            search_k: Number of candidates to search
            index_name: Index to search

        Returns:
            List of matching products with scores
        """
        import logging
        logger = logging.getLogger(__name__)

        related_categories = self.RELATED_CATEGORIES.get(category, [category])
        normalized_brand = brand.lower().strip() if brand else None
        normalized_color = color.lower().strip() if color else None
        normalized_secondary = secondary_color.lower().strip() if secondary_color else None

        # 브랜드/색상 필터링 + 벡터 유사도 정렬
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

            # 색상 조건 (attributes.colors 필드에서 검색)
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

            # 아이템 타입 조건 (예: sneakers면 슬리퍼 제외)
            normalized_item_type = item_type.lower().strip() if item_type else None
            if normalized_item_type and normalized_item_type in self.ITEM_TYPE_KEYWORDS:
                type_config = self.ITEM_TYPE_KEYWORDS[normalized_item_type]

                # 포함 키워드 (선택적)
                # include_keywords = type_config.get('include', [])
                # if include_keywords:
                #     include_should = [{'match_phrase': {'productName': kw}} for kw in include_keywords]
                #     must_clauses.append({'bool': {'should': include_should, 'minimum_should_match': 1}})

                # 제외 키워드
                exclude_keywords = type_config.get('exclude', [])
                if exclude_keywords:
                    must_clauses.append({
                        'bool': {
                            'must_not': [{'match_phrase': {'productName': kw}} for kw in exclude_keywords]
                        }
                    })

            # 방법 1: 브랜드/색상 필터된 상품들 가져오기
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
                import numpy as np

                with record_api_call('opensearch'):
                    attr_response = self.client.search(index=index_name, body=filter_query)
                filter_desc = []
                if normalized_brand:
                    filter_desc.append(f"brand='{brand}'")
                if normalized_color or normalized_secondary:
                    colors = [c for c in [normalized_color, normalized_secondary] if c]
                    filter_desc.append(f"colors={colors}")
                logger.info(f"Attribute filter ({', '.join(filter_desc)}) + category '{category}' returned {len(attr_response['hits']['hits'])} products")

                # 방법 2: Python에서 벡터 유사도 계산 후 정렬
                candidates = []
                query_vec = np.array(embedding)
                query_norm = np.linalg.norm(query_vec)

                for hit in attr_response['hits']['hits']:
                    product_vec = hit['_source'].get('image_vector')
                    if product_vec:
                        # Cosine similarity 계산
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

                # 벡터 유사도 순으로 정렬
                attribute_results = sorted(candidates, key=lambda x: x['score'], reverse=True)
                logger.info(f"Re-ranked by vector similarity, top score: {attribute_results[0]['score']:.4f}" if attribute_results else "No results")

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

        # 1. 속성(브랜드/색상) 매칭 결과 추가
        if attribute_results:
            logger.info(f"Attribute filter matched {len(attribute_results)} products in DB")
            for item in attribute_results:
                if item['product_id'] not in seen_ids:
                    results.append(item)
                    seen_ids.add(item['product_id'])
                    if len(results) >= k:
                        break

        # 2. 벡터 유사도 결과로 보충
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

        1. k-NN으로 상위 search_k개 가져오기
        2. 브랜드/색상/아이템타입으로 부스팅 및 필터링
        3. 상위 k개 반환
        """
        import logging
        logger = logging.getLogger(__name__)

        related_categories = self.RELATED_CATEGORIES.get(category, [category])
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
        exclude_item_types = []
        if normalized_item_type and normalized_item_type in self.ITEM_TYPE_KEYWORDS:
            exclude_item_types = self.ITEM_TYPE_KEYWORDS[normalized_item_type].get('exclude', [])

        # 1. k-NN 벡터 유사도 검색
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

        # 2. 결과 필터링 및 부스팅
        results = []
        boosted_results = []  # 브랜드/색상 매칭 결과

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

        # 3. 부스트된 결과 우선순위 정렬 + 나머지 결과
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

        1. 브랜드 + 카테고리로 필터 (많은 후보 확보)
        2. 벡터 유사도로 정렬
        3. 색상으로 후처리 필터
        """
        import logging
        import numpy as np
        logger = logging.getLogger(__name__)

        related_categories = self.RELATED_CATEGORIES.get(category, [category])
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

        # 아이템 타입 제외 (예: sneakers면 슬라이드 제외)
        must_not_clauses = []
        if normalized_item_type and normalized_item_type in self.ITEM_TYPE_KEYWORDS:
            exclude_keywords = self.ITEM_TYPE_KEYWORDS[normalized_item_type].get('exclude', [])
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
        logger.info(f"Step 2 - Vector sorted, top score: {candidates[0]['score']:.4f}" if candidates else "No candidates")

        # Step 3: 색상 필터 (후처리)
        if normalized_color:
            color_keywords = self.COLOR_KEYWORDS.get(normalized_color, [normalized_color])
            exclude_colors = self._get_conflicting_colors(normalized_color)

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
                # k개까지 모두 수집 (pagination 지원을 위해 early break 제거)

            logger.info(f"Step 3 - Color filter (color={color}): {len(filtered)} products")
            return filtered[:k]  # 최종적으로 k개만 반환
        else:
            return candidates[:k]

