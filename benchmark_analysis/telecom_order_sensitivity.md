# Telecom Order Sensitivity

Empirical check of whether telecom's multi-fault composed tasks are
sensitive to the order their fix tool-calls are applied in — i.e. whether
fixing one stacked fault can block, mask, or silently undo the fix for
another, requiring an agent to "route around" it rather than fix faults in
any order. Follows on from the tool-implementation reading in the
`service_issues.py` discussion (blocking dependencies, masking, unfixable
faults) — this is the empirical version: actually replaying alternate
orderings against the environment instead of reading code for evidence.

Script: [`benchmark_analysis_scripts/check_telecom_order_sensitivity.py`](../benchmark_analysis_scripts/check_telecom_order_sensitivity.py).
Raw results: [`benchmark_analysis/telecom_order_sensitivity_results.json`](telecom_order_sensitivity_results.json).

## Why this needed checking empirically, not just by reading code

`compose_tasks()` ([tasks/utils.py:61-92](../src/tau2/domains/telecom/tasks/utils.py#L61-L92))
sorts each composed task's faults **alphabetically by `BaseTask.name`** when
building the reference `evaluation_criteria.actions` trajectory — that
ordering has no causal meaning, it's just alphabetical. Generation-time
`verify_task()` ([tasks/manager.py:197-227](../src/tau2/domains/telecom/tasks/manager.py#L197-L227))
only checks that *this one* order resolves the task; it never tries
alternate orderings. So a task can pass generation cleanly while still
containing an order dependency that a different (e.g. agent-chosen) sequence
of fixes would trip over.

## Method

For each candidate task (>=2 real fix actions, excluding the
`transfer_to_human_agents` "unfixable" tasks — nothing to permute there):

1. Build a fresh telecom environment (`registry.get_env_constructor("telecom")()`).
2. Replay `initial_state.initialization_actions` to inject the stacked faults.
3. Apply `evaluation_criteria.actions` in some order via `env.make_tool_call(...)`.
4. After each call, check the returned message for a blocked/no-op marker
   (`"cannot"`, `"failed to"`, `"not possible"`).
5. After the full sequence, run every `env_assertions` entry and record
   which ones fail.

Orders tested per task: the reference (stored) order, plus — for <=5 fix
actions — every permutation exhaustively, or — for more — the fully
reversed order plus 20 random permutations (seed 42, reproducible). A task
is flagged **order-sensitive** if any non-reference order either hits a
blocked call or ends with a failed assertion that the reference order
didn't have.

Run at n=300 (stratified by fix-action count so both small and large fault
stacks are represented, not just whichever sorts first):

```
2240 multi-fault (non-unfixable) telecom tasks available
Testing 300 tasks (stratified by fix-action count)

Order-sensitive: 159 / 300 (53.0%)
Reference-order mismatches (stored order itself didn't resolve): 0
```

The `0` reference mismatches is a sanity check, not a footnote: it confirms
the replay harness agrees with generation-time `verify_task()` on the one
order that's supposed to work, so the 53% isn't a harness bug — it's real
sensitivity to orders generation never tested.

## Two confirmed root mechanisms

Both are the same shape — a "flag now, apply later" tool pair — traced
directly in the tool implementations, not inferred from the failures alone.

**1. `reset_apn_settings` / `reboot_device` (drives most of the 53% — MMS is
~87% of the dataset and most MMS faults route through APN).**

```python
# user_tools.py:611-614
def _reset_apn_settings(self):
    """Resets your APN settings to the default settings.
    This will be applied at the next reboot."""
    self.device.active_apn_settings.reset_at_reboot = True
    return "APN settings will reset at reboot."

# user_tools.py:955-958 (inside _reboot_device)
if self.device.active_apn_settings.reset_at_reboot:
    self.device.active_apn_settings = APNSettings()   # <- fix actually happens here
```

`reset_apn_settings` doesn't fix anything by itself — it just sets a flag.
The fix only lands when `reboot_device` runs *afterward* and checks that
flag. Call `reboot_device` first and it finds the flag unset, does nothing
for APN, and the broken APN setting is never replaced — silently, no error
message. Example from the sweep:

```
order: toggle_wifi_calling, reboot_device, reset_apn_settings, reseat_sim_card
failed assertion: assert_can_send_mms
```

**2. `send_payment_request` / `make_payment` (overdue-bill / suspended-line
tasks).**

```python
# user_tools.py:1082-1090
def _make_payment(self) -> Optional[str]:
    payment_request = self._check_payment_request()
    if payment_request is None:
        return None   # <- silent no-op, "You do not have a payment request."
    payment_request.paid = True
    ...
```

`make_payment` requires a `payment_request` object that only
`send_payment_request` (assistant-side) creates. Call `make_payment` first
and it silently does nothing — no exception, just a message the agent has
to notice and act on. Example from the sweep:

```
order: reboot_device, resume_line, make_payment, send_payment_request, ...
failed assertions: assert_service_status, assert_no_overdue_bill
```

## Reading on the result

Both mechanisms are the *same pattern*: a "prepare" call that only queues a
state change, paired with an "apply" call that must run afterward to
actually commit it. Neither call fails loudly when misordered — the fix
just silently doesn't take effect, and the only way to notice is the final
assertion (or, for an agent, actually re-checking whether the issue is
resolved rather than assuming success from a clean tool response). That's
a more dangerous failure mode than the hard-blocking case found earlier
(`toggle_wifi` refusing outright while airplane mode is on) — a blocked
call at least tells the agent something went wrong; a silently-ignored
`reset_apn_settings` doesn't.

This also means the earlier read of `_get_mobile_data_working` as "a flat
AND of independent preconditions" (see `subgoal_analysis.md`'s tool-count
caveat) undersells the real dependency structure — the preconditions are
independent in what they check, but *fixing* two of them (APN, billing) is
not order-independent in execution, even though the reference trajectory
never surfaces that because it's always sorted alphabetically.

## Caveats

- 300/2240 candidate tasks sampled (stratified, seed 42) — not exhaustive.
  Rerun with `--num-tasks 2240` for a full sweep (env construction is ~3ms;
  full sweep is feasible, just slower).
- For tasks with >5 fix actions, only 20 random orders + the reversed order
  are tested, not all permutations — the true order-sensitive rate for
  those tasks could be somewhat higher or lower than what a full
  permutation sweep would show.
- "Order-sensitive" here means *some* tested alternate order fails — it
  doesn't mean *most* orders fail. Some flagged tasks had only 1 bad
  ordering out of 20+ tested; others (the payment example above) had nearly
  all of them fail. The per-task `num_interfering_orders` /
  `num_orders_tested` fields in the results JSON give the actual ratio.
