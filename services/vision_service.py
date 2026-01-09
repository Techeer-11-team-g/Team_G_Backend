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
    'shoe': 'shoes',
    'shoes': 'shoes',
    'sneaker': 'shoes',
    'boot': 'shoes',
    'sandal': 'shoes',
    'footwear': 'shoes',
    'bag': 'bag',
    'handbag': 'bag',
    'backpack': 'bag',
    'purse': 'bag',
    'top': 'top',
    'shirt': 'top',
    't-shirt': 'top',
    'blouse': 'top',
    'sweater': 'top',
    'hoodie': 'top',
    'pants': 'bottom',
    'jeans': 'bottom',
    'trousers': 'bottom',
    'shorts': 'bottom',
    'jacket': 'outerwear',
    'coat': 'outerwear',
    'outerwear': 'outerwear',
    'blazer': 'outerwear',
    'hat': 'hat',
    'cap': 'hat',
    'beanie': 'hat',
    'skirt': 'skirt',
    'dress': 'dress',
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

        Args:
            image: Vision API Image object

        Returns:
            List of detected fashion items
        """
        detected_items = []

        try:
            # Object localization for bounding boxes
            response = self.client.object_localization(image=image)

            if response.error.message:
                logger.error(f"Vision API error: {response.error.message}")
                raise Exception(response.error.message)

            for obj in response.localized_object_annotations:
                category = self._map_to_fashion_category(obj.name.lower())

                if category and obj.score >= self.min_confidence:
                    # Convert normalized vertices to pixel coordinates
                    vertices = obj.bounding_poly.normalized_vertices
                    bbox = BoundingBox(
                        x_min=int(vertices[0].x * 1000),  # Normalized 0-1 → 0-1000
                        y_min=int(vertices[0].y * 1000),
                        x_max=int(vertices[2].x * 1000),
                        y_max=int(vertices[2].y * 1000),
                    )

                    detected_items.append(DetectedItem(
                        category=category,
                        bbox=bbox,
                        confidence=obj.score,
                    ))

            logger.info(f"Detected {len(detected_items)} fashion items")
            return detected_items

        except Exception as e:
            logger.error(f"Failed to detect objects: {e}")
            raise

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
