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

from services.metrics import record_api_call

logger = logging.getLogger(__name__)


def _detect_media_type(image_bytes: bytes) -> str:
    """Detect image media type from bytes."""
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    elif image_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    # Default to JPEG
    return "image/jpeg"


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
    # 길이 속성 추가
    sleeve_length: Optional[str] = None  # long_sleeve, short_sleeve, sleeveless
    pants_length: Optional[str] = None   # long, shorts, cropped
    outer_length: Optional[str] = None   # long, regular, cropped


class GPT4VService:
    """Vision service for fashion attribute extraction (Claude 3.5 Sonnet)."""

    EXTRACTION_PROMPT = """Analyze this fashion item image and extract the following attributes.
Be specific and accurate. If you can't determine something, say "unknown" or null.

Return ONLY a JSON object with these fields:
{
    "color": "primary color (black, white, gray, navy, blue, red, pink, brown, beige, green, yellow, orange, purple)",
    "secondary_color": "secondary color if any, or null",
    "material": "fabric type (cotton, denim, leather, wool, silk, nylon, velvet, linen, fur, mesh, canvas, suede)",
    "style": "style category (casual, formal, sporty, vintage, minimal, streetwear, luxury, cute)",
    "fit": "fit type (slim, regular, loose, oversized)",
    "pattern": "pattern type (solid, stripe, check, floral, graphic, dot, camo, animal)",
    "brand": "brand name if visible (from logos, text, or recognizable design), or null",
    "item_type": "specific item type (e.g., sneakers, slides, boots, loafers for shoes / t-shirt, hoodie, jacket for tops)",
    "description": "brief 2-3 word description of the item",
    "sleeve_length": "for tops/outer only: long_sleeve, short_sleeve, or sleeveless (null for other categories)",
    "pants_length": "for pants only: long, shorts, or cropped (null for other categories)",
    "outer_length": "for outer only: long, regular, or cropped (null for other categories)"
}

Important:
- For brand detection, look for logos, brand text, or distinctive brand design elements
- Common brands: Nike, Adidas, Zara, H&M, Uniqlo, North Face, etc.
- If you see a swoosh, it's Nike. Three stripes is Adidas. etc.
- Be confident in brand detection when visual evidence is clear
- For shoes: distinguish between sneakers, slides/slippers, boots, loafers, sandals, etc.
- For sleeve_length: only provide for tops (shirts, t-shirts) and outer (jackets, coats)
- For pants_length: only provide for pants/bottoms
- For outer_length: only provide for outer items (jackets, coats, cardigans)"""

    def __init__(self):
        """Initialize Claude Vision service."""
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"
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
            with record_api_call('claude_vision'):
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
            logger.info(
                "Claude 속성 추출 완료",
                extra={
                    'event': 'claude_extract_attributes',
                    'service': 'claude_vision',
                    'category': category,
                    'color': attributes.color,
                    'brand': attributes.brand,
                    'item_type': attributes.item_type,
                }
            )

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
                    sleeve_length=data.get('sleeve_length'),
                    pants_length=data.get('pants_length'),
                    outer_length=data.get('outer_length'),
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

            with record_api_call('claude_rerank'):
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

            logger.info(
                "Claude 리랭킹 완료",
                extra={
                    'event': 'claude_rerank',
                    'service': 'claude_vision',
                    'candidates_count': len(candidates[:10]),
                    'reranked_count': len(reranked),
                    'top_k': top_k,
                }
            )
            return reranked[:top_k]

        except Exception as e:
            logger.warning(f"Claude reranking failed: {e}, using original order")
            return candidates[:top_k]

    # 스타일 태그 목록 (사전 정의)
    STYLE_TAGS = {
        # 스타일
        "amekaji": "아메카지 (미국+일본 캐주얼, 빈티지한 느낌)",
        "casual": "캐주얼 (편안하고 일상적인)",
        "street": "스트릿 (힙합, 스케이트보드 문화)",
        "minimal": "미니멀 (단순하고 깔끔한)",
        "formal": "포멀 (정장, 비즈니스)",
        "sporty": "스포티 (운동복, 애슬레저)",
        "vintage": "빈티지 (레트로, 구제)",
        "cityboy": "시티보이 (도시적, 세련된 캐주얼)",
        "preppy": "프레피 (아이비리그, 단정한)",
        "workwear": "워크웨어 (작업복 스타일, 튼튼한)",
        "bohemian": "보헤미안 (자유분방, 히피)",
        "feminine": "페미닌 (여성스러운, 우아한)",
        "gothic": "고딕 (다크, 펑크)",
        "normcore": "놈코어 (평범함, 기본템)",
    }

    STYLE_TAG_PROMPT = """이 코디/착장 이미지를 분석해서 가장 어울리는 스타일 태그를 선택해주세요.

## 스타일 태그 목록
- amekaji: 아메카지 (미국+일본 캐주얼, 빈티지한 느낌, 데님+워크부츠+가죽)
- casual: 캐주얼 (편안하고 일상적인)
- street: 스트릿 (힙합, 스케이트보드 문화, 오버핏)
- minimal: 미니멀 (단순하고 깔끔한, 모노톤)
- formal: 포멀 (정장, 비즈니스)
- sporty: 스포티 (운동복, 애슬레저)
- vintage: 빈티지 (레트로, 구제, 올드스쿨)
- cityboy: 시티보이 (도시적, 세련된 캐주얼)
- preppy: 프레피 (아이비리그, 단정한, 교복 느낌)
- workwear: 워크웨어 (작업복 스타일, 카고팬츠, 튼튼한)
- bohemian: 보헤미안 (자유분방, 히피, 플로럴)
- feminine: 페미닌 (여성스러운, 우아한, 드레스)
- gothic: 고딕 (다크, 펑크, 블랙)
- normcore: 놈코어 (평범함, 기본템, 무난한)

## 규칙
1. 메인 스타일 1개는 필수 선택
2. 서브 스타일은 뚜렷하게 보이는 경우에만 선택 (없으면 null)
3. 반드시 위 목록에 있는 태그만 사용

## 응답 형식 (JSON)
{"style_tag1": "메인 스타일 태그", "style_tag2": "서브 스타일 태그 또는 null"}

예시:
- 데님 재킷 + 부츠 + 빈티지 티셔츠 → {"style_tag1": "amekaji", "style_tag2": "vintage"}
- 단순한 흰 티 + 청바지 → {"style_tag1": "casual", "style_tag2": null}
- 오버사이즈 후드 + 조거팬츠 → {"style_tag1": "street", "style_tag2": null}"""

    def extract_style_tags(
        self,
        image_bytes: bytes,
    ) -> tuple[str | None, str | None]:
        """
        코디 이미지에서 스타일 태그 추출.

        Args:
            image_bytes: 전체 코디 이미지

        Returns:
            (style_tag1, style_tag2) - 메인/서브 스타일 태그
        """
        import json
        import re

        try:
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            media_type = _detect_media_type(image_bytes)

            with record_api_call('claude_style_tags'):
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=300,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": base64_image,
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": self.STYLE_TAG_PROMPT
                                }
                            ]
                        }
                    ],
                )

            content = response.content[0].text.strip()
            logger.debug(f"Claude style tags response: {content}")

            # JSON 파싱
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                tag1 = data.get('style_tag1')
                tag2 = data.get('style_tag2')

                # 유효한 태그인지 확인
                if tag1 and tag1 not in self.STYLE_TAGS:
                    logger.warning(f"Invalid style_tag1: {tag1}")
                    tag1 = None
                if tag2 and tag2 not in self.STYLE_TAGS:
                    logger.warning(f"Invalid style_tag2: {tag2}")
                    tag2 = None

                logger.info(
                    "스타일 태그 추출 완료",
                    extra={
                        'event': 'extract_style_tags',
                        'style_tag1': tag1,
                        'style_tag2': tag2,
                    }
                )
                return tag1, tag2

        except Exception as e:
            logger.error(f"Style tag extraction failed: {e}")

        return None, None


# Singleton instance
_gpt4v_service: Optional[GPT4VService] = None


def get_gpt4v_service() -> GPT4VService:
    """Get or create GPT4VService singleton."""
    global _gpt4v_service
    if _gpt4v_service is None:
        _gpt4v_service = GPT4VService()
    return _gpt4v_service
