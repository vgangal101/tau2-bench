"""
Empirically test whether telecom's multi-fault composed tasks are sensitive
to the ORDER their fix tool-calls are applied in.

Motivation: compose_tasks() (tasks/utils.py) sorts each composed task's
faults alphabetically by BaseTask.name when building the reference
`evaluation_criteria.actions` trajectory, and generation-time verify_task()
(tasks/manager.py) only checks that ONE order works. Several telecom write
tools have real preconditions on other device state (e.g. `toggle_wifi`
refuses while `airplane_mode` is on -- user_tools.py:661-664), so an agent
that fixes stacked faults in a different order than the alphabetical
reference could hit a blocked/no-op tool call or fail to reach the fixed
state a different way. This script finds concrete instances of that by
replaying each task's reference fix actions in alternate orders against a
fresh environment and checking for blocked calls or failed final
assertions.

Requires the tau2 package (run inside .venv / from a Python that has `src`
on sys.path -- see sys.path.insert below).

Usage:
    python3 benchmark_analysis_scripts/check_telecom_order_sensitivity.py \
        [--num-tasks N] [--max-exhaustive-n N] [--num-random-perms N] [--seed N]

Output: prints a summary and writes full per-task results to
    benchmark_analysis/telecom_order_sensitivity_results.json
"""

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from itertools import permutations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tau2.data_model.tasks import (  # noqa: E402
    EnvAssertion,
    EnvFunctionCall,
    InitializationData,
)
from tau2.registry import registry  # noqa: E402

SOURCE_PATH = REPO_ROOT / "data" / "tau2" / "domains" / "telecom" / "tasks.json"
OUTPUT_PATH = REPO_ROOT / "benchmark_analysis" / "telecom_order_sensitivity_results.json"

BLOCKED_PATTERN = re.compile(r"\bcannot\b|\bfailed to\b|\bnot possible\b", re.IGNORECASE)


def load_multi_fault_tasks():
    """Tasks with >=2 real fix actions, excluding expected-failure
    (transfer_to_human_agents) tasks -- those have nothing to permute."""
    with open(SOURCE_PATH) as f:
        raw_tasks = json.load(f)
    result = []
    for t in raw_tasks:
        actions = (t.get("evaluation_criteria") or {}).get("actions") or []
        if any(a["name"] == "transfer_to_human_agents" for a in actions):
            continue
        if len(actions) < 2:
            continue
        result.append(t)
    return result


def build_fresh_env():
    return registry.get_env_constructor("telecom")()


def apply_initial_state(env, task):
    init = task.get("initial_state") or {}
    init_data_raw = init.get("initialization_data")
    init_data = InitializationData(**init_data_raw) if init_data_raw else None
    init_actions = [
        EnvFunctionCall(**a) for a in (init.get("initialization_actions") or [])
    ]
    env.set_state(
        initialization_data=init_data,
        initialization_actions=init_actions,
        message_history=[],
    )


def run_action_sequence(task, ordered_actions):
    env = build_fresh_env()
    apply_initial_state(env, task)

    blocked = []
    for i, action in enumerate(ordered_actions):
        try:
            result = env.make_tool_call(
                tool_name=action["name"],
                requestor=action.get("requestor", "assistant"),
                **action["arguments"],
            )
        except Exception as e:  # noqa: BLE001
            blocked.append(
                {"step": i, "tool": action["name"], "error": f"EXCEPTION: {e}"}
            )
            continue
        env.sync_tools()
        if isinstance(result, str) and BLOCKED_PATTERN.search(result):
            blocked.append(
                {"step": i, "tool": action["name"], "message": result[:200]}
            )

    assertions = [
        EnvAssertion(**a)
        for a in (task.get("evaluation_criteria") or {}).get("env_assertions") or []
    ]
    failed_assertions = []
    for a in assertions:
        ok = env.run_env_assertion(a, raise_assertion_error=False)
        if not ok:
            failed_assertions.append(a.func_name)

    return {
        "blocked": blocked,
        "final_ok": len(failed_assertions) == 0,
        "failed_assertions": failed_assertions,
    }


