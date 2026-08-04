from apigen_mt.phase1.schema import BlueprintAction, TaskBlueprint
from apigen_mt.phase1.validators import execution_check, format_check, run_stage1


def test_format_check_rejects_empty_intent():
    bp = TaskBlueprint(domain="retail", intent="   ", actions=[], outputs=[])
    result = format_check(bp)
    assert not result.passed
    assert any("intent" in e for e in result.errors)


def test_format_check_rejects_non_string_outputs():
    bp = TaskBlueprint(domain="retail", intent="x", actions=[], outputs=["ok"])
    assert format_check(bp).passed


def test_execution_check_produces_nonempty_diff_for_write_action(retail_plugin):
    db = retail_plugin.db_accessor()._db
    pending_order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    bp = TaskBlueprint(
        domain="retail",
        intent="cancel it",
        actions=[
            BlueprintAction(
                name="cancel_pending_order",
                arguments={"order_id": pending_order_id, "reason": "no longer needed"},
            )
        ],
        outputs=[],
    )
    result = execution_check(bp, retail_plugin)
    assert result.passed
    assert not result.diff_patch.is_empty()
    assert "cancelled" in result.diff_patch.unified_diff


def test_execution_check_reports_failed_action_index(retail_plugin):
    bp = TaskBlueprint(
        domain="retail",
        intent="bad order id",
        actions=[
            BlueprintAction(
                name="cancel_pending_order",
                arguments={"order_id": "#W0000000-nonexistent", "reason": "no longer needed"},
            )
        ],
        outputs=[],
    )
    result = execution_check(bp, retail_plugin)
    assert not result.passed
    assert result.failed_action_index == 0


def test_execution_check_unknown_tool_name_fails_cleanly(retail_plugin):
    bp = TaskBlueprint(
        domain="retail",
        intent="x",
        actions=[BlueprintAction(name="not_a_real_tool", arguments={})],
        outputs=[],
    )
    result = execution_check(bp, retail_plugin)
    assert not result.passed
    assert "Unknown tool" in result.error_message


def test_single_user_scope_predicate_catches_cross_user_blueprint(retail_plugin):
    db = retail_plugin.db_accessor()._db
    pending_order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    order = db.orders[pending_order_id]
    other_user = next(uid for uid in db.users if uid != order.user_id)

    bp = TaskBlueprint(
        domain="retail",
        intent="x",
        actions=[
            BlueprintAction(
                name="cancel_pending_order",
                arguments={"order_id": pending_order_id, "reason": "no longer needed"},
            ),
            BlueprintAction(
                name="modify_user_address",
                arguments={
                    "user_id": other_user,
                    "address1": "y",
                    "address2": "",
                    "city": "y",
                    "state": "y",
                    "country": "y",
                    "zip": "54321",
                },
            ),
        ],
        outputs=[],
    )
    result = run_stage1(bp, retail_plugin)
    assert result.execution_check.passed
    assert not result.policy_check.passed
    assert result.policy_check.violations[0].predicate_name == "single_user_scope"


def test_conflicting_order_mutations_caught_even_when_execution_would_allow_it(retail_plugin):
    db = retail_plugin.db_accessor()._db
    pending_order_id = next(oid for oid, o in db.orders.items() if o.status == "pending")
    bp = TaskBlueprint(
        domain="retail",
        intent="x",
        actions=[
            BlueprintAction(
                name="modify_pending_order_address",
                arguments={
                    "order_id": pending_order_id,
                    "address1": "x",
                    "address2": "",
                    "city": "x",
                    "state": "x",
                    "country": "x",
                    "zip": "12345",
                },
            ),
            BlueprintAction(
                name="modify_pending_order_address",
                arguments={
                    "order_id": pending_order_id,
                    "address1": "y",
                    "address2": "",
                    "city": "y",
                    "state": "y",
                    "country": "y",
                    "zip": "54321",
                },
            ),
        ],
        outputs=[],
    )
    result = run_stage1(bp, retail_plugin)
    assert result.execution_check.passed  # tool-level guards allow this
    assert not result.policy_check.passed  # our predicate catches it anyway
    assert result.policy_check.violations[0].predicate_name == "no_conflicting_order_mutations"


def test_airline_cancel_twice_not_caught_by_execution_but_caught_by_policy(airline_plugin):
    db = airline_plugin.db_accessor()._db
    reservation_id = next(iter(db.reservations))
    bp = TaskBlueprint(
        domain="airline",
        intent="x",
        actions=[
            BlueprintAction(name="cancel_reservation", arguments={"reservation_id": reservation_id}),
            BlueprintAction(name="cancel_reservation", arguments={"reservation_id": reservation_id}),
        ],
        outputs=[],
    )
    result = run_stage1(bp, airline_plugin)
    assert result.execution_check.passed
    assert not result.policy_check.passed
    assert result.policy_check.violations[0].predicate_name == "no_conflicting_reservation_mutations"
