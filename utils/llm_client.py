"""
Centralized LLM Client (OpenAI-Compatible)

Connects to LM Studio (or any OpenAI-compatible server) for text generation.
Decoupled from embedding logic (which is now local via FastEmbed).
"""

import logging
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError # type: ignore

logger = logging.getLogger(__name__)

class LLMClient:
    """Async wrapper for OpenAI-compatible APIs (like LM Studio)."""

    def __init__(self, base_url: str, api_key: str = "lm-studio", timeout: float = 120.0):
        """
        Initialize the LLM client.
        
        Args:
            base_url: URL of the inference server (e.g., http://localhost:1234/v1)
            api_key: Logic often requires a key, even if dummy.
            timeout: Request timeout in seconds.
        """
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout
        )

    async def generate_stream(self, prompt: str, model: str = "local-model") -> AsyncGenerator[str, None]:
        """
        Stream response tokens from the LLM.
        """
        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except APIConnectionError:
            logger.error("Failed to connect to LM Studio. Is it running on port 1234?")
            yield "Error: Could not connect to the local AI server. Please check if LM Studio is running."
        except APITimeoutError:
            logger.error("Request timed out.")
            yield "Error: The model took too long to respond."
        except Exception as e:
            logger.error(f"LLM Stream Error: {e}")
            yield f"Error: {e}"

    async def generate(self, prompt: str, model: str = "local-model") -> Optional[str]:
        """
        Generate a complete response (non-streaming).
        """
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Generation Error: {e}")
            return None
