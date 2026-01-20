"""
Services module for external API integrations and utilities.
"""

from .opensearch_client import OpenSearchService, get_client
from .langchain_service import LangChainService, get_langchain_service
from .rabbitmq_client import RabbitMQClient, get_rabbitmq_client
from .vision_service import VisionService, get_vision_service
from .fashn_service import FashnService, get_fashn_service
from .embedding_service import EmbeddingService, get_embedding_service
from .redis_service import RedisService, get_redis_service, AnalysisStatus

# Base classes for new services (기존 서비스는 그대로 유지)
from .base import BaseService, ExternalAPIService, SingletonMeta, retry

__all__ = [
    # Base classes (새 서비스 작성 시 사용)
    'BaseService',
    'ExternalAPIService',
    'SingletonMeta',
    'retry',
    # OpenSearch
    'OpenSearchService',
    'get_client',
    # LangChain
    'LangChainService',
    'get_langchain_service',
    # RabbitMQ
    'RabbitMQClient',
    'get_rabbitmq_client',
    # Vision
    'VisionService',
    'get_vision_service',
    # Virtual Try-On (The New Black)
    'FashnService',
    'get_fashn_service',
    # Embeddings
    'EmbeddingService',
    'get_embedding_service',
    # Redis
    'RedisService',
    'get_redis_service',
    'AnalysisStatus',
]