def orders_to_test(n, max_exhaustive_n, num_random_perms, rng):
    """Yield index-tuples: identity (reference) first, then either every
    permutation (small n) or reversed + a random sample (large n)."""
    idxs = tuple(range(n))
    seen = {idxs}
    orders = [idxs]

    if n <= max_exhaustive_n:
        for p in permutations(idxs):
            if p not in seen:
                seen.add(p)
                orders.append(p)
        return orders

    reversed_order = tuple(reversed(idxs))
    if reversed_order not in seen:
        seen.add(reversed_order)
        orders.append(reversed_order)

    attempts = 0
    target = num_random_perms + len(orders)
    while len(orders) < target and attempts < num_random_perms * 20:
        p = tuple(rng.sample(idxs, n))
        attempts += 1
        if p not in seen:
            seen.add(p)
            orders.append(p)
    return orders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-tasks", type=int, default=300)
    ap.add_argument("--max-exhaustive-n", type=int, default=5)
    ap.add_argument("--num-random-perms", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    candidates = load_multi_fault_tasks()
    print(f"{len(candidates)} multi-fault (non-unfixable) telecom tasks available")

    # Stratify the sample by fix-action count so both small and large fault
    # stacks are covered, not just whatever sorts first.
    by_n = defaultdict(list)
    for t in candidates:
        by_n[len(t["evaluation_criteria"]["actions"])].append(t)
    for bucket in by_n.values():
        rng.shuffle(bucket)

    sample = []
    ns = sorted(by_n.keys())
    i = 0
    while len(sample) < min(args.num_tasks, len(candidates)):
        n = ns[i % len(ns)]
        if by_n[n]:
            sample.append(by_n[n].pop())
        i += 1
        if all(len(v) == 0 for v in by_n.values()):
            break

    print(f"Testing {len(sample)} tasks (stratified by fix-action count)")

    results = []
    interfering_count = 0
    reference_mismatch_count = 0

    for idx, task in enumerate(sample):
        actions = task["evaluation_criteria"]["actions"]
        n = len(actions)
        orders = orders_to_test(n, args.max_exhaustive_n, args.num_random_perms, rng)

        ref_result = run_action_sequence(task, [actions[i] for i in orders[0]])
        if ref_result["blocked"] or not ref_result["final_ok"]:
            # Reference order (as stored) itself doesn't cleanly resolve --
            # flag separately, this is a different kind of finding.
            reference_mismatch_count += 1

        interfering_orders = []
        for order in orders[1:]:
            ordered_actions = [actions[i] for i in order]
            res = run_action_sequence(task, ordered_actions)
            if res["blocked"] or not res["final_ok"]:
                interfering_orders.append(
                    {
                        "order": [actions[i]["name"] for i in order],
                        "blocked": res["blocked"],
                        "failed_assertions": res["failed_assertions"],
                    }
                )

        is_interfering = len(interfering_orders) > 0
        if is_interfering:
            interfering_count += 1

        results.append(
            {
                "id": task["id"],
                "num_fix_actions": n,
                "num_orders_tested": len(orders),
                "reference_order_ok": not ref_result["blocked"]
                and ref_result["final_ok"],
                "num_interfering_orders": len(interfering_orders),
                "interfering_orders": interfering_orders[:5],  # cap for file size
            }
        )

        if (idx + 1) % 50 == 0:
            print(f"  ...{idx + 1}/{len(sample)} tasks tested")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(
            {
                "config": vars(args),
                "num_tasks_tested": len(sample),
                "num_tasks_order_sensitive": interfering_count,
                "num_reference_order_mismatches": reference_mismatch_count,
                "results": results,
            },
            f,
            indent=2,
        )

    print()
    print(f"=== {len(sample)} tasks tested ===")
    print(
        f"Order-sensitive (>=1 alternate order blocked or failed to reach fixed "
        f"state): {interfering_count} ({100 * interfering_count / len(sample):.1f}%)"
    )
    print(
        f"Reference-order mismatches (stored order itself didn't cleanly "
        f"resolve): {reference_mismatch_count}"
    )
    print(f"Full results written to {OUTPUT_PATH}")

    print("\nTop order-sensitive tasks:")
    shown = 0
    for r in results:
        if r["num_interfering_orders"] > 0:
            print(
                f"  [{r['id'][:80]}] {r['num_interfering_orders']}/"
                f"{r['num_orders_tested'] - 1} alternate orders failed"
            )
            for io in r["interfering_orders"][:1]:
                if io["blocked"]:
                    b = io["blocked"][0]
                    print(f"      order {io['order']}")
                    print(f"      blocked at step {b['step']} ({b['tool']}): "
                          f"{b.get('message', b.get('error'))}")
                elif io["failed_assertions"]:
                    print(f"      order {io['order']}")
                    print(f"      failed assertions: {io['failed_assertions']}")
            shown += 1
        if shown >= 15:
            break


if __name__ == "__main__":
    main()
