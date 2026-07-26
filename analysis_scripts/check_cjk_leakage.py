#!/usr/bin/env python
"""Scan a tau2 results.json for CJK characters in assistant message content.

Used as a quick smoke-test check for language leakage/code-switching when
running a non-CJK-prompted domain (e.g. telecom) against a model that may
occasionally emit Chinese/Japanese/Korean characters in otherwise-English
output.

Usage:
    python analysis_scripts/check_cjk_leakage.py path/to/results.json
"""

import json
import re
import sys
from pathlib import Path

# Common CJK Unicode blocks: CJK Unified Ideographs, Extension A,
# Hiragana/Katakana, Hangul syllables. Covers Chinese/Japanese/Korean.
CJK_PATTERN = re.compile(
    r"[一-鿿㐀-䶿぀-ヿ가-힯]"
)


def find_cjk_spans(text: str, context: int = 20) -> list[str]:
    """Return one context snippet per contiguous run of CJK characters."""
    runs: list[tuple[int, int]] = []
    for match in CJK_PATTERN.finditer(text):
        if runs and match.start() <= runs[-1][1] + context:
            runs[-1] = (runs[-1][0], match.end())
        else:
            runs.append((match.start(), match.end()))

    spans = []
    for start, end in runs:
        snippet_start = max(0, start - context)
        snippet_end = min(len(text), end + context)
        spans.append(text[snippet_start:snippet_end].replace("\n", " "))
    return spans


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())
    simulations = data.get("simulations", [])

    total_messages = 0
    flagged = []

    for sim in simulations:
        task_id = sim.get("task_id")
        for msg in sim.get("messages", []):
            content = msg.get("content")
            if not content:
                continue
            total_messages += 1
            spans = find_cjk_spans(content)
            if spans:
                flagged.append(
                    {
                        "task_id": task_id,
                        "simulation_id": sim.get("id"),
                        "role": msg.get("role"),
                        "spans": spans,
                    }
                )

    print(f"Scanned {len(simulations)} simulations, {total_messages} messages with text content.")
    if not flagged:
        print("No CJK characters found. No leakage detected in this run.")
        return

    print(f"\nCJK characters found in {len(flagged)} message(s):\n")
    for entry in flagged:
        print(f"- task={entry['task_id']} role={entry['role']} sim={entry['simulation_id']}")
        for span in entry["spans"]:
            print(f"    ...{span}...")


if __name__ == "__main__":
    main()
