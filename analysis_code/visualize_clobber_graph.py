"""Visualize a clobber state graph produced by build_clobber_graph.py.

Red edges indicate that the source tool's effects can invalidate the target
tool's preconditions.  Edge labels show which field is clobbered.
"""

import argparse
import json
import re
from pathlib import Path

import graphviz

ENVS = ["airline", "retail"]


def _short_label(descriptions: list[str]) -> str:
    """Condense a list of clobber descriptions to a compact edge label.

    Extracts the 'table.field' portion from each description and deduplicates,
    so long descriptions like "orders.status: set→'cancelled' invalidates ..."
    become just "orders.status".
    """
    fields = []
    for desc in descriptions:
        m = re.match(r"(\S+\.\S+):", desc)
        if m:
            field = m.group(1)
            if field not in fields:
                fields.append(field)
        else:
            fields.append(desc)
    return "\n".join(fields)


def visualize_graph(args, env: str) -> None:
    graph_file = Path(args.graph_dir) / f"{env}_clobber_graph.json"
    with open(graph_file) as f:
        adj = json.load(f)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes: set[str] = set()
    edges: list[tuple[str, str, list[str]]] = []
    for tool_name, neighbors in adj.items():
        nodes.add(tool_name)
        for neighbor, descriptions in neighbors.items():
            if descriptions:
                nodes.add(neighbor)
                edges.append((tool_name, neighbor, descriptions))

    dot = graphviz.Digraph(
        name=f"{env}_clobber_graph",
        graph_attr={
            "rankdir": "LR",
            "label": f"{env} clobber state graph",
            "fontsize": "14",
        },
        node_attr={
            "shape": "box",
            "style": "rounded,filled",
            "fillcolor": "#fff3e0",
        },
        edge_attr={
            "color": "#c0392b",
            "fontcolor": "#c0392b",
            "fontsize": "9",
        },
    )
    for node in sorted(nodes):
        dot.node(node)
    for src, dst, descriptions in edges:
        dot.edge(src, dst, label=_short_label(descriptions))

    output_stem = output_dir / f"{env}_clobber_graph"
    dot.render(str(output_stem), format=args.format, cleanup=True)
    print(f"Wrote {env} visualization to {output_stem}.{args.format}")


def get_args():
    parser = argparse.ArgumentParser(
        description="Visualize a clobber state graph produced by build_clobber_graph.py."
    )
    parser.add_argument(
        "--graph_dir",
        type=str,
        required=True,
        help="Directory containing <env>_clobber_graph.json files.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory to write rendered visualizations to.",
    )
    parser.add_argument(
        "--envs",
        type=str,
        nargs="+",
        default=ENVS,
        help="Environments to visualize.",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="png",
        help="Output image format (png, svg, pdf).",
    )
    return parser.parse_args()


def main():
    args = get_args()
    for env in args.envs:
        visualize_graph(args, env)


if __name__ == "__main__":
    main()
