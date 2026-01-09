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
