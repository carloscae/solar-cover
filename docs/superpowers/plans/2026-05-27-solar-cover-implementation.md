# Solar Cover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Home Assistant custom integration that controls solar covers (vertical blinds, horizontal awnings, tilt/venetian blinds) correctly year-round via an elevation-gated intent model with full observability.

**Architecture:** Three pure-function layers (solar engine, intent model, geometry engine) feed a per-zone DataUpdateCoordinator that commands one or more HA cover entities. Config flow is two-step: one integration entry (global settings) plus one zone entry per cover group.

**Tech Stack:** Python 3.12+, `astral` (sun position), `numpy` (geometry math), `pytest` + `pytest-homeassistant-custom-component` (testing), `ruff` (lint/format), `mypy` (type checking).

**Design spec:** `docs/2026-05-27-design.md` — read it before any task.

---

## File Map

```
custom_components/solar_cover/
  __init__.py          — async_setup_entry / async_unload_entry dispatch
  manifest.json        — domain, version, iot_class, no extra deps
  const.py             — all constants, Intent enum, CoverType enum, TiltRange enum
  solar.py             — SolarEngine: sun_position(), position_curve(), fov_window()
  geometry.py          — vertical_position(), horizontal_position(), tilt_position()
  intent.py            — evaluate_intent(): returns (Intent, float | None) tuple
  coordinator.py       — SolarCoverCoordinator(DataUpdateCoordinator) per zone
  config_flow.py       — SolarCoverConfigFlow (integration step + zone step)
  cover.py             — SolarCoverEntity(CoverEntity)
  strings.json         — UI string keys
  translations/en.json — English strings

tests/
  conftest.py          — pytest_plugins declaration + shared fixtures
  test_geometry.py     — unit tests for all 3 geometry functions (no HA)
  test_intent.py       — unit tests for intent gate model (no HA)
  test_solar.py        — unit tests for SolarEngine (no HA, real astral)
  test_config_flow.py  — config flow integration tests (uses hass fixture)

pyproject.toml         — build system, dev deps, ruff/mypy/pytest config
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `custom_components/solar_cover/__init__.py` (skeleton)
- Create: `custom_components/solar_cover/manifest.json`
- Create: `custom_components/solar_cover/const.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "solar-cover"
version = "0.1.0"
requires-python = ">=3.12"

