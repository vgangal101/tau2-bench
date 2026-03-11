# Plan: Active GoAway Reconnection for Gemini Provider

## Problem

The Gemini team reported that our current session resumption flow is incorrect.
When the server sends a `GoAway` message (indicating the session will timeout in ~30s),
we **passively wait** for the server to close the connection. Only after the connection
close exception fires do we attempt resumption.

The expected behavior is: upon receiving `GoAway`, the client should **actively close**
the connection and reconnect with the stored resumption handle. The server expects the
client to initiate the disconnect — not wait for the server to do it. The Gemini team
further clarified that the client should choose the **most appropriate moment** within
the GoAway window to perform the reconnection.

## Current Flow (Incorrect)

```
GoAway received → set _go_away_received = True, emit event, continue receiving
   ... (up to 30s pass) ...
Server closes WebSocket → receive loop catches ConnectionClosed exception
   → check _go_away_received == True → _reconnect_with_resumption()
   → close old session, connect() with stored handle → continue receive loop
```

The problem: we sit idle for up to 30 seconds between GoAway and actual reconnection,
and the server doesn't expect the client to just wait.

## Reconnection Timing Strategy

The Gemini team expects us to reconnect at the "most appropriate moment" within the
GoAway window (~30s). In our tick-based architecture, there is a natural best moment:
**the server turn boundary**.

### Why turn boundaries are the cleanest reconnection point

The provider's receive loop has a two-level structure:

```
while not stop:                          # outer: session lifetime
    turn = session.receive()
    async for response in turn:          # inner: one server turn
        parse and queue events
    # ← TURN BOUNDARY: inner loop exits
    emit turn_complete, audio.done
```

At a turn boundary:
- **No audio is mid-stream** — Gemini finished its current utterance.
- **All function calls for this turn are fully emitted** — the inner loop consumed
  every response in the turn, so all `function_call.done` events are already in the
  queue.
- **The conversation is at a well-defined state boundary** — the server explicitly
  signaled "I'm done for now."

Compare this to reconnecting immediately when GoAway is parsed (mid-turn):
- Could interrupt audio mid-stream, losing partial utterances.
- Could split a function call emission (GoAway arrives between two function_call events
  in the same turn).
- Forces the resumed session to pick up mid-thought.

### Tiered strategy

Since we have ~30s but no guarantee the current turn finishes quickly, we use a
tiered approach:

| Priority | Condition | Action |
|----------|-----------|--------|
| **Best** | Current turn completes naturally within the GoAway window | Reconnect after emitting `turn_complete` / `audio.done` — cleanest possible state |
| **Fallback** | Turn hasn't completed and safety deadline is approaching (`time_left - 5s`) | Force-break out of inner loop and reconnect immediately — avoids hitting the hard server disconnect |

### Comparison of approaches

| Approach | Pros | Cons |
|----------|------|------|
| **Immediate** (on GoAway) | Simple, deterministic | Interrupts mid-audio, mid-function-call emission. GoAway and interrupted events land in queue simultaneously |
| **At turn boundary** (chosen) | Clean state, no interrupted streams, all events for the turn fully queued before reconnect | Slightly more complex. Needs fallback timer for turns that outlast the GoAway window |

## Proposed Flow

```
GoAway received (with time_left=~30s)
   → set _reconnect_at_turn_boundary = True
   → compute _reconnect_deadline = now + (time_left - 5s)
   → continue receiving within current turn

Turn completes naturally (inner async-for exits):
   → emit turn_complete / audio.done as usual
   → check _reconnect_at_turn_boundary → True
   → call _reconnect_with_resumption()
   → reset state, continue receive loop on new session

OR deadline fires mid-turn (fallback):
   → inner loop checks deadline after each response
   → force-break, skip turn_complete emission
   → call _reconnect_with_resumption()
   → reset state, continue receive loop on new session
```

## Changes Required

### 1. New provider state (`provider.py` — `__init__`)

Replace `_reconnect_needed` with turn-boundary-aware state:

