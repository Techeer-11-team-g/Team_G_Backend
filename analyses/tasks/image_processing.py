"""
Image Processing - 이미지 처리 유틸리티.

이 모듈은 이미지 변환 및 처리를 담당합니다:
- 이미지 크롭 (bbox 기반)
- bbox 정규화
- 이미지 인코딩/디코딩

Usage:
    from analyses.tasks.image_processing import crop_image, normalize_result_bbox
"""

import io
import logging
from typing import Tuple, Optional

from PIL import Image

from analyses.constants import ImageConfig
from services.vision_service import DetectedItem


logger = logging.getLogger(__name__)


def crop_image(
    image_bytes: bytes,
    item: DetectedItem,
    padding_ratio: float = None,
) -> Tuple[bytes, dict]:
    """
    검출된 객체를 이미지에서 크롭.

    Vision API의 bbox(0-1000 정규화 좌표)를 픽셀 좌표로 변환하고,
    padding을 적용하여 크롭합니다.

    Args:
        image_bytes: 원본 이미지 바이트
        item: 검출된 아이템 (DetectedItem)
        padding_ratio: bbox 확장 비율 (기본값: ImageConfig.BBOX_PADDING_RATIO)

    Returns:
        Tuple[bytes, dict]: (크롭된 이미지 바이트, 픽셀 bbox 정보)
    """
    if padding_ratio is None:
        padding_ratio = ImageConfig.BBOX_PADDING_RATIO

    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size

    # 정규화 좌표(0-1000)를 픽셀 좌표로 변환
    bbox = item.bbox
    x_min = int(bbox.x_min * width / 1000)
    y_min = int(bbox.y_min * height / 1000)
    x_max = int(bbox.x_max * width / 1000)
    y_max = int(bbox.y_max * height / 1000)

    # 원본 pixel bbox 저장
    pixel_bbox = {
        'x_min': x_min,
        'y_min': y_min,
        'x_max': x_max,
        'y_max': y_max,
        'width': x_max - x_min,
        'height': y_max - y_min,
        'image_width': width,
        'image_height': height,
    }

    # 패딩 적용
    bbox_width = x_max - x_min
    bbox_height = y_max - y_min
    pad_x = int(bbox_width * padding_ratio)
    pad_y = int(bbox_height * padding_ratio)

    crop_x_min = max(0, x_min - pad_x)
    crop_y_min = max(0, y_min - pad_y)
    crop_x_max = min(width, x_max + pad_x)
    crop_y_max = min(height, y_max + pad_y)

    # 이미지 크롭
    cropped = image.crop((crop_x_min, crop_y_min, crop_x_max, crop_y_max))

    # RGBA → RGB 변환 (JPEG는 알파 채널 미지원)
    if cropped.mode == 'RGBA':
        cropped = cropped.convert('RGB')

    # JPEG으로 인코딩
    output = io.BytesIO()
    cropped.save(output, format='JPEG', quality=ImageConfig.JPEG_QUALITY)

    return output.getvalue(), pixel_bbox


def normalize_result_bbox(bbox: dict) -> dict:
    """
    결과의 bbox를 0-1 범위로 정규화.

    Args:
        bbox: 픽셀 bbox 정보 (image_width, image_height 포함)

    Returns:
        정규화된 bbox {'x1', 'y1', 'x2', 'y2'}
    """
    img_width = bbox.get('image_width', 1000)
    img_height = bbox.get('image_height', 1000)

    return {
        'x1': bbox.get('x_min', 0) / img_width if img_width > 0 else 0,
        'y1': bbox.get('y_min', 0) / img_height if img_height > 0 else 0,
        'x2': bbox.get('x_max', 0) / img_width if img_width > 0 else 0,
        'y2': bbox.get('y_max', 0) / img_height if img_height > 0 else 0,
    }


def crop_image_from_dict(
    image_bytes: bytes,
    detected_item_dict: dict,
    padding_ratio: float = None,
) -> Tuple[bytes, dict]:
    """
    dict 형태의 검출 정보로 이미지 크롭.

    Celery 태스크에서 직렬화된 데이터를 사용할 때 유용합니다.

    Args:
        image_bytes: 원본 이미지 바이트
        detected_item_dict: 검출 정보 dict
        padding_ratio: bbox 확장 비율

    Returns:
        Tuple[bytes, dict]: (크롭된 이미지 바이트, 픽셀 bbox 정보)
    """
    # DetectedItem 재구성
    detected_item = DetectedItem(
        category=detected_item_dict['category'],
        bbox=type('BBox', (), detected_item_dict['bbox'])(),
        confidence=detected_item_dict['confidence'],
    )

    return crop_image(image_bytes, detected_item, padding_ratio)


def resize_image_if_needed(
    image_bytes: bytes,
    max_width: int = 1024,
    max_height: int = 1024,
) -> bytes:
    """
    이미지가 최대 크기를 초과하면 리사이즈.

    Args:
        image_bytes: 원본 이미지 바이트
        max_width: 최대 너비
        max_height: 최대 높이

    Returns:
        리사이즈된 이미지 바이트 (또는 원본)
    """
    image = Image.open(io.BytesIO(image_bytes))

    if image.width <= max_width and image.height <= max_height:
        return image_bytes

    # 비율 유지하며 리사이즈
    image.thumbnail((max_width, max_height), Image.LANCZOS)

    # RGBA → RGB 변환 (JPEG는 알파 채널 미지원)
    if image.mode == 'RGBA':
        image = image.convert('RGB')

    output = io.BytesIO()
    image.save(output, format='JPEG', quality=ImageConfig.JPEG_QUALITY)

    return output.getvalue()
