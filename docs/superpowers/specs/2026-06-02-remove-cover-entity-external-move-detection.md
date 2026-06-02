# Spec: Remove Cover Entity + External Move Detection

**Date:** 2026-06-02
**Status:** Approved

---

## Problem

The integration created a virtual `SolarCoverEntity` (cover platform) that wrapped the physical cover devices. This entity served two purposes:

1. Expose `intent`, `reason`, and `reason_detail` as HA state attributes
2. Route manual position commands through `async_apply_manual_position` to start the override timer

This design was confusing: the device view showed both a Solar Cover entity and the real physical covers. Moving the wrong one (the physical entity directly) silently bypassed the manual-hold logic - the override timer never fired. There was no way to know which entity to use.

---

## Solution

### 1. Delete the cover entity

Remove `cover.py` and the `cover` platform from `PLATFORMS_ZONE`. The integration no longer creates any `CoverEntity`. The coordinator still controls physical covers via HA service calls - nothing changes in how covers are commanded.

### 2. Detect external moves in the coordinator

The coordinator subscribes to `state_changed` events on all physical cover entities listed in `CONF_COVER_ENTITIES`. When any of them reports a settled position that diverges from `_last_commanded` by more than hysteresis, it is treated as a manual move: the override timer is set, `_last_commanded` is updated, and a coordinator refresh is scheduled.

"Settled" is determined by two filters applied in order:
- **Motion state filter:** if the event's new state has `is_opening=True` or `is_closing=True`, skip (cover is still travelling to a previously commanded position)
- **Debounce filter:** ignore events arriving within 30 s of the last coordinator command (`_last_command_time`), for covers that do not expose motion state

The 30 s constant is named `_COMMAND_DEBOUNCE_SECONDS` at module level for easy adjustment.

Only triggers when automation is enabled (`self._enabled = True`). When automation is disabled, moves are inherently user-controlled - no override needed.

### 3. Preserve reason_detail accessibility

`reason_detail` was previously exposed as a cover entity attribute. After the cover entity is removed, it is added as an extra attribute on the `reason` sensor so automations and templates can still access it.

### 4. Move override-duration logic to coordinator

`_override_duration` is currently a property on `SolarCoverEntity`. It reads from zone config (`CONF_OVERRIDE_DURATION_OVERRIDE`) falling back to integration config (`CONF_OVERRIDE_DURATION`, default 120 min). This method moves to the coordinator as `_get_override_duration() -> int` — the external move listener needs it.

---

## File changes

| File | Action |
|---|---|
| `cover.py` | **Deleted** |
| `__init__.py` | Remove `"cover"` from `PLATFORMS_ZONE` |
| `coordinator.py` | Add `_last_command_time`, `_get_override_duration()`, `async_setup_cover_listeners()`, `_handle_cover_state_change()` |
| `sensor.py` | Add `reason_detail` as extra attribute on the `reason` sensor |
| `CLAUDE.md` | Remove `cover.py` module entry; update observability section |
| `tests/test_coordinator_guards.py` | Add tests: external move triggers override; coordinator self-command does not; disabled automation skips detection |

---

## Coordinator changes (detail)

### New fields

```python
_last_command_time: datetime | None = None   # set in _command_covers
```

### `_command_covers` — updated

Set `self._last_command_time = now` (UTC) at the top of the method before the service call.

### `_get_override_duration() -> int`

```python
def _get_override_duration(self) -> int:
    return int(
        self._zone.get(
            CONF_OVERRIDE_DURATION_OVERRIDE,
            self._integration.get(CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION),
        )
    )
```

### `async_setup_cover_listeners()`

Called from `__init__.py` after `async_config_entry_first_refresh`. Subscribes to `state_changed` for every entity in `CONF_COVER_ENTITIES`. Stores the unsubscribe callable so it can be cleaned up on unload.

### `_handle_cover_state_change(event)`

```
1. Get new_state from event; return if None
2. If new_state.attributes has is_opening=True or is_closing=True → return
3. If _last_command_time is set and (now - _last_command_time) < 30 s → return
4. Parse current_position from new_state.attributes; return on error
5. If _last_commanded is None → return
6. If abs(new_pos - _last_commanded) < hysteresis → return
7. If not self._enabled → return
8. Set _manual_override_until = now + override_duration
9. _clear_pending()
10. Update _last_commanded = new_pos, persist to store
11. Schedule async_request_refresh()
```

---

## Testing

New test cases in `test_coordinator_guards.py`:

- **External move triggers override:** physical cover reports a position that differs from `_last_commanded` by > hysteresis, with `_last_command_time` older than 30 s → `_manual_override_until` is set
- **Coordinator command does not self-trigger:** `_last_command_time` is recent (< 30 s) → listener returns without setting override
- **Motion state suppresses trigger:** `is_closing=True` in state attributes → listener returns without setting override
- **Delta below hysteresis does not trigger:** new position within hysteresis of `_last_commanded` → no override
- **Disabled automation skips detection:** `_enabled = False` → no override even on large position change

---

## CLAUDE.md updates

- Remove `cover.py` from module responsibilities table
- Change "Every cover entity must expose `intent` as a string attribute" → `intent` is exposed via the `Active intent` sensor
- Remove manual cover commands routing note (no longer applicable)