[project.optional-dependencies]
dev = [
    "ruff>=0.4",
    "mypy>=1.10",
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-homeassistant-custom-component>=0.13",
    "numpy>=1.26",
    "astral>=3.2",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["custom_components*"]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write manifest.json**

```json
{
  "domain": "solar_cover",
  "name": "Solar Cover",
  "version": "0.1.0",
  "config_flow": true,
  "documentation": "https://github.com/carloscae/solar-cover",
  "issue_tracker": "https://github.com/carloscae/solar-cover/issues",
  "dependencies": [],
  "requirements": [],
  "codeowners": ["@carloscae"],
  "iot_class": "calculated"
}
```

- [ ] **Step 3: Write const.py**

```python
"""Constants for the Solar Cover integration."""
from enum import StrEnum

DOMAIN = "solar_cover"

ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_ZONE = "zone"

# Integration-level config keys
CONF_WEATHER_ENTITY = "weather_entity"
CONF_WIND_THRESHOLD = "wind_threshold"
CONF_MIN_TEMP = "min_temp"
CONF_INACTIVE_POSITION = "inactive_position"
CONF_OVERRIDE_DURATION = "override_duration"

# Zone config keys
CONF_COVER_ENTITIES = "cover_entities"
CONF_COVER_TYPE = "cover_type"
CONF_AZIMUTH = "azimuth"
CONF_FOV_LEFT = "fov_left"
CONF_FOV_RIGHT = "fov_right"
CONF_ELEVATION_THRESHOLD = "elevation_threshold"
CONF_INACTIVE_POSITION_OVERRIDE = "inactive_position_override"

# Vertical blind geometry
CONF_WINDOW_HEIGHT = "window_height"
CONF_GLARE_DEPTH = "glare_depth"

# Horizontal awning geometry
CONF_ATTACH_HEIGHT = "attach_height"
CONF_AWN_LENGTH = "awn_length"
CONF_AWN_ANGLE = "awn_angle"

# Tilt geometry
CONF_SLAT_WIDTH = "slat_width"
CONF_SLAT_SPACING = "slat_spacing"
CONF_TILT_RANGE = "tilt_range"

# Advanced
CONF_MIN_POSITION = "min_position"
CONF_MAX_POSITION = "max_position"
CONF_HYSTERESIS = "hysteresis"
CONF_OVERRIDE_DURATION_OVERRIDE = "override_duration_override"


class CoverType(StrEnum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    TILT = "tilt"


class TiltRange(StrEnum):
    SINGLE = "single"
    BIDIRECTIONAL = "bidirectional"


class Intent(StrEnum):
    SHADING = "shading"
    INACTIVE_SUN_LOW = "inactive_sun_low"
    INACTIVE_OUTSIDE_FOV = "inactive_outside_fov"
    INACTIVE_WEATHER = "inactive_weather"
    MANUAL_OVERRIDE = "manual_override"


DEFAULT_INACTIVE_POSITION: int = 0
DEFAULT_OVERRIDE_DURATION: int = 120
DEFAULT_HYSTERESIS: float = 3.0
DEFAULT_ELEVATION_THRESHOLD_FACTOR: float = 0.6
UPDATE_INTERVAL_MINUTES: int = 5
```

- [ ] **Step 4: Write __init__.py skeleton**

```python
"""Solar Cover integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE

PLATFORMS_ZONE = ["cover"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)
    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN]["integration"] = entry.data
        return True
    # Zone entry — coordinator setup added in Task 5
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)
    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN].pop("integration", None)
        return True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS_ZONE)
```

- [ ] **Step 5: Write tests/conftest.py**

```python
"""Shared pytest configuration."""
pytest_plugins = ["pytest_homeassistant_custom_component"]
```

- [ ] **Step 6: Install dev deps and verify tooling**

```bash
cd ~/Projects/solar-cover
pip install -e ".[dev]"
ruff check .
mypy custom_components/solar_cover
pytest tests/ -v
```

Expected: ruff passes, mypy passes, pytest collects 0 tests (no test files yet) and exits 0.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml manifest.json custom_components/ tests/
git commit -m "feat: scaffold project structure, constants, and manifest"
```

---

## Task 2: Geometry Engine

**Files:**
- Create: `custom_components/solar_cover/geometry.py`
- Create: `tests/test_geometry.py`

These are pure functions with no HA imports. All angles are passed in degrees; internal computation uses radians.

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_geometry.py`:

```python
"""Unit tests for geometry.py — pure functions, no HA needed."""
import pytest
from custom_components.solar_cover.geometry import (
    horizontal_position,
    tilt_position,
    vertical_position,
)


class TestVerticalPosition:
    def test_midday_summer(self) -> None:
        # Sun at 60° elevation, gamma=0 (dead center), protect 1m depth, 2.5m window
        result = vertical_position(sol_elev_deg=60.0, gamma_deg=0.0, distance=1.0, h_win=2.5)
        # blind_height = (1.0 / cos(0)) * tan(60°) = 1 * 1.732 = 1.732m → 1.732/2.5*100 ≈ 69.3%
        assert abs(result - 69.3) < 0.5

    def test_low_elevation_winter(self) -> None:
        # Sun at 15° elevation, gamma=0, protect 1m, 2.5m window
        result = vertical_position(sol_elev_deg=15.0, gamma_deg=0.0, distance=1.0, h_win=2.5)
        # blind_height = tan(15°) ≈ 0.268m → 10.7%
        assert abs(result - 10.7) < 0.5

    def test_gamma_near_90_clips_to_0(self) -> None:
        # gamma=89° — sun nearly at edge of FOV, cos(89°) is very small → clip to h_win → 100%
        result = vertical_position(sol_elev_deg=30.0, gamma_deg=89.0, distance=1.0, h_win=2.0)
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        # Very low elevation — blind_height clips to 0
        result = vertical_position(sol_elev_deg=1.0, gamma_deg=0.0, distance=0.1, h_win=2.5)
        assert 0.0 <= result <= 100.0


class TestHorizontalPosition:
    def test_midday_summer(self) -> None:
        # Sun at 60°, gamma=0, attach_height=2.5m, awn_length=3m, awn_angle=15°, distance=2m
        result = horizontal_position(
            sol_elev_deg=60.0, gamma_deg=0.0,
            h_win=2.5, awn_length=3.0, awn_angle_deg=15.0, distance=2.0,
        )
        assert 0.0 <= result <= 100.0

    def test_low_elevation_winter_clips(self) -> None:
        # Low elevation sun — adaptive-cover bug was returning >100% here
        result = horizontal_position(
            sol_elev_deg=10.0, gamma_deg=0.0,
            h_win=2.5, awn_length=3.0, awn_angle_deg=15.0, distance=2.0,
        )
        assert 0.0 <= result <= 100.0

    def test_gamma_near_90_returns_100(self) -> None:
        # cos(90°)=0 → blind_height clips to h_win → (h_win - h_win) = 0 numerator → length=0 → 0%
        # Actually when gamma>90, cos(gamma)<0 → blind_height clips to 0 → full extension
        result = horizontal_position(
            sol_elev_deg=30.0, gamma_deg=91.0,
            h_win=2.5, awn_length=3.0, awn_angle_deg=15.0, distance=2.0,
        )
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        # Verify clip is active (the adaptive-cover bug was missing this)
        result = horizontal_position(
            sol_elev_deg=5.0, gamma_deg=0.0,
            h_win=3.0, awn_length=2.0, awn_angle_deg=10.0, distance=5.0,
        )
        assert 0.0 <= result <= 100.0


class TestTiltPosition:
    def test_midday_summer(self) -> None:
        # Sun at 60°, gamma=0, 80mm slat, 50mm spacing, single range
        result = tilt_position(
            sol_elev_deg=60.0, gamma_deg=0.0,
            slat_width_mm=80.0, slat_spacing_mm=50.0, bidirectional=False,
        )
        assert 0.0 <= result <= 100.0

    def test_bidirectional_range(self) -> None:
        # Bidirectional should produce lower % for same angle (180° range vs 90°)
        single = tilt_position(
            sol_elev_deg=45.0, gamma_deg=0.0,
            slat_width_mm=80.0, slat_spacing_mm=50.0, bidirectional=False,
        )
        bidi = tilt_position(
            sol_elev_deg=45.0, gamma_deg=0.0,
            slat_width_mm=80.0, slat_spacing_mm=50.0, bidirectional=True,
        )
        assert bidi == pytest.approx(single / 2.0, abs=0.1)

    def test_negative_discriminant_returns_100(self) -> None:
        # Very low elevation with wide slat spacing → discriminant goes negative → fully closed
        result = tilt_position(
            sol_elev_deg=2.0, gamma_deg=0.0,
            slat_width_mm=50.0, slat_spacing_mm=49.0, bidirectional=False,
        )
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        result = tilt_position(
            sol_elev_deg=45.0, gamma_deg=0.0,
            slat_width_mm=80.0, slat_spacing_mm=50.0, bidirectional=False,
        )
        assert 0.0 <= result <= 100.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_geometry.py -v
```

Expected: `ModuleNotFoundError: No module named 'custom_components.solar_cover.geometry'`

- [ ] **Step 3: Write geometry.py**

```python
"""Geometry engine — pure functions for cover position calculation.

All angle parameters are in degrees. Internal computation uses radians.
No HA imports permitted in this module.
"""
from __future__ import annotations

import math


def vertical_position(
    sol_elev_deg: float,
    gamma_deg: float,
    distance: float,
    h_win: float,
) -> float:
    """Return vertical blind position (0-100%) to block sun at glare depth.

    Args:
        sol_elev_deg: Solar elevation in degrees.
        gamma_deg: Surface solar azimuth in degrees (negative = sun to the right).
        distance: Glare protection depth in metres (how far from window to protect).
        h_win: Window height in metres.

    Returns:
        Position percentage (0 = fully retracted, 100 = fully deployed).
    """
    sol_elev = math.radians(sol_elev_deg)
    gamma = math.radians(gamma_deg)
    cos_gamma = math.cos(gamma)
    if cos_gamma <= 0:
        return 100.0
    blind_height = min((distance / cos_gamma) * math.tan(sol_elev), h_win)
    blind_height = max(blind_height, 0.0)
    return blind_height / h_win * 100.0


def horizontal_position(
    sol_elev_deg: float,
    gamma_deg: float,
    h_win: float,
    awn_length: float,
    awn_angle_deg: float,
    distance: float,
) -> float:
    """Return horizontal awning extension (0-100%) to protect glare depth.

    The clip on the returned value is intentional and was missing in adaptive-cover,
    causing 100% extension in winter at low sun elevations.

    Args:
        sol_elev_deg: Solar elevation in degrees.
        gamma_deg: Surface solar azimuth in degrees.
        h_win: Attachment height above floor in metres.
        awn_length: Physical maximum extension in metres.
        awn_angle_deg: Deployment angle from horizontal in degrees.
        distance: Glare protection depth in metres.

    Returns:
        Position percentage (0 = retracted, 100 = fully extended).
    """
    sol_elev = math.radians(sol_elev_deg)
    gamma = math.radians(gamma_deg)
    awn_angle = math.radians(awn_angle_deg)

    cos_gamma = math.cos(gamma)
    if cos_gamma <= 0:
        # Oblique sun (gamma > 90°) — blind_height clips to 0, full extension needed
        return 100.0

    blind_height = min(max((distance / cos_gamma) * math.tan(sol_elev), 0.0), h_win)
    a_angle = math.pi / 2.0 - sol_elev
    c_angle = sol_elev + awn_angle

    if math.sin(c_angle) == 0.0:
        return 0.0

    length = ((h_win - blind_height) * math.sin(a_angle)) / math.sin(c_angle)
    return min(max(length / awn_length * 100.0, 0.0), 100.0)


def tilt_position(
    sol_elev_deg: float,
    gamma_deg: float,
    slat_width_mm: float,
    slat_spacing_mm: float,
    bidirectional: bool,
) -> float:
    """Return venetian blind tilt position (0-100%) using MDPI formula.

    When the discriminant is negative (sun geometry outside slat range),
    returns 100.0 (fully closed) as a safe fallback.

    Args:
        sol_elev_deg: Solar elevation in degrees.
        gamma_deg: Surface solar azimuth in degrees.
        slat_width_mm: Slat width (blade depth) in millimetres.
        slat_spacing_mm: Centre-to-centre slat spacing in millimetres.
        bidirectional: True for 0-180° range, False for 0-90°.

    Returns:
        Position percentage (0 = flat/open, 100 = fully closed).
    """
    sol_elev = math.radians(sol_elev_deg)
    gamma = math.radians(gamma_deg)

    cos_gamma = math.cos(gamma)
    if cos_gamma == 0.0:
        return 100.0

    beta = math.atan(math.tan(sol_elev) / cos_gamma)
    ratio = slat_spacing_mm / slat_width_mm
    discriminant = math.tan(beta) ** 2 - ratio**2 + 1.0

    if discriminant < 0.0:
        return 100.0

    slat_rad = 2.0 * math.atan(
        (math.tan(beta) + math.sqrt(discriminant)) / (1.0 + ratio)
    )
    tilt_range = 180.0 if bidirectional else 90.0
    pct = math.degrees(slat_rad) / tilt_range * 100.0
    return min(max(pct, 0.0), 100.0)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_geometry.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/geometry.py
mypy custom_components/solar_cover/geometry.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/solar_cover/geometry.py tests/test_geometry.py
git commit -m "feat: add geometry engine with full test coverage"
```

---

## Task 3: Solar Engine

**Files:**
- Create: `custom_components/solar_cover/solar.py`
- Create: `tests/test_solar.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_solar.py`:

```python
"""Unit tests for solar.py — uses real astral library, no HA needed."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from custom_components.solar_cover.solar import SolarEngine


@pytest.fixture
def vienna_engine() -> SolarEngine:
    # Vienna: lat=48.2, lon=16.4, elevation=170m
    return SolarEngine(lat=48.2, lon=16.4, elev=170.0)


class TestSunPosition:
    def test_summer_noon_high_elevation(self, vienna_engine: SolarEngine) -> None:
        # 2026-06-21 11:00 UTC = ~13:00 Vienna time
        dt = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
        az, el = vienna_engine.sun_position(dt)
        assert 160 < az < 200  # roughly south
        assert 60 < el < 70    # high elevation in summer

    def test_winter_noon_low_elevation(self, vienna_engine: SolarEngine) -> None:
        # 2026-12-21 11:00 UTC = ~12:00 Vienna time
        dt = datetime(2026, 12, 21, 11, 0, tzinfo=timezone.utc)
        az, el = vienna_engine.sun_position(dt)
        assert 150 < az < 220
        assert 15 < el < 25  # low elevation in winter

    def test_negative_elevation_at_night(self, vienna_engine: SolarEngine) -> None:
        dt = datetime(2026, 6, 21, 21, 0, tzinfo=timezone.utc)  # 23:00 Vienna
        _, el = vienna_engine.sun_position(dt)
        assert el < 0


class TestPositionCurve:
    def test_returns_288_samples(self, vienna_engine: SolarEngine) -> None:
        curve = vienna_engine.position_curve(date(2026, 6, 21))
        assert len(curve) == 288

    def test_sample_has_required_fields(self, vienna_engine: SolarEngine) -> None:
        curve = vienna_engine.position_curve(date(2026, 6, 21))
        sample = curve[0]
        assert "time" in sample
        assert "azimuth" in sample
        assert "elevation" in sample

    def test_time_is_iso_string(self, vienna_engine: SolarEngine) -> None:
        curve = vienna_engine.position_curve(date(2026, 6, 21))
        # Should parse without error
        datetime.fromisoformat(curve[0]["time"])

    def test_hourly_curve_has_24_points(self, vienna_engine: SolarEngine) -> None:
        curve = vienna_engine.hourly_curve(date(2026, 6, 21))
        assert len(curve) == 24


class TestFovWindow:
    def test_south_window_has_entry_and_exit(self, vienna_engine: SolarEngine) -> None:
        entry, exit_ = vienna_engine.fov_window(
            azimuth_deg=180, fov_left=90, fov_right=90, date_=date(2026, 6, 21)
        )
        assert entry is not None
        assert exit_ is not None
        assert entry < exit_

    def test_entry_before_exit(self, vienna_engine: SolarEngine) -> None:
        entry, exit_ = vienna_engine.fov_window(
            azimuth_deg=180, fov_left=90, fov_right=90, date_=date(2026, 6, 21)
        )
        assert entry is not None and exit_ is not None
        assert entry < exit_

    def test_north_window_no_fov_in_summer(self, vienna_engine: SolarEngine) -> None:
        # North-facing window (0°) — sun never in FOV at 48°N in summer
        entry, exit_ = vienna_engine.fov_window(
            azimuth_deg=0, fov_left=45, fov_right=45, date_=date(2026, 6, 21)
        )
        assert entry is None
        assert exit_ is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_solar.py -v
```

Expected: `ModuleNotFoundError: No module named 'custom_components.solar_cover.solar'`

- [ ] **Step 3: Write solar.py**

```python
"""Solar engine — sun position and daily curve using astral.

No HA imports permitted. Uses hass.config values passed in at construction time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TypedDict

from astral import Observer
from astral.sun import azimuth as astral_azimuth
from astral.sun import elevation as astral_elevation


class SunSample(TypedDict):
    time: str
    azimuth: float
    elevation: float


class SolarEngine:
    """Computes solar position for a fixed geographic location."""

    def __init__(self, lat: float, lon: float, elev: float) -> None:
        self._observer = Observer(latitude=lat, longitude=lon, elevation=elev)

    def sun_position(self, dt: datetime) -> tuple[float, float]:
        """Return (azimuth_deg, elevation_deg) for the given UTC datetime."""
        az = astral_azimuth(self._observer, dt)
        el = astral_elevation(self._observer, dt)
        return az, el

    def position_curve(self, date_: date) -> list[SunSample]:
        """Return 288 five-minute samples for the given date (UTC midnight to midnight)."""
        start = datetime(date_.year, date_.month, date_.day, tzinfo=timezone.utc)
        samples: list[SunSample] = []
        for i in range(288):
            dt = start + timedelta(minutes=i * 5)
            az, el = self.sun_position(dt)
            samples.append(SunSample(time=dt.isoformat(), azimuth=az, elevation=el))
        return samples

    def hourly_curve(self, date_: date) -> list[SunSample]:
        """Return 24 hourly samples for the given date. Used for position_curve entity attribute."""
        start = datetime(date_.year, date_.month, date_.day, tzinfo=timezone.utc)
        samples: list[SunSample] = []
        for i in range(24):
            dt = start + timedelta(hours=i)
            az, el = self.sun_position(dt)
            samples.append(SunSample(time=dt.isoformat(), azimuth=az, elevation=el))
        return samples

    def fov_window(
        self,
        azimuth_deg: int,
        fov_left: int,
        fov_right: int,
        date_: date,
    ) -> tuple[datetime | None, datetime | None]:
        """Return (entry_time, exit_time) when sun enters/exits the FOV today.

        Returns (None, None) if the sun never enters the FOV on this date.
        Entry and exit times are UTC datetimes.
        """
        samples = self.position_curve(date_)
        start = datetime(date_.year, date_.month, date_.day, tzinfo=timezone.utc)
        entry: datetime | None = None
        exit_: datetime | None = None
        in_fov = False

        for i, sample in enumerate(samples):
            gamma = _gamma(azimuth_deg, sample["azimuth"])
            currently_in = sample["elevation"] > 0 and _in_fov(gamma, fov_left, fov_right)
            dt = start + timedelta(minutes=i * 5)

            if currently_in and not in_fov:
                entry = dt
            elif not currently_in and in_fov:
                exit_ = dt

            in_fov = currently_in

        return entry, exit_


def _gamma(win_azimuth: float, sol_azimuth: float) -> float:
    """Compute surface solar azimuth angle in degrees.

    Positive = sun to the left when facing the window.
    Negative = sun to the right.
    Range: (-180, 180].
    """
    return (win_azimuth - sol_azimuth + 180) % 360 - 180


def _in_fov(gamma: float, fov_left: int, fov_right: int) -> bool:
    """Return True if gamma is within the field of view."""
    return gamma < fov_left and gamma > -fov_right
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_solar.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/solar.py
mypy custom_components/solar_cover/solar.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/solar_cover/solar.py tests/test_solar.py
git commit -m "feat: add solar engine with position curve and FOV window"
```

---

## Task 4: Intent Model

**Files:**
- Create: `custom_components/solar_cover/intent.py`
- Create: `tests/test_intent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_intent.py`:

```python
"""Unit tests for intent.py — no HA needed."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.solar_cover.const import CoverType, Intent
from custom_components.solar_cover.intent import IntentInput, evaluate_intent


@pytest.fixture
def base_input() -> IntentInput:
    return IntentInput(
        sol_elev_deg=50.0,
        sol_azimuth_deg=180.0,
        win_azimuth_deg=180.0,
        fov_left=90,
        fov_right=90,
        elevation_threshold=20.0,
        raining=False,
        wind_speed=None,
        wind_threshold=None,
        outdoor_temp=None,
        min_temp=None,
        manual_override_until=None,
        now=datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
    )


class TestElevationGate:
    def test_sun_below_threshold_returns_inactive_sun_low(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "sol_elev_deg": 10.0})
        intent, position = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_SUN_LOW
        assert position is None

    def test_sun_above_threshold_continues(self, base_input: IntentInput) -> None:
        intent, _ = evaluate_intent(base_input)
        assert intent != Intent.INACTIVE_SUN_LOW


class TestFovGate:
    def test_sun_outside_fov_returns_inactive_outside_fov(self, base_input: IntentInput) -> None:
        # Sun is 100° to the right — outside fov_right=90
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 280.0})
        intent, position = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_OUTSIDE_FOV
        assert position is None

    def test_sun_inside_fov_continues(self, base_input: IntentInput) -> None:
        intent, _ = evaluate_intent(base_input)
        assert intent != Intent.INACTIVE_OUTSIDE_FOV


class TestWeatherGate:
    def test_raining_returns_inactive_weather(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "raining": True})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_WEATHER

    def test_wind_above_threshold_returns_inactive_weather(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "wind_speed": 15.0, "wind_threshold": 10.0})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_WEATHER

    def test_wind_below_threshold_continues(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "wind_speed": 5.0, "wind_threshold": 10.0})
        intent, _ = evaluate_intent(inp)
        assert intent != Intent.INACTIVE_WEATHER

    def test_temp_below_min_returns_inactive_weather(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "outdoor_temp": 5.0, "min_temp": 10.0})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_WEATHER

    def test_no_weather_data_skips_gate(self, base_input: IntentInput) -> None:
        # raining=False, no wind/temp data — weather gate passes
        intent, _ = evaluate_intent(base_input)
        assert intent != Intent.INACTIVE_WEATHER


class TestManualOverrideGate:
    def test_active_override_returns_manual_override(self, base_input: IntentInput) -> None:
        future = datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": future})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.MANUAL_OVERRIDE

    def test_expired_override_continues(self, base_input: IntentInput) -> None:
        past = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": past})
        intent, _ = evaluate_intent(inp)
        assert intent != Intent.MANUAL_OVERRIDE


class TestShadingIntent:
    def test_all_gates_pass_returns_shading(self, base_input: IntentInput) -> None:
        intent, position = evaluate_intent(base_input)
        assert intent == Intent.SHADING
        assert position is not None
        assert 0.0 <= position <= 100.0

    def test_gamma_computation(self, base_input: IntentInput) -> None:
        # Sun 45° to the right of window center — still inside 90° FOV
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 225.0})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.SHADING
```

Note: `evaluate_intent` needs geometry parameters to compute a position. Add them to `IntentInput` in the implementation.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_intent.py -v
```

Expected: `ModuleNotFoundError: No module named 'custom_components.solar_cover.intent'`

- [ ] **Step 3: Write intent.py**

```python
"""Intent model — sequential gate returning intent + computed position.

No HA imports permitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import CoverType, Intent, TiltRange
from .geometry import horizontal_position, tilt_position, vertical_position
from .solar import _gamma


@dataclass
class IntentInput:
    # Sun state
    sol_elev_deg: float
    sol_azimuth_deg: float
    # Zone config
    win_azimuth_deg: float
    fov_left: int
    fov_right: int
    elevation_threshold: float
    # Weather (all optional)
    raining: bool
    wind_speed: float | None
    wind_threshold: float | None
    outdoor_temp: float | None
    min_temp: float | None
    # Manual override
    manual_override_until: datetime | None
    now: datetime
    # Cover type (for geometry dispatch)
    cover_type: CoverType = CoverType.VERTICAL
    # Vertical geometry
    window_height: float = 2.5
    glare_depth: float = 1.0
    # Horizontal geometry
    attach_height: float = 2.5
    awn_length: float = 3.0
    awn_angle_deg: float = 15.0
    # Tilt geometry
    slat_width_mm: float = 80.0
    slat_spacing_mm: float = 50.0
    tilt_range: TiltRange = TiltRange.SINGLE


def evaluate_intent(inp: IntentInput) -> tuple[Intent, float | None]:
    """Run the sequential gate model and return (intent, computed_position | None).

    Gates evaluated in order:
    1. Elevation — is sun high enough to shade?
    2. FOV — is sun in front of this opening?
    3. Weather — are conditions safe for deployment?
    4. Manual override — has user taken manual control?
    5. Shading — compute geometry position.
    """
    # Gate 1: elevation
    if inp.sol_elev_deg <= inp.elevation_threshold:
        return Intent.INACTIVE_SUN_LOW, None

    # Gate 2: FOV
    gamma = _gamma(inp.win_azimuth_deg, inp.sol_azimuth_deg)
    if not (gamma < inp.fov_left and gamma > -inp.fov_right):
        return Intent.INACTIVE_OUTSIDE_FOV, None

    # Gate 3: weather
    if inp.raining:
        return Intent.INACTIVE_WEATHER, None
    if inp.wind_speed is not None and inp.wind_threshold is not None:
        if inp.wind_speed > inp.wind_threshold:
            return Intent.INACTIVE_WEATHER, None
    if inp.outdoor_temp is not None and inp.min_temp is not None:
        if inp.outdoor_temp < inp.min_temp:
            return Intent.INACTIVE_WEATHER, None

    # Gate 4: manual override
    if inp.manual_override_until is not None and inp.now < inp.manual_override_until:
        return Intent.MANUAL_OVERRIDE, None

    # Gate 5: shading — compute position
    position = _compute_position(inp, gamma)
    return Intent.SHADING, position


def _compute_position(inp: IntentInput, gamma: float) -> float:
    if inp.cover_type == CoverType.VERTICAL:
        return vertical_position(
            sol_elev_deg=inp.sol_elev_deg,
            gamma_deg=gamma,
            distance=inp.glare_depth,
            h_win=inp.window_height,
        )
    if inp.cover_type == CoverType.HORIZONTAL:
        return horizontal_position(
            sol_elev_deg=inp.sol_elev_deg,
            gamma_deg=gamma,
            h_win=inp.attach_height,
            awn_length=inp.awn_length,
            awn_angle_deg=inp.awn_angle_deg,
            distance=inp.glare_depth,
        )
    # CoverType.TILT
    return tilt_position(
        sol_elev_deg=inp.sol_elev_deg,
        gamma_deg=gamma,
        slat_width_mm=inp.slat_width_mm,
        slat_spacing_mm=inp.slat_spacing_mm,
        bidirectional=inp.tilt_range == TiltRange.BIDIRECTIONAL,
    )
```

- [ ] **Step 4: Fix test dataclass instantiation**

The tests use `IntentInput(**{**base_input.__dict__, ...})`. Because `IntentInput` is a dataclass with defaults, this will work. Verify by running the tests.

```bash
pytest tests/test_intent.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/intent.py
mypy custom_components/solar_cover/intent.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/solar_cover/intent.py tests/test_intent.py
git commit -m "feat: add intent model with sequential gate evaluation"
```

---

## Task 5: Coordinator

**Files:**
- Create: `custom_components/solar_cover/coordinator.py`

The coordinator orchestrates solar engine + intent model + entity updates on a 5-minute timer plus weather entity state changes.

- [ ] **Step 1: Write coordinator.py**

```python
"""Coordinator — one per Cover Zone.

Runs on a 5-minute timer and on weather entity state_changed events.
Computes sun position, evaluates intent, applies hysteresis, commands entities.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.cover import SERVICE_SET_COVER_POSITION
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ATTACH_HEIGHT,
    CONF_AWN_ANGLE,
    CONF_AWN_LENGTH,
    CONF_AZIMUTH,
    CONF_COVER_ENTITIES,
    CONF_COVER_TYPE,
    CONF_ELEVATION_THRESHOLD,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_GLARE_DEPTH,
    CONF_HYSTERESIS,
    CONF_INACTIVE_POSITION,
    CONF_INACTIVE_POSITION_OVERRIDE,
    CONF_MAX_POSITION,
    CONF_MIN_POSITION,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_TILT_RANGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_THRESHOLD,
    CONF_MIN_TEMP,
    DEFAULT_HYSTERESIS,
    DEFAULT_INACTIVE_POSITION,
    UPDATE_INTERVAL_MINUTES,
    CoverType,
    Intent,
    TiltRange,
    DOMAIN,
)
from .intent import IntentInput, evaluate_intent
from .solar import SolarEngine

