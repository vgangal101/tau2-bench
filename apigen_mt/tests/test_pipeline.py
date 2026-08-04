import random

from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage
from tau2.data_model.simulation import SimulationRun, TerminationReason

from apigen_mt.phase1.committee import CommitteeResult
from apigen_mt.phase1.schema import BlueprintAction, TaskBlueprint, ValidatedTask
from apigen_mt.phase1.validators import execution_check
from apigen_mt.phase2.driver import TrajectoryResult, build_task
from apigen_mt.pipeline import collect_trajectories, trajectory_to_record, write_jsonl


def _validated_cancel_order_task(retail_plugin):
    db = retail_plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    blueprint = TaskBlueprint(
        domain="retail",
        persona="A frugal shopper.",
        intent=f"Cancel order {order_id}.",
        actions=[BlueprintAction(name="cancel_pending_order", arguments={"order_id": order_id, "reason": "no longer needed"})],
        outputs=[],
    )
    exec_result = execution_check(blueprint, retail_plugin)
    committee = CommitteeResult(
        scores=[], majority={"correctness": 1, "completeness": 1, "satisfaction": 1, "creativity": 1},
        aggregate=4, threshold=3.0, passed=True,
    )
    return ValidatedTask(blueprint=blueprint, diff_patch=exec_result.diff_patch, committee=committee, retry_count=0), order_id


def _make_successful_trajectory(retail_plugin, validated, order_id, attempt_number):
    task = build_task(validated, retail_plugin)
    env = retail_plugin.env_factory()
    tool_call = ToolCall(id="1", name="cancel_pending_order", arguments={"order_id": order_id, "reason": "no longer needed"}, requestor="assistant")
    tool_response = env.get_response(tool_call)
    messages = [
        AssistantMessage.text("Hi! How can I help you today?"),
        UserMessage.text(f"Cancel order {order_id} please."),
        AssistantMessage.text("", tool_calls=[tool_call]),
        tool_response,
        AssistantMessage.text("Done."),
        UserMessage.text("###STOP###"),
    ]
    simulation = SimulationRun(
        id=f"sim-{attempt_number}", task_id=task.id, start_time="t0", end_time="t1", duration=1.0,
        termination_reason=TerminationReason.USER_STOP, messages=messages,
    )
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    simulation.reward_info = evaluate_simulation(
        simulation=simulation, task=task, evaluation_type=EvaluationType.ALL, solo_mode=False, domain="retail"
    )
    return TrajectoryResult(task=task, simulation=simulation, success=simulation.reward_info.reward >= 1.0, attempt_number=attempt_number)


def test_collect_trajectories_dedupes_identical_successful_attempts(retail_plugin, monkeypatch):
    validated, order_id = _validated_cancel_order_task(retail_plugin)

    def fake_run_phase2_trial(validated_, plugin, config, rng, attempt_number=1, task=None):
        return _make_successful_trajectory(retail_plugin, validated_, order_id, attempt_number)

    monkeypatch.setattr("apigen_mt.pipeline.run_phase2_trial", fake_run_phase2_trial)

    from apigen_mt.phase2.driver import Phase2Config

    result = collect_trajectories(
        validated, retail_plugin, Phase2Config(agent_model="x", user_model="y"), random.Random(0), max_attempts=3
    )
    assert len(result.attempts) == 3
    assert all(a.success for a in result.attempts)
    # all 3 attempts produce byte-identical transcripts here -> union has exactly 1 unique trajectory
    assert len(result.accepted_trajectories) == 1


def test_trajectory_to_record_and_write_jsonl_roundtrip(retail_plugin, tmp_path):
    validated, order_id = _validated_cancel_order_task(retail_plugin)
    trajectory = _make_successful_trajectory(retail_plugin, validated, order_id, attempt_number=1)

    record = trajectory_to_record(trajectory, validated)
    assert record["domain"] == "retail"
    assert record["groundtruth_actions"][0]["name"] == "cancel_pending_order"
    assert record["num_tool_calls"] == 1
    assert record["num_user_turns"] == 2  # "cancel order..." + "###STOP###"
    assert record["state_based_pass"] is True
    assert any(t["tool_call"] is not None for t in record["turns"])
    assert any(t["role"] == "tool" for t in record["turns"])

    out_file = tmp_path / "out.jsonl"
    write_jsonl([record], str(out_file))
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 1
    import json

    reloaded = json.loads(lines[0])
    assert reloaded["task_id"] == record["task_id"]
