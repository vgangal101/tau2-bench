#!/usr/bin/env python
"""Dump the telecom domain's tool definitions as readable JSON.

Usage:
    python scripts/dump_telecom_tools.py [-o output.json] [--include-discoverable]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tau2.domains.telecom.data_model import TelecomDB
from tau2.domains.telecom.tools import TelecomTools
from tau2.domains.telecom.utils import TELECOM_DB_PATH


def build_tool_entry(name: str, tool, tool_type: str, mutates_state: bool) -> dict:
    return {
        "name": name,
        "type": tool_type,
        "mutates_state": mutates_state,
        "description": tool._get_description(),
        "parameters": tool.params.model_json_schema(),
        "returns": tool.returns.model_json_schema(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Path to write the JSON output to (defaults to stdout).",
    )
    parser.add_argument(
        "--include-discoverable",
        action="store_true",
        help="Also include discoverable (hidden/unlockable) tools.",
    )
    args = parser.parse_args()

    db = TelecomDB.load(TELECOM_DB_PATH)
    toolkit = TelecomTools(db)

    tools = toolkit.get_tools()
    entries = [
        build_tool_entry(
            name, tool, toolkit.tool_type(name), toolkit.tool_mutates_state(name)
        )
        for name, tool in tools.items()
    ]

    if args.include_discoverable:
        for name, func in toolkit.get_discoverable_tools().items():
            from tau2.environment.tool import as_tool

            tool = as_tool(func)
            entries.append(
                build_tool_entry(
                    name, tool, toolkit.tool_type(name), toolkit.tool_mutates_state(name)
                )
            )

    entries.sort(key=lambda e: e["name"])
    output = json.dumps(entries, indent=2, default=str)

    if args.output:
        args.output.write_text(output + "\n")
        print(f"Wrote {len(entries)} tool definitions to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
