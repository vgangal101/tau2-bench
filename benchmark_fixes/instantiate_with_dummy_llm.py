#!/usr/bin/env python3
"""Instantiate a tau2-bench run using a dummy LLM -- no API key, no network calls.

Uses litellm's `mock_response` kwarg (threaded through via llm_args) so both the
agent and user simulator LLM calls are short-circuited locally. This is meant as
a fast, offline way to exercise the run-construction path (build_environment ->
build_agent -> build_user -> Orchestrator) without needing real credentials.

Defaults reproduce the telecom "no-user mode" ablation from docs/cli-reference.md
(--agent llm_agent_solo --user dummy_user), which currently fails during
build_user() -- see the DummyUser kwargs bug in src/tau2/runner/build.py.

Usage:
    python benchmark_fixes/instantiate_with_dummy_llm.py
    python benchmark_fixes/instantiate_with_dummy_llm.py --domain mock --agent llm_agent --user user_simulator
"""

import argparse
import sys
import traceback

from tau2.data_model.simulation import TerminationReason, TextRunConfig
from tau2.runner.batch import run_domain

MOCK_RESPONSE = "This is a mock response from a dummy LLM used to smoke-test the benchmark."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="telecom")
    parser.add_argument("--agent", default="llm_agent_solo")
    parser.add_argument("--user", default="dummy_user")
    parser.add_argument("--num-tasks", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=2)
    args = parser.parse_args()

    config = TextRunConfig(
        domain=args.domain,
        agent=args.agent,
        user=args.user,
        llm_agent="gpt-4o-mini",
        llm_args_agent={"mock_response": MOCK_RESPONSE},
        llm_user="gpt-4o-mini",
        llm_args_user={"mock_response": MOCK_RESPONSE},
        num_tasks=args.num_tasks,
        num_trials=1,
        max_steps=args.max_steps,
        max_concurrency=1,
        auto_resume=True,
    )

    print(
        f"Instantiating benchmark: domain={args.domain!r} agent={args.agent!r} "
        f"user={args.user!r} (dummy LLM, no network calls)\n"
    )

    try:
        results = run_domain(config)
    except Exception:
        print("\nFAILED -- benchmark instantiation raised an exception:\n")
        traceback.print_exc()
        return 1

    infra_errors = [
        sim
        for sim in results.simulations
        if sim.termination_reason == TerminationReason.INFRASTRUCTURE_ERROR
    ]
    if infra_errors:
        print(
            f"\nFAILED -- {len(infra_errors)}/{len(results.simulations)} "
            "simulation(s) ended in INFRASTRUCTURE_ERROR (a bug in the run "
            "pipeline, not the LLM/task). Last error message:\n"
        )
        print(f"  {infra_errors[-1].info.get('error', '(no error message captured)')}")
        return 1

    print(f"\nOK -- completed {len(results.simulations)} simulation(s), no infra errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
