# Benchmark Subgoal Task Scanning

Method and approach for scanning airline, retail, and telecom tasks
(`data/tau2/domains/{domain}/tasks.json`) to find which ones state more than
one subgoal. See [subgoal_analysis.md](subgoal_analysis.md) for what "subgoal"
means here and why it's a task-design notion, not something the scoring
schema tracks. Results are in the per-domain files:

- [conjunctive_tasks_airline.md](conjunctive_tasks_airline.md)
- [conjunctive_tasks_retail.md](conjunctive_tasks_retail.md)
- [conjunctive_tasks_telecom.md](conjunctive_tasks_telecom.md)

Script: [`benchmark_analysis_scripts/scan_conjunctive_goals.py`](../benchmark_analysis_scripts/scan_conjunctive_goals.py).

## Scope

Only `user_scenario.instructions.reason_for_call` is scanned. This is the
field that states what the user wants; `task_instructions` mostly carries
behavioral/negotiation directions (tone, fallback conditions, what to say if
the agent pushes back) rather than additional goals, so it's excluded to
avoid false hits from stylistic text.

## Why not just count tool calls

An earlier pass at this considered "task uses 2+ tools → multiple subgoals"
as the proxy. It doesn't hold in either direction — a single subgoal can
need many tool calls (a telecom task chaining 11 tool calls to fix one
stated issue across 9 stacked root causes), and a subgoal can resolve in one
tool call while a task still has several of them (three of retail task 28's
five subgoals each resolve with a single `return_delivered_order_items`
call). Tool count tracks procedural complexity, not how many distinct,
independently-gradable objectives the user stated. See the caveat section of
`subgoal_analysis.md` for the full argument. This scan instead reads the
stated goal text directly.

## Heuristic

A task is flagged as conjunctive if `reason_for_call` matches any of:

1. **Multiple action-verb types.** Two or more distinct verbs from a
   domain-specific list, each in *base form only* (no `-ed`/`-ing`/`-s`
   variants matched) — e.g. retail: `return`, `exchange`, `cancel`,
   `modify`, `change`, `refund`, `add`, `remove`, `upgrade`, `downgrade`,
   `swap`. Base-form-only matching is deliberate: it skips inflected/gerund
   uses that don't state a goal (`"after booking"`, `"you booked the
   flight"`, `"things ordered"`) while still catching verbs that share a
   single "to" across a coordinated list (`"want to return X and exchange
   Y"` — `exchange` has no `to` of its own but is still a stated goal).

2. **Multiple target IDs.** Two or more distinct order numbers (`#W\d+`,
   retail) or reservation codes (6-char alphanumeric, airline) in the text
   — e.g. `"cancel ... (IFOYYZ and NQNU5R) and change a third (M20IZO)"`.

3. **One verb, enumerated objects.** A single action verb applied to two or
   more distinct objects joined by `"and the/a/your/my"` — e.g.
   `"exchange the water bottle and the desk lamp"`. Distinct-verb-type
   counting alone misses this because the same verb is only used once.

4. **Explicit conjunction phrase + a verb.** `"also"`, `"as well as"`, `"in
   addition"`, or `"and also"` co-occurring with at least one matched verb —
   e.g. `"You also want to upgrade your class to business."`

Verb-list vocabulary was drawn from each domain's actual write-tools
(`tools.py`), not guessed English verbs — e.g. retail's list matches
`cancel_pending_order`, `exchange_delivered_order_items`,
`modify_pending_order_*`, `return_delivered_order_items`. An earlier version
included `order`/`buy`/`purchase`, which were dropped after checking that
`"order"` in retail `reason_for_call` text is overwhelmingly a noun
(`"your order #W123"`), not a verb — retail tasks manage existing orders,
they don't place new ones.

**Negation guard:** a verb match preceded within 25 characters by a negation
phrase (`"don't want to"`, `"won't"`, `"refuse to"`, ...) is dropped — e.g.
`"you don't want to cancel the flight itself"` doesn't count `cancel` as a
stated goal.

## Validation

Precision was checked by hand against ~20 flagged tasks across airline and
retail (see the tool-count caveat's own examples plus a random sample of 10
per domain) — all read as genuine multi-part asks. Two adjustments came out
of that pass:

- Dropping `order`/`buy`/`purchase` from the retail verb list (noun-usage
  false positives).
- Adding the negation guard, after airline task `46` ("you don't want to
  cancel the flight itself") was flagged purely on the negated mention.

Known remaining limitation: recall is inherently incomplete for regex over
free text — oddly-phrased compound sentences can be missed, and borderline
cases exist where a second matched verb is arguably just the expected
consequence of the first (e.g. `"cancel the flight and get a refund"` — is
refund a separate subgoal, or just what cancelling entails?). These were
left counted; treat the resulting numbers as an approximate, spot-checked
lower-bound-ish estimate rather than ground truth.

## Results

| Domain | Flagged | Total | % |
|---|---|---|---|
| airline | 15 | 50 | 30.0% |
| retail | 77 | 114 | 67.5% |
| telecom | 0 | 2285 | 0.0% |

Telecom's zero is not a heuristic miss: all 2285 tasks reduce to only **3**
distinct `reason_for_call` strings (fix no-service / fix MMS / fix mobile
data), each stating exactly one user-facing goal. The apparent complexity
visible in telecom task IDs (9+ pipe-separated fault tags) and reference
trajectories (up to 11 tool calls) is diagnostic-path depth for that one
goal, not multiple stated goals — the clearest real-world instance of the
tool-count caveat above.
