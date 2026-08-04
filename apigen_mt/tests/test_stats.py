import random

from apigen_mt.stats import measure_phase1_feedback_boost, measure_trajectory_stats
from apigen_mt.tests.conftest import FakeLLMClient, make_answer_response, make_scores_response, make_summary_response


def test_feedback_boost_report_shows_improvement_when_second_attempt_fixes_the_bug(retail_plugin):
    db = retail_plugin.db_accessor()._db
    order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")

    bad_answer = {
        "intent": "broken",
        "actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#NOPE", "reason": "no longer needed"}}],
        "outputs": [],
    }
    good_answer = {
        "intent": f"cancel order {order_id}",
        "actions": [{"name": "cancel_pending_order", "arguments": {"order_id": order_id, "reason": "no longer needed"}}],
        "outputs": [],
    }

    # Generator: first call in every retry-loop invocation is bad, every
    # subsequent call (i.e. after having seen feedback) is good.
    def generator_response(call_index, system, user):
        return make_answer_response("t", good_answer if "Feedback" in user else bad_answer)

    generator = FakeLLMClient(generator_response)
    judges = [FakeLLMClient(make_scores_response(), name="j")]
    feedback_llm = FakeLLMClient(make_summary_response("use a real order id"))

    report = measure_phase1_feedback_boost(
        retail_plugin, generator, judges, feedback_llm, random.Random(0),
        num_samples=5, max_retries_with_feedback=3,
    )
    assert report.success_rate_with_feedback == 1.0
    assert report.success_rate_without_feedback == 0.0
    assert report.feedback_boost_multiplier is None  # division by zero baseline -- documented, not a crash


def test_measure_trajectory_stats_computes_turn_and_tool_call_summaries():
    records = [
        {"turns": [{}] * 5, "num_tool_calls": 2, "num_user_turns": 2},
        {"turns": [{}] * 9, "num_tool_calls": 4, "num_user_turns": 3},
    ]
    report = measure_trajectory_stats(records, phase2_attempts=4, phase2_successes=2)
    assert report.num_trajectories == 2
    assert report.min_turns == 5
    assert report.max_turns == 9
    assert report.avg_tool_calls == 3.0
    assert report.avg_user_turns == 2.5
    assert report.phase2_success_rate == 0.5
    assert report.turns_histogram == {5: 1, 9: 1}


def test_measure_trajectory_stats_handles_empty_records():
    report = measure_trajectory_stats([], phase2_attempts=0, phase2_successes=0)
    assert report.num_trajectories == 0
    assert report.min_turns is None
    assert report.phase2_success_rate is None
