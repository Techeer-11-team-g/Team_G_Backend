"""
FashionCLIP Embeddings Service for image vector generation.
Generates embeddings directly from images using FashionCLIP model.
Uses float64 on Apple Silicon to avoid numerical precision issues.
"""

import io
import logging
import platform
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class EmbeddingService:
    """FashionCLIP-based image embedding service for vector generation."""

    # FashionCLIP model (outputs 512 dimensions)
    CLIP_MODEL = "patrickjohncyh/fashion-clip"
    # Embedding dimensions
    EMBEDDING_DIMENSIONS = 512

    def __init__(self):
        import torch
        from transformers import CLIPProcessor, CLIPModel

        logger.info(f"Loading FashionCLIP model: {self.CLIP_MODEL}")
        self.model = CLIPModel.from_pretrained(self.CLIP_MODEL)
        self.processor = CLIPProcessor.from_pretrained(self.CLIP_MODEL)

        # Check if running on Apple Silicon (M1/M2/M3)
        self.use_float64 = (
            platform.system() == "Darwin" and
            platform.processor() == "arm"
        )

        if self.use_float64:
            logger.info("Apple Silicon detected - using float64 for numerical stability")
            self.model = self.model.double()

        logger.info("FashionCLIP model loaded successfully")

    def get_image_embedding(self, image_bytes: bytes) -> list[float]:
        """
        Generate embedding directly from image using FashionCLIP.

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

            # Convert to float64 if on Apple Silicon
            if self.use_float64:
                inputs["pixel_values"] = inputs["pixel_values"].double()

            # Generate embedding
            with torch.no_grad():
                image_features = self.model.get_image_features(**inputs)

            # Normalize the embedding
            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to float32 list for compatibility
            embedding = image_features.squeeze().float().tolist()

            logger.info(f"Generated image embedding: {len(embedding)} dimensions")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate image embedding: {e}")
            raise

    def get_text_embedding(self, text: str) -> list[float]:
        """
        Generate embedding from text using FashionCLIP.
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

            # For Apple Silicon, text encoding needs special handling
            # Use float32 model temporarily for text (avoids overflow in attention mask)
            if self.use_float64:
                # Temporarily convert to float32 for text encoding
                self.model.float()
                with torch.no_grad():
                    text_features = self.model.get_text_features(**inputs)
                # Convert back to float64 for image encoding
                self.model.double()
            else:
                with torch.no_grad():
                    text_features = self.model.get_text_features(**inputs)

            # Normalize the embedding
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to float32 list for compatibility
            embedding = text_features.squeeze().float().tolist()

            logger.info(f"Generated text embedding: {len(embedding)} dimensions")
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate text embedding: {e}")
            raise

    def get_batch_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in a single batch.
        Much faster than calling get_text_embedding multiple times.

        Args:
            texts: List of texts to embed

        Returns:
            List of 512-dimensional embedding vectors
        """
        import torch

        if not texts:
            return []

        try:
            # Process all texts at once
            inputs = self.processor(text=texts, return_tensors="pt", padding=True, truncation=True)

            # For Apple Silicon, text encoding needs special handling
            if self.use_float64:
                self.model.float()
                with torch.no_grad():
                    text_features = self.model.get_text_features(**inputs)
                self.model.double()
            else:
                with torch.no_grad():
                    text_features = self.model.get_text_features(**inputs)

            # Normalize embeddings
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to list of lists
            embeddings = text_features.float().tolist()

            logger.info(f"Generated {len(embeddings)} text embeddings in batch")
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate batch text embeddings: {e}")
            return []

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

            # Convert to float64 if on Apple Silicon
            if self.use_float64:
                inputs["pixel_values"] = inputs["pixel_values"].double()

            # Generate embeddings
            with torch.no_grad():
                image_features = self.model.get_image_features(**inputs)

            # Normalize embeddings
            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)

            # Convert to float32 list of lists for compatibility
            embeddings = image_features.float().tolist()

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
