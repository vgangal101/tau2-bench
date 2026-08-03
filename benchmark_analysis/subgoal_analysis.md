# Subgoal Analysis

This note is about task *design*, not task *scoring*. See [evaluation.md](../docs/evaluation.md)
for how `evaluation_criteria` is actually graded — that schema treats a task's
outcome as a single pass/fail unit (or a product of a few reward components),
with no field for per-subgoal credit. This note instead looks at what's
inside `user_scenario.instructions`: many tasks bundle several sequential,
individually-identifiable objectives into one scenario, even though the
grader never sees them as separate.

## Definition

A **subgoal** here is a distinct objective the user wants accomplished within
a single task, such that:

- it corresponds to one or more discrete tool calls / a discrete outcome, and
- it could, in principle, succeed or fail independently of the other
  objectives in the same task.

Subgoals are usually sequential (the user states them in order, and often the
task instructions imply an order of execution), but they don't have to be
purely additive — a subgoal can be conditional on how a prior subgoal
resolved (see the refusal case below).

## Worked example: retail task `28`

Source: [`data/tau2/domains/retail/tasks.json`](../data/tau2/domains/retail/tasks.json), id `"28"`.

`reason_for_call`:

> "You want to return the skateboard, garden hose, backpack, keyboard, and
> bed. You also want to cancel the garden hose from the pending order you
> just placed (you ONLY want to cancel that hose — if this would require
> cancelling the entire order, tell the agent not to do it). Make sure ALL
> the items you want to return are returned: first return the skateboard,
> then the garden hose and backpack, then the keyboard and bed. Finally, you
> want to know the total refund amount."

This single scenario decomposes into five subgoals, in the order the user
states them:

| # | Subgoal | Reference tool call(s) | Independent of others? |
|---|---------|------------------------|--------------------------|
| 1 | Return the skateboard | `return_delivered_order_items(order_id=#W3792453, item_ids=[4293355847])` | Yes — one order, one item |
| 2 | Return the garden hose + backpack | `return_delivered_order_items(order_id=#W7181492, item_ids=[5753502325, 9851293632])` | Yes — different order |
| 3 | Return the keyboard + bed | `return_delivered_order_items(order_id=#W5565470, item_ids=[9570044148, 6857426243])` | Yes — different order |
| 4 | Cancel *only* the garden hose from the pending order; refuse if that's not possible without cancelling the whole order | (no cancellation action in the reference trajectory — correct behavior is to refuse) | Conditional — its correct resolution depends on a policy check, not on subgoals 1–3 |
| 5 | Report the total refund amount ($918.43) | `calculate(...)` + `communicate_info: ["918.43"]` | Depends on 1–3 succeeding — it's an aggregation subgoal, not independent |

Two things worth noting about the shape of this example:

- **Subgoals 1–3 are structurally identical** (return items from an order)
  but target disjoint orders/items — an agent could get any subset of them
  right independently of the others.
- **Subgoal 4 is a negative/refusal subgoal**: success means *not* taking an
  action (not cancelling the whole order), which is easy to silently fail on
  autopilot but explicit in the instructions.
- **Subgoal 5 is a rollup subgoal**: it can only be satisfied correctly if
  the agent tracked the outcomes of subgoals 1–3 accurately (the reported
  total is a function of what was actually returned).

## Why the grader collapses this to one outcome

Every subgoal above ultimately writes to (or reads from) the same shared
environment, and `evaluation_criteria` in the current schema expresses
success as:

- one target DB end-state hash (`RewardType.DB`), and
- one `communicate_info` list checked as all-or-nothing (`RewardType.COMMUNICATE`).

So an agent that nails subgoals 1, 2, 3, and 4 but reports the wrong total in
subgoal 5 gets the same `communicate_reward = 0` as an agent that botched
everything — the current scoring has no notion of "4 out of 5 subgoals."
(`RewardType.ACTION`, when enabled, gives a per-*action* match fraction via
`partial_action_reward` — see [`src/tau2/data_model/simulation.py`](../src/tau2/data_model/simulation.py) —
but that's keyed to matching one reference trajectory's tool calls, not to
semantically labeled subgoals like the table above.)

## Caveat: tool-call count is not a subgoal proxy

It's tempting to guess "if a task needs 2+ tool calls, it must have 2+
subgoals." That doesn't hold — tool count tracks *procedural complexity*
(how many steps it takes to reach an outcome), not *goal compositeness*
(how many independently-stated, independently-gradable objectives the user
has). It fails in both directions:

**Many tools, one subgoal.** This telecom MMS task
(`[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_both_permissions|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:Hard]`
in [`data/tau2/domains/telecom/tasks.json`](../data/tau2/domains/telecom/tasks.json))
stacks nine independent root-causes and needs 11 distinct tool calls to fix:

