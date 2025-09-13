import asyncio
import logging

class LLMAdapter:
    """
    Minimal LLM scaffolding.
    - generate(prompt) returns a simple echo-like response.
    Replace with provider call later (OpenAI/Local LLM/etc.).
    """
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('LLM')

    async def generate(self, prompt: str) -> str:
        self.logger.debug(f"LLM prompt: {prompt}")
        await asyncio.sleep(0.1)
        return f"You said: {prompt}"