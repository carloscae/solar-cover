"""Unit tests for intent.py -- no HA needed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.solar_cover.const import CoverType, Intent, TiltRange
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
        now=datetime(2026, 6, 21, 12, 0, tzinfo=UTC),
    )


class TestElevationGate:
    def test_sun_below_threshold_returns_inactive_sun_low(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(**{**base_input.__dict__, "sol_elev_deg": 10.0})
        intent, position = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_SUN_LOW
        assert position is None

    def test_sun_above_threshold_continues(self, base_input: IntentInput) -> None:
        intent, _ = evaluate_intent(base_input)
        assert intent != Intent.INACTIVE_SUN_LOW


class TestFovGate:
    def test_sun_outside_fov_returns_inactive_outside_fov(
        self, base_input: IntentInput
    ) -> None:
        # Sun is 100 deg to the right -- outside fov_right=90
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

    def test_wind_above_threshold_returns_inactive_weather(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "wind_speed": 15.0, "wind_threshold": 10.0}
        )
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_WEATHER

    def test_wind_below_threshold_continues(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "wind_speed": 5.0, "wind_threshold": 10.0}
        )
        intent, _ = evaluate_intent(inp)
        assert intent != Intent.INACTIVE_WEATHER

    def test_temp_below_min_returns_inactive_weather(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "outdoor_temp": 5.0, "min_temp": 10.0}
        )
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.INACTIVE_WEATHER

    def test_no_weather_data_skips_gate(self, base_input: IntentInput) -> None:
        # raining=False, no wind/temp data -- weather gate passes
        intent, _ = evaluate_intent(base_input)
        assert intent != Intent.INACTIVE_WEATHER


class TestManualOverrideGate:
    def test_active_override_returns_manual_override(
        self, base_input: IntentInput
    ) -> None:
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": future})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.MANUAL_OVERRIDE

    def test_expired_override_continues(self, base_input: IntentInput) -> None:
        past = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
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
        # Sun 45 deg to the right of window center -- still inside 90 deg FOV
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 225.0})
        intent, _ = evaluate_intent(inp)
        assert intent == Intent.SHADING

    def test_horizontal_cover_type_returns_position(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "cover_type": CoverType.HORIZONTAL,
                "attach_height": 2.5,
                "awn_length": 3.0,
                "awn_angle_deg": 15.0,
                "glare_depth": 0.5,
            }
        )
        intent, position = evaluate_intent(inp)
        assert intent == Intent.SHADING
        assert position is not None
        assert 0.0 <= position <= 100.0

    def test_tilt_cover_type_returns_position(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "cover_type": CoverType.TILT,
                "slat_width_mm": 80.0,
                "slat_spacing_mm": 50.0,
                "tilt_range": TiltRange.SINGLE,
            }
        )
        intent, position = evaluate_intent(inp)
        assert intent == Intent.SHADING
        assert position is not None
        assert 0.0 <= position <= 100.0