```
toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling,
reset_apn_settings, reboot_device, grant_app_permission, grant_app_permission,
toggle_data, refuel_data, reseat_sim_card, enable_roaming, toggle_roaming
```

But the user states exactly **one** objective: "fix my MMS." There's no
sequence of distinct user-facing asks — it's a single goal with a long
diagnostic/repair chain. Counting this as 11 subgoals would conflate steps
toward a goal with the goals themselves.

**Few tools per subgoal.** In task 28 above, three of the five subgoals
(return skateboard / return hose+backpack / return keyboard+bed) each
resolve with a single `return_delivered_order_items` call. High subgoal
count, low tool-count-per-subgoal — the opposite failure mode.

So use the scenario-text heuristic below (sequencing language, conjunctions
joining distinct targets, conditional fallbacks) to identify subgoals, not
the length of `evaluation_criteria.actions`.

## Caveat: ground-truth write-action count is not a subgoal proxy either

A tempting refinement of the tool-count guess is "count only *write*
(state-mutating) tool calls in the reference trajectory — surely 2+ of
those means 2+ subgoals." It sounds more principled (it filters out
read-only lookups like `get_user_details`), but it fails for the same
underlying reason as raw tool count: a write tool is often called once per
*target* (reservation, order, root-cause) in service of a single stated
goal, not once per goal.

This was checked directly with a script
([`benchmark_analysis_scripts/scan_write_action_count.py`](../benchmark_analysis_scripts/scan_write_action_count.py))
that counts `evaluation_criteria.actions` entries whose tool name is in each
domain's write-tool set (`cancel_reservation`, `book_reservation`, ... for
airline; `return_delivered_order_items`, `cancel_pending_order`, ... for
retail; `toggle_airplane_mode`, `enable_roaming`, ... for telecom — pulled
from each domain's `@is_tool(ToolType.WRITE)` decorators, not guessed) and
flags a task when that count is >=2:

| Domain | Flagged (write-count >=2) | Total | % | vs. text heuristic |
|---|---|---|---|---|
| airline | 13 | 50 | 26.0% | 15 (30.0%) |
| retail | 44 | 114 | 38.6% | 77 (67.5%) |
| **telecom** | **2240** | 2285 | **98.0%** | 0 (0.0%) |

Telecom is the decisive case: this heuristic flags almost the entire
domain, directly contradicting the earlier finding that all 2285 telecom
tasks reduce to just 3 single-goal `reason_for_call` templates. The
mechanism is visible in the flagged examples themselves — e.g. a task whose
write actions are `toggle_airplane_mode` + `enable_roaming` +
`toggle_roaming` isn't three subgoals, it's three fixes for three stacked
root-causes of one stated problem ("fix my mobile data").

Airline shows the same pattern at smaller scale. Task `18`'s entire
`reason_for_call` is:

> "You just faced some money issue and want to downgrade all business
> flights to economy, without changing the flights or passengers."

One stated goal — yet its reference trajectory has **five** identical
`update_reservation_flights` calls, one per reservation the user holds:

```
update_reservation_flights(reservation_id=JG7FMM, cabin=economy, ...)
update_reservation_flights(reservation_id=2FBBAH, cabin=economy, ...)
update_reservation_flights(reservation_id=X7BYG1, cabin=economy, ...)
update_reservation_flights(reservation_id=EQ1G6C, cabin=economy, ...)
update_reservation_flights(reservation_id=BOH180, cabin=economy, ...)
```

So write-action count conflates two distinct shapes with "N subgoals":

- **Per-target repetition** — one goal, applied across N reservations/orders
  (airline task 18; retail tasks with repeated `return_delivered_order_items`
  across orders).
- **Multi-step repair chains** — one goal, N fixes for N stacked causes
  (telecom, entire domain).

Neither is "N subgoals" under the definition above — the user asked for one
thing once. Net conclusion: neither raw tool-call count nor ground-truth
write-action count is a reliable subgoal proxy. Reading the stated-goal text
itself (the scenario-text heuristic below) is what actually distinguishes
them, precisely because it's the only signal that tracks *what the user
asked for* rather than *how many calls it took to do it*.

## Recognizing subgoal-bearing tasks

A quick heuristic for spotting these while reading `tasks.json`: look for
`reason_for_call` / `task_instructions` text containing sequencing language
("first... then... finally"), conjunctions joining distinct objects/orders
("and", "also"), or conditional fallback clauses ("if the agent asks again,
do X instead"). Task 28 hits all three. Other examples seen in
`data/tau2/domains/retail/tasks.json`: task `5` (exchange two different
items, with cascading fallback preferences if the agent asks for
confirmation), and the broader family of ~16 retail tasks that combine
"place/have an order" language with "change/cancel/modify" language in the
same scenario (found via a simple keyword scan over `reason_for_call` +
`task_instructions`).
