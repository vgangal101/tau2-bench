"""Domain abstraction: everything APIGen-MT's core pipeline needs from a tau2
domain, behind one interface. Adding a new domain means writing one new
module here and touching nothing under phase1/, phase2/, or graph.py.
"""

from __future__ import annotations

import random
import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from pydantic import BaseModel

from tau2.data_model.tasks import Task
from tau2.environment.environment import Environment
from tau2.environment.toolkit import ToolKitBase, ToolType

if TYPE_CHECKING:
    from apigen_mt.graph import APIGraph
    from apigen_mt.phase1.schema import ExecutionCheckResult, TaskBlueprint


@dataclass(frozen=True)
class ToolInfo:
    """A tool available in a domain, with the read/write classification tau2
    already bakes into the domain's own toolkit via ``@is_tool(ToolType...)``.
    """

    name: str
    tool_type: str  # "read" | "write" | "think" | "generic"
    mutates_state: bool
    signature: str  # str(tau2 Tool) -- function signature + docstring
    openai_schema: dict
    params_fields: tuple[str, ...]  # argument names this tool consumes
    produced_fields: tuple[str, ...]  # entity field names this tool's return plausibly exposes


def _unwrap_basemodel(annotation: object) -> Optional[type[BaseModel]]:
    """Find a BaseModel subclass inside a (possibly generic) type annotation,
    e.g. Optional[Order], List[DirectFlight], Dict[str, FlightDateStatus].
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        found = _unwrap_basemodel(arg)
        if found is not None:
            return found
    return None


def _id_tokens_from_name(func_name: str) -> tuple[str, ...]:
    """Heuristically extract identifier-like tokens from a lookup function's
    name, e.g. 'find_user_id_by_email' -> ('user_id',). Generic string
    tokenization, no domain knowledge.
    """
    tokens = func_name.split("_")
    found = []
    for i, tok in enumerate(tokens):
        if tok in ("id", "number") and i > 0:
            found.append(f"{tokens[i - 1]}_{tok}")
    return tuple(found)


def tools_from_toolkit(toolkit: ToolKitBase) -> list[ToolInfo]:
    """Generic reflection over a tau2 ToolKitBase -- shared by all plugins."""
    infos = []
    for name, tool in sorted(toolkit.get_tools().items()):
        params_fields = tuple(tool.params.model_fields.keys())
        returns_anno = tool.returns.model_fields["returns"].annotation
        return_model = _unwrap_basemodel(returns_anno)
        produced = set(return_model.model_fields.keys()) if return_model else set()
        produced |= set(_id_tokens_from_name(name))
        infos.append(
            ToolInfo(
                name=name,
                tool_type=toolkit.tool_type(name).value,
                mutates_state=toolkit.tool_mutates_state(name),
                signature=str(tool),
                openai_schema=tool.openai_schema,
                params_fields=params_fields,
                produced_fields=tuple(sorted(produced)),
            )
        )
    return infos


@dataclass
class PolicyPredicate:
    """A hand-written executable check translated from the domain's policy
    doc. ``check`` returns None if the predicate is satisfied, else a
    human-readable violation message.
    """

    name: str
    description: str
    check: Callable[["TaskBlueprint", "ExecutionCheckResult"], Optional[str]]


class DomainDBAccessor(ABC):
    """Generic sampling surface over a domain's concrete DB records."""

    @abstractmethod
    def sample_user(self, rng: random.Random) -> dict:
        """A JSON-able dict describing one concrete user (id + profile)."""

    @abstractmethod
    def sample_related_records(
        self, user_id: str, rng: random.Random, k: int = 2
    ) -> list[dict]:
        """Up to k JSON-able dicts of records owned by ``user_id``
        (e.g. orders, reservations), with metadata useful for grounding
        a task (cost, status, items, dates, ...).
        """


class DomainPlugin(ABC):
    """Everything domain-specific the APIGen-MT pipeline needs.

    Core modules (graph.py, phase1/*, phase2/*) take a DomainPlugin instance
    and must never branch on ``plugin.name`` -- any domain-specific decision
    belongs on this interface instead.
    """

    name: str

    @abstractmethod
    def env_factory(self) -> Environment:
        """A fresh tau2 Environment instance for this domain."""

    @abstractmethod
    def tools(self) -> list[ToolInfo]:
        """All tools registered for this domain's assistant toolkit."""

    @abstractmethod
    def api_graph_edges(self) -> list[tuple[str, str]]:
        """Hand-annotated dependency edges (tool_a -> tool_b) beyond what
        the generic arg/output-overlap heuristic in graph.py infers.
        """

    @abstractmethod
    def policy_doc_path(self) -> Path:
        """Path to this domain's policy markdown."""

    @abstractmethod
    def policy_predicates(self) -> list[PolicyPredicate]:
        """Hand-written executable checks derived from the policy doc."""

    @abstractmethod
    def db_accessor(self) -> DomainDBAccessor:
        """Wraps this domain's DB for generic record sampling."""

    @abstractmethod
    def persona_bank(self) -> list[str]:
        """Domain-appropriate free-text personas (PersonaHub-style)."""

    @abstractmethod
    def example_tasks(self) -> list[dict]:
        """Few-shot {intent, actions, outputs} examples for the generator prompt."""

    @abstractmethod
    def blueprint_to_native_task(self, blueprint: "TaskBlueprint", task_id: str) -> Task:
        """Domain-specific half of the blueprint -> tau2 Task adaptation."""

    # -- concrete helpers shared by every plugin -----------------------

    def policy_text(self) -> str:
        return self.policy_doc_path().read_text()

    def tools_by_name(self) -> dict[str, ToolInfo]:
        return {t.name: t for t in self.tools()}

    def write_tools(self) -> list[ToolInfo]:
        return [t for t in self.tools() if t.tool_type == ToolType.WRITE.value]

    def read_tools(self) -> list[ToolInfo]:
        return [t for t in self.tools() if t.tool_type == ToolType.READ.value]

    def api_graph(self) -> "APIGraph":
        from apigen_mt.graph import build_api_graph

        return build_api_graph(self)
