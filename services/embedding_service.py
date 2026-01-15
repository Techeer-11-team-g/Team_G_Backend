"""
Marqo-FashionCLIP Embeddings Service for image vector generation.
Generates embeddings directly from images using Marqo-FashionCLIP model.
Uses float64 on Apple Silicon to avoid numerical precision issues.

Marqo-FashionCLIP: +57% improvement over FashionCLIP 2.0 (Aug 2024)
https://huggingface.co/Marqo/marqo-fashionCLIP
"""

import io
import logging
import platform
from typing import Optional

import torch
from PIL import Image

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Marqo-FashionCLIP-based image embedding service for vector generation."""

    # Marqo-FashionCLIP model (outputs 512 dimensions, +57% vs FashionCLIP 2.0)
    CLIP_MODEL = "hf-hub:Marqo/marqo-fashionCLIP"
    # Embedding dimensions (same as FashionCLIP - compatible with existing DB)
    EMBEDDING_DIMENSIONS = 512

    def __init__(self):
        import open_clip

        logger.info(f"Loading Marqo-FashionCLIP model: {self.CLIP_MODEL}")

        # Load model using open_clip
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(self.CLIP_MODEL)
        self.tokenizer = open_clip.get_tokenizer(self.CLIP_MODEL)

        # Check if running on Apple Silicon (M1/M2/M3)
        self.use_float64 = (
            platform.system() == "Darwin" and
            platform.processor() == "arm"
        )

        if self.use_float64:
            logger.info("Apple Silicon detected - using float64 for numerical stability")
            self.model = self.model.double()

        # Set to evaluation mode
        self.model.eval()

        logger.info("Marqo-FashionCLIP model loaded successfully")

    def get_image_embedding(self, image_bytes: bytes) -> list[float]:
        """
        Generate embedding directly from image using Marqo-FashionCLIP.

        Args:
            image_bytes: Raw image bytes

        Returns:
            512-dimensional embedding vector
        """
        try:
            # Load image from bytes
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Preprocess image
            image_tensor = self.preprocess(image).unsqueeze(0)

            # Convert to float64 if on Apple Silicon
            if self.use_float64:
                image_tensor = image_tensor.double()

            # Generate embedding
            with torch.no_grad():
                image_features = self.model.encode_image(image_tensor)

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
        Generate embedding from text using Marqo-FashionCLIP.
        Useful for text-based product search.

        Args:
            text: Text to embed

        Returns:
            512-dimensional embedding vector
        """
        try:
            # Tokenize text
            text_tokens = self.tokenizer([text])

            # For Apple Silicon, text encoding needs special handling
            if self.use_float64:
                self.model.float()
                with torch.no_grad():
                    text_features = self.model.encode_text(text_tokens)
                self.model.double()
            else:
                with torch.no_grad():
                    text_features = self.model.encode_text(text_tokens)

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
        if not texts:
            return []

        try:
            # Tokenize all texts at once
            text_tokens = self.tokenizer(texts)

            # For Apple Silicon, text encoding needs special handling
            if self.use_float64:
                self.model.float()
                with torch.no_grad():
                    text_features = self.model.encode_text(text_tokens)
                self.model.double()
            else:
                with torch.no_grad():
                    text_features = self.model.encode_text(text_tokens)

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
        try:
            # Load and preprocess all images
            images = []
            for img_bytes in image_bytes_list:
                image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                images.append(self.preprocess(image))

            # Stack into batch tensor
            image_tensor = torch.stack(images)

            # Convert to float64 if on Apple Silicon
            if self.use_float64:
                image_tensor = image_tensor.double()

            # Generate embeddings
            with torch.no_grad():
                image_features = self.model.encode_image(image_tensor)

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
