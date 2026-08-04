import random

from apigen_mt.phase1.committee import CommitteeResult
from apigen_mt.phase1.recombination import combine_blueprints, run_recombination
from apigen_mt.phase1.schema import BlueprintAction, PermanentFailure, TaskBlueprint, ValidatedTask
from apigen_mt.phase1.validators import execution_check
from apigen_mt.tests.conftest import FakeLLMClient, make_answer_response, make_scores_response, make_summary_response


def _validated(blueprint, plugin):
    exec_result = execution_check(blueprint, plugin)
    assert exec_result.passed, exec_result.error_message
    committee = CommitteeResult(
        scores=[], majority={"correctness": 1, "completeness": 1, "satisfaction": 1, "creativity": 1},
        aggregate=4, threshold=3.0, passed=True,
    )
    return ValidatedTask(blueprint=blueprint, diff_patch=exec_result.diff_patch, committee=committee, retry_count=0)


def _non_conflicting_components(retail_plugin):
    db = retail_plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    order = db.orders[order_id]
    user_id = order.user_id

    task_a = TaskBlueprint(
        domain="retail", persona="A frugal shopper.", intent="cancel my order",
        actions=[BlueprintAction(name="cancel_pending_order", arguments={"order_id": order_id, "reason": "no longer needed"})],
        outputs=[],
    )
    task_b = TaskBlueprint(
        domain="retail", persona="A frugal shopper.", intent="update my address",
        actions=[BlueprintAction(
            name="modify_user_address",
            arguments={"user_id": user_id, "address1": "1 Main St", "address2": "", "city": "X", "state": "X", "country": "USA", "zip": "00000"},
        )],
        outputs=[],
    )
    return _validated(task_a, retail_plugin), _validated(task_b, retail_plugin)


def _conflicting_components(retail_plugin):
    db = retail_plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")

    task_a = TaskBlueprint(
        domain="retail", persona="A frugal shopper.", intent="cancel my order",
        actions=[BlueprintAction(name="cancel_pending_order", arguments={"order_id": order_id, "reason": "no longer needed"})],
        outputs=[],
    )
    task_b = TaskBlueprint(
        domain="retail", persona="A frugal shopper.", intent="change my order address",
        actions=[BlueprintAction(
            name="modify_pending_order_address",
            arguments={"order_id": order_id, "address1": "1 Main St", "address2": "", "city": "X", "state": "X", "country": "USA", "zip": "00000"},
        )],
        outputs=[],
    )
    return _validated(task_a, retail_plugin), _validated(task_b, retail_plugin)


def test_combine_blueprints_concatenates_actions_and_records_lineage(retail_plugin):
    task_a, task_b = _non_conflicting_components(retail_plugin)
    combiner = FakeLLMClient("<thought>t</thought><answer>Please cancel my order and update my address.</answer>")
    combined = combine_blueprints([task_a, task_b], retail_plugin, combiner)

    assert combined.intent == "Please cancel my order and update my address."
    assert len(combined.actions) == 2
    assert combined.source_blueprint_ids == [task_a.blueprint.blueprint_id, task_b.blueprint.blueprint_id]


def test_run_recombination_succeeds_for_non_conflicting_components(retail_plugin):
    task_a, task_b = _non_conflicting_components(retail_plugin)
    combiner = FakeLLMClient("<thought>t</thought><answer>Cancel my order and update my address.</answer>")
    judges = [FakeLLMClient(make_scores_response(), name=f"j{i}") for i in range(3)]
    feedback_llm = FakeLLMClient(make_summary_response("n/a"))

    result = run_recombination(
        [task_a, task_b], retail_plugin, combiner, judges, feedback_llm, random.Random(0)
    )
    assert isinstance(result, ValidatedTask)
    assert len(result.blueprint.actions) == 2
    assert not result.diff_patch.is_empty()


def test_run_recombination_rejects_conflicting_components_even_though_llm_would_combine_them(retail_plugin):
    # This is the paper's exact example: returning/cancelling + modifying the same order.
    task_a, task_b = _conflicting_components(retail_plugin)
    combiner = FakeLLMClient("<thought>t</thought><answer>Cancel my order and also change its address.</answer>")
    judges = [FakeLLMClient(make_scores_response(), name="j")]
    feedback_llm = FakeLLMClient(make_summary_response("these conflict, pick one"))

    result = run_recombination(
        [task_a, task_b], retail_plugin, combiner, judges, feedback_llm, random.Random(0), max_retries=2
    )
    assert isinstance(result, PermanentFailure)
    assert len(result.history) == 2
    assert result.history[0].stage2 is None  # rejected before ever reaching the committee
