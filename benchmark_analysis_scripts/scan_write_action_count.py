"""
Alternate heuristic for subgoal count: instead of reading reason_for_call
text (scan_conjunctive_goals.py), count *write* (state-mutating) tool calls
in each task's evaluation_criteria.actions reference trajectory. A task is
flagged if it has >=2 write actions.

Write-tool names below were pulled from each domain's tools.py/user_tools.py
via `@is_tool(ToolType.WRITE)` decorators (confirmed by instantiating each
domain's Environment and checking `toolkit.tool_type(name) == ToolType.WRITE`
in a REPL) rather than guessed — read-only lookups (get_user_details,
get_order_details, ...) are excluded so they don't inflate the count.

Note: `evaluation_criteria.actions` records one reference trajectory, and for
telecom it mixes requestor="assistant" tool calls (agent-side) with
requestor="user" tool calls (the user simulator's device performing a toggle
the agent walked them through) — both are counted here since the toolkit
each name belongs to already disambiguates requestor.

Run: python3 benchmark_analysis_scripts/scan_write_action_count.py
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "tau2" / "domains"

WRITE_TOOLS = {
    "airline": {
        "book_reservation", "cancel_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_flights",
        "update_reservation_passengers",
    },
    "retail": {
        "cancel_pending_order", "exchange_delivered_order_items",
        "modify_pending_order_address", "modify_pending_order_items",
        "modify_pending_order_payment", "modify_user_address",
        "return_delivered_order_items",
    },
    "telecom": {
        # agent-side (tools.py)
        "disable_roaming", "enable_roaming", "refuel_data", "resume_line",
        "send_payment_request", "suspend_line",
        # user-side (user_tools.py) — the user's device performing a fix
        "connect_vpn", "disconnect_vpn", "grant_app_permission",
        "make_payment", "reboot_device", "reseat_sim_card",
        "reset_apn_settings", "set_apn_settings",
        "set_network_mode_preference", "toggle_airplane_mode",
        "toggle_data", "toggle_data_saver_mode", "toggle_roaming",
        "toggle_wifi", "toggle_wifi_calling",
    },
}


def scan_domain(domain):
    path = DATA_DIR / domain / "tasks.json"
    with open(path) as f:
        tasks = json.load(f)

    write_tools = WRITE_TOOLS[domain]
    flagged = []
    counts = {}
    for t in tasks:
        actions = (t.get("evaluation_criteria") or {}).get("actions") or []
        write_actions = [a for a in actions if a["name"] in write_tools]
        n = len(write_actions)
        counts[n] = counts.get(n, 0) + 1
        if n >= 2:
            flagged.append(
                {
                    "id": t["id"],
                    "num_write_actions": n,
                    "write_actions": [
                        f"{a['name']}({a.get('requestor', 'assistant')})" for a in write_actions
                    ],
                }
            )

    return len(tasks), flagged, counts


def main():
    for domain in ["airline", "retail", "telecom"]:
        total, flagged, counts = scan_domain(domain)
        pct = 100 * len(flagged) / total if total else 0
        print(f"\n=== {domain}: {len(flagged)}/{total} flagged ({pct:.1f}%) ===")
        print(f"  write-action-count histogram: {dict(sorted(counts.items()))}")
        for f in flagged[:10]:
            print(f"  [{f['id']}] {f['num_write_actions']} write actions: {f['write_actions']}")


if __name__ == "__main__":
    main()