_LOGGER = logging.getLogger(__name__)


class CoordinatorData:
    """Snapshot of latest coordinator state, attached to entities as attributes."""

    def __init__(
        self,
        intent: Intent,
        computed_position: float | None,
        commanded_position: float | None,
        sun_azimuth: float,
        sun_elevation: float,
        gamma: float,
        position_curve: list[dict],
        fov_entry: str | None,
        fov_exit: str | None,
    ) -> None:
        self.intent = intent
        self.computed_position = computed_position
        self.commanded_position = commanded_position
        self.sun_azimuth = sun_azimuth
        self.sun_elevation = sun_elevation
        self.gamma = gamma
        self.position_curve = position_curve
        self.fov_entry = fov_entry
        self.fov_exit = fov_exit


class SolarCoverCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator for a single Cover Zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        zone_data: dict,
        integration_data: dict,
        solar_engine: SolarEngine,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{zone_data.get('name', 'zone')}",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._zone = zone_data
        self._integration = integration_data
        self._solar = solar_engine
        self._last_commanded: float | None = None
        self._manual_override_until: datetime | None = None

        weather_entity = integration_data.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            self._unsub_weather = async_track_state_change_event(
                hass, [weather_entity], self._on_weather_change
            )

    @callback
    def _on_weather_change(self, event) -> None:
        self.async_request_refresh()

    async def _async_update_data(self) -> CoordinatorData:
        now = datetime.now(tz=timezone.utc)
        sol_az, sol_el = self._solar.sun_position(now)

        weather_state = None
        weather_entity = self._integration.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            weather_state = self.hass.states.get(weather_entity)

        raining = False
        wind_speed: float | None = None
        outdoor_temp: float | None = None

        if weather_state and weather_state.state not in ("unavailable", "unknown"):
            raining = weather_state.state in ("rainy", "pouring", "snowy", "lightning-rainy")
            attrs = weather_state.attributes
            wind_speed = attrs.get("wind_speed")
            outdoor_temp = attrs.get("temperature")

        win_az = self._zone[CONF_AZIMUTH]
        from .solar import _gamma as compute_gamma
        gamma = compute_gamma(win_az, sol_az)

        inp = IntentInput(
            sol_elev_deg=sol_el,
            sol_azimuth_deg=sol_az,
            win_azimuth_deg=win_az,
            fov_left=self._zone[CONF_FOV_LEFT],
            fov_right=self._zone[CONF_FOV_RIGHT],
            elevation_threshold=self._zone[CONF_ELEVATION_THRESHOLD],
            raining=raining,
            wind_speed=wind_speed,
            wind_threshold=self._integration.get(CONF_WIND_THRESHOLD),
            outdoor_temp=outdoor_temp,
            min_temp=self._integration.get(CONF_MIN_TEMP),
            manual_override_until=self._manual_override_until,
            now=now,
            cover_type=CoverType(self._zone[CONF_COVER_TYPE]),
            window_height=self._zone.get("window_height", 2.5),
            glare_depth=self._zone.get(CONF_GLARE_DEPTH, 1.0),
            attach_height=self._zone.get(CONF_ATTACH_HEIGHT, 2.5),
            awn_length=self._zone.get(CONF_AWN_LENGTH, 3.0),
            awn_angle_deg=self._zone.get(CONF_AWN_ANGLE, 15.0),
            slat_width_mm=self._zone.get(CONF_SLAT_WIDTH, 80.0),
            slat_spacing_mm=self._zone.get(CONF_SLAT_SPACING, 50.0),
            tilt_range=TiltRange(self._zone.get(CONF_TILT_RANGE, TiltRange.SINGLE)),
        )

        intent, computed_pos = evaluate_intent(inp)

        # Resolve final position
        inactive_pos = self._zone.get(
            CONF_INACTIVE_POSITION_OVERRIDE,
            self._integration.get(CONF_INACTIVE_POSITION, DEFAULT_INACTIVE_POSITION),
        )
        raw_position = computed_pos if intent == Intent.SHADING else float(inactive_pos)

        # Apply min/max clamp
        min_pos = self._zone.get(CONF_MIN_POSITION)
        max_pos = self._zone.get(CONF_MAX_POSITION)
        clamped = raw_position
        if min_pos is not None:
            clamped = max(clamped, float(min_pos))
        if max_pos is not None:
            clamped = min(clamped, float(max_pos))

        commanded: float | None = None

        # Apply hysteresis — only command if delta exceeds threshold
        hysteresis = float(self._zone.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS))
        if self._last_commanded is None or abs(clamped - self._last_commanded) >= hysteresis:
            await self._command_covers(clamped)
            self._last_commanded = clamped
            commanded = clamped
        else:
            commanded = self._last_commanded

        # Build hourly curve for entity attribute
        curve = self._solar.hourly_curve(now.date())

        entry, exit_ = self._solar.fov_window(
            azimuth_deg=win_az,
            fov_left=self._zone[CONF_FOV_LEFT],
            fov_right=self._zone[CONF_FOV_RIGHT],
            date_=now.date(),
        )

        return CoordinatorData(
            intent=intent,
            computed_position=computed_pos,
            commanded_position=commanded,
            sun_azimuth=sol_az,
            sun_elevation=sol_el,
            gamma=gamma,
            position_curve=[dict(s) for s in curve],
            fov_entry=entry.isoformat() if entry else None,
            fov_exit=exit_.isoformat() if exit_ else None,
        )

    async def _command_covers(self, position: float) -> None:
        entities = self._zone.get(CONF_COVER_ENTITIES, [])
        if not entities:
            return
        await self.hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entities, "position": round(position)},
            blocking=False,
        )

    def set_manual_override(self, until: datetime) -> None:
        self._manual_override_until = until
        self.async_request_refresh()

    def clear_manual_override(self) -> None:
        self._manual_override_until = None
        self.async_request_refresh()
