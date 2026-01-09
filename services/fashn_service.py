"""
fashn.ai API Service for virtual fitting.
Generates virtual try-on images using fashn.ai API.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class FittingResult:
    """Virtual fitting result."""
    id: str
    status: str
    output_url: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'status': self.status,
            'output_url': self.output_url,
            'error': self.error,
        }


class FashnService:
    """fashn.ai API service for virtual fitting."""

    BASE_URL = "https://api.fashn.ai/v1"

    def __init__(self):
        self.api_key = getattr(settings, 'FASHN_API_KEY', '')
        if not self.api_key:
            logger.warning("FASHN_API_KEY not configured")

        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        self.timeout = 30
        self.poll_interval = 2  # seconds
        self.max_poll_attempts = 60  # 2 minutes max

    def create_fitting(
        self,
        model_image_url: str,
        garment_image_url: str,
        category: str = 'tops',
    ) -> FittingResult:
        """
        Create a virtual fitting request.

        Args:
            model_image_url: URL of the model/person image
            garment_image_url: URL of the garment image
            category: Garment category (tops, bottoms, one-pieces)

        Returns:
            FittingResult with job ID
        """
        endpoint = f"{self.BASE_URL}/run"

        payload = {
            'model_image': model_image_url,
            'garment_image': garment_image_url,
            'category': category,
        }

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Created fitting job: {data.get('id')}")

            return FittingResult(
                id=data.get('id', ''),
                status=data.get('status', 'pending'),
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create fitting: {e}")
            return FittingResult(
                id='',
                status='error',
                error=str(e),
            )

    def get_fitting_status(self, job_id: str) -> FittingResult:
        """
        Get the status of a fitting job.

        Args:
            job_id: The fitting job ID

        Returns:
            FittingResult with current status
        """
        endpoint = f"{self.BASE_URL}/status/{job_id}"

        try:
            response = requests.get(
                endpoint,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()

            return FittingResult(
                id=job_id,
                status=data.get('status', 'unknown'),
                output_url=data.get('output'),
                error=data.get('error'),
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get fitting status: {e}")
            return FittingResult(
                id=job_id,
                status='error',
                error=str(e),
            )

    def create_fitting_and_wait(
        self,
        model_image_url: str,
        garment_image_url: str,
        category: str = 'tops',
    ) -> FittingResult:
        """
        Create a fitting and wait for completion.

        Args:
            model_image_url: URL of the model/person image
            garment_image_url: URL of the garment image
            category: Garment category

        Returns:
            FittingResult with output URL when complete
        """
        # Create the fitting job
        result = self.create_fitting(model_image_url, garment_image_url, category)

        if result.status == 'error':
            return result

        # Poll for completion
        for _ in range(self.max_poll_attempts):
            time.sleep(self.poll_interval)

            result = self.get_fitting_status(result.id)

            if result.status == 'completed':
                logger.info(f"Fitting completed: {result.id}")
                return result
            elif result.status == 'error':
                logger.error(f"Fitting failed: {result.error}")
                return result

        # Timeout
        return FittingResult(
            id=result.id,
            status='timeout',
            error='Fitting job timed out',
        )

    def map_category(self, detected_category: str) -> str:
        """
        Map detected category to fashn.ai category.

        Args:
            detected_category: Category from Vision API

        Returns:
            fashn.ai compatible category
        """
        mapping = {
            'top': 'tops',
            'bottom': 'bottoms',
            'dress': 'one-pieces',
            'outerwear': 'tops',  # Treated as tops in fashn.ai
            'skirt': 'bottoms',
        }
        return mapping.get(detected_category, 'tops')


# Singleton instance
_fashn_service: Optional[FashnService] = None


def get_fashn_service() -> FashnService:
    """Get or create FashnService singleton."""
    global _fashn_service
    if _fashn_service is None:
        _fashn_service = FashnService()
    return _fashn_service
