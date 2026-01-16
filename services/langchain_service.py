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
            query: User's natural language query (e.g., "상의만 다시 검색해줘")
            available_categories: List of available categories from detected objects

        Returns:
            Parsed action with filters
        """
        prompt = f"""다음 사용자 요청을 분석하여 이미지 분석 결과 수정에 필요한 정보를 추출하세요.

사용자 요청: "{query}"

현재 검출된 객체 카테고리: {available_categories}

다음 JSON 형식으로 응답하세요:
{{
    "action": "research" | "filter" | "change_category",
    "target_categories": ["상의", "하의" 등 대상 카테고리 목록 - 원본 카테고리명 사용],
    "search_keywords": "추가 검색 키워드 (없으면 null)",
    "brand_filter": "브랜드 필터 (없으면 null)",
    "price_filter": {{"min": 숫자, "max": 숫자}} (없으면 null),
    "style_keywords": ["캐주얼", "포멀" 등 스타일 키워드 목록]
}}

규칙:
- "상의", "top", "아우터", "outer" 등은 모두 target_categories에 해당 카테고리로 포함
- "하의", "bottom", "pants", "바지" 등도 마찬가지
- "다시 검색", "재검색" 등은 action: "research"
- "비슷한", "더 저렴한" 등 조건 추가는 action: "filter"
- 카테고리 변경 요청은 action: "change_category"
- target_categories가 비어있으면 모든 카테고리 대상"""

        try:
            response = self.chat(prompt, system_message="You are a Korean fashion search assistant. Always respond in valid JSON format.")
            import json
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                # Validate and normalize
                if 'target_categories' not in result or not result['target_categories']:
                    result['target_categories'] = available_categories
                if 'action' not in result:
                    result['action'] = 'research'
                return result
            return {
                'action': 'research',
                'target_categories': available_categories,
                'search_keywords': None,
                'brand_filter': None,
                'price_filter': None,
                'style_keywords': [],
            }
        except Exception as e:
            return {
                'action': 'research',
                'target_categories': available_categories,
                'search_keywords': None,
                'brand_filter': None,
                'price_filter': None,
                'style_keywords': [],
                'error': str(e),
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