```

- [ ] **Step 2: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/coordinator.py
mypy custom_components/solar_cover/coordinator.py
```

Fix any type errors before continuing.

- [ ] **Step 3: Commit**

```bash
git add custom_components/solar_cover/coordinator.py
git commit -m "feat: add zone coordinator with weather gate and hysteresis"
```

---

## Task 6: Cover Entity

**Files:**
- Create: `custom_components/solar_cover/cover.py`

- [ ] **Step 1: Write cover.py**

```python
"""Solar Cover entity — reads coordinator state, exposes observability attributes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_OVERRIDE_DURATION, CONF_OVERRIDE_DURATION_OVERRIDE, DEFAULT_OVERRIDE_DURATION, DOMAIN
from .coordinator import SolarCoverCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolarCoverCoordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]
    integration_data = hass.data[DOMAIN].get("integration", {})
    async_add_entities([SolarCoverEntity(coordinator, entry, integration_data)])


class SolarCoverEntity(CoordinatorEntity[SolarCoverCoordinator], CoverEntity):
    """Represents a Solar Cover zone — commands all physical covers in the zone."""

    _attr_has_entity_name = True
    _attr_supported_features = CoverEntityFeature.SET_POSITION

    def __init__(
        self,
        coordinator: SolarCoverCoordinator,
        entry: ConfigEntry,
        integration_data: dict,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._integration_data = integration_data
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title
        self._attr_device_class = CoverDeviceClass.BLIND

    @property
    def is_closed(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        pos = self.coordinator.data.commanded_position
        return pos is not None and pos == 0

    @property
    def current_cover_position(self) -> int | None:
        if self.coordinator.data is None:
            return None
        pos = self.coordinator.data.commanded_position
        return round(pos) if pos is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "intent": str(data.intent),
            "sun_azimuth": round(data.sun_azimuth, 1),
            "sun_elevation": round(data.sun_elevation, 1),
            "surface_azimuth": round(data.gamma, 1),
            "computed_position": (
                round(data.computed_position) if data.computed_position is not None else None
            ),
            "commanded_position": (
                round(data.commanded_position) if data.commanded_position is not None else None
            ),
            "fov_entry": data.fov_entry,
            "fov_exit": data.fov_exit,
            "position_curve": data.position_curve,
        }

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs.get("position", 0)
        override_minutes = self._entry.data.get(
            CONF_OVERRIDE_DURATION_OVERRIDE,
            self._integration_data.get(CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION),
        )
        until = datetime.now(tz=timezone.utc) + timedelta(minutes=int(override_minutes))
        self.coordinator.set_manual_override(until)

    async def async_open_cover(self, **kwargs) -> None:
        await self.async_set_cover_position(position=100)

    async def async_close_cover(self, **kwargs) -> None:
        await self.async_set_cover_position(position=0)
```

