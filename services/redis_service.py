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

    # Default TTL (24 hours)
    DEFAULT_TTL = 24 * 60 * 60

    def __init__(self):
        self.client = redis.Redis(
            host=getattr(settings, 'REDIS_HOST', 'localhost'),
            port=int(getattr(settings, 'REDIS_PORT', 6379)),
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
            ttl: TTL in seconds (default 24h)

        Returns:
            Success status
        """
        key = self._get_status_key(analysis_id)
        ttl = ttl or self.DEFAULT_TTL

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
        ttl = ttl or self.DEFAULT_TTL

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
        ttl = ttl or self.DEFAULT_TTL

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


# Singleton instance
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    """Get or create RedisService singleton."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
