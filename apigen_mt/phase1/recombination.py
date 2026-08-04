"""Reverse Task Recombination (Subsection 4.1.3): build complex tasks from
simpler, independently-validated building blocks that share a persona.
"""

from __future__ import annotations

import random
import re
from typing import Optional, Sequence, Union

from apigen_mt.domains.base import DomainPlugin
from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.committee import run_committee, task_object_text
from apigen_mt.phase1.feedback import summarize_feedback
from apigen_mt.phase1.schema import (
    ExecutionCheckResult,
    FormatCheckResult,
    PermanentFailure,
    PolicyCheckResult,
    Stage1Result,
    Stage2Result,
    TaskBlueprint,
    ValidatedTask,
    ValidationAttempt,
)
from apigen_mt.phase1.validators import execution_check, policy_check

COMBINE_SYSTEM_PROMPT = (
    "You are a data-generation agent that combines several already-validated sub-tasks "
    "into a single, coherent, more complex user request for the same persona."
)

COMBINE_PROMPT_TEMPLATE = """
## Instructions
Below are {n} previously validated tasks for the same user persona. Synthesize ONE new, coherent user \
instruction that logically frames all of their actions as a single combined request from the user. Do \
not simply concatenate the separate instructions -- write it as one natural, overarching request a \
real person would make in a single conversation.

## Persona
{persona}

## Component Tasks
{components}

## Output Format
Enclose your reasoning within <thought></thought> tags, and the combined instruction (plain text, not \
JSON -- just the new instruction string) within <answer></answer> tags.
""".strip()

_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


class RecombinationRejected(Exception):
    """The concatenated action sequence failed execution or policy re-check."""


def same_persona(tasks: Sequence[ValidatedTask]) -> bool:
    return len({t.blueprint.persona for t in tasks}) == 1


def combine_blueprints(
    tasks: Sequence[ValidatedTask],
    plugin: DomainPlugin,
    llm: LLMClient,
    feedback: Optional[str] = None,
) -> TaskBlueprint:
    if len(tasks) < 2:
        raise ValueError("Recombination requires at least 2 component tasks")
    if not same_persona(tasks):
        raise ValueError("Recombination requires all component tasks to share a persona")

    combined_actions = [a for t in tasks for a in t.blueprint.actions]
    combined_outputs = [o for t in tasks for o in t.blueprint.outputs]

    components_text = "\n\n".join(
        f"### Component {i + 1}\n{task_object_text(t.blueprint)}" for i, t in enumerate(tasks)
    )
    prompt = COMBINE_PROMPT_TEMPLATE.format(
        n=len(tasks), persona=tasks[0].blueprint.persona or "(none)", components=components_text
    )
    if feedback:
        prompt += f"\n\n## Feedback From Previous Attempt\n{feedback}\n"

    raw = llm.complete(system=COMBINE_SYSTEM_PROMPT, user=prompt, temperature=0.7)
    match = _ANSWER_RE.search(raw)
    combined_intent = match.group(1).strip() if match else raw.strip()

    return TaskBlueprint(
        domain=plugin.name,
        persona=tasks[0].blueprint.persona,
        intent=combined_intent,
        actions=combined_actions,
        outputs=combined_outputs,
        source_blueprint_ids=[t.blueprint.blueprint_id for t in tasks],
    )


def recheck_combined_policy(
    blueprint: TaskBlueprint, plugin: DomainPlugin
) -> ExecutionCheckResult:
    """Re-run execution and policy compliance on the concatenated action
    sequence. Stage 1's LLM-facing gating is skipped per the paper (each
    component's actions were already individually execution-checked); we
    still physically replay the combined sequence because the Stage 2
    judges need a genuine diff_patch for the *combined* trajectory, and
    because concatenation can surface conflicts invisible to either
    component alone (e.g. cancelling and returning the same order).
    """
    exec_result = execution_check(blueprint, plugin)
    if not exec_result.passed:
        raise RecombinationRejected(
            f"Combined action sequence failed execution: {exec_result.error_message}"
        )
    policy_result = policy_check(blueprint, exec_result, plugin)
    if not policy_result.passed:
        violations = "; ".join(
            f"[{v.predicate_name}] {v.message}" for v in policy_result.violations
        )
        raise RecombinationRejected(f"Combined action sequence violates policy: {violations}")
    return exec_result


def run_recombination(
    tasks: Sequence[ValidatedTask],
    plugin: DomainPlugin,
    combiner_llm: LLMClient,
    judge_llms: Sequence[LLMClient],
    feedback_llm: LLMClient,
    rng: random.Random,
    max_retries: int = 3,
    committee_threshold: float = 3.0,
) -> Union[ValidatedTask, PermanentFailure]:
    """Steps 2-5 of Reverse Task Recombination: concatenate, re-check
    policy, synthesize a combined instruction, and re-validate starting
    from Stage 2 (with its own feedback-driven retry loop).
    """
    history: list[ValidationAttempt] = []
    feedback_text: Optional[str] = None
    combined_persona = tasks[0].blueprint.persona if tasks else None

    for attempt in range(1, max_retries + 1):
        blueprint = combine_blueprints(tasks, plugin, combiner_llm, feedback=feedback_text)

        try:
            exec_result = recheck_combined_policy(blueprint, plugin)
        except RecombinationRejected as exc:
            stage1 = Stage1Result(format_check=FormatCheckResult(passed=True))
            history.append(
                ValidationAttempt(attempt_number=attempt, blueprint=blueprint, stage1=stage1)
            )
            feedback_text = summarize_feedback(blueprint, str(exc), feedback_llm)
            continue

        committee = run_committee(
            blueprint, exec_result, plugin, judge_llms, threshold=committee_threshold
        )
        stage2 = Stage2Result(committee=committee)
        history.append(
            ValidationAttempt(
                attempt_number=attempt,
                blueprint=blueprint,
                stage1=Stage1Result(
                    format_check=FormatCheckResult(passed=True),
                    execution_check=exec_result,
                    policy_check=PolicyCheckResult(passed=True),
                ),
                stage2=stage2,
            )
        )
        if stage2.passed:
            return ValidatedTask(
                blueprint=blueprint,
                diff_patch=exec_result.diff_patch,
                committee=committee,
                retry_count=attempt - 1,
                history=history,
            )
        feedback_text = summarize_feedback(blueprint, stage2.failure_summary, feedback_llm)

    return PermanentFailure(
        domain=plugin.name,
        persona=combined_persona,
        retry_count=max_retries,
        history=history,
        final_failure_summary=feedback_text or "Exhausted recombination retries.",
    )
