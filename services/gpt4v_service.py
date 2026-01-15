"""
Vision Service for Fashion Attribute Extraction.

Supports: Claude 3.5 Sonnet (default), GPT-4o

Extracts detailed fashion attributes from cropped item images:
- Color (primary, secondary)
- Material (fabric type)
- Style (casual, formal, sporty, etc.)
- Fit (loose, slim, regular)
- Pattern (solid, striped, checkered, etc.)
- Brand (detected from logos/text)
"""

import base64
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class FashionAttributes:
    """Extracted fashion attributes from an image."""
    color: str
    secondary_color: Optional[str] = None
    material: Optional[str] = None
    style: Optional[str] = None
    fit: Optional[str] = None
    pattern: Optional[str] = None
    brand: Optional[str] = None
    item_type: Optional[str] = None  # sneakers, slides, t-shirt, hoodie, etc.
    description: Optional[str] = None


class GPT4VService:
    """Vision service for fashion attribute extraction (Claude 3.5 Sonnet)."""

    EXTRACTION_PROMPT = """Analyze this fashion item image and extract the following attributes.
Be specific and accurate. If you can't determine something, say "unknown".

Return ONLY a JSON object with these fields:
{
    "color": "primary color (e.g., navy blue, black, white, beige)",
    "secondary_color": "secondary color if any, or null",
    "material": "fabric type (e.g., cotton, denim, leather, knit, polyester)",
    "style": "style category (casual, formal, sporty, streetwear, vintage, minimalist)",
    "fit": "fit type (slim, regular, loose, oversized)",
    "pattern": "pattern type (solid, striped, checkered, floral, graphic, logo)",
    "brand": "brand name if visible (from logos, text, or recognizable design), or null",
    "item_type": "specific item type (e.g., sneakers, slides, boots, loafers for shoes / t-shirt, hoodie, jacket for tops)",
    "description": "brief 2-3 word description of the item"
}

Important:
- For brand detection, look for logos, brand text, or distinctive brand design elements
- Common brands: Nike, Adidas, Zara, H&M, Uniqlo, North Face, etc.
- If you see a swoosh, it's Nike. Three stripes is Adidas. etc.
- Be confident in brand detection when visual evidence is clear
- For shoes: distinguish between sneakers, slides/slippers, boots, loafers, sandals, etc."""

    def __init__(self):
        """Initialize Claude Opus service."""
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-opus-4-20250514"
        logger.info(f"Claude Vision service initialized (model: {self.model})")

    def extract_attributes(
        self,
        image_bytes: bytes,
        category: str = None,
    ) -> FashionAttributes:
        """
        Extract fashion attributes from an image.

        Args:
            image_bytes: Image as bytes
            category: Optional category hint (top, bottom, shoes, etc.)

        Returns:
            FashionAttributes with extracted data
        """
        try:
            # Encode image to base64
            base64_image = base64.b64encode(image_bytes).decode('utf-8')

            # Add category context if provided
            prompt = self.EXTRACTION_PROMPT
            if category:
                prompt = f"This is a {category} item.\n\n" + prompt

            # Call Claude 3.5 Sonnet
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64_image,
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
            )

            # Parse response
            content = response.content[0].text
            logger.debug(f"Claude response: {content}")

            # Extract JSON from response
            attributes = self._parse_response(content)
            logger.info(f"Extracted attributes: color={attributes.color}, brand={attributes.brand}")

            return attributes

        except Exception as e:
            logger.error(f"Claude attribute extraction failed: {e}")
            # Return default attributes on failure
            return FashionAttributes(
                color="unknown",
                description="fashion item"
            )

    def _parse_response(self, content: str) -> FashionAttributes:
        """Parse GPT-4V response into FashionAttributes."""
        import json
        import re

        try:
            # Try to extract JSON from response
            # Handle case where response includes markdown code blocks
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                data = json.loads(json_str)

                return FashionAttributes(
                    color=data.get('color', 'unknown'),
                    secondary_color=data.get('secondary_color'),
                    material=data.get('material'),
                    style=data.get('style'),
                    fit=data.get('fit'),
                    pattern=data.get('pattern'),
                    brand=data.get('brand'),
                    item_type=data.get('item_type'),
                    description=data.get('description'),
                )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from GPT-4V response: {e}")

        # Fallback: return basic attributes
        return FashionAttributes(
            color="unknown",
            description="fashion item"
        )

    def rerank_products(
        self,
        query_image_bytes: bytes,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """
        Claude로 최종 리랭킹.

        Args:
            query_image_bytes: 쿼리 이미지 (크롭된 패션 아이템)
            candidates: 후보 상품 리스트 [{name, image_url, brand, ...}, ...]
            top_k: 반환할 상위 개수

        Returns:
            리랭킹된 상품 리스트
        """
        import httpx

        if not candidates or len(candidates) <= 1:
            return candidates[:top_k]

        try:
            # 쿼리 이미지 base64
            query_base64 = base64.b64encode(query_image_bytes).decode('utf-8')

            # 후보 상품 정보 텍스트로 구성
            candidates_text = ""
            for i, item in enumerate(candidates[:10]):  # 상위 10개만 리랭킹
                name = item.get('name', 'Unknown')
                brand = item.get('brand', 'Unknown')
                candidates_text += f"{i+1}. [{brand}] {name}\n"

            prompt = f"""I have a query fashion item image and a list of candidate products.
Rank the candidates by how similar they are to the query image.

Consider:
1. Visual similarity (shape, style, design)
2. Color match
3. Brand match (if visible)
4. Item type match (sneakers vs sneakers, jacket vs jacket, etc.)

Candidates:
{candidates_text}

Return ONLY the ranking as comma-separated numbers (e.g., "3,1,5,2,4").
Most similar first. Only include the numbers, no explanation."""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": query_base64,
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
            )

            # 응답 파싱
            ranking_text = response.content[0].text.strip()
            logger.debug(f"Claude rerank response: {ranking_text}")

            # 숫자 추출
            import re
            numbers = re.findall(r'\d+', ranking_text)
            ranking = [int(n) - 1 for n in numbers if int(n) <= len(candidates[:10])]

            # 리랭킹된 결과 구성
            reranked = []
            seen = set()
            for idx in ranking:
                if 0 <= idx < len(candidates) and idx not in seen:
                    reranked.append(candidates[idx])
                    seen.add(idx)

            # 누락된 항목 추가
            for i, item in enumerate(candidates[:10]):
                if i not in seen:
                    reranked.append(item)

            logger.info(f"Claude reranked {len(candidates[:10])} candidates")
            return reranked[:top_k]

        except Exception as e:
            logger.warning(f"Claude reranking failed: {e}, using original order")
            return candidates[:top_k]


# Singleton instance
_gpt4v_service: Optional[GPT4VService] = None


def get_gpt4v_service() -> GPT4VService:
    """Get or create GPT4VService singleton."""
    global _gpt4v_service
    if _gpt4v_service is None:
        _gpt4v_service = GPT4VService()
    return _gpt4v_service
