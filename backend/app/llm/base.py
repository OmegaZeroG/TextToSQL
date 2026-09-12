from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """Return the raw text completion for a single-turn prompt."""
        raise NotImplementedError
