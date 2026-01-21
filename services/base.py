"""
서비스 레이어 기본 클래스.

싱글톤 패턴 및 공통 기능을 제공합니다.
기존 서비스들의 중복 코드를 제거하기 위한 베이스 클래스입니다.
"""

import logging
import time
from abc import ABC, abstractmethod
from functools import wraps
from typing import TypeVar, Callable, Any, Optional

T = TypeVar('T')


class SingletonMeta(type):
    """
    싱글톤 메타클래스.

    클래스당 하나의 인스턴스만 생성되도록 보장합니다.
    스레드 안전하지 않으므로 Django 앱 초기화 시점에 인스턴스화하세요.
    """
    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    @classmethod
    def clear_instance(mcs, cls):
        """테스트용: 특정 클래스의 싱글톤 인스턴스 제거."""
        if cls in mcs._instances:
            del mcs._instances[cls]

    @classmethod
    def clear_all(mcs):
        """테스트용: 모든 싱글톤 인스턴스 제거."""
        mcs._instances.clear()


class BaseService(metaclass=SingletonMeta):
    """
    서비스 기본 클래스.

    모든 서비스가 상속받아 사용합니다.
    싱글톤 패턴과 로깅을 자동으로 제공합니다.

    Usage:
        class MyService(BaseService):
            def _initialize(self):
                self.client = SomeClient()
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
        self._initialize()
        self._initialized = True
        self.logger.debug(f"{self.__class__.__name__} initialized")

    def _initialize(self):
        """
        서비스 초기화.

        하위 클래스에서 오버라이드하여 클라이언트 초기화 등을 수행합니다.
        """
        pass

    def _log_call(self, method_name: str, **kwargs):
        """메서드 호출 로깅."""
        self.logger.info(
            f"{method_name} called",
            extra={'service': self.__class__.__name__, **kwargs}
        )


class ExternalAPIService(BaseService):
    """
    외부 API 호출 서비스 기본 클래스.

    재시도 로직과 에러 처리를 포함합니다.

    Usage:
        class VisionService(ExternalAPIService):
            retry_count = 3
            retry_delay = 1.0

            def _initialize(self):
                self.client = vision.ImageAnnotatorClient()
    """

    # 하위 클래스에서 오버라이드 가능
    retry_count: int = 3
    retry_delay: float = 1.0
    retry_exceptions: tuple = (Exception,)

    def _call_with_retry(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        재시도 로직이 포함된 API 호출.

        Args:
            func: 실행할 함수
            *args: 함수 인자
            **kwargs: 함수 키워드 인자

        Returns:
            함수 실행 결과

        Raises:
            마지막 시도에서 발생한 예외
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.retry_count):
            try:
                return func(*args, **kwargs)
            except self.retry_exceptions as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    delay = self.retry_delay * (attempt + 1)
                    self.logger.warning(
                        f"Attempt {attempt + 1}/{self.retry_count} failed: {e}. "
                        f"Retrying in {delay}s...",
                        extra={'service': self.__class__.__name__}
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        f"All {self.retry_count} attempts failed: {e}",
                        extra={'service': self.__class__.__name__}
                    )

        raise last_error


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions: tuple = (Exception,),
    backoff: float = 2.0
):
    """
    재시도 데코레이터.

    Args:
        max_retries: 최대 재시도 횟수
        delay: 초기 대기 시간 (초)
        exceptions: 재시도할 예외 타입들
        backoff: 대기 시간 증가 배율 (지수 백오프)

    Usage:
        @retry(max_retries=3, delay=1.0)
        def call_external_api():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            logger = logging.getLogger(func.__module__)
            last_error: Optional[Exception] = None
            current_delay = delay

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{func.__name__} attempt {attempt + 1}/{max_retries} "
                            f"failed: {e}. Retrying in {current_delay}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} all {max_retries} attempts failed: {e}"
                        )

            raise last_error
        return wrapper
    return decorator
