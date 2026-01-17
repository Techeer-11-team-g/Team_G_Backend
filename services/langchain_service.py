"""
LangChain service configuration.
"""

from django.conf import settings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage


class LangChainService:
    """LangChain service for LLM operations."""

    def __init__(self, model: str = 'gpt-4o-mini', temperature: float = 0.7):
        """
        Initialize LangChain service.

        Args:
            model: OpenAI model name
            temperature: Sampling temperature
        """
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=model,
            temperature=temperature,
        )
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
        )

    def chat(self, user_message: str, system_message: str = None) -> str:
        """
        Send a chat message and get response.

        Args:
            user_message: User's message
            system_message: Optional system prompt

        Returns:
            Assistant's response
        """
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=user_message))

        response = self.llm.invoke(messages)
        return response.content

    def chat_with_template(self, template: str, **kwargs) -> str:
        """
        Chat using a prompt template.

        Args:
            template: Prompt template string
            **kwargs: Template variables

        Returns:
            Assistant's response
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | self.llm
        response = chain.invoke(kwargs)
        return response.content

    def get_embedding(self, text: str) -> list[float]:
        """
        Get embedding vector for text.

        Args:
            text: Input text

        Returns:
            Embedding vector
        """
        return self.embeddings.embed_query(text)

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Get embedding vectors for multiple texts.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        return self.embeddings.embed_documents(texts)

    def evaluate_search_result(
        self,
        category: str,
        confidence: float,
        match_score: float,
        product_id: str,
    ) -> dict:
        """
        Evaluate search result quality using LLM.

        Args:
            category: Detected item category
            confidence: Detection confidence
            match_score: k-NN search match score
            product_id: Matched product ID

        Returns:
            Evaluation result with quality and reason
        """
        prompt = f"""Evaluate this product search result quality:

Category: {category}
Detection Confidence: {confidence:.2f}
Match Score: {match_score:.4f}
Product ID: {product_id}

Based on these metrics, rate the match quality as:
- "high" if match_score > 0.85 and confidence > 0.7
- "medium" if match_score > 0.7 or confidence > 0.6
- "low" otherwise

Respond in JSON format:
{{"quality": "high/medium/low", "reason": "brief explanation"}}"""

        try:
            response = self.chat(prompt)
            # Parse JSON from response
            import json
            # Try to extract JSON from response
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            return {'quality': 'unknown', 'reason': 'Could not parse response'}
        except Exception as e:
            return {'quality': 'unknown', 'reason': str(e)}

    def parse_refine_query(
        self,
        query: str,
        available_categories: list[str],
    ) -> dict:
        """
        Parse natural language query for result refinement.

        Args:
            query: User's natural language query (e.g., "바지를 검은 바지로 다시 찾아줘")
            available_categories: List of available categories from detected objects

        Returns:
            Parsed action with filters including color, brand, price
        """
        import json
        import logging
        logger = logging.getLogger(__name__)

        prompt = f"""다음 사용자 요청을 분석하여 이미지 분석 결과 재검색에 필요한 정보를 추출하세요.

사용자 요청: "{query}"

현재 검출된 객체 카테고리: {available_categories}

다음 JSON 형식으로 응답하세요:
{{
    "action": "research" | "filter" | "change_style",
    "target_categories": ["top", "pants" 등 대상 카테고리 - 영문 소문자 사용],
    "color_filter": "black" | "white" | "navy" | "blue" | "red" | "green" | "gray" | "beige" | "brown" | "pink" | "yellow" | "orange" | "purple" 등 (없으면 null),
    "pattern_filter": "solid" | "stripe" | "check" | "floral" | "graphic" | "dot" | "camo" | "animal" (없으면 null),
    "style_vibe": "casual" | "formal" | "sporty" | "vintage" | "minimal" | "streetwear" | "luxury" | "cute" (없으면 null),
    "sleeve_length": "long_sleeve" | "short_sleeve" | "sleeveless" (top/outer 카테고리용, 없으면 null),
    "pants_length": "long" | "shorts" | "cropped" (pants 카테고리용, 없으면 null),
    "outer_length": "long" | "regular" | "cropped" (outer 카테고리용, 없으면 null),
    "material_filter": "leather" | "denim" | "cotton" | "wool" 등 (없으면 null),
    "brand_filter": "nike" | "adidas" 등 브랜드명 영문 소문자 (없으면 null),
    "price_sort": "lowest" | "highest" (가격 정렬 요청시, 없으면 null)
}}

카테고리 매핑:
- "상의", "top", "티셔츠", "셔츠", "나시", "반팔", "긴팔" → "top"
- "아우터", "outer", "자켓", "코트", "가디건", "점퍼", "패딩", "집업" → "outer"
- "하의", "bottom", "바지", "pants", "청바지", "슬랙스", "반바지" → "pants"
- "신발", "shoes", "운동화", "스니커즈", "부츠", "샌들", "슬리퍼" → "shoes"
- "가방", "bag", "백팩", "토트백", "크로스백" → "bag"

