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
*   **Install dev deps**: `pip install -e ".[dev]" --config-settings editable_mode=compat`
    *   The `editable_mode=compat` flag is **required**: the default PEP 660 editable install creates an `__editable__.*finder.__path_hook__` entry that Home Assistant's integration loader trips over (`FileNotFoundError` during config-flow/platform tests). Compat mode writes a plain `.pth` instead. Plain `pip install -e ".[dev]"` resolves fine but the HA-integration tests will fail without this flag.
    *   Do not pin `pytest`, `pytest-asyncio`, `numpy`, or `astral` in `[dev]`: `pytest-homeassistant-custom-component` and `homeassistant` pin those exactly, and independent pins dead-end the resolver. The PHACC floor is kept high on purpose (old releases pin `pytest-asyncio==0.23.4`/`pytest<8`).

### Repository Layout
```
custom_components/solar_cover/   Integration source
tests/                           pytest test suite (mirrors source structure)
docs/                            Design specs, sprints, handoffs
.agent/                          Concurrency claims and agent roster
```

### Text Formatting & Linting Style
*   **No Unicode em-dashes**: use hyphens or rewrite the sentence.
*   **ruff** is linter and formatter - run before every commit.
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
*   No positional dataclass unpacking (`*list` into constructor args) - use keyword arguments.
*   No `pandas` - plain lists and numpy for numeric work.

### Home Assistant Conventions
*   Integration domain: `solar_cover`
*   Config entries: two types - `integration` (global) and `zone` (per cover group).
*   Coordinator: one per zone. Update trigger: 5-minute interval + weather entity `state_changed`.
*   No runtime dependency on `sun.sun` entity - solar position computed internally via `astral`.
*   Read location from `hass.config.latitude / longitude / elevation` only - never ask the user.
*   All entity attributes must be JSON-serialisable (no datetime objects - use ISO strings).

