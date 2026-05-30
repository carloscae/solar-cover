# Consolidated Developer & Agent Instructions

This is the single source of truth for repository guidelines, developer commands, Agile parallelization workflows, and technical standards. All contributing AI agents (Claude, Gemini, Cursor, Copilot/Codex) are bound by these rules.

---

## 1. Operational & CLI Reference

### Essential CLI Commands
*   **Lint**: `ruff check .`
*   **Format**: `ruff format .`
*   **Type check**: `mypy custom_components/solar_cover`
*   **Test suite**: `pytest tests/ -v`
*   **Test with coverage**: `pytest tests/ --cov=custom_components/solar_cover --cov-report=term-missing`
*   **Install dev deps**: `pip install -e ".[dev]"`

### Repository Layout
```
custom_components/solar_cover/   Integration source
tests/                           pytest test suite (mirrors source structure)
docs/                            Design specs, sprints, handoffs
.agent/                          Concurrency claims and agent roster
```

### Text Formatting & Linting Style
*   **No Unicode em-dashes**: use hyphens or rewrite the sentence.
*   **ruff** is linter and formatter — run before every commit.
*   **No bare `except`**: always catch specific exceptions.

---

## 2. Agile Multi-Agent Governance

To execute tasks in parallel without merge collisions or overlapping efforts, follow these rules:
1.  **Check Claims Ledger**: Read `.agent/active/claims.md` and check if the module you plan to modify is currently locked by another agent.
2.  **Claim Your Task**: Add an active claim row in `claims.md`, change the task checkbox to `[/]` (In Progress) in the active sprint (e.g. `docs/sprints/SPRINT_1.md`), and add yourself to `.agent/active/roster.md`.
3.  **Perform Session Checkout**: On completion, move your claim to **Completed Claims** inside `claims.md`, change the task checkbox to `[x]` (Complete) in the active sprint file with brief notes, and move yourself to the **Hall of Fame** in `roster.md`.
4.  **Handoff Writing**: When concluding a session or a major sprint milestone, compose a formal handoff log under `docs/handoffs/log/` and record it in `docs/handoffs/index.md`.

---

## 3. Project Technical & Coding Rules

### Language & Runtime
*   Python 3.12+. Type hints on every function signature.
*   No positional dataclass unpacking (`*list` into constructor args) — use keyword arguments.
*   No `pandas` — plain lists and numpy for numeric work.

### Home Assistant Conventions
*   Integration domain: `solar_cover`
*   Config entries: two types — `integration` (global) and `zone` (per cover group).
*   Coordinator: one per zone. Update trigger: 5-minute interval + weather entity `state_changed`.
*   No runtime dependency on `sun.sun` entity — solar position computed internally via `astral`.
*   Read location from `hass.config.latitude / longitude / elevation` only — never ask the user.
*   All entity attributes must be JSON-serialisable (no datetime objects — use ISO strings).

### Module Responsibilities
*   `solar.py` — sun position and daily curve via astral. Pure functions where possible.
*   `geometry.py` — cover position formulas (vertical, horizontal, tilt). Pure functions, no HA imports.
*   `intent.py` — sequential gate model (weather safety → manual override → elevation → FOV → overcast/radiation → shading). Returns intent enum + computed position. Manual override is evaluated after weather safety (so wind/rain can still retract) but before the comfort gates (so a user's manual position holds even when the sun dips below threshold, leaves the FOV, or it turns overcast).
*   `coordinator.py` — orchestrates solar engine, intent model, entity state updates.
*   `config_flow.py` — two-step flow: integration setup, then zone setup.
*   `cover.py` — HA cover entity. Reads coordinator state, exposes observability attributes.

### Testing
*   `geometry.py` and `intent.py` must have unit tests that run without HA. Use plain pytest fixtures.
*   Config flow tests use `pytest-homeassistant-custom-component`.
*   Every geometry formula must have at least: a midday summer case, a low-elevation winter case, and a gamma-near-90 edge case.

### Key Design Decisions (do not revisit without updating the spec)
*   FOV right is uncapped for horizontal covers (up to 180°). Capped at 90° for vertical and tilt.
*   Horizontal awning clip (`clip(length, 0, awn_length)`) is active — it was commented out in adaptive-cover and caused 100% deployment in winter.
*   Tilt formula NaN guard: when discriminant < 0, return 100% (fully closed).
*   Elevation threshold defaults to `(90 - latitude) * 0.6`. Auto-computed, user-adjustable per zone.
*   Compass bearing input (not "azimuth") — no magnetic declination correction in v1.
*   Manual override outranks the comfort gates but not weather safety. While an override is active the coordinator holds the user's last-set position and never drives to the inactive rest position; wind/rain can still retract because the weather gate precedes override.
*   Manual cover commands route through `coordinator.async_apply_manual_position`, which records `_last_commanded` and persists it. Never call `_command_covers` directly from the entity -- that leaves the committed baseline stale.

### Observability (non-negotiable)
Every cover entity must expose `intent` as a string attribute. Valid values:
`shading`, `inactive_sun_low`, `inactive_outside_fov`, `inactive_weather`, `inactive_overcast`, `manual_override`

### Config Entry Titles (enforced at startup)
*   Integration entry title: `"Global Settings"`
*   Zone entry title: `"Zone: <name>"` (applied via `async_update_entry` in `async_setup_entry`)
*   Changing global settings triggers cascade reload of all zone entries via `_async_update_integration_listener`.

### Sensor Subscription Pattern
The coordinator subscribes to weather + cloud + radiation entities via a single `async_track_state_change_event` call stored in `_unsub_sensors`. Any of the three changing triggers a refresh.

### Cloud/Radiation Gate (Gate 5 in intent model)
*   Radiation takes precedence when both are configured: if `radiation < radiation_threshold` returns `INACTIVE_OVERCAST`.
*   If only cloud is configured: if `cloud_coverage > cloud_threshold` returns `INACTIVE_OVERCAST`.
*   Sensor reads use `_read_sensor()` helper — handles None entity_id, unavailable/unknown state, and non-numeric values gracefully.

### External Submissions
*   HACS default store: PR #8092 in `hacs/default` (master branch), all checks passing as of 2026-05-30.
*   HA brands: not needed since HA 2026.3.0 -- brand icons are served from `custom_components/solar_cover/brand/icon.png` directly.
*   HACS store listing icon: `icon.png` at repo root (256x256).