```python
self._reconnect_at_turn_boundary: bool = False
self._reconnect_deadline: Optional[float] = None  # asyncio loop time
```

### 2. Set flags when GoAway is parsed (`provider.py` — `_parse_response`)

In the GoAway handling block (around line 1091), after setting `_go_away_received = True`,
signal deferred reconnection:

```python
self._go_away_received = True
self._reconnect_at_turn_boundary = True

# Compute deadline: reconnect before server's hard cutoff
time_left = time_left if time_left is not None else 30.0
safety_margin = 5.0
self._reconnect_deadline = (
    asyncio.get_event_loop().time() + max(time_left - safety_margin, 1.0)
)
```

### 3. Check deadline in inner loop (`provider.py` — `_receive_loop_coro`)

In the inner loop (`async for response in turn`), after queuing events, check the
fallback deadline:

```python
async for response in turn:
    if self._stop_receive:
        break

    response_count += 1
    events = self._parse_response(response)
    for event in events:
        await self._event_queue.put(event)

    # NEW: If GoAway received and deadline approaching, force-break
    if (
        self._reconnect_at_turn_boundary
        and self._reconnect_deadline is not None
        and asyncio.get_event_loop().time() >= self._reconnect_deadline
    ):
        logger.warning(
            "GoAway deadline approaching, force-breaking out of turn"
        )
        break
```

### 4. Reconnect at turn boundary or after forced break (`provider.py` — `_receive_loop_coro`)

After the inner loop exits, and **after** emitting `turn.complete` / `audio.done`
(for the natural turn boundary case), check the flag:

```python
# Turn ended normally - emit turn complete
if not self._stop_receive:
    await self._event_queue.put(
        GeminiTurnCompleteEvent(type="turn.complete")
    )
    await self._event_queue.put(
        GeminiAudioDoneEvent(
            type="audio.done",
            item_id=self._current_item_id,
        )
    )
    self._current_item_id = self._generate_item_id()

# NEW: Active GoAway reconnection at turn boundary
if self._reconnect_at_turn_boundary:
    self._reconnect_at_turn_boundary = False
    self._reconnect_deadline = None
    logger.info(
        "GoAway received — actively disconnecting and "
        "reconnecting at turn boundary"
    )
    try:
        success = await self._reconnect_with_resumption()
        if success:
            logger.info(
                "Active GoAway reconnection successful, "
                "restarting receive loop"
            )
            continue  # restart while loop with new session
    except Exception as e:
        logger.error(f"Active GoAway reconnection failed: {e}")
    # If reconnection failed, raise to surface the error
    raise RuntimeError("Active GoAway reconnection failed")
```

Note: for the **natural turn boundary** path, `turn_complete` and `audio.done` are
emitted before the reconnection — the adapter sees a complete turn. For the **forced
break** (deadline), the turn was incomplete, so we skip `turn_complete` emission
(the `_stop_receive` check handles this implicitly since we broke out of the inner
loop without the turn finishing). In practice, the forced break only triggers if the
turn outlasts the GoAway window minus the 5s safety margin.

### 5. Reset `_go_away_received` after reconnection (`provider.py` — `_reconnect_with_resumption`)

At the end of `_reconnect_with_resumption()`, after a successful `connect()`, reset
GoAway state so the new session can detect its own future GoAway:

```python
self._go_away_received = False
self._reconnect_at_turn_boundary = False
self._reconnect_deadline = None
```

### 6. Simplify the exception handler in the receive loop

The exception handler for `is_connection_closed` currently has the `resume_only_on_timeout`
/ `_go_away_received` logic. With active GoAway handling, the exception path should now
only fire for **unexpected** disconnects (no GoAway received). This means:

- If `_go_away_received` is True when we hit the exception handler, it means the active
  reconnection path above failed or was somehow skipped — treat as a bug / hard failure.
- If `_go_away_received` is False, it's a genuine unexpected disconnect. The existing
  `resume_only_on_timeout` logic still applies here: if `resume_only_on_timeout=False`,
  attempt resumption even on unexpected disconnects; if True (default), fail fast.

