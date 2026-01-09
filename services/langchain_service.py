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
