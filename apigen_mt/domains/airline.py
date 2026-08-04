"""DomainPlugin implementation over tau2's airline domain."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from tau2.data_model.tasks import Action, EvaluationCriteria, RewardType, Task, UserScenario
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.airline.environment import get_environment
from tau2.domains.airline.utils import AIRLINE_DB_PATH, AIRLINE_POLICY_PATH
from tau2.environment.environment import Environment

from apigen_mt.domains.base import (
    DomainDBAccessor,
    DomainPlugin,
    PolicyPredicate,
    ToolInfo,
    tools_from_toolkit,
)
from apigen_mt.phase1.schema import ExecutionCheckResult, TaskBlueprint

EXAMPLES_PATH = Path(__file__).parent / "data" / "airline_examples.json"
PERSONAS_PATH = Path(__file__).parent / "data" / "airline_personas.json"

_RESERVATION_MUTATING_TOOLS = {
    "cancel_reservation",
    "update_reservation_baggages",
    "update_reservation_flights",
    "update_reservation_passengers",
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
    return ids


def _single_user_scope(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> Optional[str]:
    """Policy: the agent handles one user's reservations per conversation.
    Not enforced by any individual tool -- only visible once the full
    action sequence's resolved identities are compared.
    """
    ids = _resolve_user_ids(blueprint, execution_result)
    if len(ids) > 1:
        return f"actions reference {len(ids)} distinct users {sorted(ids)}, but a task may only touch one user"
    return None


def _no_conflicting_reservation_mutations(
    blueprint: TaskBlueprint, execution_result: ExecutionCheckResult
) -> Optional[str]:
    """cancel_reservation has no status guard and can silently be called
    more than once (each call just appends another refund), so this
    conflict is invisible to the execution replay -- it must be caught
    here, as a check over the action sequence itself.
    """
    by_reservation: dict[str, list[str]] = {}
    for action in blueprint.actions:
        if action.name in _RESERVATION_MUTATING_TOOLS:
            reservation_id = action.arguments.get("reservation_id")
            if isinstance(reservation_id, str):
                by_reservation.setdefault(reservation_id, []).append(action.name)
    for reservation_id, tool_names in by_reservation.items():
        if len(tool_names) > 1:
            return (
                f"reservation {reservation_id} is targeted by more than one mutating "
                f"action in a single blueprint: {tool_names}"
            )
    return None


class AirlineDBAccessor(DomainDBAccessor):
    def __init__(self, db: Optional[FlightDB] = None):
        self._db = db or FlightDB.load(AIRLINE_DB_PATH)

    def sample_user(self, rng: random.Random) -> dict:
        with_reservations = [uid for uid, u in self._db.users.items() if u.reservations]
        pool = with_reservations or list(self._db.users.keys())
        user_id = rng.choice(pool)
        user = self._db.users[user_id]
        return {
            "user_id": user_id,
            "first_name": user.name.first_name,
            "last_name": user.name.last_name,
            "email": user.email,
            "membership": user.membership,
            "reservation_ids": list(user.reservations),
            "payment_method_ids": list(user.payment_methods.keys()),
        }

    def sample_related_records(
        self, user_id: str, rng: random.Random, k: int = 2
    ) -> list[dict]:
        user = self._db.users.get(user_id)
        if user is None or not user.reservations:
            return []
        reservation_ids = rng.sample(user.reservations, min(k, len(user.reservations)))
        records = []
        for reservation_id in reservation_ids:
            reservation = self._db.reservations.get(reservation_id)
            if reservation is None:
                continue
            records.append(
                {
                    "reservation_id": reservation_id,
                    "status": reservation.status,
                    "origin": reservation.origin,
                    "destination": reservation.destination,
                    "cabin": reservation.cabin,
                    "flights": [
                        {"flight_number": f.flight_number, "date": f.date}
                        for f in reservation.flights
                    ],
                    "total_baggages": reservation.total_baggages,
                    "nonfree_baggages": reservation.nonfree_baggages,
                    "insurance": reservation.insurance,
                }
            )
        return records


class AirlineDomainPlugin(DomainPlugin):
    name = "airline"

    def env_factory(self) -> Environment:
        return get_environment()

    def tools(self) -> list[ToolInfo]:
        return tools_from_toolkit(get_environment().tools)

    def api_graph_edges(self) -> list[tuple[str, str]]:
        return [
            ("get_user_details", "cancel_reservation"),
            ("get_user_details", "update_reservation_baggages"),
            ("get_user_details", "update_reservation_flights"),
            ("get_user_details", "update_reservation_passengers"),
            ("get_user_details", "send_certificate"),
            ("get_reservation_details", "cancel_reservation"),
            ("get_reservation_details", "update_reservation_baggages"),
            ("get_reservation_details", "update_reservation_flights"),
            ("get_reservation_details", "update_reservation_passengers"),
            ("list_all_airports", "search_direct_flight"),
            ("list_all_airports", "search_onestop_flight"),
            ("search_direct_flight", "book_reservation"),
            ("search_onestop_flight", "book_reservation"),
        ]

    def policy_doc_path(self) -> Path:
        return AIRLINE_POLICY_PATH

    def policy_predicates(self) -> list[PolicyPredicate]:
        return [
            PolicyPredicate(
                name="single_user_scope",
                description="The agent handles one user's reservations per conversation.",
                check=_single_user_scope,
            ),
            PolicyPredicate(
                name="no_conflicting_reservation_mutations",
                description="At most one mutating action per reservation in a single blueprint.",
                check=_no_conflicting_reservation_mutations,
            ),
        ]

    def db_accessor(self) -> DomainDBAccessor:
        return AirlineDBAccessor()

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
