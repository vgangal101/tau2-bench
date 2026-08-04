"""Pydantic types for the APIGen-MT Phase 1 blueprint pipeline.

These model the POMDP task artifact described in the paper: a blueprint is
``{intent: q, actions: a_gt, outputs: o_gt}`` plus the validation history
that got it there.
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    return str(uuid.uuid4())


class BlueprintAction(BaseModel):
    """One entry of a_gt: a groundtruth tool call."""

    name: str
    arguments: dict
    requestor: Literal["assistant", "user"] = "assistant"


class TaskBlueprint(BaseModel):
    """The {intent, actions, outputs} tuple produced by Phase 1."""

    blueprint_id: str = Field(default_factory=_new_id)
    domain: str
    persona: Optional[str] = None
    thought: Optional[str] = None
    intent: str
    actions: list[BlueprintAction] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    source_blueprint_ids: list[str] = Field(
        default_factory=list,
        description="Non-empty for tasks produced by reverse task recombination.",
    )


class TraceStep(BaseModel):
    """Result of replaying one BlueprintAction against a fresh environment."""

    action: BlueprintAction
    result_json: Optional[str] = None
    error: bool = False
    error_message: Optional[str] = None


class DiffPatch(BaseModel):
    """git-diff-style summary of the environment state change caused by a_gt."""

    unified_diff: str
    before: dict
    after: dict

    def is_empty(self) -> bool:
        return self.before == self.after


class FormatCheckResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)


class PolicyViolation(BaseModel):
    predicate_name: str
    message: str


class PolicyCheckResult(BaseModel):
    passed: bool
    violations: list[PolicyViolation] = Field(default_factory=list)


class ExecutionCheckResult(BaseModel):
    passed: bool
    trace: list[TraceStep] = Field(default_factory=list)
    diff_patch: Optional[DiffPatch] = None
    failed_action_index: Optional[int] = None
    error_message: Optional[str] = None


class Stage1Result(BaseModel):
    """Action Validation: format + execution + policy compliance."""

    format_check: FormatCheckResult
    execution_check: Optional[ExecutionCheckResult] = None
    policy_check: Optional[PolicyCheckResult] = None

    @property
    def passed(self) -> bool:
        if not self.format_check.passed:
            return False
        if self.execution_check is None or not self.execution_check.passed:
            return False
        if self.policy_check is None or not self.policy_check.passed:
            return False
        return True

    @property
    def failure_summary(self) -> str:
        if not self.format_check.passed:
            return "Format check failed: " + "; ".join(self.format_check.errors)
        if self.execution_check is not None and not self.execution_check.passed:
            return f"Execution check failed: {self.execution_check.error_message}"
        if self.policy_check is not None and not self.policy_check.passed:
            return "Policy check failed: " + "; ".join(
                f"[{v.predicate_name}] {v.message}" for v in self.policy_check.violations
            )
        return ""


class JudgeScore(BaseModel):
    judge_name: str
    reflection: str = ""
    correctness: int = 0
    completeness: int = 0
    satisfaction: int = 0
    creativity: int = 0
    correction: Optional[str] = None

    @property
    def total(self) -> int:
        return self.correctness + self.completeness + self.satisfaction + self.creativity


class CommitteeResult(BaseModel):
    """Stage 2: Alignment Validation via majority vote across judges."""

    scores: list[JudgeScore] = Field(default_factory=list)
    majority: dict[str, int] = Field(
        default_factory=dict,
        description="Per-criterion majority vote (0/1), keys: correctness/completeness/satisfaction/creativity.",
    )
    aggregate: int = 0
    threshold: float = 3.0
    passed: bool = False


class Stage2Result(BaseModel):
    committee: CommitteeResult

    @property
    def passed(self) -> bool:
        return self.committee.passed

    @property
    def failure_summary(self) -> str:
        lines = []
        for s in self.committee.scores:
            if s.correction:
                lines.append(f"[{s.judge_name}] {s.correction}")
            elif s.reflection:
                lines.append(f"[{s.judge_name}] {s.reflection}")
        return "\n".join(lines)


class ValidationAttempt(BaseModel):
    """One generate-validate iteration in the retry loop."""

    attempt_number: int
    blueprint: TaskBlueprint
    stage1: Stage1Result
    stage2: Optional[Stage2Result] = None
    feedback_summary: Optional[str] = None


class ValidatedTask(BaseModel):
    """A blueprint that passed all three Phase 1 stages."""

    blueprint: TaskBlueprint
    diff_patch: DiffPatch
    committee: CommitteeResult
    retry_count: int
    history: list[ValidationAttempt] = Field(default_factory=list)


class PermanentFailure(BaseModel):
    """A blueprint that exhausted its retry budget without validating."""

    domain: str
    persona: Optional[str]
    retry_count: int
    history: list[ValidationAttempt]
    final_failure_summary: str