The exception handler logic doesn't need to change structurally — it already does the
right thing for unexpected disconnects. But we should update the comments to clarify
that GoAway-triggered reconnection is now handled proactively above, and the exception
handler is the fallback for unexpected closes.

### 7. Adapter-level changes (`discrete_time_adapter.py`)

**None required.** The adapter already delegates GoAway handling to the provider:

```python
elif isinstance(event, GeminiGoAwayEvent):
    logger.warning(...)
    # The provider will handle reconnection automatically
```

This comment is already accurate with the new flow — the provider handles it internally
within the receive loop. The adapter sees no difference.

## Edge Cases

> **Important note:** The edge cases documented below are **not new risks introduced
> by this change**. They all exist in the current (reactive) implementation — where
> the server decides when to disconnect, giving us zero control over timing. The
> current approach is actually *worse*: the server can cut the connection mid-audio,
> mid-function-call emission, or during `send_tool_response()` at its own convenience.
>
> The turn-boundary strategy **reduces** the risk surface by giving us control over
> when the disconnect happens. Specifically:
>
> | Concern | Current (reactive) | Proposed (turn-boundary) |
> |---------|-------------------|--------------------------|
> | Mid-audio-stream disconnect | Possible — server decides | Avoided — we wait for turn end |
> | Mid-function-call-emission disconnect | Possible — server decides | Avoided — turn end means all function calls fully emitted |
> | Pending tool call state across resumption | Same risk | Same risk, but all calls guaranteed received |
> | `send_tool_response()` on stale session | Possible — timing uncontrolled | Extremely unlikely — we control reconnection timing |
> | Interrupted turn (partial events in queue) | Possible | Only in deadline fallback path |
>
> The analysis below documents these scenarios for completeness and to highlight
> what remains as residual risk.

### 1. GoAway arrives mid-tool-call (detailed analysis)

There are two distinct sub-scenarios depending on when GoAway arrives relative to the
tool call lifecycle. Both involve the interplay between the provider's background
**receive loop** (an `asyncio.Task` running `_receive_loop_coro`) and the adapter's
**tick execution** (`_async_run_tick`), which communicate via an `asyncio.Queue`.

#### Architecture context

```
┌─────────────────────────────┐      ┌──────────────────────────────────┐
│  Provider receive loop      │      │  Adapter tick (_async_run_tick)  │
│  (background asyncio.Task)  │      │  (called per tick)              │
│                             │      │                                 │
│  async for response in turn │      │  1. send pending tool results   │
│    → _parse_response()      │      │  2. send user audio             │
│    → _event_queue.put()  ───┼──→───┤  3. receive_events_for_duration │
│                             │      │     → drains _event_queue       │
│                             │      │  4. process events              │
│                             │      │  5. return TickResult           │
└─────────────────────────────┘      └──────────────────────────────────┘
                                                    │
                                                    ▼
                                     ┌──────────────────────────────────┐
                                     │  Orchestrator                    │
                                     │  - receives TickResult           │
                                     │  - executes tool calls against   │
                                     │    environment                   │
                                     │  - passes results back to        │
                                     │    adapter on NEXT tick          │
                                     └──────────────────────────────────┘
```

Tool calls have a multi-tick lifecycle:

```
Tick N:   Gemini emits function_call.done → queued → adapter puts in TickResult.tool_calls
          Orchestrator executes tool, stores result as pending
Tick N+1: Adapter sends pending tool result via provider._session.send_tool_response()
          Gemini receives result, generates audio response
```

#### Scenario A: GoAway arrives after `function_call.done` but before tool result is sent back

This is the **most likely** scenario. GoAway comes ~30s before timeout, so it can
easily land between the tick where Gemini issues the function call (tick N) and the
tick where we send the result back (tick N+1).

With the turn-boundary strategy, this scenario is **significantly improved** compared
to immediate reconnection. Here's why:

