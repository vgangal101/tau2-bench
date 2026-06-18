# for each tool retrieve tool name, arguments, and DB models used in the tool
# Unified across domains (retail + airline). Select the environment with --env.
import argparse
import copy
from pathlib import Path
import json

from tau2.environment.toolkit import get_tool_signatures, ToolType
from tau2.environment.tool import Tool
from tau2.domains.retail.tools import RetailTools
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.utils import RETAIL_DB_PATH

from tau2.domains.airline.tools import AirlineTools
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.airline.utils import AIRLINE_DB_PATH

from tau2.environment.tool import Tool
import typing 


# Registry mapping an environment name to how its toolkit is constructed.
# Each entry returns an instantiated ToolKitBase whose signatures we extract.
ENV_REGISTRY = {
    "retail": lambda: RetailTools(RetailDB.load(RETAIL_DB_PATH)),
    "airline": lambda: AirlineTools(FlightDB.load(AIRLINE_DB_PATH)),
}


def get_args():
    parser = argparse.ArgumentParser(
        description="Retrieve tool specifications for a tau2 environment."
    )
    parser.add_argument(
        "--env",
        choices=list(ENV_REGISTRY.keys()) + ["all"],
        default="all",
        help="Which environment's tool schema to analyze (default: all).",
    )
    parser.add_argument("--schema-version",type=int, choices=[1,2,3],
                        default=1)
    args = parser.parse_args()
    return args


def process_tool_signatures(schema):
    """
    Parameters:
        schema: dict
            maps tool name -> ToolSignature (a pydantic BaseModel)

    Returns:
        schema_processed: dict
            maps tool name -> plain JSON-serializable dict of the signature
    """
    for name, signature in schema.items(): 
        print("name:", name)
        print("signature:", signature)
        print("\n")

    #return {name: signature.model_dump() for name, signature in schema.items()}


def get_tool_schemas(env, schema_dir):
    """Extract and write the tool signatures for a single environment."""
    schema_file = schema_dir / f"{env}_tool_signatures.json"
    toolset = ENV_REGISTRY[env]()
    toolschema = get_tool_signatures(toolset)

    schema_processed = process_tool_signatures(toolschema)

    with open(schema_file, 'w') as f:
        json.dump(schema_processed, f, indent=2)

    print(f"Wrote {len(schema_processed)} {env} tool signatures to {schema_file}")


def openai_schema(env, schema_dir):

    schema_file = schema_dir / f'{env}_openai_schema.json'
    toolset: typing.Union[RetailTools, AirlineTools] = ENV_REGISTRY[env]()

    read_tools = {}
    write_tools = {}

    env_tools = toolset.get_tools()
    for name, tool in env_tools.items():
        # tool_type is not an attribute on the Tool; it's read via the toolkit,
        # which returns a ToolType enum (values are lowercase: "read"/"write"/...).
        tool_type = toolset.tool_type(name)
        if tool_type == ToolType.WRITE:
            write_tools[name] = tool.openai_schema  # property, not a method call
        elif tool_type == ToolType.READ:
            read_tools[name] = tool.openai_schema

    full_schema = {**read_tools, **write_tools}

    with open(schema_file, 'w') as f:
        json.dump(full_schema, f, indent=2)
    
    # given you have access to the toolset how would you extract the schema
    # this is so that you have access to the type hints and data models to create the API-Dependency-Graphs, and state cancellation graphs




def main():
    args = get_args()

    artifacts_dir = Path("analyzer_code/artifacts")
    schema_dir = artifacts_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    envs = list(ENV_REGISTRY.keys()) if args.env == "all" else [args.env]

    if args.schema_version == 1: 
        processor = get_tool_schemas
    elif args.schema_version == 2: 
        processor = openai_schema

    for env in envs:
        processor(env, schema_dir)


if __name__ == "__main__":
    main()
