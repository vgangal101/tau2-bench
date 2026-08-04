"""Context preparation: the five samplers (API, policy, domain data,
persona, example) from Subsection 4.1.1, all driven generically by a
DomainPlugin. Sampling frequency/mix is randomized per call to avoid
repetitive scenarios.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from apigen_mt.domains.base import DomainPlugin, ToolInfo


@dataclass
class SampledContext:
    write_tools: list[ToolInfo]
    read_tools: list[ToolInfo]
    policy_excerpt: str
    user_record: dict
    related_records: list[dict] = field(default_factory=list)
    persona: str = ""
    examples: list[dict] = field(default_factory=list)
    suggested_sequence: list[str] = field(default_factory=list)


def _split_into_sections(text: str) -> list[str]:
    """Split a markdown policy doc on '#' headers, keeping each section's
    header line attached to its body.
    """
    lines = text.splitlines()
    sections: list[list[str]] = [[]]
    for line in lines:
        if line.startswith("#") and sections[-1]:
            sections.append([])
        sections[-1].append(line)
    return ["\n".join(s) for s in sections if s]


class ContextSampler:
    def __init__(self, plugin: DomainPlugin, rng: random.Random):
        self.plugin = plugin
        self.rng = rng
        self._graph = plugin.api_graph()

    def sample(
        self,
        min_writes: int = 1,
        max_writes: int = 3,
        num_examples_range: tuple[int, int] = (1, 2),
        num_records_range: tuple[int, int] = (1, 3),
    ) -> SampledContext:
        write_tools_all = self.plugin.write_tools()
        max_writes = min(max_writes, len(write_tools_all))
        min_writes = min(min_writes, max_writes) if max_writes else 0

        sequence = (
            self._graph.random_walk(self.rng, min_writes=min_writes, max_writes=max_writes)
            if max_writes
            else []
        )
        tools_by_name = self.plugin.tools_by_name()
        seq_tools = [tools_by_name[n] for n in sequence if n in tools_by_name]
        write_tools = [t for t in seq_tools if t.tool_type == "write"]
        if not write_tools and write_tools_all:
            write_tools = self.rng.sample(write_tools_all, max(min_writes, 1))
        read_tools = [t for t in seq_tools if t.tool_type == "read"]

        accessor = self.plugin.db_accessor()
        user_record = accessor.sample_user(self.rng)
        num_records = self.rng.randint(*num_records_range)
        related_records = accessor.sample_related_records(
            user_record["user_id"], self.rng, k=num_records
        )

        persona_bank = self.plugin.persona_bank()
        persona = self.rng.choice(persona_bank) if persona_bank else ""

        examples = self.plugin.example_tasks()
        num_examples = min(len(examples), self.rng.randint(*num_examples_range))
        sampled_examples = self.rng.sample(examples, num_examples) if num_examples else []

        return SampledContext(
            write_tools=write_tools,
            read_tools=read_tools,
            policy_excerpt=self._sample_policy_excerpt(),
            user_record=user_record,
            related_records=related_records,
            persona=persona,
            examples=sampled_examples,
            suggested_sequence=sequence,
        )

    def _sample_policy_excerpt(self) -> str:
        """Always keep the intro section (core rules like authentication and
        single-user scope) and sample a variable-size subset of the rest, so
        task complexity varies with how many policy constraints are in view.
        """
        sections = _split_into_sections(self.plugin.policy_text())
        if len(sections) <= 1:
            return "\n\n".join(sections)
        rest = list(range(1, len(sections)))
        k = self.rng.randint(max(1, len(rest) // 2), len(rest))
        chosen_rest = sorted(self.rng.sample(rest, k))
        return "\n\n".join(sections[i] for i in [0] + chosen_rest)