In Gemini's Live API, a server turn that includes function calls ends with
`turn_complete` after all function calls are emitted. So the turn boundary falls
**after** all function_call.done events are in the queue. The reconnection happens at
this clean boundary:

**Timeline:**

```
Tick N (or spanning multiple ticks):
  1. Receive loop: inner async-for receives function_call.done events → queued
  2. Receive loop: inner async-for receives GoAway → sets _reconnect_at_turn_boundary
  3. Receive loop: inner async-for continues (NOT breaking — waiting for turn end)
  4. Receive loop: inner async-for exits naturally (server's turn is complete)
  5. Receive loop: emits turn_complete + audio.done → queued
  6. Receive loop: checks _reconnect_at_turn_boundary → True
  7. Receive loop: calls _reconnect_with_resumption()

  Meanwhile, adapter drains queue across ticks:
  - Sees function_call.done → adds to TickResult.tool_calls
  - Sees GoAwayEvent → logs warning (no-op)
  - Sees turn_complete → logs

  Orchestrator: executes tool calls, stores results as pending

Between ticks:
  8. Receive loop completes reconnection (close old session, connect() with handle)
  9. New session is established, receive loop restarts with new self._session

Tick N+1:
  10. Adapter calls self.provider._session.send_tool_response() on the NEW session
  11. Gemini (resumed session) receives the tool result
```

The key difference from immediate reconnection: step 3 — we **don't break** out of
the inner loop when GoAway is parsed. We let the turn finish, so all function calls
are fully received before we reconnect. This means the adapter and orchestrator see a
complete, uninterrupted tool call sequence.

**Fallback case:** If the turn outlasts the GoAway window (deadline fires), we
force-break mid-turn. In this case, some function_call.done events might have been
queued but the turn didn't complete. The adapter will still process whatever was
queued, but there may be an incomplete set of function calls for that turn. This is
an inherent limitation — the server is about to disconnect us anyway.

**Concurrency safety:** Since everything runs on the same asyncio event loop, there is
no true parallelism. The receive loop and the adapter tick alternate on `await` points.
Between tick N ending and tick N+1 starting, the receive loop gets the event loop to
itself and completes the reconnection. By the time tick N+1 calls
`send_tool_response()`, `self.provider._session` points to the new (valid) session.

**Key risk — does Gemini preserve pending tool call state across resumption?**
When we reconnect with the resumption handle, does the resumed session remember that
it issued a function call and is waiting for the result? If it does, our
`send_tool_response()` on the new session will work normally. If it doesn't, the tool
result will be rejected or ignored, and the conversation will stall.

**⚠️ This must be verified with the Gemini team.** If resumption does NOT preserve
pending tool call state, we would need to either:
- Re-send the original function call context after resumption so Gemini re-issues it, or
- Detect this case and replay the tool result as part of conversation history, or
- Delay reconnection until the full tool call round-trip completes (send result +
  receive response) — but this risks hitting the hard timeout.

**Verdict:** The turn-boundary strategy reduces the risk surface: all function calls
from the turn are fully received before reconnection. The remaining open question is
whether the resumed session accepts tool results for calls made pre-disconnect.

#### Scenario B: GoAway arrives during `send_tool_response()` on tick N+1

This would mean the old connection is being torn down (by our active reconnection in
the receive loop) at the exact moment the adapter is writing to it.

**How this could happen:**

```
Tick N+1 starts:
  1. Adapter calls send_tool_response() on self.provider._session
  2. Concurrently, receive loop is in _reconnect_with_resumption():
     - Calls self._session_context_manager.__aexit__()  → closes the WebSocket
     - Sets self._session = None
  3. The send_tool_response() write hits a closed socket → raises exception
```

