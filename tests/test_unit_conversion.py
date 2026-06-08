"""Tests for weather unit conversion helpers in the coordinator.

Weather entities report wind/temperature in their own units; the integration's
thresholds are canonically km/h and °C. These guards ensure measured values are
converted before comparison, which is the difference between covers retracting
at the right wind speed and at a third of it.
"""

from __future__ import annotations

import pytest

from custom_components.solar_cover.coordinator import _temp_to_celsius, _wind_to_kmh


class TestWindToKmh:
    def test_kmh_passthrough(self) -> None:
        assert _wind_to_kmh(40, "km/h") == pytest.approx(40)

    def test_missing_unit_assumes_kmh(self) -> None:
        # No unit reported -> assume already canonical, do not silently rescale.
        assert _wind_to_kmh(40, None) == pytest.approx(40)

    def test_ms_converts_to_kmh(self) -> None:
        # 10 m/s == 36 km/h. This is the bug that prompted the fix: a raw
        # comparison would have treated 10 m/s as 10 km/h.
        assert _wind_to_kmh(10, "m/s") == pytest.approx(36.0)

    def test_mph_converts_to_kmh(self) -> None:
        assert _wind_to_kmh(10, "mph") == pytest.approx(16.0934, rel=1e-3)

    def test_none_value_returns_none(self) -> None:
        assert _wind_to_kmh(None, "m/s") is None

    def test_non_numeric_returns_none(self) -> None:
        assert _wind_to_kmh("calm", "m/s") is None

    def test_unknown_unit_falls_back_to_raw(self) -> None:
        assert _wind_to_kmh(40, "furlongs/fortnight") == pytest.approx(40)


class TestTempToCelsius:
    def test_celsius_passthrough(self) -> None:
        assert _temp_to_celsius(5, "°C") == pytest.approx(5)

    def test_missing_unit_assumes_celsius(self) -> None:
        assert _temp_to_celsius(5, None) == pytest.approx(5)

    def test_fahrenheit_converts(self) -> None:
        # 41 °F == 5 °C.
        assert _temp_to_celsius(41, "°F") == pytest.approx(5.0)

    def test_none_value_returns_none(self) -> None:
        assert _temp_to_celsius(None, "°F") is None

    def test_non_numeric_returns_none(self) -> None:
        assert _temp_to_celsius("warm", "°F") is None
