"""
fashn.ai API Service for virtual fitting.
Generates virtual try-on images using fashn.ai API.
"""

import base64
import logging
import mimetypes
import time
from dataclasses import dataclass
from typing import Optional, Union

import requests
from django.conf import settings
from django.db.models.fields.files import FieldFile

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

    def _to_image_data(self, image_source: Union[str, FieldFile]) -> str:
        """
        Convert image source to a format acceptable by fashn.ai API.
        
        Supports:
        - URL string (http/https) - returned as-is
        - Base64 string (data:image/...) - returned as-is
        - File path string - converted to base64
        - Django FieldFile/ImageField - converted to base64
        
        Args:
            image_source: URL, base64 string, file path, or FieldFile
            
        Returns:
            URL or base64 data URI string
        """
        # If it's a FieldFile (ImageField), get the file path
        if isinstance(image_source, FieldFile):
            if not image_source:
                raise ValueError("ImageField is empty")
            image_source = image_source.path
        
        # Convert to string
        image_str = str(image_source)
        
        # Already a URL or base64
        if image_str.startswith(('http://', 'https://', 'data:image/')):
            return image_str
        
        # Local file path - convert to base64
        return self._file_to_base64(image_str)
    
    def _file_to_base64(self, file_path: str) -> str:
        """
        Convert local file to base64 data URI.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Base64 data URI string (data:image/jpeg;base64,...)
        """
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'image/jpeg'
        
        with open(file_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        
        return f"data:{mime_type};base64,{encoded}"

    def create_fitting_with_files(
        self,
        model_image: Union[str, FieldFile],
        garment_image: Union[str, FieldFile],
        category: str = 'tops',
    ) -> 'FittingResult':
        """
        Create a virtual fitting request with file support.
        
        Accepts URLs, file paths, or Django ImageField objects.
        Local files are automatically converted to base64.
        
        Args:
            model_image: URL, file path, or ImageField of the model/person
            garment_image: URL, file path, or ImageField of the garment
            category: Garment category (tops, bottoms, one-pieces)
            
        Returns:
            FittingResult with job ID
        """
        try:
            model_data = self._to_image_data(model_image)
            garment_data = self._to_image_data(garment_image)
        except Exception as e:
            logger.error(f"Failed to prepare image data: {e}")
            return FittingResult(
                id='',
                status='error',
                error=f'Image preparation failed: {e}',
            )
        
        return self.create_fitting(model_data, garment_data, category)

    def create_fitting(
        self,
        model_image_url: str,
        product_image_url: str,
        category: str = 'tops',
    ) -> FittingResult:
        """
        Create a virtual fitting request.

        Args:
            model_image_url: URL of the model/person image
            product_image_url: URL of the garment image
            category: Garment category (tops, bottoms, one-pieces)

        Returns:
            FittingResult with job ID
        """
        endpoint = f"{self.BASE_URL}/run"

        payload = {
            'model_image': model_image_url,
            'garment_image': product_image_url,
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