However, this is **extremely unlikely** in practice because:
- The turn-boundary strategy means reconnection happens after a turn completes, which
  is between ticks (the adapter's tick drives the pacing). The adapter's next tick
  (which sends tool results) only starts after the reconnection is already complete.
- For this to happen, the turn boundary and the tick boundary would need to misalign
  so that `_reconnect_with_resumption()` and `send_tool_response()` overlap at an
  `await` point — an extremely narrow window.

If it did happen, the exception would propagate up through `_async_run_tick`:

```python
except Exception as e:
    logger.error(f"Error in run_tick (tick={tick_number}): {e}")
    raise
```

This would surface as a hard tick failure to the orchestrator.

**Possible mitigation (optional, low priority):** Add a retry wrapper in the adapter's
`send_tool_response` path — if sending fails due to a closed connection, wait briefly
for reconnection to complete (e.g., poll `self.provider.is_connected` with a short
backoff), then retry on the new session. This adds complexity and is likely unnecessary
given the timing analysis above.

**Verdict:** Extremely unlikely. Not worth mitigating unless observed in practice.

#### Summary table

| Scenario | Description | Likelihood | Concurrency safe? | Gemini-side risk |
|----------|-------------|-----------|-------------------|-----------------|
| **A** | GoAway between function_call.done (tick N) and send_tool_response (tick N+1) | High | Yes — turn-boundary strategy ensures all function calls are received before reconnect. Reconnection completes between ticks. | **Must verify** resumed session accepts tool results for pre-disconnect calls |
| **B** | GoAway during send_tool_response() write | Very low | Write-to-closed-socket exception | N/A — fails before reaching Gemini |

### 2. GoAway arrives but no resumption handle yet

`_reconnect_with_resumption()` checks for `_resumption_handle is None` and returns
False. The receive loop raises a RuntimeError. This matches current behavior — can't
resume without a handle.

### 3. Multiple GoAways

Unlikely but safe. The first one triggers reconnection. After reconnect,
`_go_away_received` and `_reconnect_needed` are reset, so a future GoAway on the new
session will also be handled correctly.

### 4. `max_resumptions` exhausted

`_reconnect_with_resumption()` checks the count and returns False. The receive loop
raises a RuntimeError. Same as current behavior.

### 5. `send_audio` called during reconnection

The receive loop and `send_audio` run on the same event loop. Since
`_reconnect_with_resumption` is awaited inside the receive loop, there is no concurrent
`send_audio` call — the adapter's tick is blocked waiting for events from the queue.
No race condition.

## Open Questions for Gemini Team

1. **Does session resumption preserve pending tool call state?** If Gemini issued a
   `function_call` before GoAway and we reconnect with the resumption handle, does the
   resumed session still expect (and accept) the corresponding `function_response`?
   This is critical for Scenario A above. Our turn-boundary strategy ensures all
   function calls are received before reconnecting, but we still need the resumed
   session to accept the results.

2. **Is the `time_left` value in GoAway reliable for deadline computation?** We use
   `time_left - 5s` as a safety margin for the fallback timer. Is 5 seconds sufficient,
   or should we use a larger margin?

## Files Modified

| File | Change |
|------|--------|
| `provider.py` | Add `_reconnect_at_turn_boundary` and `_reconnect_deadline` state, set on GoAway, check deadline in inner loop, reconnect after turn boundary, reset state after reconnect |
| `discrete_time_adapter.py` | No changes needed |
| `events.py` | No changes needed |

## Testing

- Unit: Verify that parsing a GoAway response sets `_reconnect_at_turn_boundary = True`
  and computes `_reconnect_deadline` correctly.
- Integration: Run a long session (>10 min) against Gemini Live and confirm:
  - Reconnection happens at the first turn boundary after GoAway (not after ~30s delay).
  - `turn_complete` / `audio.done` events are emitted before reconnection (clean turn).
  - `_resumption_count` increments correctly across multiple GoAway cycles.
- If possible, trigger a GoAway during an active tool call round-trip and verify:
  - All function calls from the turn are received before reconnection.
  - The tool result is accepted on the resumed session (validates Scenario A).
- Deadline fallback: Simulate a long-running turn that would outlast the GoAway window
  and verify the forced break triggers correctly.
