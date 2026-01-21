"""
Google Vision API Service for object detection.
Detects fashion items (shoes, bags, tops, bottoms, outerwear, hats, skirts) in images.
"""

import io
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from google.cloud import vision
from google.cloud.vision_v1 import types

from services.metrics import record_api_call, DETECTED_OBJECTS_TOTAL

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """Detected object bounding box."""
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min

    def to_dict(self) -> dict:
        return {
            'x_min': self.x_min,
            'y_min': self.y_min,
            'x_max': self.x_max,
            'y_max': self.y_max,
            'width': self.width,
            'height': self.height,
        }


@dataclass
class DetectedItem:
    """Detected fashion item."""
    category: str
    bbox: BoundingBox
    confidence: float

    def to_dict(self) -> dict:
        return {
            'category': self.category,
            'bbox': self.bbox.to_dict(),
            'confidence': self.confidence,
        }


# Fashion category mapping from Vision API labels
FASHION_CATEGORIES = {
    # 1. 신발
    'shoe': 'shoes',
    'shoes': 'shoes',
    'sneaker': 'shoes',
    'boot': 'shoes',
    'sandal': 'shoes',
    'footwear': 'shoes',
    
    # 2. 가방
    'bag': 'bag',
    'handbag': 'bag',
    'backpack': 'bag',
    'purse': 'bag',
    
    # 3. 상의
    'top': 'top',
    'shirt': 'top',
    't-shirt': 'top',
    'blouse': 'top',
    'sweater': 'top',
    'hoodie': 'top',
    
    # 4. 하의
    'pants': 'bottom',
    'jeans': 'bottom',
    'trousers': 'bottom',
    'shorts': 'bottom',
    'skirt': 'bottom',
    
    # 5. 외투
    'jacket': 'outerwear',
    'coat': 'outerwear',
    'outerwear': 'outerwear',
    'blazer': 'outerwear',
    
    # 6. 모자
    'hat': 'hat',
    'cap': 'hat',
    'beanie': 'hat',
}


class VisionService:
    """Google Cloud Vision API service for fashion item detection."""

    def __init__(self):
        self.client = vision.ImageAnnotatorClient()
        self.min_confidence = 0.5

    def detect_objects_from_bytes(self, image_bytes: bytes) -> list[DetectedItem]:
        """
        Detect fashion items from image bytes.

        Args:
            image_bytes: Raw image bytes

        Returns:
            List of detected fashion items with bounding boxes
        """
        image = types.Image(content=image_bytes)
        return self._detect_objects(image)

    def detect_objects_from_uri(self, image_uri: str) -> list[DetectedItem]:
        """
        Detect fashion items from GCS URI.

        Args:
            image_uri: GCS URI (gs://bucket/path/to/image.jpg)

        Returns:
            List of detected fashion items with bounding boxes
        """
        image = types.Image()
        image.source.image_uri = image_uri
        return self._detect_objects(image)

    def _detect_objects(self, image: types.Image) -> list[DetectedItem]:
        """
        Internal method to detect objects using Vision API.
        Returns only the highest confidence item for each category.
        """
        best_items_by_category = {}

        try:
            # Object localization for bounding boxes
            with record_api_call('google_vision'):
                response = self.client.object_localization(image=image)

            if response.error.message:
                logger.error(f"Vision API error: {response.error.message}")
                raise Exception(response.error.message)

            for obj in response.localized_object_annotations:
                category = self._map_to_fashion_category(obj.name.lower())

                if category and obj.score >= self.min_confidence:
                    # Keep only the highest confidence item for each category
                    if category not in best_items_by_category or obj.score > best_items_by_category[category].confidence:
                        vertices = obj.bounding_poly.normalized_vertices
                        bbox = BoundingBox(
                            x_min=int(vertices[0].x * 1000),
                            y_min=int(vertices[0].y * 1000),
                            x_max=int(vertices[2].x * 1000),
                            y_max=int(vertices[2].y * 1000),
                        )

                        best_items_by_category[category] = DetectedItem(
                            category=category,
                            bbox=bbox,
                            confidence=obj.score,
                        )

            result_list = list(best_items_by_category.values())

            # 겹치는 bbox 제거 (IoU > 0.7이면 confidence 높은 것만 유지)
            filtered_list = self._remove_overlapping_items(result_list)
            logger.info(
                "Google Vision 객체 탐지 완료",
                extra={
                    'event': 'vision_api_detect',
                    'service': 'google_vision',
                    'detected_count': len(filtered_list),
                    'categories': [item.category for item in filtered_list],
                }
            )

            # Record detected objects metrics
            for item in filtered_list:
                DETECTED_OBJECTS_TOTAL.labels(category=item.category).inc()

            return filtered_list

        except Exception as e:
            logger.error(f"Failed to detect objects: {e}")
            raise

    def _calculate_iou(self, bbox1: BoundingBox, bbox2: BoundingBox) -> float:
        """Calculate Intersection over Union of two bounding boxes."""
        x_left = max(bbox1.x_min, bbox2.x_min)
        y_top = max(bbox1.y_min, bbox2.y_min)
        x_right = min(bbox1.x_max, bbox2.x_max)
        y_bottom = min(bbox1.y_max, bbox2.y_max)

        if x_right < x_left or y_bottom < y_top:
            return 0.0

        intersection = (x_right - x_left) * (y_bottom - y_top)
        area1 = bbox1.width * bbox1.height
        area2 = bbox2.width * bbox2.height
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def _remove_overlapping_items(self, items: list[DetectedItem], iou_threshold: float = 0.7) -> list[DetectedItem]:
        """
        Remove overlapping items, keeping the one with higher confidence.
        top/outerwear가 같은 영역에서 감지되면 하나만 유지.
        """
        if len(items) <= 1:
            return items

        # confidence 기준 내림차순 정렬
        sorted_items = sorted(items, key=lambda x: x.confidence, reverse=True)
        kept_items = []

        for item in sorted_items:
            is_overlapping = False
            for kept in kept_items:
                iou = self._calculate_iou(item.bbox, kept.bbox)
                if iou > iou_threshold:
                    is_overlapping = True
                    break
            if not is_overlapping:
                kept_items.append(item)

        return kept_items

    def _map_to_fashion_category(self, label: str) -> Optional[str]:
        """
        Map Vision API label to fashion category.

        Args:
            label: Raw label from Vision API

        Returns:
            Fashion category or None if not a fashion item
        """
        label = label.lower().strip()
        return FASHION_CATEGORIES.get(label)

    def detect_with_image_dimensions(
        self,
        image_bytes: bytes,
        width: int,
        height: int
    ) -> list[DetectedItem]:
        """
        Detect objects and convert normalized bbox to actual pixel coordinates.

        Args:
            image_bytes: Raw image bytes
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            List of detected items with pixel coordinates
        """
        items = self.detect_objects_from_bytes(image_bytes)

        for item in items:
            # Convert from normalized (0-1000) to actual pixel coordinates
            item.bbox.x_min = int(item.bbox.x_min * width / 1000)
            item.bbox.y_min = int(item.bbox.y_min * height / 1000)
            item.bbox.x_max = int(item.bbox.x_max * width / 1000)
            item.bbox.y_max = int(item.bbox.y_max * height / 1000)

        return items


# Singleton instance
_vision_service: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """Get or create VisionService singleton."""
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service
