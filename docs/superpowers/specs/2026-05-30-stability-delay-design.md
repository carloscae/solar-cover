# Stability Delay — Design Spec

**Date:** 2026-05-30
**Feature:** Intent-change stability delay ("hysteresis" for weather/sensor gates)
**Status:** Approved, ready for implementation

---

## Problem

On partly-cloudy or gusty days, sensor values oscillate around a configured threshold
(cloud coverage, radiation, wind speed). Each crossing flips the intent between
`INACTIVE_OVERCAST` / `INACTIVE_WEATHER` and `SHADING`, which bypasses the existing
position hysteresis check and causes covers to open and close repeatedly.

---

## Goal

Add an optional time-based stability delay so that an intent change is only acted on
after the new intent has held continuously for a configurable number of minutes.
Two independent toggles let the user decide whether to apply the delay when conditions
worsen, when they improve, or both.

---

## Out of Scope

- Per-gate delays (one shared delay covers all weather gates)
- Deadband / threshold margin (not in this iteration)
- New entities or attributes (existing `intent` attribute is sufficient)

---

## Configuration

Three new optional settings in the **Global Settings** config entry.

| Constant | UI label | Type | Default | Range |
|----------|----------|------|---------|-------|
| `CONF_STABILITY_DELAY` (`stability_delay_minutes`) | "Stability delay (minutes)" | int | `0` | 0–60 |
| `CONF_STABILITY_DELAY_ON_WORSENING` (`stability_delay_on_worsening`) | "Apply delay when conditions worsen" | bool | `True` | — |
| `CONF_STABILITY_DELAY_ON_RECOVERY` (`stability_delay_on_recovery`) | "Apply delay when conditions improve" | bool | `True` | — |

When `stability_delay_minutes` is `0` the feature is entirely bypassed — no pending
state is maintained, behavior is identical to the current implementation.

**Direction definitions:**
- *Worsening*: `_last_intent == SHADING` and `new_intent` is any `INACTIVE_*`
- *Recovery*: `_last_intent` is `INACTIVE_OVERCAST` or `INACTIVE_WEATHER` and `new_intent == SHADING`

Transitions that are neither worsening nor recovery (e.g. `INACTIVE_SUN_LOW` →
`INACTIVE_OUTSIDE_FOV`) are always acted on immediately.

---

## Coordinator State Machine

### New fields on `SolarCoverCoordinator`

```python
_pending_intent: Intent | None = None
_pending_since: datetime | None = None
```

`_last_intent` continues to track the **last committed** intent — the one that caused
a cover command. The new fields track the **candidate** that has not yet held long enough.

### Logic (replaces the current `intent_changed` block)

```
new_intent = evaluate_intent(inp)

if new_intent == _last_intent:
    # Oscillated back — clear any pending candidate
    _pending_intent = None
    _pending_since = None
    act normally (position hysteresis still applies)

else:
    direction = classify(new_intent, _last_intent)  # "worsening" | "recovery" | "other"

    delay_applies = (
        stability_delay_minutes > 0
        and (
            (direction == "worsening" and delay_on_worsening)
            or (direction == "recovery" and delay_on_recovery)
        )
    )

    if not delay_applies:
        # Commit immediately (existing behavior)
        _last_intent = new_intent
        _pending_intent = None
        _pending_since = None
        command covers

    else:
        # The clock measures time since we first diverged from the committed
        # intent, NOT since this specific candidate appeared. A different
        # candidate of the same delayed direction (e.g. overcast then wind,
        # both "worsening" from SHADING) keeps the clock running so alternating
        # sensors on a stormy day cannot pin the hold open forever. The clock
        # only resets when we return to the committed intent (branch above).
        if _pending_since is None:
            _pending_since = now
        _pending_intent = new_intent
        if (now - _pending_since) >= timedelta(minutes=stability_delay_minutes):
            # Delay elapsed — commit
            _last_intent = new_intent
            _pending_intent = None
            _pending_since = None
            command covers
        # else: still waiting — do not command, hold last position
```

### Timing note

There are no HA timers involved. The check fires on every coordinator update —
the 5-minute polling interval plus any sensor state-change events. Timing is
approximate (within one update tick) which is acceptable for a comfort feature.

---

## Files to Change

| File | Change |
|------|--------|
| `custom_components/solar_cover/const.py` | Add `CONF_STABILITY_DELAY`, `CONF_STABILITY_DELAY_ON_WORSENING`, `CONF_STABILITY_DELAY_ON_RECOVERY`, `DEFAULT_STABILITY_DELAY = 0` |
| `custom_components/solar_cover/config_flow.py` | Add three fields to Global Settings options schema |
| `custom_components/solar_cover/coordinator.py` | Add `_pending_intent`, `_pending_since`; replace `intent_changed` block with stability state machine |
| `tests/test_coordinator.py` (or new `tests/test_stability.py`) | Unit tests for pending-intent state machine |

---

## Tests

### Pending-intent unit tests (no HA required beyond coordinator scaffolding)

1. **No delay configured** — intent change commits immediately; `_pending_intent` stays `None`.
2. **Delay configured, intent holds** — after N ticks past the delay threshold, covers are commanded exactly once.
3. **Delay configured, intent oscillates back** — pending is cleared, no cover command issued.
4. **Worsening flag disabled** — worsening transition commits immediately; recovery transition is delayed.
5. **Recovery flag disabled** — recovery commits immediately; worsening is delayed.
6. **Direction "other"** (`INACTIVE_SUN_LOW` → `INACTIVE_OUTSIDE_FOV`) — always commits immediately regardless of flags.
7. **Candidate changes mid-hold** — a different same-direction candidate keeps the clock running (origin unchanged); commit still fires at the original divergence + delay.

### Config flow tests

- New keys round-trip through options flow with defaults.
- `stability_delay_minutes = 0` round-trips correctly (feature off).

---

## Non-Goals / Future Considerations

- Per-gate delays: deferred. One shared delay covers the stated problem.
- Deadband margin: a separate, complementary feature if needed later.
- Exposing `_pending_intent` as an entity attribute: only add if users request observability of the pending state.
