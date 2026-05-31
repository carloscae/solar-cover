# Detailed Intent Reporting - Design Spec

**Date:** 2026-05-31
**Feature:** Fine-grained reason reporting + timer visibility + reset button
**Status:** Approved, ready for implementation

---

## Problem

The `intent` attribute is a single coarse enum. `inactive_weather` collapses rain,
high wind, and low temperature into one value, and never shows the measured value
that tripped the gate. When a cover "isn't doing what I expect," the user has no way
to tell which condition fired or how far over a limit they are - so they can't tune
their thresholds. Two timers (the stability-delay hold and the manual override) live
entirely as hidden coordinator state, so a cover that is mid-hold looks unresponsive
with no explanation.

---

## Goal

1. Surface, alongside the unchanged `intent` enum, **which** condition fired and the
   **measured value vs. threshold** that caused it - directly actionable for tuning.
2. Expose the two internal timers (stability hold, manual override) as diagnostic
   sensors.
3. Provide a button that clears both timers so the live evaluation takes over at once.

---

## Out of Scope (YAGNI)

- Localisation / translations of reason text
- Per-gate enable/disable, history logging, new tuning config options
- Changing the six `intent` enum values (non-negotiable observability contract)
- Countdown-duration sensors (timers are exposed as timestamps; HA renders relative time)

---

## 1. Architecture

All diagnostics are built in the **pure `intent.py`** (no HA imports), where every gate
decision and every value/threshold already lives in `IntentInput`. This keeps the logic
unit-testable with plain pytest, matching the existing test contract. The coordinator
serialises the result onto entity attributes; it does not re-derive reasons.

`evaluate_intent` changes its return type from `tuple[Intent, float | None]` to a richer
`IntentResult`. The entity-attribute contract (`intent` enum) is untouched - only the
internal function signature changes, so the coordinator and intent tests are updated.

---

## 2. Data model (`intent.py`)

```python
@dataclass
class ReasonTrigger:
    code: str               # fine-grained sub-reason (see catalog)
    measured: float | None  # the live value tested
    threshold: float | None # the limit it was tested against
    unit: str               # "km/h" | "°C" | "°" | "%" | "W/m²" | ""
    margin: float | None    # measured - threshold (signed: how far over/under)
    text: str               # human phrase, e.g. "wind 45 km/h exceeds 40 km/h limit"

@dataclass
class IntentResult:
    intent: Intent                 # unchanged 6-value enum
    position: float | None
    reason: str                    # full sentence built from triggers
    triggers: list[ReasonTrigger]  # serialised to list[dict] for the attribute
```

`evaluate_intent(inp) -> IntentResult`.

---

## 3. Reason catalog

| intent enum | sub-codes | example `reason` |
|---|---|---|
| `inactive_weather` | `weather_rain`, `weather_wind`, `weather_cold` (**one or more**) | "Retracted (weather): raining; wind 45 km/h exceeds 40 km/h limit" |
| `inactive_sun_low` | `sun_low` | "Idle (sun too low): elevation 12° is below the 20° threshold (8° to go)" |
| `inactive_outside_fov` | `fov_left` / `fov_right` | "Idle (out of view): sun 95° off-axis, past the 90° right edge" |
| `inactive_overcast` | `overcast_radiation` **or** `overcast_cloud` (radiation wins when both configured) | "Idle (overcast): radiation 80 W/m² below 150 W/m² threshold" |
| `manual_override` | `manual_override` (measured = minutes remaining) | "Manual override: holding for 47 more min" |
| `shading` | `shading` (measured = computed position) | "Shading: sun 35° elevation, 40° off-axis → 70%" |

**Multi-trigger weather:** the weather gate is restructured to *collect* all active
triggers (rain, wind, cold) rather than returning on the first hit. The intent decision
is unchanged - any one trigger ⇒ `inactive_weather` - only the reporting is richer.

**FOV side:** derived from gamma's sign relative to the FOV edges. `gamma >= fov_left`
⇒ `fov_left`; `gamma <= -fov_right` ⇒ `fov_right`. The reason names the edge and the
limit it crossed.

---

## 4. Coordinator (`coordinator.py`)

- Unpack `IntentResult` (`intent`, `position`, `reason`, `triggers`).
- **Stability-delay correctness:** the exposed intent is the *last committed* one
  (`_last_intent`), which can lag the freshly-evaluated intent during a hold. The reason
  must travel with it - add `_last_reason: str` and `_last_triggers: list[dict]`, updated
  in the same `should_commit` block that sets `_last_intent`, so `reason` always matches
  the displayed `intent`.
- `CoordinatorData` gains:
  - `reason: str`
  - `reason_detail: list[dict]`
  - `stability_pending_until: str | None` (ISO) - `_pending_since + delay` when a hold
    is active, else `None`
  - `pending_intent: str | None` - the intent waiting to commit, else `None`
  - `manual_override_until: str | None` (ISO) - `_manual_override_until`, else `None`
- New `reset_timers()` method: clears `_pending_intent` / `_pending_since` and
  `_manual_override_until`, then requests a refresh. `clear_manual_override()` and the
  pending-reset inside `set_enabled()` are refactored to reuse it where appropriate.

---

## 5. Cover entity attributes (`cover.py`)

Two additive attributes; all existing attributes stay:

```python
"reason": data.reason,
"reason_detail": data.reason_detail,  # list of {code, measured, threshold, unit, margin, text}
```

---

## 6. Diagnostic sensors (`sensor.py`)

Two new TIMESTAMP diagnostic sensors (HA renders relative "in 3 min" and self-updates;
value_fn parses ISO → datetime, mirroring `fov_entry`/`fov_exit`):

| Sensor key | Device class | Shows | `None` when |
|---|---|---|---|
| `stability_pending_until` | timestamp | When the pending intent change will commit | no hold active |
| `manual_override_until` | timestamp | When the manual hold expires | no override active |

`stability_pending_until` exposes a **`pending_intent`** extra-state attribute so the
panel shows not just *when* but *what* is being held back.

---

## 7. Reset-timers button (new `button` platform, `button.py`)

A single button entity → `coordinator.reset_timers()`. Clears both holds so the current
live evaluation takes over immediately (no waiting out a stability delay or manual hold).
`EntityCategory.CONFIG` (pressing it changes runtime behavior). `button` is added to
`PLATFORMS_ZONE` in `__init__.py`.

---

## 8. Constants (`const.py`)

Add a `ReasonCode` StrEnum for the sub-codes (discoverable, typo-proof):
`weather_rain`, `weather_wind`, `weather_cold`, `sun_low`, `fov_left`, `fov_right`,
`overcast_radiation`, `overcast_cloud`, `manual_override`, `shading`.

---

## 9. Testing

HA-free (`test_intent.py`):
- one assertion per sub-code (text, code, measured, threshold, margin sign)
- multi-trigger weather (rain + wind together both present in `triggers`)
- FOV-side detection at gamma near ±90°
- manual-override minutes-remaining

HA fixtures:
- coordinator: `stability_pending_until` set during a hold, `None` after commit;
  `manual_override_until` reflects an active override; `reason` matches the *committed*
  intent during a stability hold; `reset_timers()` clears both and re-evaluates
- cover: `reason` / `reason_detail` shape
- button: press → both timers clear

---

## 10. Docs

`CLAUDE.md` Observability section: document the two new cover attributes, the reason-code
list, the two timer sensors, and the reset button.

---

## Backward compatibility

`intent` enum unchanged. All new entity attributes and entities are additive. Existing
dashboards and automations keep working.
