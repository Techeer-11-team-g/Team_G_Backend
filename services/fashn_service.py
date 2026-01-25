"""
The New Black Virtual Try-On API Service.
Supports virtual try-on for clothes, bags, and shoes.
"""

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Optional, Union

import requests
from django.conf import settings
from django.db.models.fields.files import FieldFile

logger = logging.getLogger(__name__)

# OpenTelemetry tracer (optional)
try:
    from opentelemetry import trace
    tracer = trace.get_tracer("services.fashn_service")
except ImportError:
    tracer = None


def _create_span(name: str):
    """Create a span if tracer is available, otherwise return nullcontext."""
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


@dataclass
class FittingResult:
    """Virtual fitting result."""
    id: str
    status: str
    output_url: Optional[str] = None
    error: Optional[str] = None


class FashnService:
    """The New Black Virtual Try-On API service."""

    BASE_URL = "https://thenewblack.ai/api/1.1/wf"

    ENDPOINTS = {
        'upper_body': 'vto_stream',
        'lower_body': 'vto_stream',
        'dresses': 'vto_stream',
        'top': 'vto_stream',
        'bottom': 'vto_stream',
        'bag': 'vto-bag',
        'shoes': 'vto-shoes',
    }

    PARAM_CONFIG = {
        'vto_stream': {
            'model_param': 'model_photo',
            'item_param': 'clothing_photo',
            'extra': {'ratio': 'auto', 'prompt': 'virtual try on'},
            'has_description': False,
        },
        'vto': {
            'model_param': 'model_photo',
            'item_param': 'clothing_photo',
            'extra': {'ratio': 'auto', 'prompt': 'virtual try on'},
            'has_description': True,
        },
        'vto-bag': {
            'model_param': 'model_photo',
            'item_param': 'bag_photo',
            'extra': {},
            'has_description': True,
        },
        'vto-shoes': {
            'model_param': 'model_photo',
            'item_param': 'shoes_photo',
            'extra': {},
            'has_description': True,
        },
    }

    def __init__(self):
        self.api_key = getattr(settings, 'THENEWBLACK_API_KEY', '')
        if not self.api_key:
            logger.warning("THENEWBLACK_API_KEY not configured")
        # Timeout 분리: (connect_timeout, read_timeout)
        # - connect: 서버 연결까지 최대 10초 (서버 다운 시 빠른 실패 감지)
        # - read: 응답 대기 최대 120초 (이미지 생성에 시간 소요)
        self.timeout = (10, 120)

    def _to_image_url(self, image_source: Union[str, FieldFile]) -> str:
        """Convert image source to URL."""
        if isinstance(image_source, FieldFile):
            if not image_source:
                raise ValueError("ImageField is empty")
            image_source = image_source.url

        image_str = str(image_source)
        if image_str.startswith(('http://', 'https://')):
            return image_str

        raise ValueError(f"Invalid image source: {image_str}. Must be a URL.")

    def _get_endpoint_config(self, category: str) -> tuple:
        """Get endpoint and config for category."""
        endpoint = self.ENDPOINTS.get(category, 'vto')
        config = self.PARAM_CONFIG.get(endpoint, self.PARAM_CONFIG['vto'])
        return endpoint, config

    def create_fitting_with_files(
        self,
        model_image: Union[str, FieldFile],
        garment_image: Union[str, FieldFile],
        category: str = 'top',
        garment_description: str = '',
    ) -> FittingResult:
        """Create a virtual fitting request."""
        try:
            model_url = self._to_image_url(model_image)
            garment_url = self._to_image_url(garment_image)
        except Exception as e:
            logger.error(f"Failed to prepare image data: {e}")
            return FittingResult(id='', status='error', error=f'Image preparation failed: {e}')

        return self.create_fitting(model_url, garment_url, category, garment_description)

    def create_fitting(
        self,
        model_image_url: str,
        product_image_url: str,
        category: str = 'top',
        garment_description: str = '',
    ) -> FittingResult:
        """Create a virtual fitting request (synchronous)."""
        with _create_span("thenewblack_api_call") as span:
            endpoint_name, config = self._get_endpoint_config(category)
            url = f"{self.BASE_URL}/{endpoint_name}?api_key={self.api_key}"

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("thenewblack.endpoint", endpoint_name)
                span.set_attribute("thenewblack.category", category)

            form_data = {
                config['model_param']: (None, model_image_url),
                config['item_param']: (None, product_image_url),
            }

            for key, value in config.get('extra', {}).items():
                form_data[key] = (None, value)

            if config.get('has_description'):
                form_data['description'] = (None, garment_description or 'fashion item')

            try:
                logger.info(f"The New Black request: endpoint={endpoint_name}")

                response = requests.post(url, files=form_data, timeout=self.timeout)
                response.raise_for_status()

                output_url = response.text.strip()
                if output_url.startswith('http'):
                    logger.info(f"The New Black completed: {output_url[:80]}...")
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("thenewblack.status", "completed")
                    return FittingResult(id='tnb-sync', status='completed', output_url=output_url)

                logger.warning(f"The New Black unexpected response: {output_url[:200]}")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("thenewblack.status", "unexpected_response")
                return FittingResult(id='', status='error', error=f'Unexpected response: {output_url[:200]}')

            except requests.exceptions.Timeout:
                logger.error("The New Black request timed out")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("thenewblack.status", "timeout")
                return FittingResult(id='', status='error', error='Request timed out')
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to create fitting: {e}")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("thenewblack.status", "error")
                    span.set_attribute("thenewblack.error", str(e)[:200])
                error_detail = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = e.response.json()
                    except:
                        error_detail = e.response.text
                return FittingResult(id='', status='error', error=str(error_detail))

    def map_category(self, detected_category: str) -> str:
        """Map detected category to The New Black category."""
        if not detected_category:
            return 'top'

        mapping = {
            'top': 'top',
            'bottom': 'bottom',
            'pants': 'bottom',
            'dress': 'dresses',
            'dresses': 'dresses',
            'outer': 'top',
            'outerwear': 'top',
            'skirt': 'bottom',
            'upper_body': 'top',
            'lower_body': 'bottom',
            'bag': 'bag',
            'bags': 'bag',
            'handbag': 'bag',
            'shoes': 'shoes',
            'shoe': 'shoes',
            'sneakers': 'shoes',
            'boots': 'shoes',
            'hat': 'top',
        }
        return mapping.get(detected_category.lower(), 'top')


_fashn_service: Optional[FashnService] = None


def get_fashn_service() -> FashnService:
    """Get or create FashnService singleton."""
    global _fashn_service
    if _fashn_service is None:
        _fashn_service = FashnService()
    return _fashn_service
