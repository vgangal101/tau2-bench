"""Model-agnostic LLM interface for the Phase 1 roles (data generator,
review committee judges, feedback generator). Phase 2 (human simulator,
test agent) reuses tau2's own litellm-based agent/user modules instead --
see phase2/driver.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    """A single named LLM role. Swappable: nothing in phase1/ depends on
    which provider or model backs an implementation.
    """

    name: str

    @abstractmethod
    def complete(
        self, *, system: str, user: str, temperature: float = 0.7, max_tokens: int = 4000
    ) -> str:
        """Return the raw text completion for a single-turn system+user prompt."""


class AnthropicLLMClient(LLMClient):
    def __init__(self, model: str, api_key: Optional[str] = None, name: Optional[str] = None):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only when uninstalled
            raise RuntimeError(
                "The 'anthropic' package is required for AnthropicLLMClient. "
                "Install it with `pip install anthropic`."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.name = name or f"anthropic:{model}"

    def complete(
        self, *, system: str, user: str, temperature: float = 0.7, max_tokens: int = 4000
    ) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