- [ ] **Step 2: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/cover.py
mypy custom_components/solar_cover/cover.py
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/solar_cover/cover.py
git commit -m "feat: add cover entity with intent and observability attributes"
```

---

## Task 7: Config Flow

**Files:**
- Create: `custom_components/solar_cover/config_flow.py`
- Create: `custom_components/solar_cover/strings.json`
- Create: `custom_components/solar_cover/translations/en.json`

- [ ] **Step 1: Write strings.json**

```json
{
  "config": {
    "step": {
      "integration": {
        "title": "Solar Cover — Global Settings",
        "description": "These settings apply to all cover zones. All fields are optional.",
        "data": {
          "weather_entity": "Weather entity",
          "wind_threshold": "Wind speed threshold (m/s)",
          "min_temp": "Minimum outdoor temperature (°C)",
          "inactive_position": "Inactive position (%)",
          "override_duration": "Manual override duration (minutes)"
        }
      },
      "zone": {
        "title": "Cover Zone",
        "description": "Configure a group of covers that move together.",
        "data": {
          "cover_entities": "Cover entities",
          "cover_type": "Cover type",
          "azimuth": "Compass bearing (°)",
          "fov_left": "Field of view — left (°)",
          "fov_right": "Field of view — right (°)",
          "elevation_threshold": "Elevation threshold (°)",
          "window_height": "Window height (m)",
          "glare_depth": "Glare protection depth (m)",
          "attach_height": "Attachment height above floor (m)",
          "awn_length": "Awning span length (m)",
          "awn_angle": "Awning angle from horizontal (°)",
          "slat_width": "Slat width (mm)",
          "slat_spacing": "Slat spacing (mm)",
          "tilt_range": "Tilt range"
        }
      }
    },
    "error": {
      "spacing_exceeds_width": "Slat spacing must be less than or equal to slat width.",
      "unknown": "Unexpected error. Check the logs."
    }
  }
}
```

- [ ] **Step 2: Write translations/en.json**

```json
{
  "config": {
    "step": {
      "integration": {
        "title": "Solar Cover — Global Settings",
        "description": "These settings apply to all cover zones. All fields are optional.",
        "data": {
          "weather_entity": "Weather entity",
          "wind_threshold": "Wind speed threshold (m/s)",
          "min_temp": "Minimum outdoor temperature (°C)",
          "inactive_position": "Inactive position (%)",
          "override_duration": "Manual override duration (minutes)"
        }
      },
      "zone": {
        "title": "Cover Zone",
        "description": "Configure a group of covers that move together. Hold your phone flat against the glass to read the compass bearing.",
        "data": {
          "cover_entities": "Cover entities",
          "cover_type": "Cover type",
          "azimuth": "Compass bearing (°)",
          "fov_left": "Field of view — left (°)",
          "fov_right": "Field of view — right (°)",
          "elevation_threshold": "Elevation threshold (°)",
          "window_height": "Window height (m)",
          "glare_depth": "Glare protection depth (m)",
          "attach_height": "Attachment height above floor (m)",
          "awn_length": "Awning span length (m)",
          "awn_angle": "Awning angle from horizontal (°)",
          "slat_width": "Slat width (mm)",
          "slat_spacing": "Slat spacing (mm)",
          "tilt_range": "Tilt range"
        }
      }
    },
    "error": {
      "spacing_exceeds_width": "Slat spacing must be less than or equal to slat width.",
      "unknown": "Unexpected error. Check the logs."
    }
  }
}
```

- [ ] **Step 3: Write config_flow.py**

```python
"""Config flow for Solar Cover — integration step then zone step."""
from __future__ import annotations

