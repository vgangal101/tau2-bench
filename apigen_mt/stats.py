"""Success-rate and trajectory statistics, reproducing the paper's Figure 4
/ Figure 5 style reporting (task-config success rate with/without the
agentic feedback loop, turn-count distribution, tool-call/user-turn
averages) for a given run.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence

from apigen_mt.domains.base import DomainPlugin
from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.feedback import GenerationLoopConfig, run_generation_loop
from apigen_mt.phase1.schema import PermanentFailure


@dataclass
class Phase1SuccessRateReport:
    num_samples: int
    success_rate_with_feedback: float
    success_rate_without_feedback: float

    @property
    def feedback_boost_multiplier(self) -> Optional[float]:
        if self.success_rate_without_feedback == 0:
            return None
        return self.success_rate_with_feedback / self.success_rate_without_feedback


def measure_phase1_feedback_boost(
    plugin: DomainPlugin,
    generator_llm: LLMClient,
    judge_llms: Sequence[LLMClient],
    feedback_llm: LLMClient,
    rng: random.Random,
    num_samples: int = 20,
    max_retries_with_feedback: int = 3,
    committee_threshold: float = 3.0,
) -> Phase1SuccessRateReport:
    """Reproduces Figure 4's "Task Config S.R. (Phase 1)" vs "... w/o
    Agentic Feedback" comparison: run the full retry+feedback loop for
    ``num_samples`` fresh blueprints, and separately run a single-shot
    (max_retries=1, so feedback is never consumed) baseline for the same
    number of samples.
    """
    with_feedback_successes = 0
    for _ in range(num_samples):
        result = run_generation_loop(
            plugin,
            generator_llm,
            judge_llms,
            feedback_llm,
            rng,
            config=GenerationLoopConfig(
                max_retries=max_retries_with_feedback, committee_threshold=committee_threshold
            ),
        )
        if not isinstance(result, PermanentFailure):
            with_feedback_successes += 1

    without_feedback_successes = 0
    for _ in range(num_samples):
        result = run_generation_loop(
            plugin,
            generator_llm,
            judge_llms,
            feedback_llm,
            rng,
            config=GenerationLoopConfig(max_retries=1, committee_threshold=committee_threshold),
        )
        if not isinstance(result, PermanentFailure):
            without_feedback_successes += 1

    return Phase1SuccessRateReport(
        num_samples=num_samples,
        success_rate_with_feedback=with_feedback_successes / num_samples,
        success_rate_without_feedback=without_feedback_successes / num_samples,
    )


@dataclass
class TrajectoryStatsReport:
    num_trajectories: int
    phase2_success_rate: Optional[float]
    min_turns: Optional[int]
    max_turns: Optional[int]
    avg_tool_calls: Optional[float]
    avg_user_turns: Optional[float]
    turns_histogram: dict[int, int] = field(default_factory=dict)


def measure_trajectory_stats(
    records: Sequence[dict], phase2_attempts: int = 0, phase2_successes: int = 0
) -> TrajectoryStatsReport:
    """Reproduces Figure 4/5's trajectory-level statistics from dataset
    records as produced by ``pipeline.trajectory_to_record``.
    """
    phase2_success_rate = (phase2_successes / phase2_attempts) if phase2_attempts else None
    if not records:
        return TrajectoryStatsReport(
            num_trajectories=0,
            phase2_success_rate=phase2_success_rate,
            min_turns=None,
            max_turns=None,
            avg_tool_calls=None,
            avg_user_turns=None,
        )

    turn_counts = [len(r["turns"]) for r in records]
    tool_call_counts = [r["num_tool_calls"] for r in records]
    user_turn_counts = [r["num_user_turns"] for r in records]
    histogram: dict[int, int] = {}
    for count in turn_counts:
        histogram[count] = histogram.get(count, 0) + 1

    return TrajectoryStatsReport(
        num_trajectories=len(records),
        phase2_success_rate=phase2_success_rate,
        min_turns=min(turn_counts),
        max_turns=max(turn_counts),
        avg_tool_calls=statistics.mean(tool_call_counts),
        avg_user_turns=statistics.mean(user_turn_counts),
        turns_histogram=histogram,
    )