### Module Responsibilities
*   `solar.py` - sun position and daily curve via astral. Pure functions where possible.
*   `geometry.py` - cover position formulas (vertical, horizontal, tilt). Pure functions, no HA imports.
*   `intent.py` - sequential gate model (weather safety → manual override → elevation → FOV → overcast/radiation → shading). Returns intent enum + computed position. Manual override is evaluated after weather safety (so wind/rain can still retract) but before the comfort gates (so a user's manual position holds even when the sun dips below threshold, leaves the FOV, or it turns overcast).
*   `coordinator.py` - orchestrates solar engine, intent model, entity state updates.
*   `config_flow.py` - two-step flow: integration setup, then zone setup.

### Testing
*   `geometry.py` and `intent.py` must have unit tests that run without HA. Use plain pytest fixtures.
*   Config flow tests use `pytest-homeassistant-custom-component`.
*   Every geometry formula must have at least: a midday summer case, a low-elevation winter case, and a gamma-near-90 edge case.

### Key Design Decisions (do not revisit without updating the spec)
*   FOV right is uncapped for horizontal covers (up to 180°). Capped at 90° for vertical and tilt.
*   Horizontal awning clip (`clip(length, 0, awn_length)`) is active - it was commented out in adaptive-cover and caused 100% deployment in winter.
*   Tilt formula NaN guard: when discriminant < 0, return 100% (fully closed).
*   Elevation threshold defaults to `(90 - latitude) * 0.6`. Auto-computed, user-adjustable per zone.
*   Compass bearing input (not "azimuth") - no magnetic declination correction in v1.
*   Manual override is tracked per cover (dict keyed by cover entity_id), not per zone. Moving one cover manually holds only that cover at its last-set position; siblings keep tracking the automatic sun intent. Override still outranks the comfort gates but not weather safety: while a cover's hold is active the coordinator holds that cover's position and never drives it to the inactive rest position, but wind/rain retracts every cover (the weather gate precedes the per-cover hold, and the hold resumes for each cover once weather clears). The coordinator evaluates the pure automatic intent (`intent.py` is called with `manual_override_until=None`); the per-cover hold is applied by the coordinator's resolver, not by the intent model.
*   External cover moves (physical remote, other automations) are detected automatically by the coordinator via state-change listeners on the zone's physical cover entities. The handler reads the moved cover from `event.data["entity_id"]` and keys all state (debounce, baseline, hold) off it, so a move of one cover never perturbs a sibling. Any position change exceeding hysteresis and outside that cover's 30-second post-command debounce window sets a manual override for that cover only, and does not disturb the zone stability hold. Never call `_command_covers` directly from outside the coordinator; it takes a `dict[str, float]` of per-cover targets and returns the set of failed entity_ids.
*   Coordinator persisted state (`.storage/solar_cover.<entry_id>`) is schema version 2, shaped `{"covers": {entity_id: {last_commanded, manual_position, manual_override_until}}}`. Migration lives in a `_SolarCoverStore(Store)` subclass in `coordinator.py` overriding `_async_migrate_func`; any pre-v2 payload migrates to no active overrides (the v1 scalar was never tied to an entity_id). This is separate from config-entry migration (`async_migrate_entry` in `__init__.py`). On restore, stored cover keys are intersected with the current `cover_entities` and stale keys are pruned and re-saved.

### Observability (non-negotiable)
Every zone exposes `intent` as the state of the `Active intent` sensor. Valid values:
`shading`, `inactive_sun_low`, `inactive_outside_fov`, `inactive_weather`, `inactive_overcast`, `manual_override`

The integration exposes observability via diagnostic sensors and registers **no CoverEntity** (the platforms are `button`, `sensor`, and `switch`). `reason`/`reason_detail` are surfaced as the `reason` sensor's state and attributes, not as cover-entity attributes.

The `intent` enum is fixed (the contract above). Finer detail is **additive**, alongside it:
*   `reason` (reason sensor state / attribute) -- a human sentence, e.g. `"Retracted (weather): raining; wind 45 km/h exceeds 40 km/h limit"`.
*   `reason_detail` (reason sensor attribute) -- a list of trigger dicts `{code, text, measured, threshold, unit, margin}` for templating/automations. `margin = measured - threshold` (signed). The weather gate reports **all** active triggers (rain + wind + cold), not just the first.
*   `ReasonCode` (in `const.py`) enumerates the sub-codes: `weather_rain`, `weather_wind`, `weather_cold`, `sun_low`, `fov_left`, `fov_right`, `overcast_radiation`, `overcast_cloud`, `manual_override`, `shading`.
*   `evaluate_intent` returns an `IntentResult(intent, position, reason, triggers)` -- all reason text is built in the pure `intent.py` so it stays HA-free and unit-testable. The coordinator stores `_last_reason`/`_last_triggers` so the exposed `reason` always tracks the **committed** intent during a stability hold (never disagrees with `intent`).

Two diagnostic **timestamp** sensors surface the internal timers (HA renders relative time, value `None` when inactive):
*   `stability_pending_until` -- when a held intent change will commit; carries a `pending_intent` extra attribute naming the waiting candidate.
*   `manual_override_until` -- when the active manual hold expires.

Per-cover observability: each configured cover has its own HA device (nested under the zone device via `via_device`) exposing `commanded_position`, `manual_override_until`, and `intent` sensors (this cover's effective intent: `manual_override` if held, else the shared automatic intent) plus a `reset_override` button that clears only that cover's hold. The zone `intent`/`reason` sensors report `manual_override` / the override text only when EVERY configured cover is currently held; otherwise they report the shared automatic value. The zone-level `commanded_position` sensor is removed (superseded by the per-cover one). A diagnostic **button** (`reset_timers`, "Reset all", `button.py`) calls `coordinator.reset_timers()`, which drops the committed intent, clears the stability hold, and clears every per-cover hold so the live evaluation takes over on the next refresh. `set_enabled`, `clear_manual_override`, and `reset_timers` share the `_clear_pending()` helper.

### Config Entry Titles (enforced at startup)
*   Integration entry title: `"Global Settings"`
*   Zone entry title: `"Zone: <name>"` (applied via `async_update_entry` in `async_setup_entry`)
*   Changing global settings triggers cascade reload of all zone entries via `_async_update_integration_listener`.

### Sensor Subscription Pattern
The coordinator subscribes to weather + cloud + radiation entities via a single `async_track_state_change_event` call stored in `_unsub_sensors`. Any of the three changing triggers a refresh.

### Cloud/Radiation Gate (Gate 5 in intent model)
*   Radiation takes precedence when both are configured: if `radiation < radiation_threshold` returns `INACTIVE_OVERCAST`.
*   If only cloud is configured: if `cloud_coverage > cloud_threshold` returns `INACTIVE_OVERCAST`.
*   Sensor reads use `_read_sensor()` helper - handles None entity_id, unavailable/unknown state, and non-numeric values gracefully.

### External Submissions
*   HACS default store: PR #8092 in `hacs/default` (master branch), all checks passing as of 2026-05-30.
*   HA brands: not needed since HA 2026.3.0 -- brand icons are served from `custom_components/solar_cover/brand/icon.png` directly.
*   HACS store listing icon: `icon.png` at repo root (256x256).

### Release Process (automated via `.github/workflows/release.yml`)
Releasing is **automatic on a version bump**. HACS installs the integration from the latest release **tag** (it pulls `custom_components/solar_cover/` from the tagged source). With the current minimal `hacs.json` (no `zip_release`/`filename`) HACS **ignores any release zip asset**, so no build/zip step is needed. To release:
1.  Bump `"version"` in `custom_components/solar_cover/manifest.json` (semver: new feature -> minor, fix-only -> patch). Run `ruff format . && ruff check . && mypy custom_components/solar_cover && pytest tests/ -v` first -- everything must pass (there is no CI gate on tests, so verify locally before bumping).
2.  Commit the bump (e.g. `chore: bump to X.Y.Z ...`) and `git push origin main`.
3.  The `Release` workflow fires on any push to `main` that touches `manifest.json`, reads the version, and -- if a `vX.Y.Z` release does not already exist -- creates the tag and a GitHub release with auto-generated notes. It is idempotent (a manifest change with an unchanged version is a no-op).
*   Do **not** hand-create releases or build `solar_cover.zip` -- both are obsolete. The version bump is the single trigger.
*   `workflow_dispatch` is enabled for manual re-runs if needed.
