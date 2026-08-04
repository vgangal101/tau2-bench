"""Domain-agnostic API dependency graph + random-walk task-sequence sampler.

Nodes are tool names (from ``plugin.tools()``). An edge A -> B means "B's
input arguments can plausibly depend on A's output" -- inferred generically
from pydantic field-name overlap between A's return type and B's parameters,
unioned with any edges the domain plugin hand-annotates. No domain-specific
logic lives here; everything domain-specific comes in through the
``DomainPlugin`` argument.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from apigen_mt.domains.base import DomainPlugin, ToolInfo


@dataclass
class APIGraph:
    plugin: DomainPlugin
    nodes: list[str]
    edges: dict[str, set[str]] = field(default_factory=dict)

    def successors(self, name: str) -> list[str]:
        return sorted(self.edges.get(name, set()))

    def predecessors(self, name: str) -> list[str]:
        return sorted(n for n, succs in self.edges.items() if name in succs)

    def random_walk(
        self,
        rng: random.Random,
        min_writes: int = 1,
        max_writes: int = 3,
        max_len: int = 6,
        prepend_read_prob: float = 0.6,
    ) -> list[str]:
        """Sample a plausible ordered tool-name sequence: pick 1..max_writes
        write tools, optionally prepending one prerequisite read tool per
        write when the graph indicates a dependency, capped at ``max_len``.
        """
        write_names = [t.name for t in self.plugin.write_tools()]
        if not write_names:
            return []
        k = rng.randint(min(min_writes, len(write_names)), min(max_writes, len(write_names)))
        chosen_writes = rng.sample(write_names, k)

        sequence: list[str] = []
        for w in chosen_writes:
            preds = self.predecessors(w)
            read_preds = [
                p for p in preds if self.plugin.tools_by_name()[p].tool_type == "read"
            ]
            if read_preds and rng.random() < prepend_read_prob:
                pred = rng.choice(read_preds)
                if pred not in sequence:
                    sequence.append(pred)
            sequence.append(w)

        # de-dupe consecutive repeats, cap length
        deduped: list[str] = []
        for name in sequence:
            if not deduped or deduped[-1] != name:
                deduped.append(name)
        return deduped[:max_len]


def build_api_graph(plugin: DomainPlugin) -> APIGraph:
    tools = plugin.tools()
    names = [t.name for t in tools]
    edges: dict[str, set[str]] = {n: set() for n in names}

    by_name: dict[str, ToolInfo] = {t.name: t for t in tools}
    for a in tools:
        produced = set(a.produced_fields)
        if not produced:
            continue
        for b in tools:
            if a.name == b.name:
                continue
            if produced & set(b.params_fields):
                edges[a.name].add(b.name)

    for src, dst in plugin.api_graph_edges():
        if src in edges and dst in by_name:
            edges[src].add(dst)

    return APIGraph(plugin=plugin, nodes=names, edges=edges)
