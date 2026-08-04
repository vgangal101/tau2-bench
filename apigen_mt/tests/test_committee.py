from apigen_mt.phase1.committee import parse_judge_response, run_committee
from apigen_mt.phase1.schema import BlueprintAction, ExecutionCheckResult, TaskBlueprint
from apigen_mt.tests.conftest import FakeLLMClient, make_scores_response


def _bp():
    return TaskBlueprint(
        domain="retail",
        intent="cancel it",
        actions=[BlueprintAction(name="get_user_details", arguments={"user_id": "x"})],
        outputs=[],
    )


def test_parse_judge_response_roundtrip():
    raw = make_scores_response(correctness=1, completeness=0, satisfaction=1, creativity=1)
    score = parse_judge_response(raw, "judge_a")
    assert score.total == 3
    assert score.completeness == 0


def test_majority_vote_passes_with_unanimous_judges(retail_plugin):
    exec_result = ExecutionCheckResult(passed=True, trace=[], diff_patch=None)
    judges = [
        FakeLLMClient(make_scores_response(), name=f"judge_{i}") for i in range(3)
    ]
    result = run_committee(_bp(), exec_result, retail_plugin, judges, threshold=3.0)
    assert result.passed
    assert result.aggregate == 4
    assert all(v == 1 for v in result.majority.values())


def test_majority_vote_uses_majority_not_unanimity(retail_plugin):
    exec_result = ExecutionCheckResult(passed=True, trace=[], diff_patch=None)
    judges = [
        FakeLLMClient(make_scores_response(correctness=1), name="j1"),
        FakeLLMClient(make_scores_response(correctness=1), name="j2"),
        FakeLLMClient(make_scores_response(correctness=0), name="j3"),
    ]
    result = run_committee(_bp(), exec_result, retail_plugin, judges, threshold=3.0)
    assert result.majority["correctness"] == 1  # 2 out of 3 vote yes


def test_committee_fails_below_threshold(retail_plugin):
    exec_result = ExecutionCheckResult(passed=True, trace=[], diff_patch=None)
    judges = [
        FakeLLMClient(
            make_scores_response(correctness=0, completeness=0, satisfaction=1, creativity=1),
            name="j1",
        )
    ]
    result = run_committee(_bp(), exec_result, retail_plugin, judges, threshold=3.0)
    assert not result.passed
    assert result.aggregate == 2


def test_unparseable_judge_output_scores_zero_instead_of_crashing(retail_plugin):
    exec_result = ExecutionCheckResult(passed=True, trace=[], diff_patch=None)
    judges = [FakeLLMClient("garbage, no tags", name="broken_judge")]
    result = run_committee(_bp(), exec_result, retail_plugin, judges, threshold=3.0)
    assert not result.passed
    assert result.scores[0].total == 0
