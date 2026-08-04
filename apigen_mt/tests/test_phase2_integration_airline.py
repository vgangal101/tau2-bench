"""Same blueprint -> task -> evaluator round-trip as
test_phase2_integration.py, but for the airline plugin -- this is the
checkpoint that proves blueprint_to_native_task is genuinely a per-plugin
hook and not hardcoded to retail's task shape.
"""

from __future__ import annotations

from tau2.agent.llm_agent import LLMAgent
from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.orchestrator.orchestrator import Orchestrator

from apigen_mt.phase1.committee import CommitteeResult
from apigen_mt.phase1.schema import BlueprintAction, TaskBlueprint, ValidatedTask
from apigen_mt.phase1.validators import execution_check
from apigen_mt.phase2.driver import build_task
from apigen_mt.phase2.human_sim import build_human_simulator


def _validated_cancel_reservation_task(airline_plugin):
    db = airline_plugin.db_accessor()._db
    reservation_id = next(
        rid for rid, r in db.reservations.items() if r.status != "cancelled"
    )
    reservation = db.reservations[reservation_id]
    user = db.users[reservation.user_id]

    blueprint = TaskBlueprint(
        domain="airline",
        persona="A calm retiree.",
        intent=(
            f"You are {user.name.first_name} {user.name.last_name}, user id {user.user_id}. "
            f"Cancel reservation {reservation_id} because your plans changed."
        ),
        actions=[
            BlueprintAction(name="cancel_reservation", arguments={"reservation_id": reservation_id})
        ],
        outputs=[],
    )
    exec_result = execution_check(blueprint, airline_plugin)
    assert exec_result.passed
    committee = CommitteeResult(
        scores=[], majority={"correctness": 1, "completeness": 1, "satisfaction": 1, "creativity": 1},
        aggregate=4, threshold=3.0, passed=True,
    )
    validated = ValidatedTask(
        blueprint=blueprint, diff_patch=exec_result.diff_patch, committee=committee, retry_count=0
    )
    return validated, reservation_id


def test_airline_blueprint_to_task_uses_airline_specific_shape(airline_plugin):
    validated, reservation_id = _validated_cancel_reservation_task(airline_plugin)
    task = build_task(validated, airline_plugin)
    assert task.evaluation_criteria.actions[0].name == "cancel_reservation"
    assert task.evaluation_criteria.actions[0].arguments["reservation_id"] == reservation_id


def test_airline_orchestrator_construction_succeeds_without_llm_calls(airline_plugin):
    validated, _ = _validated_cancel_reservation_task(airline_plugin)
    task = build_task(validated, airline_plugin)
    env = airline_plugin.env_factory()
    agent = LLMAgent(tools=env.get_tools(), domain_policy=env.get_policy(), llm="gpt-4.1-2025-04-14")
    user = build_human_simulator(task, llm="gpt-4.1-2025-04-14")
    assert user.tools is None

    orchestrator = Orchestrator(domain="airline", agent=agent, user=user, environment=env, task=task, max_steps=20)
    orchestrator.initialize()
    assert len(orchestrator.trajectory) == 1


def test_airline_evaluator_scores_reward_one_for_correct_trajectory(airline_plugin):
    validated, reservation_id = _validated_cancel_reservation_task(airline_plugin)
    task = build_task(validated, airline_plugin)

    fresh_env = airline_plugin.env_factory()
    tool_call = ToolCall(id="1", name="cancel_reservation", arguments={"reservation_id": reservation_id}, requestor="assistant")
    tool_response = fresh_env.get_response(tool_call)
    assert not tool_response.error

    messages = [
        AssistantMessage.text("Hi! How can I help you today?"),
        UserMessage.text(f"Please cancel reservation {reservation_id}."),
        AssistantMessage.text("", tool_calls=[tool_call]),
        tool_response,
        AssistantMessage.text("Done, your reservation has been cancelled."),
        UserMessage.text("###STOP###"),
    ]
    simulation = SimulationRun(
        id="sim-air-1", task_id=task.id, start_time="2026-01-01T00:00:00", end_time="2026-01-01T00:01:00",
        duration=60.0, termination_reason=TerminationReason.USER_STOP, messages=messages,
    )
    reward_info = evaluate_simulation(
        simulation=simulation, task=task, evaluation_type=EvaluationType.ALL, solo_mode=False, domain="airline",
    )
    assert reward_info.reward == 1.0
