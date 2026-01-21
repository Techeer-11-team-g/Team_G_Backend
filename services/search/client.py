"""
OpenSearch 클라이언트 기본 클래스.

OpenSearch 연결 및 기본 작업(인덱스 생성, 문서 CRUD, 벡터 검색)을 제공합니다.
"""

from opensearchpy import OpenSearch
from django.conf import settings

from .utils import KNN_INDEX_SETTINGS


def get_opensearch_client() -> OpenSearch:
    """
    OpenSearch 클라이언트 인스턴스 생성.

    Returns:
        OpenSearch: 설정된 OpenSearch 클라이언트
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
    OpenSearch 클라이언트 싱글톤 반환.

    Returns:
        OpenSearch: 싱글톤 OpenSearch 클라이언트
    """
    global _client
    if _client is None:
        _client = get_opensearch_client()
    return _client


class OpenSearchClient:
    """
    OpenSearch 기본 작업 클래스.

    인덱스 생성, 문서 CRUD, 기본 검색 기능을 제공합니다.
    """

    def __init__(self):
        self.client = get_client()

    # =========================================================================
    # Index Operations
    # =========================================================================

    def create_index(self, index_name: str, body: dict = None) -> dict:
        """인덱스 생성."""
        if not self.client.indices.exists(index=index_name):
            return self.client.indices.create(index=index_name, body=body or {})
        return {'acknowledged': True, 'already_exists': True}

    def create_knn_index(self, index_name: str = 'products') -> dict:
        """
        k-NN 활성화된 인덱스 생성.

        Args:
            index_name: 생성할 인덱스명

        Returns:
            인덱스 생성 결과
        """
        if not self.client.indices.exists(index=index_name):
            return self.client.indices.create(
                index=index_name,
                body=KNN_INDEX_SETTINGS,
            )
        return {'acknowledged': True, 'already_exists': True}

    def delete_index(self, index_name: str) -> dict:
        """인덱스 삭제."""
        if self.client.indices.exists(index=index_name):
            return self.client.indices.delete(index=index_name)
        return {'acknowledged': True, 'not_exists': True}

    # =========================================================================
    # Document Operations
    # =========================================================================

    def index_document(self, index_name: str, document: dict, doc_id: str = None) -> dict:
        """문서 인덱싱."""
        return self.client.index(
            index=index_name,
            body=document,
            id=doc_id,
            refresh=True,
        )

    def get_document(self, index_name: str, doc_id: str) -> dict:
        """문서 조회."""
        return self.client.get(index=index_name, id=doc_id)

    def delete_document(self, index_name: str, doc_id: str) -> dict:
        """문서 삭제."""
        return self.client.delete(index=index_name, id=doc_id, refresh=True)

    def bulk_index(self, index_name: str, documents: list, id_field: str = 'id') -> dict:
        """
        대량 문서 인덱싱.

        Args:
            index_name: 대상 인덱스
            documents: 문서 리스트
            id_field: ID로 사용할 필드명

        Returns:
            bulk 작업 결과
        """
        from opensearchpy.helpers import bulk

        actions = []
        for doc in documents:
            action = {
                '_index': index_name,
                '_source': doc,
            }
            if id_field and id_field in doc:
                action['_id'] = doc[id_field]
            actions.append(action)

        return bulk(self.client, actions, refresh=True)

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(self, index_name: str, query: dict) -> dict:
        """기본 검색."""
        return self.client.search(index=index_name, body=query)

    def vector_search(
        self,
        index_name: str,
        vector: list,
        k: int = 10,
        field: str = 'embedding'
    ) -> dict:
        """
        k-NN 벡터 검색.

        Args:
            index_name: 검색할 인덱스
            vector: 쿼리 벡터
            k: 반환할 결과 수
            field: 벡터 필드명

        Returns:
            검색 결과
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

    # =========================================================================
    # Product Indexing
    # =========================================================================

    def index_product(
        self,
        product_id: str,
        embedding: list[float],
        category: str = None,
        brand: str = None,
        index_name: str = 'musinsa_products',
    ) -> dict:
        """
        상품 임베딩 인덱싱.

        Args:
            product_id: MySQL 상품 ID
            embedding: 벡터 임베딩
            category: 상품 카테고리
            brand: 브랜드명
            index_name: 인덱스명

        Returns:
            인덱싱 결과
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
