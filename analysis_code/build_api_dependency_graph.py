from pathlib import Path
import argparse
import typing 
from typing import *
import json
from tau2.environment.toolkit import ToolType
from tau2.domains.airline.data_model import * 
from tau2.domains.retail.data_model import * 
import importlib
from functools import lru_cache

from schema_types import annotation_to_str


@lru_cache(maxsize=None)
def resolve_db_entity(env: str, entity_name: str):
    """Dynamically resolve an entity-name string to its pydantic class.

    The schema records a tool's output entity as a bare name (e.g.
    "Reservation"); the actual class lives in ``tau2.domains.<env>.data_model``.
    Returns the class, or None for scalars / unknown names (e.g. "str").
    """
    module = importlib.import_module(f"tau2.domains.{env}.data_model")
    return getattr(module, entity_name, None)


def is_identifier(name: str) -> bool:
    """Whether a field/argument name denotes an entity identifier.

    Real API dependencies flow through identifiers (primary/foreign keys) that
    one tool produces and another consumes -- e.g. ``reservation_id``,
    ``user_id``, ``flight_number`` -- not through descriptive attributes the
    agent supplies fresh (``origin``, ``cabin``, ``total_baggages``). Matches
    the ``_id`` / ``_number`` convention used by the domain data models.
    """
    return name.endswith("_id") or name.endswith("_number")


def get_entity_fields(entity_cls) -> dict:
    """Collect an entity's fields with their type annotations.

    Returns a mapping of field name -> annotation (the typing object, e.g.
    ``str``, ``Optional[int]``, ``list[Passenger]``). Returns an empty dict for
    scalars / unresolved entities (``entity_cls`` is None).
    """
    if entity_cls is None:
        return {}
    return {
        name: field.annotation
        for name, field in entity_cls.model_fields.items()
    }


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema_dir",type=str)
    parser.add_argument("--output_dir",type=str)
    args = parser.parse_args()
    return args 


def build_graph(args, env): 
    # represent graph as an adjacency matrix
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{env}_api_dep_graph.json"
    # access the schema file
    schema_file = Path(args.schema_dir) / f"{env}_augmented_schema.json"

    with open(schema_file, 'r') as fp:
        schema_loaded = json.load(fp)

    tools = schema_loaded['tools']

    # needs to also be consistent with domain policy -> make the policy checks !!!!!
    # an exercise: can you make this graph_building algorithm faster ?
    # need to run through each
    adj_matrix = {}
    for t_a, tool_def_a in tools.items():
        if tool_def_a['type'] == ToolType.READ:
            continue

        # Determine t_a's produced *identifiers*: the entity ids it returns
        # that a downstream tool could consume to address the same entity.
        # Only identifier fields count -- descriptive attributes (origin,
        # cabin, baggage counts) are supplied fresh by the agent and are not
        # data dependencies.
        #   * DB entity output -> the entity's identifier fields (name + type).
        #   * single scalar output -> one unnamed value; with no field name it
        #     cannot be recognized as an identifier, so it produces no edges.
        tool_def_a_output = tool_def_a['output']
        if tool_def_a_output['is_db_entity']:
            entity_cls = resolve_db_entity(env, tool_def_a_output['entity'])
            produced_ids = {
                pname: annotation_to_str(ann)
                for pname, ann in get_entity_fields(entity_cls).items()
                if is_identifier(pname)
            }
        else:
            produced_ids = {}

        if t_a not in adj_matrix:
            adj_matrix[t_a] = {}
        for t_b, tool_def_b in tools.items():
            if t_b == t_a:
                continue

            # The dependency graph is limited to write methods: skip read
            # consumers, only other writes can depend on a write's output.
            if tool_def_b['type'] == ToolType.READ:
                continue

            # An edge t_a -> t_b exists when t_b consumes an identifier that
            # t_a produces, matched on BOTH name and type.
            input_args_b = tool_def_b['inputs']  # name -> type str
            matched_args = [
                name
                for name, ptype in produced_ids.items()
                if input_args_b.get(name) == ptype
            ]
            if matched_args:
                adj_matrix[t_a][t_b] = matched_args

    with open(output_file, 'w') as fp:
        json.dump(adj_matrix, fp, indent=2)
        
    print(f"Wrote {env} API dependency graph to {output_file}")

def main(): 
    args = get_args()
    
    envs = ['airline','retail']
    for e in envs: 
        build_graph(args, e)



if __name__ == "__main__": 
    main()