색상 매핑:
- "검은", "검정", "블랙" → "black"
- "흰", "하얀", "화이트" → "white"
- "파란", "블루" → "blue"
- "빨간", "레드" → "red"
- "네이비", "남색" → "navy"
- "회색", "그레이" → "gray"
- "베이지" → "beige"

패턴 매핑:
- "무지", "단색" → "solid"
- "줄무늬", "스트라이프" → "stripe"
- "체크", "격자" → "check"
- "꽃무늬", "플로럴" → "floral"
- "그래픽", "프린트" → "graphic"
- "도트", "물방울" → "dot"
- "카모", "밀리터리" → "camo"

스타일 매핑:
- "캐주얼", "편한" → "casual"
- "포멀", "정장" → "formal"
- "스포티", "운동" → "sporty"
- "빈티지", "레트로" → "vintage"
- "미니멀", "심플" → "minimal"
- "스트릿", "힙한" → "streetwear"
- "럭셔리", "고급" → "luxury"
- "귀여운", "큐트" → "cute"

소매 길이 매핑:
- "긴팔" → "long_sleeve"
- "반팔" → "short_sleeve"
- "나시", "민소매", "슬리브리스" → "sleeveless"

바지 길이 매핑:
- "긴바지", "롱팬츠" → "long"
- "반바지", "숏팬츠", "숏츠" → "shorts"
- "크롭", "7부", "8부" → "cropped"

소재 매핑:
- "가죽", "레더" → "leather"
- "데님", "청" → "denim"
- "면", "코튼" → "cotton"
- "울", "모직" → "wool"
- "니트" → "wool"

예시:
- "바지를 검은 바지로 다시 찾아줘" → {{"action": "research", "target_categories": ["pants"], "color_filter": "black", ...}}
- "줄무늬 셔츠로 바꿔줘" → {{"action": "research", "target_categories": ["top"], "pattern_filter": "stripe", ...}}
- "캐주얼한 느낌으로" → {{"action": "change_style", "style_vibe": "casual", ...}}

JSON만 응답하세요."""

        try:
            response = self.chat(prompt, system_message="You are a Korean fashion search assistant. Always respond in valid JSON format only.")
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                # 필수 필드 기본값 설정
                if 'target_categories' not in result or not result['target_categories']:
                    result['target_categories'] = available_categories
                if 'action' not in result:
                    result['action'] = 'research'
                # 새 필드 기본값
                result.setdefault('color_filter', None)
                result.setdefault('pattern_filter', None)
                result.setdefault('style_vibe', None)
                result.setdefault('sleeve_length', None)
                result.setdefault('pants_length', None)
                result.setdefault('outer_length', None)
                result.setdefault('material_filter', None)
                result.setdefault('brand_filter', None)
                result.setdefault('price_sort', None)
                logger.info(f"Parsed refine query: {result}")
                return result
        except Exception as e:
            logger.warning(f"Failed to parse refine query: {e}")

        return {
            'action': 'research',
            'target_categories': available_categories,
            'color_filter': None,
            'pattern_filter': None,
            'style_vibe': None,
            'sleeve_length': None,
            'pants_length': None,
            'outer_length': None,
            'material_filter': None,
            'brand_filter': None,
            'price_sort': None,
        }

    def refine_search_filters(
        self,
        category: str,
        initial_results: list[dict],
        user_preferences: dict = None,
    ) -> dict:
        """
        Use LLM to suggest refined search filters based on initial results.

        Args:
            category: Product category
            initial_results: Initial search results
            user_preferences: User's preferences (brand, price range, etc.)

        Returns:
            Suggested filter adjustments
        """
        prompt = f"""Analyze these product search results and suggest filter adjustments:

Category: {category}
Number of results: {len(initial_results)}
Top match score: {initial_results[0]['score'] if initial_results else 'N/A'}
User preferences: {user_preferences or 'None specified'}

If results quality is poor, suggest:
1. Should we broaden or narrow the category?
2. Should we adjust the number of results?
3. Any specific brand or style filters to add?

Respond in JSON format:
{{"adjust_category": true/false, "suggested_category": "...", "adjust_k": true/false, "suggested_k": 10, "filters": {{"brand": "...", "style": "..."}}}}"""

        try:
            response = self.chat(prompt)
            import json
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            return {}
        except Exception as e:
            return {'error': str(e)}


# Convenience function
def get_langchain_service(model: str = 'gpt-4o-mini', temperature: float = 0.7) -> LangChainService:
    """
    Get LangChain service instance.

    Args:
        model: OpenAI model name
        temperature: Sampling temperature

    Returns:
        LangChainService instance
    """
    return LangChainService(model=model, temperature=temperature)
