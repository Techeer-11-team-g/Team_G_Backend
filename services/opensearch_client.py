"""
OpenSearch client configuration.
"""

from opensearchpy import OpenSearch
from django.conf import settings


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
    RELATED_CATEGORIES = {
        'top': ['top', 'outer'],
        'outer': ['outer', 'top'],
        'pants': ['pants', 'dress'],  # 바지 + 치마/원피스
        'bottom': ['pants', 'dress'],  # 하의 = 바지 + 치마/원피스
        'dress': ['dress', 'pants'],  # 치마/원피스 + 바지
        'shoes': ['shoes'],
        'bag': ['bag'],
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
            product_category = hit['_source'].get('category')
            result_item = {
                'product_id': hit['_source'].get('itemId'),
                'score': hit['_score'],
                'category': product_category,
                'brand': hit['_source'].get('brand'),
                'name': hit['_source'].get('productName'),
                'image_url': hit['_source'].get('imageUrl'),
                'price': hit['_source'].get('price'),
                'product_url': hit['_source'].get('productUrl'),
            }

            all_results.append(result_item)

            if product_category in related_categories:
                results.append(result_item)
                if len(results) >= k:
                    break

        # 4. 카테고리 필터 결과가 부족하면 벡터 유사도 높은 순으로 반환
        if len(results) < k:
            for item in all_results:
                if item not in results:
                    results.append(item)
                    if len(results) >= k:
                        break

        return results

