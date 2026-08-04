"""Integration tests for the Phase 1 blueprint -> tau2 Task -> tau2
evaluator round-trip. No live LLM calls: we hand-script the message
trajectory a real agent+user rollout would produce and feed it straight to
tau2's own evaluator, and separately verify Orchestrator/agent/user
construction succeeds (covers everything up to, but not including, the
actual LLM-driven step() loop).
"""

from __future__ import annotations

from tau2.agent.llm_agent import LLMAgent
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.orchestrator.orchestrator import Orchestrator

from apigen_mt.phase1.committee import CommitteeResult
from apigen_mt.phase1.schema import BlueprintAction, TaskBlueprint, ValidatedTask
from apigen_mt.phase1.validators import execution_check
from apigen_mt.phase2.blueprint_adapter import blueprint_to_task
from apigen_mt.phase2.driver import build_task
from apigen_mt.phase2.human_sim import build_human_simulator


def _validated_cancel_order_task(retail_plugin):
    db = retail_plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    order = db.orders[order_id]
    user = db.users[order.user_id]

    blueprint = TaskBlueprint(
        domain="retail",
        persona="A frugal shopper.",
        intent=f"You are {user.name.first_name} {user.name.last_name}. Cancel order {order_id} because it's no longer needed.",
        actions=[
            BlueprintAction(
                name="cancel_pending_order",
                arguments={"order_id": order_id, "reason": "no longer needed"},
            )
        ],
        outputs=[],
    )
    exec_result = execution_check(blueprint, retail_plugin)
    assert exec_result.passed
    committee = CommitteeResult(
        scores=[], majority={"correctness": 1, "completeness": 1, "satisfaction": 1, "creativity": 1},
        aggregate=4, threshold=3.0, passed=True,
    )
    validated = ValidatedTask(
        blueprint=blueprint, diff_patch=exec_result.diff_patch, committee=committee, retry_count=0
    )
    return validated, order_id


def test_blueprint_to_task_produces_valid_tau2_task(retail_plugin):
    validated, order_id = _validated_cancel_order_task(retail_plugin)
    task = build_task(validated, retail_plugin)

    assert task.evaluation_criteria.actions[0].name == "cancel_pending_order"
    assert task.evaluation_criteria.actions[0].arguments["order_id"] == order_id
    assert task.user_scenario.persona == "A frugal shopper."
    assert task.description.purpose is None or isinstance(task.description.purpose, str)


def test_orchestrator_agent_user_construction_succeeds_without_llm_calls(retail_plugin):
    # Everything up to the first LLM call: env/agent/user/task/orchestrator wiring.
    validated, _ = _validated_cancel_order_task(retail_plugin)
    task = build_task(validated, retail_plugin)
    env = retail_plugin.env_factory()

    agent = LLMAgent(tools=env.get_tools(), domain_policy=env.get_policy(), llm="gpt-4.1-2025-04-14")
    user = build_human_simulator(task, llm="gpt-4.1-2025-04-14")
    assert user.tools is None  # dual control disabled

    orchestrator = Orchestrator(
        domain="retail", agent=agent, user=user, environment=env, task=task, max_steps=20
    )
    orchestrator.initialize()  # no LLM call needed: seeds the default first agent message
    assert len(orchestrator.trajectory) == 1
    assert orchestrator.trajectory[0].content == "Hi! How can I help you today?"


def test_evaluator_accepts_hand_scripted_correct_trajectory_and_scores_reward_one(retail_plugin):
    validated, order_id = _validated_cancel_order_task(retail_plugin)
    task = build_task(validated, retail_plugin)

    # Replay the exact tool call against a fresh env to get the *real*
    # ToolMessage content -- evaluator replay compares byte-for-byte.
    fresh_env = retail_plugin.env_factory()
    tool_call = ToolCall(
        id="1", name="cancel_pending_order",
        arguments={"order_id": order_id, "reason": "no longer needed"},
        requestor="assistant",
    )
    tool_response = fresh_env.get_response(tool_call)
    assert not tool_response.error

    messages = [
        AssistantMessage.text("Hi! How can I help you today?"),
        UserMessage.text(f"Please cancel order {order_id}, I don't need it anymore."),
        AssistantMessage.text("", tool_calls=[tool_call]),
        tool_response,
        AssistantMessage.text("Done, your order has been cancelled."),
        UserMessage.text("###STOP###"),
    ]
    simulation = SimulationRun(
        id="sim-1", task_id=task.id, start_time="2026-01-01T00:00:00", end_time="2026-01-01T00:01:00",
        duration=60.0, termination_reason=TerminationReason.USER_STOP, messages=messages,
    )
    reward_info = evaluate_simulation(
        simulation=simulation, task=task, evaluation_type=EvaluationType.ALL,
        solo_mode=False, domain="retail",
    )
    assert reward_info.reward == 1.0
    assert reward_info.db_check.db_match is True


def test_evaluator_scores_reward_zero_when_agent_never_acts(retail_plugin):
    validated, order_id = _validated_cancel_order_task(retail_plugin)
    task = build_task(validated, retail_plugin)

    messages = [
        AssistantMessage.text("Hi! How can I help you today?"),
        UserMessage.text(f"Please cancel order {order_id}."),
        AssistantMessage.text("Sorry, I can't help with that."),
        UserMessage.text("###STOP###"),
    ]
    simulation = SimulationRun(
        id="sim-2", task_id=task.id, start_time="2026-01-01T00:00:00", end_time="2026-01-01T00:01:00",
        duration=60.0, termination_reason=TerminationReason.USER_STOP, messages=messages,
    )
    reward_info = evaluate_simulation(
        simulation=simulation, task=task, evaluation_type=EvaluationType.ALL,
        solo_mode=False, domain="retail",
    )
    assert reward_info.reward == 0.0
    assert reward_info.db_check.db_match is False
