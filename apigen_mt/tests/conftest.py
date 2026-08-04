import json
from typing import Callable, Optional, Union

import pytest

from apigen_mt.llm_client import LLMClient


class FakeLLMClient(LLMClient):
    """Deterministic stand-in for LLMClient in tests. ``responses`` can be a
    single string (returned every call), a list (one per call, cycling the
    last entry once exhausted), or a callable(call_index, system, user) -> str.
    """

    def __init__(
        self,
        responses: Union[str, list[str], Callable[[int, str, str], str]],
        name: str = "fake",
    ):
        self.responses = responses
        self.name = name
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float = 0.7, max_tokens: int = 4000) -> str:
        index = len(self.calls)
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        if callable(self.responses):
            return self.responses(index, system, user)
        if isinstance(self.responses, list):
            return self.responses[min(index, len(self.responses) - 1)]
        return self.responses


def make_answer_response(thought: str, answer: dict) -> str:
    return f"<thought>{thought}</thought><answer>{json.dumps(answer)}</answer>"


def make_scores_response(
    *, correctness=1, completeness=1, satisfaction=1, creativity=1, reflection="looks good"
) -> str:
    payload = {
        "reflection": reflection,
        "correctness": correctness,
        "completeness": completeness,
        "satisfaction": satisfaction,
        "creativity": creativity,
        "correction": None,
    }
    return f"<scores>{json.dumps(payload)}</scores>"


def make_summary_response(summary: str) -> str:
    return f"<thought>reflecting</thought><summary>{summary}</summary>"


@pytest.fixture
def retail_plugin():
    from apigen_mt.domains.retail import RetailDomainPlugin

    return RetailDomainPlugin()


@pytest.fixture
def airline_plugin():
    from apigen_mt.domains.airline import AirlineDomainPlugin

    return AirlineDomainPlugin()
