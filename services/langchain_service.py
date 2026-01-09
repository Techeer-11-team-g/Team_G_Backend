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
