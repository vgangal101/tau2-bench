from pathlib import Path
import argparse
import json

import graphviz


def get_args():
    parser = argparse.ArgumentParser(
        description="Visualize an API dependency graph produced by "
        "build_api_dependency_graph.py."
    )
    parser.add_argument(
        "--graph_dir",
        type=str,
        required=True,
        help="Directory containing the <env>_api_dep_graph.json files.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory to write the rendered visualizations to.",
    )
    parser.add_argument(
        "--envs",
        type=str,
        nargs="+",
        default=["airline", "retail"],
        help="Environments to visualize.",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="png",
        help="Output image format (e.g. png, svg, pdf).",
    )
    args = parser.parse_args()
    return args


def visualize_graph(args, env):
    graph_file = Path(args.graph_dir) / f"{env}_api_dep_graph.json"
    with open(graph_file, "r") as fp:
        adj_matrix = json.load(fp)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Iterate the graph: for each tool, an entry in its adjacency list whose
    # shared-parameter list is non-empty is an edge. Collect those edges (and
    # the parameters they share, used as the edge label).
    edges = []
    nodes = set()
    for tool_name, adjacency in adj_matrix.items():
        nodes.add(tool_name)
        for neighbor, shared_params in adjacency.items():
            if not shared_params:
                continue
            nodes.add(neighbor)
            edges.append((tool_name, neighbor, shared_params))

    # Build the visualization from the discovered nodes/edges.
    dot = graphviz.Digraph(
        name=f"{env}_api_dep_graph",
        graph_attr={"rankdir": "LR", "label": f"{env} API dependency graph"},
        node_attr={"shape": "box", "style": "rounded,filled", "fillcolor": "#eef3fb"},
    )
    for node in sorted(nodes):
        dot.node(node)
    for src, dst, shared_params in edges:
        dot.edge(src, dst, label=", ".join(shared_params))

    # graphviz appends the format extension itself, so render with the stem.
    output_stem = output_dir / f"{env}_api_dep_graph"
    dot.render(output_stem, format=args.format, cleanup=True)
    print(f"Wrote {env} visualization to {output_stem}.{args.format}")



def main():
    args = get_args()
    for env in args.envs:
        visualize_graph(args, env)


if __name__ == "__main__":
    main()
