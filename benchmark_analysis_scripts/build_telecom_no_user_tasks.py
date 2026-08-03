"""
Build the 114-task telecom subset used for "no-user mode" (solo) runs
(llm_agent_solo + dummy_user — see launch_scripts/run_telecom_no_user_*.sh).

Selection: proportional stratified sampling from the full 2285-task
data/tau2/domains/telecom/tasks.json, stratified on (purpose, persona) —
9 cells (3 purposes: mobile data / MMS / no-service, x 3 personas:
Easy/Hard/None). Quotas are computed with the largest-remainder method at
two levels (purpose quotas summing to 114, then persona quotas within each
purpose summing to that purpose's quota) so the 114-task subset mirrors the
full dataset's skew (MMS dominates at ~87%) instead of over- or
under-sampling any purpose/persona combination. Ties in the remainder step
are broken by (fractional part desc, persona name asc) for determinism.

Each task is copied verbatim from the source file — `ticket` (solo-mode
prompt) and `evaluation_criteria.actions` (ground-truth reference
trajectory) are already present on every telecom task and are NOT modified.

Reproducible via a fixed random seed (see SEED below). Rerunning this
script produces the exact same 114 task IDs.

Run: python3 benchmark_analysis_scripts/build_telecom_no_user_tasks.py
"""

import json
import random
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = REPO_ROOT / "data" / "tau2" / "domains" / "telecom" / "tasks.json"
OUTPUT_PATH = REPO_ROOT / "benchmark_analysis" / "telecom_no_user_mode_tasks.json"

TARGET_TOTAL = 114
SEED = 42


def persona_of(task):
    m = re.search(r"\[PERSONA:([^\]]*)\]", task["id"])
    return m.group(1) if m else "None"


def largest_remainder_quotas(counts_by_key, target_total):
    """Round counts_by_key (dict[key, int]) proportionally so quotas sum to
    target_total, using the largest-remainder method. Ties broken by
    (fractional part desc, key asc) for determinism."""
    total = sum(counts_by_key.values())
    raw = {k: v * target_total / total for k, v in counts_by_key.items()}
    floors = {k: int(v) for k, v in raw.items()}
    remainder = target_total - sum(floors.values())
    fracs = sorted(
        raw.keys(), key=lambda k: (-(raw[k] - floors[k]), k)
    )
    quotas = dict(floors)
    for k in fracs[:remainder]:
        quotas[k] += 1
    assert sum(quotas.values()) == target_total
    return quotas


def main():
    with open(SOURCE_PATH) as f:
        all_tasks = json.load(f)

    by_purpose = defaultdict(list)
    for t in all_tasks:
        by_purpose[t["description"]["purpose"]].append(t)

    purpose_counts = {p: len(ts) for p, ts in by_purpose.items()}
    purpose_quotas = largest_remainder_quotas(purpose_counts, TARGET_TOTAL)

    rng = random.Random(SEED)
    selected = []
    summary_lines = []

    for purpose, purpose_tasks in by_purpose.items():
        by_persona = defaultdict(list)
        for t in purpose_tasks:
            by_persona[persona_of(t)].append(t)

        persona_counts = {p: len(ts) for p, ts in by_persona.items()}
        persona_quotas = largest_remainder_quotas(
            persona_counts, purpose_quotas[purpose]
        )

        for persona, persona_tasks in by_persona.items():
            quota = persona_quotas[persona]
            sample = rng.sample(persona_tasks, quota)
            selected.extend(sample)
            summary_lines.append(
                f"  {purpose[:45]:47s} persona={persona:5s} "
                f"{quota:3d}/{len(persona_tasks)}"
            )

    assert len(selected) == TARGET_TOTAL, len(selected)

    # Verify ground truth is intact on every selected task.
    missing_ticket = [t["id"] for t in selected if not t.get("ticket")]
    missing_actions = [
        t["id"]
        for t in selected
        if not (t.get("evaluation_criteria") or {}).get("actions")
    ]
    if missing_ticket:
        raise AssertionError(f"{len(missing_ticket)} tasks missing ticket")
    if missing_actions:
        raise AssertionError(
            f"{len(missing_actions)} tasks missing evaluation_criteria.actions"
        )

    rng.shuffle(selected)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(selected, f, indent=2)

    print(f"Wrote {len(selected)} tasks to {OUTPUT_PATH}")
    print(f"Purpose quotas (of {TARGET_TOTAL}): {purpose_quotas}")
    print("Per-cell breakdown:")
    for line in summary_lines:
        print(line)
    print(
        f"All {len(selected)} tasks have non-null ticket and "
        f"non-empty evaluation_criteria.actions."
    )


if __name__ == "__main__":
    main()