import math
from typing import Any

import voluptuous as vol
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_ATTACH_HEIGHT,
    CONF_AWN_ANGLE,
    CONF_AWN_LENGTH,
    CONF_AZIMUTH,
    CONF_COVER_ENTITIES,
    CONF_COVER_TYPE,
    CONF_ELEVATION_THRESHOLD,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_GLARE_DEPTH,
    CONF_INACTIVE_POSITION,
    CONF_MIN_TEMP,
    CONF_OVERRIDE_DURATION,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_TILT_RANGE,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_HEIGHT,
    CONF_WIND_THRESHOLD,
    DOMAIN,
    DEFAULT_INACTIVE_POSITION,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_ELEVATION_THRESHOLD_FACTOR,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    CoverType,
    TiltRange,
)


def _auto_elevation_threshold(hass_config) -> float:
    lat = getattr(hass_config, "latitude", 48.0)
    return round((90.0 - abs(lat)) * DEFAULT_ELEVATION_THRESHOLD_FACTOR, 1)


class SolarCoverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step config flow: integration (global) then zone."""

    VERSION = 1

    def __init__(self) -> None:
        self._integration_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # If integration entry already exists, go directly to zone setup
        existing = [
            e for e in self._async_current_entries()
            if e.data.get("entry_type") == ENTRY_TYPE_INTEGRATION
        ]
        if existing:
            self._integration_entry = existing[0]
            return await self.async_step_zone()
        return await self.async_step_integration()

    async def async_step_integration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {
                "entry_type": ENTRY_TYPE_INTEGRATION,
                **user_input,
            }
            return self.async_create_entry(title="Solar Cover", data=data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_WIND_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=50, step=0.5, mode="box", unit_of_measurement="m/s")
                ),
                vol.Optional(CONF_MIN_TEMP): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-20, max=30, step=1, mode="box", unit_of_measurement="°C")
                ),
                vol.Optional(CONF_INACTIVE_POSITION, default=DEFAULT_INACTIVE_POSITION): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=1, mode="slider", unit_of_measurement="%")
                ),
                vol.Optional(CONF_OVERRIDE_DURATION, default=DEFAULT_OVERRIDE_DURATION): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=15, max=480, step=15, mode="slider", unit_of_measurement="min")
                ),
            }
        )
        return self.async_show_form(step_id="integration", data_schema=schema)

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            cover_type = user_input.get(CONF_COVER_TYPE)
            if cover_type == CoverType.TILT:
                slat_width = user_input.get(CONF_SLAT_WIDTH, 80.0)
                slat_spacing = user_input.get(CONF_SLAT_SPACING, 50.0)
                if slat_spacing > slat_width:
                    errors[CONF_SLAT_SPACING] = "spacing_exceeds_width"

            if not errors:
                data = {
                    "entry_type": ENTRY_TYPE_ZONE,
                    **user_input,
                }
                title = user_input.get("name", "Cover Zone")
                return self.async_create_entry(title=title, data=data)

        auto_threshold = _auto_elevation_threshold(self.hass.config)
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required(CONF_COVER_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=COVER_DOMAIN, multiple=True)
                ),
                vol.Required(CONF_COVER_TYPE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[e.value for e in CoverType],
                        translation_key=CONF_COVER_TYPE,
                    )
                ),
                vol.Required(CONF_AZIMUTH, default=180): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=359, step=1, mode="box", unit_of_measurement="°")
                ),
                vol.Required(CONF_FOV_LEFT, default=90): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=180, step=1, mode="slider", unit_of_measurement="°")
                ),
                vol.Required(CONF_FOV_RIGHT, default=90): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=180, step=1, mode="slider", unit_of_measurement="°")
                ),
                vol.Required(CONF_ELEVATION_THRESHOLD, default=auto_threshold): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=45, step=0.5, mode="box", unit_of_measurement="°")
                ),
                # Vertical geometry (always shown; hidden by cover_type in UI TBD)
                vol.Optional(CONF_WINDOW_HEIGHT, default=2.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=5.0, step=0.1, mode="box", unit_of_measurement="m")
                ),
                vol.Optional(CONF_GLARE_DEPTH, default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=5.0, step=0.1, mode="box", unit_of_measurement="m")
                ),
                # Horizontal geometry
                vol.Optional(CONF_ATTACH_HEIGHT, default=2.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=5.0, step=0.1, mode="box", unit_of_measurement="m")
                ),
                vol.Optional(CONF_AWN_LENGTH, default=3.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=10.0, step=0.1, mode="box", unit_of_measurement="m")
                ),
                vol.Optional(CONF_AWN_ANGLE, default=15): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=45, step=1, mode="box", unit_of_measurement="°")
                ),
                # Tilt geometry
                vol.Optional(CONF_SLAT_WIDTH, default=80): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=200, step=1, mode="box", unit_of_measurement="mm")
                ),
                vol.Optional(CONF_SLAT_SPACING, default=50): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=200, step=1, mode="box", unit_of_measurement="mm")
                ),
                vol.Optional(CONF_TILT_RANGE, default=TiltRange.SINGLE): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[e.value for e in TiltRange])
                ),
            }
        )
        return self.async_show_form(step_id="zone", data_schema=schema, errors=errors)
```

- [ ] **Step 4: Run ruff and mypy**

```bash
ruff check custom_components/solar_cover/config_flow.py
mypy custom_components/solar_cover/config_flow.py
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/solar_cover/config_flow.py \
        custom_components/solar_cover/strings.json \
        custom_components/solar_cover/translations/
git commit -m "feat: add config flow with integration and zone steps"
```

---

## Task 8: Wire __init__.py — Full Integration Entry Point

**Files:**
- Modify: `custom_components/solar_cover/__init__.py`

- [ ] **Step 1: Rewrite __init__.py with full coordinator setup**

```python
"""Solar Cover integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
)
from .coordinator import SolarCoverCoordinator
from .solar import SolarEngine

