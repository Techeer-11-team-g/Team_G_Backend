"""
BLIP-2 Service for image captioning and re-ranking.
Uses BLIP-2 to generate text descriptions from images for better product matching.
"""

import io
import logging
import platform
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class BlipService:
    """BLIP based image captioning service for re-ranking."""

    # BLIP model (large version ~2GB, better captions)
    MODEL_NAME = "Salesforce/blip-image-captioning-large"

    def __init__(self):
        import torch
        from transformers import BlipProcessor, BlipForConditionalGeneration

        logger.info(f"Loading BLIP model: {self.MODEL_NAME}")

        self.processor = BlipProcessor.from_pretrained(self.MODEL_NAME)
        self.model = BlipForConditionalGeneration.from_pretrained(self.MODEL_NAME)

        # Move to GPU if available, otherwise CPU
        if torch.cuda.is_available():
            self.model = self.model.to("cuda")
            self.device = "cuda"
        elif platform.system() == "Darwin" and platform.processor() == "arm":
            # Apple Silicon - use MPS if available
            if torch.backends.mps.is_available():
                self.model = self.model.to("mps")
                self.device = "mps"
            else:
                self.device = "cpu"
        else:
            self.device = "cpu"

        logger.info(f"BLIP model loaded on {self.device}")

    # Category-specific prompts for better caption generation
    CATEGORY_PROMPTS = {
        'shoes': "The color of these sneakers is",
        'bag': "This bag is a",
        'top': "This is a photo of",
        'bottom': "This is a photo of",
        'outer': "This is a photo of",
        'outerwear': "This is a photo of",
    }

    def generate_caption(self, image_bytes: bytes, prompt: str = None, category: str = None) -> str:
        """
        Generate a caption/description for an image.

        Args:
            image_bytes: Raw image bytes
            prompt: Optional prompt to guide caption generation
            category: Optional category for category-specific prompts

        Returns:
            Generated caption string
        """
        import torch

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Use category-specific prompt if available
            if prompt is None:
                if category and category.lower() in self.CATEGORY_PROMPTS:
                    prompt = self.CATEGORY_PROMPTS[category.lower()]
                else:
                    prompt = "This is a photo of"

            inputs = self.processor(image, text=prompt, return_tensors="pt")

            # Move inputs to device
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                generated_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=50,
                    num_beams=3,
                )

            caption = self.processor.batch_decode(
                generated_ids, skip_special_tokens=True
            )[0].strip()

            logger.info(f"Generated caption: {caption}")
            return caption

        except Exception as e:
            logger.error(f"Failed to generate caption: {e}")
            return ""

    def generate_fashion_description(self, image_bytes: bytes) -> dict:
        """
        Generate detailed fashion description including color and style.

        Args:
            image_bytes: Raw image bytes

        Returns:
            Dict with 'caption', 'color', 'style' keys
        """
        result = {
            'caption': '',
            'color': '',
            'style': '',
        }

        try:
            # General caption
            result['caption'] = self.generate_caption(
                image_bytes,
                "This is a photo of"
            )

            # Color-focused caption
            color_caption = self.generate_caption(
                image_bytes,
                "The color of this clothing is"
            )
            result['color'] = color_caption

            # Style-focused caption
            style_caption = self.generate_caption(
                image_bytes,
                "The style of this clothing is"
            )
            result['style'] = style_caption

            return result

        except Exception as e:
            logger.error(f"Failed to generate fashion description: {e}")
            return result

    # English to Korean color mapping
    COLOR_MAPPING = {
        'black': ['블랙', 'black', '검정', '검은'],
        'white': ['화이트', 'white', '흰', '아이보리', 'ivory', '크림', 'cream'],
        'gray': ['그레이', 'grey', 'gray', '회색', '차콜', 'charcoal'],
        'brown': ['브라운', 'brown', '갈색', '카멜', 'camel', '베이지', 'beige', '탄', '모카', 'mocha'],
        'blue': ['블루', 'blue', '파란', '인디고', 'indigo', '네이비', 'navy', '데님', 'denim', '스카이', 'sky'],
        'red': ['레드', 'red', '빨간', '버건디', 'burgundy', '와인', 'wine'],
        'pink': ['핑크', 'pink', '분홍', '로즈', 'rose'],
        'green': ['그린', 'green', '카키', 'khaki', '올리브', 'olive', '민트', 'mint'],
        'yellow': ['옐로우', 'yellow', '노란', '머스타드', 'mustard'],
        'orange': ['오렌지', 'orange', '주황', '코랄', 'coral'],
        'purple': ['퍼플', 'purple', '보라', '바이올렛', 'violet', '라벤더', 'lavender'],
    }

    # English to Korean clothing type mapping
    CLOTHING_TYPE_MAPPING = {
        'sweater': ['스웨터', 'sweater', '니트', 'knit', '맨투맨'],
        'hoodie': ['후드', 'hoodie', '후디', '후드티'],
        'sweatshirt': ['스웨트셔츠', 'sweatshirt', '맨투맨', '스웻'],
        'jacket': ['자켓', 'jacket', '재킷', '점퍼', 'jumper'],
        'coat': ['코트', 'coat'],
        'cardigan': ['가디건', 'cardigan'],
        'pants': ['팬츠', 'pants', '바지', '슬랙스', 'slacks'],
        'jeans': ['청바지', 'jeans', '데님', 'denim', '진'],
        'trousers': ['트라우저', 'trousers', '바지'],
        'skirt': ['스커트', 'skirt', '치마'],
        'dress': ['원피스', 'dress', '드레스'],
        'shirt': ['셔츠', 'shirt', '블라우스', 'blouse'],
        't-shirt': ['티셔츠', 't-shirt', 'tee', '티'],
        'sneakers': ['스니커즈', 'sneakers', '운동화', '스니커'],
        'shoes': ['슈즈', 'shoes', '신발', '구두'],
        'boots': ['부츠', 'boots', '부트'],
        'bag': ['가방', 'bag', '백', '토트', 'tote', '숄더', 'shoulder'],
        'handbag': ['핸드백', 'handbag', '가방', '백'],
        'purse': ['파우치', 'purse', '가방', '백', '핸드백'],
    }

    # Style/fit mapping
    STYLE_MAPPING = {
        'oversized': ['오버사이즈', 'oversized', '오버핏', '루즈핏', 'loose'],
        'slim': ['슬림', 'slim', '슬림핏', '스키니', 'skinny'],
        'wide': ['와이드', 'wide', '와이드핏', '벌룬', 'balloon'],
        'cropped': ['크롭', 'cropped', '크롭트'],
        'long': ['롱', 'long', '롱기장', '맥시', 'maxi'],
        'mini': ['미니', 'mini', '숏', 'short'],
    }

    def calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two text strings.
        Includes color, clothing type, and style matching for Korean product names.

        Args:
            text1: First text (caption - English)
            text2: Second text (product name - Korean/English)

        Returns:
            Similarity score (0-1)
        """
        if not text1 or not text2:
            return 0.0

        text1_lower = text1.lower()
        text2_lower = text2.lower()

        score = 0.0

        # Color matching (highest priority)
        for eng_color, variants in self.COLOR_MAPPING.items():
            if eng_color in text1_lower:
                for variant in variants:
                    if variant in text2_lower:
                        score += 0.4
                        break

        # Clothing type matching (high priority)
        for eng_type, variants in self.CLOTHING_TYPE_MAPPING.items():
            if eng_type in text1_lower:
                for variant in variants:
                    if variant in text2_lower:
                        score += 0.3
                        break

        # Style/fit matching
        for eng_style, variants in self.STYLE_MAPPING.items():
            if eng_style in text1_lower:
                for variant in variants:
                    if variant in text2_lower:
                        score += 0.2
                        break

        # Word overlap (lower priority)
        words1 = set(text1_lower.split())
        words2 = set(text2_lower.split())
        intersection = len(words1 & words2)
        if intersection > 0:
            score += 0.05 * intersection

        return min(score, 1.0)  # Cap at 1.0

    # Keywords that indicate a useful fashion caption
    FASHION_KEYWORDS = {
        # Colors
        'black', 'white', 'gray', 'grey', 'brown', 'blue', 'red', 'pink',
        'green', 'yellow', 'orange', 'purple', 'beige', 'navy', 'cream',
        # Clothing types
        'sweater', 'hoodie', 'sweatshirt', 'jacket', 'coat', 'cardigan',
        'pants', 'jeans', 'trousers', 'skirt', 'dress', 'shirt', 't-shirt',
        'sneakers', 'shoes', 'boots', 'bag', 'handbag', 'purse', 'top', 'bottom',
        # Materials
        'denim', 'leather', 'cotton', 'wool', 'knit',
        # Descriptors
        'wearing', 'outfit', 'clothing', 'fashion',
    }

    def _is_useful_caption(self, caption: str) -> bool:
        """
        Check if caption contains fashion-related keywords.

        Args:
            caption: Generated caption

        Returns:
            True if caption is useful for fashion matching
        """
        if not caption:
            return False

        caption_lower = caption.lower()

        # Check if any fashion keyword is present
        for keyword in self.FASHION_KEYWORDS:
            if keyword in caption_lower:
                return True

        return False

    def rerank_products(
        self,
        image_bytes: bytes,
        candidates: list[dict],
        top_k: int = 5,
        image_embedding: list = None,
        category: str = None,
    ) -> list[dict]:
        """
        Re-rank product candidates using BLIP caption + CLIP cross-encoder.

        Uses two signals:
        1. BLIP caption → text similarity with product names
        2. CLIP cross-encoder → image embedding vs product name embedding

        Args:
            image_bytes: Query image bytes
            candidates: List of candidate products with 'name', 'score' etc.
            top_k: Number of results to return
            image_embedding: Pre-computed image embedding (optional)
            category: Product category for category-specific prompts

        Returns:
            Re-ranked list of products
        """
        if not candidates:
            return []

        try:
            # Generate caption for query image (with category-specific prompt)
            caption = self.generate_caption(image_bytes, category=category)
            logger.info(f"Query caption: {caption}")

            # Check if caption is useful for fashion matching
            use_blip = self._is_useful_caption(caption)
            if not use_blip:
                logger.info(f"Caption not useful, using CLIP cross-encoder only")

            # Get CLIP cross-encoder scores if image embedding provided
            clip_scores = {}
            if image_embedding is not None:
                clip_scores = self._compute_clip_scores(image_embedding, candidates)

            # Calculate combined score for each candidate
            for candidate in candidates:
                product_name = candidate.get('name', '')
                original_score = candidate.get('score', 0)

                # BLIP text similarity (if caption is useful)
                if use_blip:
                    text_sim = self.calculate_text_similarity(caption, product_name)
                else:
                    text_sim = 0.0

                # CLIP cross-encoder score
                clip_score = clip_scores.get(product_name, 0.0)

                # Combined score with all signals
                if use_blip and clip_scores:
                    # All three signals
                    combined_score = original_score * 0.5 + text_sim * 0.25 + clip_score * 0.25
                elif use_blip:
                    # BLIP only
                    combined_score = original_score * 0.7 + text_sim * 0.3
                elif clip_scores:
                    # CLIP only
                    combined_score = original_score * 0.7 + clip_score * 0.3
                else:
                    # Original only
                    combined_score = original_score

                candidate['text_similarity'] = text_sim
                candidate['clip_score'] = clip_score
                candidate['combined_score'] = combined_score

            # Sort by combined score
            reranked = sorted(
                candidates,
                key=lambda x: x.get('combined_score', 0),
                reverse=True
            )

            logger.info(f"Re-ranked {len(candidates)} candidates")
            return reranked[:top_k]

        except Exception as e:
            logger.error(f"Failed to rerank products: {e}")
            # Return original candidates if reranking fails
            return candidates[:top_k]

    def _compute_clip_scores(self, image_embedding: list, candidates: list[dict]) -> dict:
        """
        Compute CLIP cross-encoder scores between image and product names.
        Uses batch processing for efficiency.

        Args:
            image_embedding: Image embedding vector
            candidates: List of candidate products

        Returns:
            Dict mapping product name to similarity score
        """
        try:
            from services.embedding_service import get_embedding_service
            import numpy as np

            embedding_service = get_embedding_service()

            # Collect all product names
            product_names = [c.get('name', '') for c in candidates if c.get('name')]
            if not product_names:
                return {}

            # Get all text embeddings in one batch (much faster!)
            text_embeddings = embedding_service.get_batch_text_embeddings(product_names)
            if not text_embeddings:
                return {}

            # Compute cosine similarities
            img_vec = np.array(image_embedding)
            img_norm = np.linalg.norm(img_vec)

            scores = {}
            for name, txt_emb in zip(product_names, text_embeddings):
                txt_vec = np.array(txt_emb)
                similarity = np.dot(img_vec, txt_vec) / (img_norm * np.linalg.norm(txt_vec) + 1e-8)
                scores[name] = float(similarity)

            return scores

        except Exception as e:
            logger.error(f"Failed to compute CLIP scores: {e}")
            return {}


# Singleton instance
_blip_service: Optional[BlipService] = None


def get_blip_service() -> BlipService:
    """Get or create BlipService singleton."""
    global _blip_service
    if _blip_service is None:
        _blip_service = BlipService()
    return _blip_service
