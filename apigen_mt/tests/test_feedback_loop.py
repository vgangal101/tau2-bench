import random

from apigen_mt.phase1.feedback import GenerationLoopConfig, run_generation_loop
from apigen_mt.phase1.schema import PermanentFailure, ValidatedTask
from apigen_mt.tests.conftest import FakeLLMClient, make_answer_response, make_scores_response, make_summary_response


def _find_pending_order(plugin):
    db = plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    return order_id, db.orders[order_id]


def test_loop_recovers_after_stage1_failure_via_feedback(retail_plugin):
    order_id, order = _find_pending_order(retail_plugin)
    bad_answer = {
        "intent": "cancel a nonexistent order",
        "actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#NOPE", "reason": "no longer needed"}}],
        "outputs": [],
    }
    good_answer = {
        "intent": f"cancel order {order_id}",
        "actions": [
            {"name": "cancel_pending_order", "arguments": {"order_id": order_id, "reason": "no longer needed"}}
        ],
        "outputs": [],
    }
    generator = FakeLLMClient(
        [make_answer_response("t1", bad_answer), make_answer_response("t2", good_answer)]
    )
    judges = [FakeLLMClient(make_scores_response(), name=f"judge_{i}") for i in range(3)]
    feedback_llm = FakeLLMClient(make_summary_response("use a real order id next time"))

    rng = random.Random(5)
    result = run_generation_loop(
        retail_plugin,
        generator,
        judges,
        feedback_llm,
        rng,
        config=GenerationLoopConfig(max_retries=3),
    )

    assert isinstance(result, ValidatedTask)
    assert result.retry_count == 1
    assert result.blueprint.intent == good_answer["intent"]
    assert len(result.history) == 2
    assert not result.history[0].stage1.passed
    assert result.history[1].stage1.passed
    # the second generator call must have seen the feedback summary
    assert "use a real order id next time" in generator.calls[1]["user"]


def test_loop_exhausts_retries_and_returns_permanent_failure(retail_plugin):
    bad_answer = {
        "intent": "always broken",
        "actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#NOPE", "reason": "no longer needed"}}],
        "outputs": [],
    }
    generator = FakeLLMClient(make_answer_response("t", bad_answer))
    judges = [FakeLLMClient(make_scores_response(), name="j")]
    feedback_llm = FakeLLMClient(make_summary_response("still broken"))

    rng = random.Random(9)
    result = run_generation_loop(
        retail_plugin,
        generator,
        judges,
        feedback_llm,
        rng,
        config=GenerationLoopConfig(max_retries=2),
    )
    assert isinstance(result, PermanentFailure)
    assert result.retry_count == 2
    assert len(result.history) == 2


def test_loop_fails_stage2_when_committee_rejects(retail_plugin):
    order_id, order = _find_pending_order(retail_plugin)
    answer = {
        "intent": f"cancel order {order_id}",
        "actions": [
            {"name": "cancel_pending_order", "arguments": {"order_id": order_id, "reason": "no longer needed"}}
        ],
        "outputs": [],
    }
    generator = FakeLLMClient(make_answer_response("t", answer))
    rejecting_judges = [
        FakeLLMClient(make_scores_response(correctness=0, completeness=0, satisfaction=0, creativity=0), name="j")
    ]
    feedback_llm = FakeLLMClient(make_summary_response("not creative enough"))

    rng = random.Random(1)
    result = run_generation_loop(
        retail_plugin,
        generator,
        rejecting_judges,
        feedback_llm,
        rng,
        config=GenerationLoopConfig(max_retries=1),
    )
    assert isinstance(result, PermanentFailure)
    assert result.history[0].stage1.passed
    assert not result.history[0].stage2.passed


def test_max_retries_one_is_the_no_feedback_baseline(retail_plugin):
    # With max_retries=1 there is no second attempt, so feedback is never
    # actually consumed -- this is the "without agentic feedback" ablation.
    bad_answer = {
        "intent": "broken",
        "actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#NOPE", "reason": "no longer needed"}}],
        "outputs": [],
    }
    generator = FakeLLMClient(make_answer_response("t", bad_answer))
    judges = [FakeLLMClient(make_scores_response(), name="j")]
    feedback_llm = FakeLLMClient(make_summary_response("unused"))
    rng = random.Random(2)
    result = run_generation_loop(
        retail_plugin, generator, judges, feedback_llm, rng, config=GenerationLoopConfig(max_retries=1)
    )
    assert isinstance(result, PermanentFailure)
    assert len(generator.calls) == 1
