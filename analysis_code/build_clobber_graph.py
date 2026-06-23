"""Build a clobber state graph from augmented tool schemas.

An edge A → B in the clobber graph means that at least one of A's effects
can invalidate at least one of B's preconditions.  Running A before B may
therefore cause B to fail.

Clobber rules
-------------
Only field_set effects are checked (list_append / record_create do not
invalidate any precondition kind we currently capture):

    field_set(table, field, to=X)  ×  field_equals(table, field, value=Y)
        → clobbers when X ≠ Y  (A leaves field in wrong state for B)

    field_set(table, field, to=X)  ×  field_not_equals(table, field, value=Y)
        → clobbers when X == Y  (A leaves field in forbidden state for B)

    field_set(table, field="status", ...)  ×  opaque_predicate(table=same)
        → always clobbers (conservative: all opaque predicates in these
          domains are status checks, so any status mutation is a conflict)
"""

import argparse
import json
from pathlib import Path


ENVS = ["airline", "retail"]


def _clobber_description(effect: dict, precond: dict) -> str | None:
    """Return a human-readable description if effect invalidates precond, else None."""
    if effect["kind"] != "field_set":
        return None

    e_table = effect.get("table")
    e_field = effect.get("field")
    e_to = effect.get("to", effect.get("from_input", "<derived>"))

    if precond["kind"] == "field_equals":
        if e_table == precond.get("table") and e_field == precond.get("field"):
            req = precond["value"]
            if str(e_to) != str(req):
                return (
                    f"{e_table}.{e_field}: "
                    f"set→'{e_to}' invalidates requires='{req}'"
                )

    elif precond["kind"] == "field_not_equals":
        if e_table == precond.get("table") and e_field == precond.get("field"):
            forbidden = precond["value"]
            if str(e_to) == str(forbidden):
                return (
                    f"{e_table}.{e_field}: "
                    f"set→'{e_to}' invalidates not_equals='{forbidden}'"
                )

    elif precond["kind"] == "opaque_predicate":
        # Conservative: any status mutation on the same table conflicts with
        # an opaque status predicate on that table.
        if e_table == precond.get("table") and e_field == "status":
            pred = precond.get("predicate", "unknown")
            return (
                f"{e_table}.{e_field}: "
                f"set→'{e_to}' may invalidate opaque_predicate '{pred}'"
            )

    return None


def build_clobber_graph(schema: dict) -> dict:
    """Compute the clobber adjacency list for a single domain schema."""
    tools = schema["tools"]
    write_tools = {
        name: defn for name, defn in tools.items() if defn["type"] == "write"
    }

    adj: dict[str, dict[str, list[str]]] = {}

    for name_a, defn_a in write_tools.items():
        adj.setdefault(name_a, {})
        effects_a = defn_a.get("effects", [])
        if not effects_a:
            continue

        for name_b, defn_b in write_tools.items():
            if name_b == name_a:
                continue
            preconditions_b = defn_b.get("preconditions", [])
            if not preconditions_b:
                continue

            clobbers = []
            for effect in effects_a:
                for precond in preconditions_b:
                    desc = _clobber_description(effect, precond)
                    if desc and desc not in clobbers:
                        clobbers.append(desc)

            if clobbers:
                adj[name_a][name_b] = clobbers

    return adj


def get_args():
    parser = argparse.ArgumentParser(
        description="Build a clobber state graph from augmented tool schemas."
    )
    parser.add_argument(
        "--schema_dir",
        type=str,
        required=True,
        help="Directory containing <env>_augmented_schema.json files.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory to write <env>_clobber_graph.json files to.",
    )
    parser.add_argument(
        "--envs",
        type=str,
        nargs="+",
        default=ENVS,
        help="Environments to process.",
    )
    return parser.parse_args()


def main():
    args = get_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for env in args.envs:
        schema_file = Path(args.schema_dir) / f"{env}_augmented_schema.json"
        with open(schema_file) as f:
            schema = json.load(f)

        adj = build_clobber_graph(schema)

        out_file = output_dir / f"{env}_clobber_graph.json"
        with open(out_file, "w") as f:
            json.dump(adj, f, indent=2)
        print(f"Wrote {env} clobber graph to {out_file}")


if __name__ == "__main__":
    main()
