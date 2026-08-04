"""Stage 3: Final Semantic Review & Refinement, plus the generate-validate
retry loop that ties samplers -> generator -> Stage 1 -> Stage 2 -> feedback
together (Subsection 4.1, steps 1-5).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Union

from apigen_mt.domains.base import DomainPlugin
from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.committee import run_committee, task_object_text
from apigen_mt.phase1.generator import GenerationParseError, generate_blueprint
from apigen_mt.phase1.samplers import ContextSampler
from apigen_mt.phase1.schema import (
    FormatCheckResult,
    PermanentFailure,
    Stage1Result,
    Stage2Result,
    TaskBlueprint,
    ValidatedTask,
    ValidationAttempt,
)
from apigen_mt.phase1.validators import run_stage1

FEEDBACK_SYSTEM_PROMPT = (
    "You are responsible for analyzing and summarizing feedback from multiple AI judges "
    "or automated validation failures. Your primary goal is to provide clear, actionable "
    "feedback that will help the generator LLM improve its next attempt. You do not "
    "evaluate the task directly; instead you review and ground the existing feedback."
)

FEEDBACK_PROMPT_TEMPLATE = """
## Review Process
- Begin by analyzing the individual failure reason(s) below.
- Summarize common points of agreement or disagreement.
- Offer a concise summary of actionable feedback to send back to the data generator, aimed at \
improving the next round of data quality.

## Generated Task Data
{task_object}

## Failure Reasons / Judges' Feedback
{feedback_sources}

## Output Format
Enclose your reasoning within <thought></thought> tags, and the final summary of actionable feedback \
within <summary></summary> tags.
""".strip()

_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


def summarize_feedback(blueprint: TaskBlueprint, failure_text: str, llm: LLMClient) -> str:
    prompt = FEEDBACK_PROMPT_TEMPLATE.format(
        task_object=task_object_text(blueprint), feedback_sources=failure_text
    )
    raw = llm.complete(system=FEEDBACK_SYSTEM_PROMPT, user=prompt, temperature=0.3)
    match = _SUMMARY_RE.search(raw)
    return match.group(1).strip() if match else raw.strip()


@dataclass
class GenerationLoopConfig:
    max_retries: int = 3
    committee_threshold: float = 3.0
    min_writes: int = 1
    max_writes: int = 3


def run_generation_loop(
    plugin: DomainPlugin,
    generator_llm: LLMClient,
    judge_llms: Sequence[LLMClient],
    feedback_llm: LLMClient,
    rng: random.Random,
    config: Optional[GenerationLoopConfig] = None,
) -> Union[ValidatedTask, PermanentFailure]:
    """Generate-validate-refine loop. ``config.max_retries=1`` reproduces the
    "without agentic feedback" baseline (single attempt, no feedback ever
    used) so the with/without success-rate delta can be measured directly by
    calling this twice with different configs -- see stats.py.
    """
    config = config or GenerationLoopConfig()
    sampler = ContextSampler(plugin, rng)
    context = sampler.sample(min_writes=config.min_writes, max_writes=config.max_writes)

    history: list[ValidationAttempt] = []
    feedback_text: Optional[str] = None

    for attempt in range(1, config.max_retries + 1):
        try:
            blueprint = generate_blueprint(plugin, generator_llm, context, feedback=feedback_text)
        except GenerationParseError as exc:
            placeholder = TaskBlueprint(domain=plugin.name, persona=context.persona, intent="")
            stage1 = Stage1Result(
                format_check=FormatCheckResult(passed=False, errors=[str(exc)])
            )
            history.append(
                ValidationAttempt(attempt_number=attempt, blueprint=placeholder, stage1=stage1)
            )
            feedback_text = summarize_feedback(placeholder, str(exc), feedback_llm)
            continue

        stage1 = run_stage1(blueprint, plugin)
        if not stage1.passed:
            history.append(
                ValidationAttempt(attempt_number=attempt, blueprint=blueprint, stage1=stage1)
            )
            feedback_text = summarize_feedback(blueprint, stage1.failure_summary, feedback_llm)
            continue

        committee = run_committee(
            blueprint,
            stage1.execution_check,
            plugin,
            judge_llms,
            threshold=config.committee_threshold,
        )
        stage2 = Stage2Result(committee=committee)
        history.append(
            ValidationAttempt(
                attempt_number=attempt, blueprint=blueprint, stage1=stage1, stage2=stage2
            )
        )

        if stage2.passed:
            return ValidatedTask(
                blueprint=blueprint,
                diff_patch=stage1.execution_check.diff_patch,
                committee=committee,
                retry_count=attempt - 1,
                history=history,
            )

        feedback_text = summarize_feedback(blueprint, stage2.failure_summary, feedback_llm)

    return PermanentFailure(
        domain=plugin.name,
        persona=context.persona,
        retry_count=config.max_retries,
        history=history,
        final_failure_summary=feedback_text or "Exhausted retries with no usable feedback.",
    )
