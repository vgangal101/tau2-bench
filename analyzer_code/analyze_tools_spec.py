# for each tool retrieve tool name, arguments, and DB models used in the tool
# Unified across domains (retail + airline). Select the environment with --env.
import argparse
from pathlib import Path
import json

from tau2.environment.toolkit import get_tool_signatures

from tau2.domains.retail.tools import RetailTools
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.utils import RETAIL_DB_PATH

from tau2.domains.airline.tools import AirlineTools
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.airline.utils import AIRLINE_DB_PATH


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
    return {name: signature.model_dump() for name, signature in schema.items()}


def get_tool_schemas(env, schema_dir):
    """Extract and write the tool signatures for a single environment."""
    schema_file = schema_dir / f"{env}_tool_signatures.json"
    toolset = ENV_REGISTRY[env]()
    toolschema = get_tool_signatures(toolset)

    schema_processed = process_tool_signatures(toolschema)

    with open(schema_file, 'w') as f:
        json.dump(schema_processed, f, indent=2)

    print(f"Wrote {len(schema_processed)} {env} tool signatures to {schema_file}")


def main():
    args = get_args()

    artifacts_dir = Path("analyzer_code/artifacts")
    schema_dir = artifacts_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    envs = list(ENV_REGISTRY.keys()) if args.env == "all" else [args.env]
    for env in envs:
        get_tool_schemas(env, schema_dir)


if __name__ == "__main__":
    main()
