"""Unit tests for intent.py -- no HA needed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.solar_cover.const import (
    CoverType,
    Intent,
    ReasonCode,
    TiltRange,
)
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
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
        assert intent == Intent.INACTIVE_SUN_LOW
        assert position is None

    def test_sun_above_threshold_continues(self, base_input: IntentInput) -> None:
        intent = evaluate_intent(base_input).intent
        assert intent != Intent.INACTIVE_SUN_LOW


class TestFovGate:
    def test_sun_outside_fov_returns_inactive_outside_fov(
        self, base_input: IntentInput
    ) -> None:
        # Sun is 100 deg to the right -- outside fov_right=90
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 280.0})
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
        assert intent == Intent.INACTIVE_OUTSIDE_FOV
        assert position is None

    def test_sun_inside_fov_continues(self, base_input: IntentInput) -> None:
        intent = evaluate_intent(base_input).intent
        assert intent != Intent.INACTIVE_OUTSIDE_FOV


class TestWeatherGate:
    def test_raining_returns_inactive_weather(self, base_input: IntentInput) -> None:
        inp = IntentInput(**{**base_input.__dict__, "raining": True})
        intent = evaluate_intent(inp).intent
        assert intent == Intent.INACTIVE_WEATHER

    def test_wind_above_threshold_returns_inactive_weather(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "wind_speed": 15.0, "wind_threshold": 10.0}
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.INACTIVE_WEATHER

    def test_wind_below_threshold_continues(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "wind_speed": 5.0, "wind_threshold": 10.0}
        )
        intent = evaluate_intent(inp).intent
        assert intent != Intent.INACTIVE_WEATHER

    def test_temp_below_min_returns_inactive_weather(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "outdoor_temp": 5.0, "min_temp": 10.0}
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.INACTIVE_WEATHER

    def test_no_weather_data_skips_gate(self, base_input: IntentInput) -> None:
        # raining=False, no wind/temp data -- weather gate passes
        intent = evaluate_intent(base_input).intent
        assert intent != Intent.INACTIVE_WEATHER


class TestOvercastGate:
    def test_radiation_below_threshold_returns_inactive_overcast(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "radiation": 80.0, "radiation_threshold": 120.0}
        )
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
        assert intent == Intent.INACTIVE_OVERCAST
        assert position is None

    def test_radiation_above_threshold_continues(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "radiation": 500.0, "radiation_threshold": 120.0}
        )
        intent = evaluate_intent(inp).intent
        assert intent != Intent.INACTIVE_OVERCAST

    def test_cloud_above_threshold_returns_inactive_overcast(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "cloud_coverage": 90.0, "cloud_threshold": 80.0}
        )
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
        assert intent == Intent.INACTIVE_OVERCAST
        assert position is None

    def test_cloud_below_threshold_continues(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "cloud_coverage": 50.0, "cloud_threshold": 80.0}
        )
        intent = evaluate_intent(inp).intent
        assert intent != Intent.INACTIVE_OVERCAST

    def test_cloud_blocks_when_radiation_ok(self, base_input: IntentInput) -> None:
        # Radiation is fine but cloud is over threshold -- cloud gate should still block
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "radiation": 500.0,
                "radiation_threshold": 120.0,
                "cloud_coverage": 95.0,
                "cloud_threshold": 80.0,
            }
        )
        intent = evaluate_intent(inp).intent
        # radiation passes, cloud blocks
        assert intent == Intent.INACTIVE_OVERCAST

    def test_radiation_blocks_regardless_of_cloud(
        self, base_input: IntentInput
    ) -> None:
        # Radiation below threshold -- should block even if cloud is fine
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "radiation": 50.0,
                "radiation_threshold": 120.0,
                "cloud_coverage": 10.0,
                "cloud_threshold": 80.0,
            }
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.INACTIVE_OVERCAST

    def test_no_sensor_configured_skips_gate(self, base_input: IntentInput) -> None:
        intent = evaluate_intent(base_input).intent
        assert intent != Intent.INACTIVE_OVERCAST

    def test_sensor_without_threshold_skips_gate(self, base_input: IntentInput) -> None:
        # Entity configured but threshold not set -- gate is skipped
        inp = IntentInput(**{**base_input.__dict__, "radiation": 50.0})
        intent = evaluate_intent(inp).intent
        assert intent != Intent.INACTIVE_OVERCAST


class TestManualOverrideGate:
    def test_active_override_returns_manual_override(
        self, base_input: IntentInput
    ) -> None:
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": future})
        intent = evaluate_intent(inp).intent
        assert intent == Intent.MANUAL_OVERRIDE

    def test_expired_override_continues(self, base_input: IntentInput) -> None:
        past = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": past})
        intent = evaluate_intent(inp).intent
        assert intent != Intent.MANUAL_OVERRIDE

    def test_override_beats_low_sun(self, base_input: IntentInput) -> None:
        # Sun below threshold but an override is active -- override holds.
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "sol_elev_deg": 5.0,
                "manual_override_until": future,
            }
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.MANUAL_OVERRIDE

    def test_override_beats_outside_fov(self, base_input: IntentInput) -> None:
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "sol_azimuth_deg": 280.0,
                "manual_override_until": future,
            }
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.MANUAL_OVERRIDE

    def test_override_beats_overcast(self, base_input: IntentInput) -> None:
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "cloud_coverage": 95.0,
                "cloud_threshold": 80.0,
                "manual_override_until": future,
            }
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.MANUAL_OVERRIDE

    def test_weather_safety_beats_override(self, base_input: IntentInput) -> None:
        # Hard safety (rain/wind) must still retract even under a manual override.
        future = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "raining": True,
                "manual_override_until": future,
            }
        )
        intent = evaluate_intent(inp).intent
        assert intent == Intent.INACTIVE_WEATHER


class TestShadingIntent:
    def test_all_gates_pass_returns_shading(self, base_input: IntentInput) -> None:
        result = evaluate_intent(base_input)
        intent, position = result.intent, result.position
        assert intent == Intent.SHADING
        assert position is not None
        assert 0.0 <= position <= 100.0

    def test_gamma_computation(self, base_input: IntentInput) -> None:
        # Sun 45 deg to the right of window center -- still inside 90 deg FOV
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 225.0})
        intent = evaluate_intent(inp).intent
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
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
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
        result = evaluate_intent(inp)
        intent, position = result.intent, result.position
        assert intent == Intent.SHADING
        assert position is not None
        assert 0.0 <= position <= 100.0


def _trigger(result, code: ReasonCode):
    """Return the single trigger with the given code, or fail."""
    matches = [t for t in result.triggers if t.code == code]
    assert matches, f"no trigger {code} in {[t.code for t in result.triggers]}"
    return matches[0]


class TestReasonReporting:
    """The richer IntentResult: reason sentence + structured triggers."""

    def test_result_carries_intent_and_position(self, base_input: IntentInput) -> None:
        result = evaluate_intent(base_input)
        assert result.intent == Intent.SHADING
        assert result.position is not None
        assert isinstance(result.reason, str) and result.reason

    def test_wind_trigger_reports_value_threshold_margin(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "wind_speed": 45.0, "wind_threshold": 40.0}
        )
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_WEATHER
        wind = _trigger(result, ReasonCode.WEATHER_WIND)
        assert wind.measured == 45.0
        assert wind.threshold == 40.0
        assert wind.margin == 5.0
        assert wind.unit == "km/h"
        assert "45" in result.reason and "40" in result.reason

    def test_rain_and_wind_both_reported(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{
                **base_input.__dict__,
                "raining": True,
                "wind_speed": 45.0,
                "wind_threshold": 40.0,
            }
        )
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_WEATHER
        codes = {t.code for t in result.triggers}
        assert ReasonCode.WEATHER_RAIN in codes
        assert ReasonCode.WEATHER_WIND in codes

    def test_cold_trigger_reports_negative_margin(
        self, base_input: IntentInput
    ) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "outdoor_temp": 5.0, "min_temp": 10.0}
        )
        result = evaluate_intent(inp)
        cold = _trigger(result, ReasonCode.WEATHER_COLD)
        assert cold.measured == 5.0
        assert cold.threshold == 10.0
        assert cold.margin == -5.0
        assert cold.unit == "°C"

    def test_sun_low_reports_gap_to_threshold(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "sol_elev_deg": 12.0, "elevation_threshold": 20.0}
        )
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_SUN_LOW
        t = _trigger(result, ReasonCode.SUN_LOW)
        assert t.measured == 12.0
        assert t.threshold == 20.0
        assert t.margin == -8.0
        assert t.unit == "°"

    def test_fov_right_edge(self, base_input: IntentInput) -> None:
        # sol_azimuth 280 vs window 180 -> gamma -100 (sun to the right).
        # Structured detail reports the off-axis magnitude vs the edge limit so
        # measured/threshold/margin stay consistent with the text.
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 280.0})
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_OUTSIDE_FOV
        t = _trigger(result, ReasonCode.FOV_RIGHT)
        assert t.measured == 100.0
        assert t.threshold == 90.0
        assert t.margin == 10.0  # 10 deg past the 90 deg right edge
        assert "right" in result.reason

    def test_fov_exact_boundary_says_at_not_past(self, base_input: IntentInput) -> None:
        # sol_azimuth 270 vs window 180 -> gamma exactly -90, sitting on the
        # right edge (FOV uses strict inequalities, so the boundary is "out").
        # Text must not claim "past" when margin is 0.
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 270.0})
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_OUTSIDE_FOV
        t = _trigger(result, ReasonCode.FOV_RIGHT)
        assert t.margin == 0.0
        assert "past" not in result.reason
        assert "at the" in result.reason

    def test_fov_left_edge(self, base_input: IntentInput) -> None:
        # sol_azimuth 80 vs window 180 -> gamma +100 (sun to the left)
        inp = IntentInput(**{**base_input.__dict__, "sol_azimuth_deg": 80.0})
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_OUTSIDE_FOV
        t = _trigger(result, ReasonCode.FOV_LEFT)
        assert t.measured == 100.0
        assert t.threshold == 90.0
        assert t.margin == 10.0  # 10 deg past the 90 deg left edge
        assert "left" in result.reason

    def test_overcast_radiation_trigger(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "radiation": 80.0, "radiation_threshold": 150.0}
        )
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_OVERCAST
        t = _trigger(result, ReasonCode.OVERCAST_RADIATION)
        assert t.measured == 80.0
        assert t.threshold == 150.0
        assert t.margin == -70.0
        assert t.unit == "W/m²"

    def test_overcast_cloud_trigger(self, base_input: IntentInput) -> None:
        inp = IntentInput(
            **{**base_input.__dict__, "cloud_coverage": 95.0, "cloud_threshold": 80.0}
        )
        result = evaluate_intent(inp)
        assert result.intent == Intent.INACTIVE_OVERCAST
        t = _trigger(result, ReasonCode.OVERCAST_CLOUD)
        assert t.measured == 95.0
        assert t.threshold == 80.0
        assert t.margin == 15.0
        assert t.unit == "%"

    def test_manual_override_reports_minutes_remaining(
        self, base_input: IntentInput
    ) -> None:
        # now is 12:00, override until 12:47 -> 47 minutes remaining
        until = datetime(2026, 6, 21, 12, 47, tzinfo=UTC)
        inp = IntentInput(**{**base_input.__dict__, "manual_override_until": until})
        result = evaluate_intent(inp)
        assert result.intent == Intent.MANUAL_OVERRIDE
        t = _trigger(result, ReasonCode.MANUAL_OVERRIDE)
        assert t.measured == 47.0
        assert t.unit == "min"
        assert "47" in result.reason

    def test_shading_reports_position(self, base_input: IntentInput) -> None:
        result = evaluate_intent(base_input)
        assert result.intent == Intent.SHADING
        t = _trigger(result, ReasonCode.SHADING)
        assert t.measured == round(result.position, 1)
        assert t.unit == "%"