PLATFORMS_ZONE = ["cover"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"coordinators": {}})

    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN]["integration"] = dict(entry.data)
        return True

    # Zone entry
    integration_data = hass.data[DOMAIN].get("integration", {})
    solar = SolarEngine(
        lat=hass.config.latitude,
        lon=hass.config.longitude,
        elev=hass.config.elevation,
    )

    coordinator = SolarCoverCoordinator(
        hass=hass,
        zone_data=dict(entry.data),
        integration_data=integration_data,
        solar_engine=solar,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ZONE)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN].pop("integration", None)
        return True

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS_ZONE)
    if unloaded:
        hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)
    return unloaded
```

- [ ] **Step 2: Run ruff and mypy on all modules**

```bash
ruff check custom_components/solar_cover/
mypy custom_components/solar_cover/
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all existing tests (geometry, intent, solar) PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/solar_cover/__init__.py
git commit -m "feat: wire coordinator into setup_entry; complete integration entry point"
```

---

## Task 9: Config Flow Tests

**Files:**
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Write config flow tests**

```python
"""Config flow integration tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.const import (
    CONF_AZIMUTH,
    CONF_COVER_ENTITIES,
    CONF_COVER_TYPE,
    CONF_ELEVATION_THRESHOLD,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_WINDOW_HEIGHT,
    CONF_GLARE_DEPTH,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    CoverType,
)


ZONE_INPUT = {
    "name": "South Terrace",
    CONF_COVER_ENTITIES: ["cover.terrace_awning"],
    CONF_COVER_TYPE: CoverType.VERTICAL,
    CONF_AZIMUTH: 180,
    CONF_FOV_LEFT: 90,
    CONF_FOV_RIGHT: 90,
    CONF_ELEVATION_THRESHOLD: 27.0,
    CONF_WINDOW_HEIGHT: 2.5,
    CONF_GLARE_DEPTH: 1.0,
}


@pytest.fixture
def integration_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": ENTRY_TYPE_INTEGRATION},
        title="Solar Cover",
    )
    entry.add_to_hass(hass)
    return entry


class TestIntegrationStep:
    async def test_shows_integration_form_when_no_entry_exists(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "integration"

    async def test_creates_integration_entry(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["entry_type"] == ENTRY_TYPE_INTEGRATION


class TestZoneStep:
    async def test_shows_zone_form_when_integration_exists(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "zone"

    async def test_creates_zone_entry(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=ZONE_INPUT
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result2["data"][CONF_AZIMUTH] == 180

    async def test_tilt_spacing_validation(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        bad_input = {
            **ZONE_INPUT,
            CONF_COVER_TYPE: CoverType.TILT,
            "slat_width": 50.0,
            "slat_spacing": 60.0,  # spacing > width — should fail
        }
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_input
        )
        assert result2["type"] == FlowResultType.FORM
        assert "slat_spacing" in result2.get("errors", {})
```

- [ ] **Step 2: Run config flow tests**

```bash
pytest tests/test_config_flow.py -v --tb=short
```

Expected: tests PASS. If HA fixtures are unavailable, install with `pip install pytest-homeassistant-custom-component`.

- [ ] **Step 3: Run full suite with coverage**

```bash
pytest tests/ -v --cov=custom_components/solar_cover --cov-report=term-missing
```

Expected: all tests pass. Coverage should be >70% across all modules.

- [ ] **Step 4: Final lint and type check**

```bash
ruff check .
mypy custom_components/solar_cover/
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/test_config_flow.py
git commit -m "feat: add config flow tests; integration complete"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec requirement | Task that covers it |
|---|---|
| vertical_position formula | Task 2 |
| horizontal_position with clip | Task 2 |
| tilt_position with NaN guard | Task 2 |
| sun_position via astral | Task 3 |
| 288-sample daily curve | Task 3 |
| fov_window entry/exit | Task 3 |
| Sequential intent gate | Task 4 |
| All 5 intent values | Task 4 |
| Coordinator 5-min update | Task 5 |
| Weather state_changed trigger | Task 5 |
| Hysteresis (3% default) | Task 5 |
| Min/max position clamp | Task 5 |
| Manual override timer | Task 5, 6 |
| `intent` attribute on entity | Task 6 |
| `position_curve` attribute | Task 6 |
| All observability attributes | Task 6 |
| Two-step config flow | Task 7 |
| Slat spacing validation | Task 7 |
| Auto elevation threshold | Task 7 |
| Integration entry detection | Task 7, 8 |
| Integration/zone wiring | Task 8 |
| Config flow tests | Task 9 |

**Type consistency verified:** `SolarEngine`, `IntentInput`, `CoordinatorData`, `SolarCoverCoordinator`, and `SolarCoverEntity` all reference consistent field names across tasks.

**No placeholders found.**
