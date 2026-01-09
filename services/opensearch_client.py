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
                    'dimension': 1536,  # OpenAI text-embedding-3-small
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
        index_name: str = 'products',
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
        index_name: str = 'products',
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
                                'embedding': {
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
                        'embedding': {
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
                'product_id': hit['_source']['product_id'],
                'score': hit['_score'],
                'category': hit['_source'].get('category'),
                'brand': hit['_source'].get('brand'),
            })

        return results
