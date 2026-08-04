"""Orchestrates Phase 1 -> Phase 2 -> JSONL dataset writer for one domain.

Rejection sampling (Subsection 4.2, "Trajectory Collection"): each validated
blueprint is attempted up to ``phase2_max_attempts`` times in Phase 2, and
the union of all unique successful trajectories is kept -- not just the
first success.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from apigen_mt.domains.airline import AirlineDomainPlugin
from apigen_mt.domains.base import DomainPlugin
from apigen_mt.domains.retail import RetailDomainPlugin
from apigen_mt.llm_client import AnthropicLLMClient, LLMClient
from apigen_mt.phase1.feedback import GenerationLoopConfig, run_generation_loop
from apigen_mt.phase1.schema import PermanentFailure, ValidatedTask
from apigen_mt.phase2.driver import Phase2Config, TrajectoryResult, build_task, run_phase2_trial

DOMAIN_PLUGINS = {"retail": RetailDomainPlugin, "airline": AirlineDomainPlugin}


def get_plugin(domain: str) -> DomainPlugin:
    if domain not in DOMAIN_PLUGINS:
        raise ValueError(f"Unknown domain {domain!r}. Available: {sorted(DOMAIN_PLUGINS)}")
    return DOMAIN_PLUGINS[domain]()


@dataclass
class RejectionSamplingResult:
    validated: ValidatedTask
    accepted_trajectories: list[TrajectoryResult] = field(default_factory=list)
    attempts: list[TrajectoryResult] = field(default_factory=list)


def _trajectory_signature(result: TrajectoryResult) -> str:
    """A cheap fingerprint of a trajectory's substantive content (tool calls
    + text), used to dedupe rejection-sampling attempts into a *unique*
    successful-trajectory union rather than just counting successes.
    """
    parts = []
    for message in result.simulation.get_messages():
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            parts.append(json.dumps([tc.model_dump() for tc in tool_calls], sort_keys=True, default=str))
        content = getattr(message, "content", None)
        if content:
            parts.append(content)
    return "||".join(parts)


def collect_trajectories(
    validated: ValidatedTask,
    plugin: DomainPlugin,
    phase2_config: Phase2Config,
    rng: random.Random,
    max_attempts: int = 3,
) -> RejectionSamplingResult:
    task = build_task(validated, plugin)
    result = RejectionSamplingResult(validated=validated)
    seen_signatures: set[str] = set()

    for attempt in range(1, max_attempts + 1):
        trial = run_phase2_trial(validated, plugin, phase2_config, rng, attempt_number=attempt, task=task)
        result.attempts.append(trial)
        if trial.success:
            signature = _trajectory_signature(trial)
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                result.accepted_trajectories.append(trial)

    return result


def trajectory_to_record(trajectory: TrajectoryResult, validated: ValidatedTask) -> dict:
    turns = []
    num_tool_calls = 0
    num_user_turns = 0
    for message in trajectory.simulation.get_messages():
        role = message.role
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            for tool_call in tool_calls:
                turns.append({"role": role, "content": None, "tool_call": tool_call.model_dump()})
                num_tool_calls += 1
            continue
        content = getattr(message, "content", None)
        if role == "tool":
            tool_messages = getattr(message, "tool_messages", None)
            if tool_messages:  # MultiToolMessage
                for tm in tool_messages:
                    turns.append({"role": "tool", "content": tm.content, "tool_call": None})
            else:
                turns.append({"role": "tool", "content": content, "tool_call": None})
            continue
        turns.append({"role": role, "content": content, "tool_call": None})
        if role == "user":
            num_user_turns += 1

    return {
        "task_id": trajectory.task.id,
        "domain": validated.blueprint.domain,
        "persona": validated.blueprint.persona,
        "intent": validated.blueprint.intent,
        "groundtruth_actions": [a.model_dump() for a in validated.blueprint.actions],
        "groundtruth_outputs": validated.blueprint.outputs,
        "diff_patch": validated.diff_patch.unified_diff,
        "turns": turns,
        "num_user_turns": num_user_turns,
        "num_tool_calls": num_tool_calls,
        "phase1_judge_scores": [s.model_dump() for s in validated.committee.scores],
        "phase1_retry_count": validated.retry_count,
        "phase2_attempt_number": trajectory.attempt_number,
        "state_based_pass": trajectory.state_based_pass,
        "output_based_pass": trajectory.output_based_pass,
    }


def write_jsonl(records: Sequence[dict], path: str) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


@dataclass
class PipelineConfig:
    domain: str
    num_tasks: int = 10
    phase1_max_retries: int = 3
    committee_threshold: float = 3.0
    phase2_max_attempts: int = 3
    agent_model: str = "gpt-4.1-2025-04-14"
    user_model: str = "gpt-4.1-2025-04-14"
    use_bon: bool = False
    seed: int = 0
    output_path: str = "apigen_mt_dataset.jsonl"


@dataclass
class PipelineStats:
    phase1_validated: int = 0
    phase1_permanent_failures: int = 0
    phase2_trajectories_accepted: int = 0
    tasks_with_at_least_one_success: int = 0
    num_records_written: int = 0

    @property
    def phase1_success_rate(self) -> Optional[float]:
        total = self.phase1_validated + self.phase1_permanent_failures
        return self.phase1_validated / total if total else None


def run_pipeline(
    config: PipelineConfig,
    generator_llm: LLMClient,
    judge_llms: Sequence[LLMClient],
    feedback_llm: LLMClient,
    bon_judge: Optional[LLMClient] = None,
) -> PipelineStats:
    plugin = get_plugin(config.domain)
    rng = random.Random(config.seed)
    stats = PipelineStats()
    records: list[dict] = []

    for _ in range(config.num_tasks):
        loop_result = run_generation_loop(
            plugin,
            generator_llm,
            judge_llms,
            feedback_llm,
            rng,
            config=GenerationLoopConfig(
                max_retries=config.phase1_max_retries, committee_threshold=config.committee_threshold
            ),
        )
        if isinstance(loop_result, PermanentFailure):
            stats.phase1_permanent_failures += 1
            continue
        stats.phase1_validated += 1

        phase2_config = Phase2Config(
            agent_model=config.agent_model,
            user_model=config.user_model,
            use_bon=config.use_bon,
            bon_judge=bon_judge,
        )
        sampling_result = collect_trajectories(
            loop_result, plugin, phase2_config, rng, max_attempts=config.phase2_max_attempts
        )
        if sampling_result.accepted_trajectories:
            stats.tasks_with_at_least_one_success += 1
        stats.phase2_trajectories_accepted += len(sampling_result.accepted_trajectories)
        for trajectory in sampling_result.accepted_trajectories:
            records.append(trajectory_to_record(trajectory, loop_result))

    write_jsonl(records, config.output_path)
    stats.num_records_written = len(records)
    return stats


def _build_default_llm_clients(model: str, num_judges: int) -> tuple[LLMClient, list[LLMClient], LLMClient]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    generator = AnthropicLLMClient(model=model, api_key=api_key, name="generator")
    judges = [
        AnthropicLLMClient(model=model, api_key=api_key, name=f"judge_{i}") for i in range(num_judges)
    ]
    feedback = AnthropicLLMClient(model=model, api_key=api_key, name="feedback")
    return generator, judges, feedback


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="APIGen-MT data synthesis pipeline")
    parser.add_argument("--domain", required=True, choices=sorted(DOMAIN_PLUGINS))
    parser.add_argument("--num-tasks", type=int, default=10)
    parser.add_argument("--phase1-max-retries", type=int, default=3)
    parser.add_argument("--committee-threshold", type=float, default=3.0)
    parser.add_argument("--phase2-max-attempts", type=int, default=3)
    parser.add_argument("--num-judges", type=int, default=3)
    parser.add_argument("--phase1-model", default="claude-sonnet-5")
    parser.add_argument("--agent-model", default="gpt-4.1-2025-04-14")
    parser.add_argument("--user-model", default="gpt-4.1-2025-04-14")
    parser.add_argument("--use-bon", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", default="apigen_mt_dataset.jsonl")
    args = parser.parse_args(argv)

    config = PipelineConfig(
        domain=args.domain,
        num_tasks=args.num_tasks,
        phase1_max_retries=args.phase1_max_retries,
        committee_threshold=args.committee_threshold,
        phase2_max_attempts=args.phase2_max_attempts,
        agent_model=args.agent_model,
        user_model=args.user_model,
        use_bon=args.use_bon,
        seed=args.seed,
        output_path=args.output,
    )
    generator_llm, judge_llms, feedback_llm = _build_default_llm_clients(
        args.phase1_model, args.num_judges
    )
    bon_judge = generator_llm if args.use_bon else None
    stats = run_pipeline(config, generator_llm, judge_llms, feedback_llm, bon_judge=bon_judge)
    print(json.dumps(stats.__dict__, indent=2))


if __name__ == "__main__":
    main()
