"""Stage 2: Alignment Validation. A committee of independent LLM judges
scores {intent, actions, outputs, diff_patch} against a four-criterion
rubric; the final per-criterion verdict is the majority vote across judges.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Sequence

from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.schema import CommitteeResult, ExecutionCheckResult, JudgeScore, TaskBlueprint

if TYPE_CHECKING:
    from apigen_mt.domains.base import DomainPlugin

JUDGE_SYSTEM_PROMPT = (
    "You are an AI judge and your goal is to judge the quality and validity of the "
    "provided task object based on the guidelines, following the rubric."
)

JUDGE_PROMPT_TEMPLATE = """
## Guidelines
- The task object contains an 'intent' (q) from a user, 'actions' (a_gt), and 'outputs' (o_gt).
- The 'actions' correspond to the tool_calls made by an AI assistant to satisfy the instruction.
- A description of the 'tools' available to the AI assistant is provided.
- The 'diff_patch' is the difference in the database state after the tool_calls are made. It should \
only reflect changes corresponding to the 'intent'. There should be no extraneous changes. If the \
'diff_patch' is empty, it means the tool_calls did not change the database state, which is fine if \
the instruction was to provide information only.
- Perform a brief reflection on the task based on the Rubric below.
- Think step-by-step to generate a score of 0 or 1 for each criterion (1 means follows criterion, 0 \
means does not).

## Rubric
- Correctness: Do the actions (a_gt) accurately implement the instruction (q)?
- Completeness: Is the instruction (q) sufficiently detailed, and is it fully addressed by the actions?
- Satisfaction: Do the expected outputs (o_gt) fulfill any explicit or implicit information requests \
within the instruction (q)?
- Creativity: Does the task represent a non-trivial, plausible, and potentially interesting scenario \
within the domain?

## Task Object
{task_object}

## Tools
{tools}

## Diff Patch
{diff_patch}

## Output format
<scores>
{{
  "reflection": "<a brief high-level review of the task>",
  "correctness": <0 or 1>,
  "completeness": <0 or 1>,
  "satisfaction": <0 or 1>,
  "creativity": <0 or 1>,
  "correction": "<brief explanation and suggested correction, if needed>"
}}
</scores>
""".strip()

CRITERIA = ("correctness", "completeness", "satisfaction", "creativity")

_SCORES_RE = re.compile(r"<scores>(.*?)</scores>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


class JudgeParseError(ValueError):
    pass


def task_object_text(blueprint: TaskBlueprint) -> str:
    return json.dumps(
        {
            "intent": blueprint.intent,
            "actions": [a.model_dump() for a in blueprint.actions],
            "outputs": blueprint.outputs,
        },
        indent=2,
    )


def build_judge_prompt(blueprint: TaskBlueprint, tools_text: str, diff_patch_text: str) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(
        task_object=task_object_text(blueprint),
        tools=tools_text,
        diff_patch=diff_patch_text,
    )


def parse_judge_response(raw_text: str, judge_name: str) -> JudgeScore:
    match = _SCORES_RE.search(raw_text)
    if not match:
        raise JudgeParseError(f"No <scores> block found in judge output: {raw_text[:500]!r}")
    text = _FENCE_RE.sub("", match.group(1).strip()).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"Could not parse JSON in <scores>: {exc}\n{text[:500]!r}") from exc
    return JudgeScore(
        judge_name=judge_name,
        reflection=data.get("reflection", ""),
        correctness=int(bool(data.get("correctness", 0))),
        completeness=int(bool(data.get("completeness", 0))),
        satisfaction=int(bool(data.get("satisfaction", 0))),
        creativity=int(bool(data.get("creativity", 0))),
        correction=data.get("correction"),
    )


def _majority_vote(scores: Sequence[JudgeScore]) -> dict[str, int]:
    n = len(scores)
    majority = {}
    for criterion in CRITERIA:
        votes = sum(getattr(s, criterion) for s in scores)
        majority[criterion] = 1 if votes * 2 > n else 0
    return majority


def run_committee(
    blueprint: TaskBlueprint,
    execution_result: ExecutionCheckResult,
    plugin: "DomainPlugin",
    judges: Sequence[LLMClient],
    threshold: float = 3.0,
) -> CommitteeResult:
    """Run the review committee and aggregate scores via majority vote."""
    used_tool_names = {a.name for a in blueprint.actions}
    tools_text = (
        "\n\n".join(t.signature for t in plugin.tools() if t.name in used_tool_names)
        or "(no tool calls)"
    )
    diff_text = (
        execution_result.diff_patch.unified_diff
        if execution_result.diff_patch is not None
        else "(empty)"
    )
    prompt = build_judge_prompt(blueprint, tools_text, diff_text)

    scores: list[JudgeScore] = []
    for judge in judges:
        raw = judge.complete(system=JUDGE_SYSTEM_PROMPT, user=prompt, temperature=0.3)
        try:
            scores.append(parse_judge_response(raw, judge.name))
        except JudgeParseError:
            scores.append(
                JudgeScore(
                    judge_name=judge.name,
                    reflection="Failed to parse judge output; scored 0 on all criteria.",
                )
            )

    majority = _majority_vote(scores)
    aggregate = sum(majority.values())
    return CommitteeResult(
        scores=scores,
        majority=majority,
        aggregate=aggregate,
        threshold=threshold,
        passed=aggregate >= threshold,
    )
