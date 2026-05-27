"""Unit tests for geometry.py -- pure functions, no HA needed."""

import pytest

from custom_components.solar_cover.geometry import (
    horizontal_position,
    tilt_position,
    vertical_position,
)


class TestVerticalPosition:
    def test_midday_summer(self) -> None:
        # Sun at 60 deg elevation, gamma=0 (dead center), protect 1m depth, 2.5m window
        result = vertical_position(
            sol_elev_deg=60.0, gamma_deg=0.0, distance=1.0, h_win=2.5
        )
        # blind_height = (1.0 / cos(0)) * tan(60 deg) = 1 * 1.732 = 1.732m
        # -> 1.732/2.5*100 ~= 69.3%
        assert abs(result - 69.3) < 0.5

    def test_low_elevation_winter(self) -> None:
        # Sun at 15 deg elevation, gamma=0, protect 1m, 2.5m window
        result = vertical_position(
            sol_elev_deg=15.0, gamma_deg=0.0, distance=1.0, h_win=2.5
        )
        # blind_height = tan(15 deg) ~= 0.268m -> 10.7%
        assert abs(result - 10.7) < 0.5

    def test_gamma_near_90_returns_100(self) -> None:
        # gamma=89 deg -- sun nearly at edge of FOV, cos(89 deg) is very small
        # -> clip to h_win -> 100%
        result = vertical_position(
            sol_elev_deg=30.0, gamma_deg=89.0, distance=1.0, h_win=2.0
        )
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        # Very low elevation -- blind_height clips to 0
        result = vertical_position(
            sol_elev_deg=1.0, gamma_deg=0.0, distance=0.1, h_win=2.5
        )
        assert 0.0 <= result <= 100.0

    def test_gamma_above_90_returns_100(self) -> None:
        # gamma > 90 deg triggers the cos_gamma <= 0 guard directly
        result = vertical_position(
            sol_elev_deg=30.0, gamma_deg=91.0, distance=1.0, h_win=2.0
        )
        assert result == 100.0


class TestHorizontalPosition:
    def test_midday_summer(self) -> None:
        # Sun at 30 deg, gamma=0, h_win=2.5m, awn_length=3m,
        # awn_angle=15 deg, distance=0.5m
        # blind_height = (0.5 / cos(0)) * tan(30) = 0.5 * 0.577 = 0.289m
        # a_angle = 90 - 30 = 60 deg, c_angle = 30 + 15 = 45 deg
        # length = (2.5 - 0.289) * sin(60) / sin(45) = 2.211 * 0.866 / 0.707 = 2.709m
        # result = min(2.709 / 3.0 * 100, 100) ~= 90.3%
        result = horizontal_position(
            sol_elev_deg=30.0,
            gamma_deg=0.0,
            h_win=2.5,
            awn_length=3.0,
            awn_angle_deg=15.0,
            distance=0.5,
        )
        assert abs(result - 90.3) < 1.0

    def test_low_elevation_winter_clips(self) -> None:
        # Low elevation sun -- adaptive-cover bug was returning >100% here
        result = horizontal_position(
            sol_elev_deg=10.0,
            gamma_deg=0.0,
            h_win=2.5,
            awn_length=3.0,
            awn_angle_deg=15.0,
            distance=2.0,
        )
        assert 0.0 <= result <= 100.0

    def test_gamma_near_90_returns_100(self) -> None:
        result = horizontal_position(
            sol_elev_deg=30.0,
            gamma_deg=91.0,
            h_win=2.5,
            awn_length=3.0,
            awn_angle_deg=15.0,
            distance=2.0,
        )
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        # Verify clip is active (the adaptive-cover bug was missing this)
        result = horizontal_position(
            sol_elev_deg=5.0,
            gamma_deg=0.0,
            h_win=3.0,
            awn_length=2.0,
            awn_angle_deg=10.0,
            distance=5.0,
        )
        assert 0.0 <= result <= 100.0

    def test_zero_c_angle_returns_0(self) -> None:
        # sol_elev=0 + awn_angle=0 -> c_angle=0 -> sin(c_angle)=0.0 -> return 0.0
        result = horizontal_position(
            sol_elev_deg=0.0,
            gamma_deg=0.0,
            h_win=2.5,
            awn_length=3.0,
            awn_angle_deg=0.0,
            distance=1.0,
        )
        assert result == 0.0


class TestTiltPosition:
    def test_midday_summer(self) -> None:
        # Sun at 60 deg, gamma=0, 80mm slat, 50mm spacing, single range
        result = tilt_position(
            sol_elev_deg=60.0,
            gamma_deg=0.0,
            slat_width_mm=80.0,
            slat_spacing_mm=50.0,
            bidirectional=False,
        )
        assert 0.0 <= result <= 100.0

    def test_bidirectional_range(self) -> None:
        # Bidirectional should produce exactly half the single-direction % for
        # same geometry. sol_elev=30 gives single ~97% (not clamped), so the
        # half-range relationship holds.
        single = tilt_position(
            sol_elev_deg=30.0,
            gamma_deg=0.0,
            slat_width_mm=80.0,
            slat_spacing_mm=50.0,
            bidirectional=False,
        )
        bidi = tilt_position(
            sol_elev_deg=30.0,
            gamma_deg=0.0,
            slat_width_mm=80.0,
            slat_spacing_mm=50.0,
            bidirectional=True,
        )
        assert bidi == pytest.approx(single / 2.0, abs=0.1)

    def test_negative_discriminant_returns_100(self) -> None:
        # Discriminant < 0 when slat_spacing > slat_width (ratio > 1).
        # With spacing=100mm and width=50mm (ratio=2), discriminant is strongly
        # negative at any realistic elevation -> formula returns 100% (fully closed).
        result = tilt_position(
            sol_elev_deg=2.0,
            gamma_deg=0.0,
            slat_width_mm=50.0,
            slat_spacing_mm=100.0,
            bidirectional=False,
        )
        assert result == 100.0

    def test_result_clamped_0_to_100(self) -> None:
        result = tilt_position(
            sol_elev_deg=45.0,
            gamma_deg=0.0,
            slat_width_mm=80.0,
            slat_spacing_mm=50.0,
            bidirectional=False,
        )
        assert 0.0 <= result <= 100.0

    def test_gamma_90_returns_100(self) -> None:
        # gamma=90 deg exactly -> cos_gamma ~= 6e-17, abs < 1e-9 guard fires -> 100%
        result = tilt_position(
            sol_elev_deg=30.0,
            gamma_deg=90.0,
            slat_width_mm=80.0,
            slat_spacing_mm=50.0,
            bidirectional=False,
        )
        assert result == 100.0
