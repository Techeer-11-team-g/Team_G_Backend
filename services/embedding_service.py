"""
CLIP Embeddings Service for image vector generation.
Generates embeddings directly from images using CLIP model.
"""

import io
import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class EmbeddingService:
    """CLIP-based image embedding service for vector generation."""

    # CLIP model (outputs 512 dimensions)
    CLIP_MODEL = "openai/clip-vit-base-patch32"
    # Embedding dimensions
    EMBEDDING_DIMENSIONS = 512

    def __init__(self):
        from transformers import CLIPProcessor, CLIPModel

        logger.info(f"Loading CLIP model: {self.CLIP_MODEL}")
        self.model = CLIPModel.from_pretrained(self.CLIP_MODEL)
        self.processor = CLIPProcessor.from_pretrained(self.CLIP_MODEL)
        logger.info("CLIP model loaded successfully")

    def get_image_embedding(self, image_bytes: bytes) -> list[float]:
        """
        Generate embedding directly from image using CLIP.

        Args:
            image_bytes: Raw image bytes

        Returns:
            512-dimensional embedding vector
        """
        import torch

        try:
            # Load image from bytes
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Process image for CLIP
            inputs = self.processor(images=image, return_tensors="pt")

            # Generate embedding
            with torch.no_grad():
                image_features = self.model.get_image_features(**inputs)

            # Normalize the embedding
            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to list
            embedding = image_features.squeeze().tolist()

            logger.info(f"Generated image embedding: {len(embedding)} dimensions")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate image embedding: {e}")
            raise

    def get_text_embedding(self, text: str) -> list[float]:
        """
        Generate embedding from text using CLIP.
        Useful for text-based product search.

        Args:
            text: Text to embed

        Returns:
            512-dimensional embedding vector
        """
        import torch

        try:
            # Process text for CLIP
            inputs = self.processor(text=[text], return_tensors="pt", padding=True)

            # Generate embedding
            with torch.no_grad():
                text_features = self.model.get_text_features(**inputs)

            # Normalize the embedding
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to list
            embedding = text_features.squeeze().tolist()

            logger.info(f"Generated text embedding: {len(embedding)} dimensions")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate text embedding: {e}")
            raise

    def get_batch_image_embeddings(self, image_bytes_list: list[bytes]) -> list[list[float]]:
        """
        Generate embeddings for multiple images.

        Args:
            image_bytes_list: List of raw image bytes

        Returns:
            List of 512-dimensional embedding vectors
        """
        import torch

        try:
            # Load all images
            images = [
                Image.open(io.BytesIO(img_bytes)).convert("RGB")
                for img_bytes in image_bytes_list
            ]

            # Process images for CLIP
            inputs = self.processor(images=images, return_tensors="pt")

            # Generate embeddings
            with torch.no_grad():
                image_features = self.model.get_image_features(**inputs)

            # Normalize embeddings
            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to list of lists
            embeddings = image_features.tolist()

            logger.info(f"Generated {len(embeddings)} image embeddings")
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate batch image embeddings: {e}")
            raise


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
