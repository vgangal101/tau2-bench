"""Stage 1 (Action Validation): format check, execution replay against a
fresh tau2 environment, and policy compliance checks.
"""

from __future__ import annotations

import difflib
import json

from tau2.data_model.message import ToolCall
from tau2.environment.environment import Environment

from apigen_mt.domains.base import DomainPlugin
from apigen_mt.phase1.schema import (
    DiffPatch,
    ExecutionCheckResult,
    FormatCheckResult,
    PolicyCheckResult,
    PolicyViolation,
    Stage1Result,
    TaskBlueprint,
    TraceStep,
)


def format_check(blueprint: TaskBlueprint) -> FormatCheckResult:
    errors: list[str] = []
    if not blueprint.intent or not blueprint.intent.strip():
        errors.append("intent is empty")
    if not isinstance(blueprint.actions, list):
        errors.append("actions must be a list")
    else:
        for i, action in enumerate(blueprint.actions):
            if not action.name:
                errors.append(f"actions[{i}] missing tool name")
            if not isinstance(action.arguments, dict):
                errors.append(f"actions[{i}] arguments must be a dict")
    if not isinstance(blueprint.outputs, list) or not all(
        isinstance(o, str) for o in blueprint.outputs
    ):
        errors.append("outputs must be a list of strings")
    return FormatCheckResult(passed=len(errors) == 0, errors=errors)


def _snapshot(env: Environment) -> dict:
    return env.tools.db.model_dump(mode="json")


def _unified_diff(before: dict, after: dict) -> str:
    before_text = json.dumps(before, indent=2, sort_keys=True, default=str).splitlines()
    after_text = json.dumps(after, indent=2, sort_keys=True, default=str).splitlines()
    return "\n".join(
        difflib.unified_diff(
            before_text, after_text, fromfile="before", tofile="after", lineterm="", n=2
        )
    )


def execution_check(blueprint: TaskBlueprint, plugin: DomainPlugin) -> ExecutionCheckResult:
    """Replay a_gt against a fresh environment instance, capturing a
    git-diff-style patch of the cumulative state change (diff_patch).
    """
    env = plugin.env_factory()
    before = _snapshot(env)
    trace: list[TraceStep] = []
    tools_by_name = plugin.tools_by_name()

    for i, action in enumerate(blueprint.actions):
        if action.name not in tools_by_name:
            return ExecutionCheckResult(
                passed=False,
                trace=trace,
                failed_action_index=i,
                error_message=f"Unknown tool '{action.name}'",
            )
        tool_call = ToolCall(
            name=action.name, arguments=action.arguments, requestor=action.requestor
        )
        response = env.get_response(tool_call)
        step = TraceStep(
            action=action,
            result_json=response.content,
            error=response.error,
            error_message=response.content if response.error else None,
        )
        trace.append(step)
        if response.error:
            return ExecutionCheckResult(
                passed=False,
                trace=trace,
                failed_action_index=i,
                error_message=response.content,
            )

    after = _snapshot(env)
    diff_patch = DiffPatch(
        unified_diff=_unified_diff(before, after), before=before, after=after
    )
    return ExecutionCheckResult(passed=True, trace=trace, diff_patch=diff_patch)


def policy_check(
    blueprint: TaskBlueprint,
    execution_result: ExecutionCheckResult,
    plugin: DomainPlugin,
) -> PolicyCheckResult:
    violations: list[PolicyViolation] = []
    for predicate in plugin.policy_predicates():
        message = predicate.check(blueprint, execution_result)
        if message is not None:
            violations.append(
                PolicyViolation(predicate_name=predicate.name, message=message)
            )
    return PolicyCheckResult(passed=len(violations) == 0, violations=violations)


def run_stage1(blueprint: TaskBlueprint, plugin: DomainPlugin) -> Stage1Result:
    fmt = format_check(blueprint)
    if not fmt.passed:
        return Stage1Result(format_check=fmt)

    execu = execution_check(blueprint, plugin)
    if not execu.passed:
        return Stage1Result(format_check=fmt, execution_check=execu)

    pol = policy_check(blueprint, execu, plugin)
    return Stage1Result(format_check=fmt, execution_check=execu, policy_check=pol)
