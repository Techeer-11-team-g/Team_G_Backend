"""
OpenAI Embeddings Service for vector generation.
Generates embeddings for images and text using OpenAI API.
"""

import base64
import logging
from io import BytesIO
from typing import Optional

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingService:
    """OpenAI Embeddings service for vector generation."""

    # Default model for text embeddings
    TEXT_EMBEDDING_MODEL = "text-embedding-3-small"
    # Vision model for image understanding
    VISION_MODEL = "gpt-4o-mini"
    # Embedding dimensions
    EMBEDDING_DIMENSIONS = 1536

    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', '')
        if not api_key:
            logger.warning("OPENAI_API_KEY not configured")

        self.client = OpenAI(api_key=api_key)

    def get_text_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        try:
            response = self.client.embeddings.create(
                model=self.TEXT_EMBEDDING_MODEL,
                input=text,
            )
            embedding = response.data[0].embedding
            logger.info(f"Generated text embedding: {len(embedding)} dimensions")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate text embedding: {e}")
            raise

    def get_image_embedding(self, image_bytes: bytes) -> list[float]:
        """
        Generate embedding for image using GPT-4 Vision + text embedding.

        Process:
        1. Use GPT-4 Vision to describe the image in detail
        2. Generate text embedding from the description

        Args:
            image_bytes: Raw image bytes

        Returns:
            Embedding vector
        """
        try:
            # Step 1: Get image description using Vision
            description = self._describe_image(image_bytes)

            # Step 2: Generate embedding from description
            embedding = self.get_text_embedding(description)

            logger.info("Generated image embedding via description")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate image embedding: {e}")
            raise

    def _describe_image(self, image_bytes: bytes) -> str:
        """
        Generate detailed description of image using GPT-4 Vision.

        Args:
            image_bytes: Raw image bytes

        Returns:
            Detailed description of the image
        """
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')

        try:
            response = self.client.chat.completions.create(
                model=self.VISION_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a fashion item descriptor. Describe the fashion item "
                            "in the image with specific details about: color, material, style, "
                            "pattern, brand indicators, and any distinguishing features. "
                            "Be specific and detailed for accurate product matching."
                        )
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Describe this fashion item in detail."
                            }
                        ]
                    }
                ],
                max_tokens=300,
            )

            description = response.choices[0].message.content
            logger.info(f"Image description: {description[:100]}...")
            return description

        except Exception as e:
            logger.error(f"Failed to describe image: {e}")
            raise

    def get_batch_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        try:
            response = self.client.embeddings.create(
                model=self.TEXT_EMBEDDING_MODEL,
                input=texts,
            )

            embeddings = [data.embedding for data in response.data]
            logger.info(f"Generated {len(embeddings)} embeddings")
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
