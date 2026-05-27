# solar-cover

A Home Assistant custom integration for solar-aware cover automation. Controls vertical blinds, horizontal awnings, and tilt/venetian blinds correctly year-round.

Built as a ground-up replacement for [adaptive-cover](https://github.com/basbruss/adaptive-cover), fixing its core problems: a broken horizontal awning formula at low sun elevations, 56 non-obvious configuration parameters, and no way to understand why a position decision was made.

> **Status:** Design complete. Implementation in progress.

---

## Why

Existing cover automation integrations solve the wrong problem. They calculate a geometrically precise position based on sun angle, but position alone is not the goal — the goal is to shade when shading is appropriate, and stay out of the way when it isn't. In winter, a perfect position calculation still deploys your awning fully and blocks passive heating.

solar-cover separates these concerns:

- **Solar engine** — where is the sun, when does it enter and exit this opening
- **Intent model** — should I shade right now (elevation-based, handles seasonal transitions automatically)
- **Geometry engine** — given "yes, shade", what position achieves it

Every decision is explainable. The `intent` attribute on each entity tells you exactly why it is where it is.

---

## Features

- Vertical blinds, horizontal awnings, and tilt/venetian blinds
- **Cover Zones** — one config entry controls multiple motors that move together
- **Elevation-aware intent model** — auto-computes a shade threshold from your latitude, handles winter without intervention or temperature sensors
- **Optional weather gate** — hold retracted when it rains or wind exceeds a threshold
- **~17–21 parameters** depending on cover type (vs 56 in adaptive-cover), all load-bearing
- **`intent` attribute** on every entity: `shading`, `inactive_sun_low`, `inactive_outside_fov`, `inactive_weather`, `manual_override`
- **`position_curve`** attribute: 24-point hourly position forecast, ready for a companion Lovelace card
- No dependency on the `sun.sun` entity — solar position computed internally from your HA location config

---

## Installation

HACS support coming once the integration reaches stable. For now:

1. Copy `custom_components/solar_cover/` into your HA `custom_components/` directory
2. Restart Home Assistant
3. Add via Settings → Integrations → Add Integration → Solar Cover

---

## Configuration

Setup is a two-step flow:

**Step 1 — Integration (once)**
Weather entity, wind threshold, minimum outside temperature, default inactive position, default manual override duration. All optional.

**Step 2 — Cover Zone**
Name, compass bearing (hold your phone flat against the glass), FOV left/right, cover entities (multi-select), cover type, and type-specific geometry. The elevation threshold is auto-computed from your latitude and shown with a plain-language explanation.

---

## Design

Full design spec: [`docs/2026-05-27-design.md`](docs/2026-05-27-design.md)

---

## Contributing

See [AGENTS.md](AGENTS.md) for project conventions, module responsibilities, and coding rules. This file is also read by Claude Code, Cursor, GitHub Copilot, and Gemini CLI automatically.

---

## License

MIT
