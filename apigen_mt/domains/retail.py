"""DomainPlugin implementation over tau2's retail domain."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from tau2.data_model.tasks import Action, EvaluationCriteria, RewardType, Task, UserScenario
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.environment import get_environment
from tau2.domains.retail.utils import RETAIL_DB_PATH, RETAIL_POLICY_PATH
from tau2.environment.environment import Environment

from apigen_mt.domains.base import (
    DomainDBAccessor,
    DomainPlugin,
    PolicyPredicate,
    ToolInfo,
    tools_from_toolkit,
)
from apigen_mt.phase1.schema import ExecutionCheckResult, TaskBlueprint

EXAMPLES_PATH = Path(__file__).parent / "data" / "retail_examples.json"
PERSONAS_PATH = Path(__file__).parent / "data" / "retail_personas.json"

_ORDER_MUTATING_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_items",
    "modify_pending_order_address",
    "modify_pending_order_payment",
    "exchange_delivered_order_items",
    "return_delivered_order_items",
}


def _resolve_user_ids(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> set[str]:
    ids: set[str] = set()
    for action in blueprint.actions:
        if isinstance(action.arguments.get("user_id"), str):
            ids.add(action.arguments["user_id"])
    for step in execution_result.trace:
        if step.error or not step.result_json:
            continue
        try:
            data = json.loads(step.result_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("user_id"), str):
            ids.add(data["user_id"])
        elif isinstance(data, str) and step.action.name in (
            "find_user_id_by_email",
            "find_user_id_by_name_zip",
        ):
            ids.add(data)
    return ids


def _single_user_scope(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> Optional[str]:
    """Policy: 'You can only help one user per conversation.' Not enforced
    by any individual tool -- only visible once the full action sequence's
    resolved identities are compared.
    """
    ids = _resolve_user_ids(blueprint, execution_result)
    if len(ids) > 1:
        return f"actions reference {len(ids)} distinct users {sorted(ids)}, but a task may only touch one user"
    return None


def _no_redundant_duplicate_actions(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> Optional[str]:
    seen: set[tuple[str, str]] = set()
    for action in blueprint.actions:
        key = (action.name, json.dumps(action.arguments, sort_keys=True, default=str))
        if key in seen:
            return f"duplicate action '{action.name}' with identical arguments appears twice"
        seen.add(key)
    return None


def _no_conflicting_order_mutations(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> Optional[str]:
    """Policy: combining actions could 'cause conflicting actions to appear
    together, e.g. returning and cancelling the same order.' This is the
    exact example the paper gives for reverse task recombination's Stage-1
    re-check; we run it defensively at single-task validation too.
    """
    by_order: dict[str, list[str]] = {}
    for action in blueprint.actions:
        if action.name in _ORDER_MUTATING_TOOLS:
            order_id = action.arguments.get("order_id")
            if isinstance(order_id, str):
                by_order.setdefault(order_id, []).append(action.name)
    for order_id, tool_names in by_order.items():
        if len(tool_names) > 1:
            return f"order {order_id} is targeted by more than one mutating action in a single blueprint: {tool_names}"
    return None


class RetailDBAccessor(DomainDBAccessor):
    def __init__(self, db: Optional[RetailDB] = None):
        self._db = db or RetailDB.load(RETAIL_DB_PATH)

    def sample_user(self, rng: random.Random) -> dict:
        with_orders = [uid for uid, u in self._db.users.items() if u.orders]
        pool = with_orders or list(self._db.users.keys())
        user_id = rng.choice(pool)
        user = self._db.users[user_id]
        return {
            "user_id": user_id,
            "first_name": user.name.first_name,
            "last_name": user.name.last_name,
            "email": user.email,
            "zip": user.address.zip,
            "order_ids": list(user.orders),
            "payment_method_ids": list(user.payment_methods.keys()),
        }

    def sample_related_records(
        self, user_id: str, rng: random.Random, k: int = 2
    ) -> list[dict]:
        user = self._db.users.get(user_id)
        if user is None or not user.orders:
            return []
        order_ids = rng.sample(user.orders, min(k, len(user.orders)))
        records = []
        for order_id in order_ids:
            order = self._db.orders.get(order_id)
            if order is None:
                continue
            records.append(
                {
                    "order_id": order_id,
                    "status": order.status,
                    "items": [
                        {
                            "item_id": item.item_id,
                            "product_id": item.product_id,
                            "name": item.name,
                            "price": item.price,
                        }
                        for item in order.items
                    ],
                    "payment_history": [
                        {
                            "payment_method_id": p.payment_method_id,
                            "transaction_type": p.transaction_type,
                            "amount": p.amount,
                        }
                        for p in order.payment_history
                    ],
                }
            )
        return records


class RetailDomainPlugin(DomainPlugin):
    name = "retail"

    def env_factory(self) -> Environment:
        return get_environment()

    def tools(self) -> list[ToolInfo]:
        return tools_from_toolkit(get_environment().tools)

    def api_graph_edges(self) -> list[tuple[str, str]]:
        return [
            ("find_user_id_by_email", "get_user_details"),
            ("find_user_id_by_name_zip", "get_user_details"),
            ("get_user_details", "get_order_details"),
            ("get_order_details", "get_product_details"),
            ("get_order_details", "modify_pending_order_items"),
            ("get_order_details", "modify_pending_order_address"),
            ("get_order_details", "modify_pending_order_payment"),
            ("get_order_details", "cancel_pending_order"),
            ("get_order_details", "exchange_delivered_order_items"),
            ("get_order_details", "return_delivered_order_items"),
            ("get_product_details", "exchange_delivered_order_items"),
            ("get_product_details", "modify_pending_order_items"),
            ("list_all_product_types", "get_product_details"),
        ]

    def policy_doc_path(self) -> Path:
        return RETAIL_POLICY_PATH

    def policy_predicates(self) -> list[PolicyPredicate]:
        return [
            PolicyPredicate(
                name="single_user_scope",
                description="You can only help one user per conversation.",
                check=_single_user_scope,
            ),
            PolicyPredicate(
                name="no_redundant_duplicate_actions",
                description="No exact duplicate action should appear twice in one blueprint.",
                check=_no_redundant_duplicate_actions,
            ),
            PolicyPredicate(
                name="no_conflicting_order_mutations",
                description="At most one mutating action per order in a single blueprint.",
                check=_no_conflicting_order_mutations,
            ),
        ]

    def db_accessor(self) -> DomainDBAccessor:
        return RetailDBAccessor()

    def persona_bank(self) -> list[str]:
        return json.loads(PERSONAS_PATH.read_text())

    def example_tasks(self) -> list[dict]:
        return json.loads(EXAMPLES_PATH.read_text())

    def blueprint_to_native_task(self, blueprint: TaskBlueprint, task_id: str) -> Task:
        actions = [
            Action(
                action_id=f"{task_id}_{i}",
                requestor=action.requestor,
                name=action.name,
                arguments=action.arguments,
            )
            for i, action in enumerate(blueprint.actions)
        ]
        return Task(
            id=task_id,
            user_scenario=UserScenario(persona=blueprint.persona, instructions=blueprint.intent),
            evaluation_criteria=EvaluationCriteria(
                actions=actions,
                communicate_info=list(blueprint.outputs),
                reward_basis=[RewardType.DB, RewardType.COMMUNICATE],
            ),
        )
