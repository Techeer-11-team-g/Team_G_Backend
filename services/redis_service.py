"""
Redis Cache Service for analysis status management.
Manages analysis job status with TTL for frontend polling.
"""

import json
import logging
from enum import Enum
from typing import Optional

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


class AnalysisStatus(str, Enum):
    """Analysis job status."""
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    DONE = 'DONE'
    FAILED = 'FAILED'


class RedisService:
    """Redis service for caching and status management."""

    # Key patterns
    ANALYSIS_STATUS_KEY = 'analysis:{analysis_id}:status'
    ANALYSIS_PROGRESS_KEY = 'analysis:{analysis_id}:progress'
    ANALYSIS_DATA_KEY = 'analysis:{analysis_id}:data'

    # TTL 정책 (용도별 구분)
    # - 폴링용 상태: 분석 완료 후 결과 확인까지 충분한 시간 (30분)
    # - 대화 히스토리: 세션 유지용 (2시간)
    # - 재분석 상태: 재분석 완료 후 확인까지 (30분)
    # - 분석 데이터 캐시: 결과 재사용을 위한 장기 캐시 (24시간)
    TTL_POLLING = 30 * 60           # 30분 - 분석/피팅 상태 폴링용
    TTL_CONVERSATION = 2 * 60 * 60  # 2시간 - 대화 히스토리 (연속 재분석 세션)
    TTL_REFINE = 30 * 60            # 30분 - 재분석 상태 폴링용
    TTL_DATA_CACHE = 24 * 60 * 60   # 24시간 - 분석 결과 데이터 캐시

    # 피드/히스토리 캐시용 TTL
    TTL_FEED = 5 * 60               # 5분 - 피드 목록 캐시
    TTL_FEED_STYLES = 24 * 60 * 60  # 24시간 - 스타일 태그 (정적 데이터)
    TTL_USER_HISTORY = 10 * 60      # 10분 - 사용자 히스토리 캐시

    # 피드/히스토리 캐시 키 패턴
    FEED_CACHE_KEY = 'feed:cursor:{cursor}:style:{style}:cat:{category}'
    FEED_STYLES_KEY = 'feed:styles'
    USER_HISTORY_KEY = 'user:{user_id}:history:cursor:{cursor}'

    # 하위 호환성을 위한 기본값 (신규 코드는 용도별 TTL 사용 권장)
    DEFAULT_TTL = TTL_POLLING

    def __init__(self):
        self.client = redis.Redis(
            host=getattr(settings, 'REDIS_HOST', 'localhost'),
            port=int(getattr(settings, 'REDIS_PORT', 6379)),
            password=getattr(settings, 'REDIS_PASSWORD', None),
            db=0,
            decode_responses=True,
        )

    def _get_status_key(self, analysis_id: str) -> str:
        return self.ANALYSIS_STATUS_KEY.format(analysis_id=analysis_id)

    def _get_progress_key(self, analysis_id: str) -> str:
        return self.ANALYSIS_PROGRESS_KEY.format(analysis_id=analysis_id)

    def _get_data_key(self, analysis_id: str) -> str:
        return self.ANALYSIS_DATA_KEY.format(analysis_id=analysis_id)

    # =========================================================================
    # Analysis Status Management
    # =========================================================================

    def set_analysis_status(
        self,
        analysis_id: str,
        status: AnalysisStatus,
        ttl: int = None,
    ) -> bool:
        """
        Set analysis status.

        Args:
            analysis_id: Analysis job ID
            status: Job status
            ttl: TTL in seconds (default 30분)

        Returns:
            Success status
        """
        key = self._get_status_key(analysis_id)
        ttl = ttl or self.TTL_POLLING

        try:
            self.client.setex(key, ttl, status.value)
            logger.info(f"Set analysis {analysis_id} status to {status.value}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to set status: {e}")
            return False

    def get_analysis_status(self, analysis_id: str) -> Optional[str]:
        """
        Get analysis status.

        Args:
            analysis_id: Analysis job ID

        Returns:
            Status string or None if not found
        """
        key = self._get_status_key(analysis_id)
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            logger.error(f"Failed to get status: {e}")
            return None

    def set_analysis_progress(
        self,
        analysis_id: str,
        progress: int,
        ttl: int = None,
    ) -> bool:
        """
        Set analysis progress (0-100).

        Args:
            analysis_id: Analysis job ID
            progress: Progress percentage
            ttl: TTL in seconds

        Returns:
            Success status
        """
        key = self._get_progress_key(analysis_id)
        ttl = ttl or self.TTL_POLLING

        try:
            self.client.setex(key, ttl, str(progress))
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to set progress: {e}")
            return False

    def get_analysis_progress(self, analysis_id: str) -> int:
        """
        Get analysis progress.

        Args:
            analysis_id: Analysis job ID

        Returns:
            Progress percentage (0 if not found)
        """
        key = self._get_progress_key(analysis_id)
        try:
            progress = self.client.get(key)
            return int(progress) if progress else 0
        except (redis.RedisError, ValueError) as e:
            logger.error(f"Failed to get progress: {e}")
            return 0

    def set_analysis_data(
        self,
        analysis_id: str,
        data: dict,
        ttl: int = None,
    ) -> bool:
        """
        Cache analysis result data.

        Args:
            analysis_id: Analysis job ID
            data: Result data to cache
            ttl: TTL in seconds

        Returns:
            Success status
        """
        key = self._get_data_key(analysis_id)
        ttl = ttl or self.TTL_DATA_CACHE  # 24시간 캐시

        try:
            self.client.setex(key, ttl, json.dumps(data))
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to set data: {e}")
            return False

    def get_analysis_data(self, analysis_id: str) -> Optional[dict]:
        """
        Get cached analysis result data.

        Args:
            analysis_id: Analysis job ID

        Returns:
            Cached data or None
        """
        key = self._get_data_key(analysis_id)
        try:
            data = self.client.get(key)
            return json.loads(data) if data else None
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get data: {e}")
            return None

    def update_analysis_running(
        self,
        analysis_id: str,
        progress: int = 0,
    ) -> bool:
        """
        Update analysis to RUNNING status with progress.

        Args:
            analysis_id: Analysis job ID
            progress: Initial progress

        Returns:
            Success status
        """
        success = self.set_analysis_status(analysis_id, AnalysisStatus.RUNNING)
        if success:
            self.set_analysis_progress(analysis_id, progress)
        return success

    def update_analysis_done(
        self,
        analysis_id: str,
        result_data: dict = None,
    ) -> bool:
        """
        Update analysis to DONE status.

        Args:
            analysis_id: Analysis job ID
            result_data: Optional result data to cache

        Returns:
            Success status
        """
        success = self.set_analysis_status(analysis_id, AnalysisStatus.DONE)
        if success:
            self.set_analysis_progress(analysis_id, 100)
            if result_data:
                self.set_analysis_data(analysis_id, result_data)
        return success

    def update_analysis_failed(
        self,
        analysis_id: str,
        error_message: str = None,
    ) -> bool:
        """
        Update analysis to FAILED status.

        Args:
            analysis_id: Analysis job ID
            error_message: Error message

        Returns:
            Success status
        """
        success = self.set_analysis_status(analysis_id, AnalysisStatus.FAILED)
        if success and error_message:
            self.set_analysis_data(analysis_id, {'error': error_message})
        return success

    # =========================================================================
    # General Cache Operations
    # =========================================================================

    def get(self, key: str) -> Optional[str]:
        """Get a value from cache."""
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            logger.error(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: str, ttl: int = None) -> bool:
        """Set a value in cache."""
        try:
            if ttl:
                self.client.setex(key, ttl, value)
            else:
                self.client.set(key, value)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        try:
            self.client.delete(key)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.client.exists(key))
        except redis.RedisError as e:
            logger.error(f"Redis exists error: {e}")
            return False

    def setex(self, key: str, ttl: int, value: str) -> bool:
        """Set a value with expiration."""
        try:
            self.client.setex(key, ttl, value)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis setex error: {e}")
            return False

    def lpush(self, key: str, value: str) -> bool:
        """Push a value to the left of a list."""
        try:
            self.client.lpush(key, value)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis lpush error: {e}")
            return False

    def ltrim(self, key: str, start: int, end: int) -> bool:
        """Trim a list to the specified range."""
        try:
            self.client.ltrim(key, start, end)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis ltrim error: {e}")
            return False

    def lrange(self, key: str, start: int, end: int) -> list:
        """Get a range of elements from a list."""
        try:
            return self.client.lrange(key, start, end)
        except redis.RedisError as e:
            logger.error(f"Redis lrange error: {e}")
            return []

    def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on a key."""
        try:
            self.client.expire(key, ttl)
            return True
        except redis.RedisError as e:
            logger.error(f"Redis expire error: {e}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching the pattern using SCAN (production-safe).
        
        Args:
            pattern: Redis key pattern (e.g., 'feed:cursor:first:*')
            
        Returns:
            Number of keys deleted
        """
        deleted_count = 0
        try:
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    self.client.delete(*keys)
                    deleted_count += len(keys)
                    logger.debug(f"Deleted {len(keys)} keys matching '{pattern}'")
                if cursor == 0:
                    break
            if deleted_count > 0:
                logger.info(f"Total deleted {deleted_count} keys matching '{pattern}'")
            return deleted_count
        except redis.RedisError as e:
            logger.error(f"Redis delete_pattern error: {e}")
            return 0


# Singleton instance
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    """Get or create RedisService singleton."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
