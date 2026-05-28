"""Unit tests for solar.py -- uses real astral library, no HA needed."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.solar_cover.solar import SolarEngine


@pytest.fixture
def vienna_engine() -> SolarEngine:
    # Vienna: lat=48.2, lon=16.4, elevation=170m
    return SolarEngine(lat=48.2, lon=16.4, elev=170.0)


class TestSunPosition:
    def test_summer_noon_high_elevation(self, vienna_engine: SolarEngine) -> None:
        # 2026-06-21 11:00 UTC = ~13:00 Vienna time
        dt = datetime(2026, 6, 21, 11, 0, tzinfo=UTC)
        az, el = vienna_engine.sun_position(dt)
        assert 160 < az < 200  # roughly south
        assert 60 < el < 70  # high elevation in summer

    def test_winter_noon_low_elevation(self, vienna_engine: SolarEngine) -> None:
        # 2026-12-21 11:00 UTC = ~12:00 Vienna time
        dt = datetime(2026, 12, 21, 11, 0, tzinfo=UTC)
        az, el = vienna_engine.sun_position(dt)
        assert 150 < az < 220
        assert 15 < el < 25  # low elevation in winter

    def test_negative_elevation_at_night(self, vienna_engine: SolarEngine) -> None:
        dt = datetime(2026, 6, 21, 21, 0, tzinfo=UTC)  # 23:00 Vienna
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
        # North-facing window (0 deg) -- sun never in FOV at 48 deg N in summer
        entry, exit_ = vienna_engine.fov_window(
            azimuth_deg=0, fov_left=45, fov_right=45, date_=date(2026, 6, 21)
        )
        assert entry is None
        assert exit_ is None
