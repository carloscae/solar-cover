"""Invariant sweep for the geometry formulas.

A focused, property-style re-audit: rather than hand-picking a few cases, sweep a
dense grid of physically plausible inputs and assert the contract that every
caller relies on -- the result is always a finite float in [0, 100] and the
function never raises. Complements the representative cases in test_geometry.py.
"""

from __future__ import annotations

import math

import pytest

from custom_components.solar_cover.geometry import (
    horizontal_position,
    tilt_position,
    vertical_position,
)

# Solar elevations from below the horizon up to zenith; the gates only call
# geometry above the elevation threshold, but the formulas must stay total
# across the whole range. Gammas span the full half-plane the FOV can admit.
_ELEVATIONS = [float(e) for e in range(-10, 91, 5)]
_GAMMAS = [float(g) for g in range(-179, 180, 7)]


def _ok(value: float) -> bool:
    return isinstance(value, float) and math.isfinite(value) and 0.0 <= value <= 100.0


class TestVerticalInvariants:
    @pytest.mark.parametrize("distance", [0.1, 1.0, 2.5, 5.0])
    @pytest.mark.parametrize("h_win", [0.5, 2.5, 5.0])
    def test_in_range_across_grid(self, distance: float, h_win: float) -> None:
        for elev in _ELEVATIONS:
            for gamma in _GAMMAS:
                result = vertical_position(
                    sol_elev_deg=elev,
                    gamma_deg=gamma,
                    distance=distance,
                    h_win=h_win,
                )
                assert _ok(result), (elev, gamma, distance, h_win, result)

    def test_monotonic_non_decreasing_in_elevation(self) -> None:
        # At gamma=0 the blind height is distance*tan(elev), strictly increasing
        # until it clips to the window height -- so position is non-decreasing.
        prev = -1.0
        for elev in [float(e) for e in range(0, 90, 2)]:
            result = vertical_position(
                sol_elev_deg=elev, gamma_deg=0.0, distance=1.0, h_win=2.5
            )
            assert result >= prev - 1e-9, (elev, result, prev)
            prev = result

    def test_zero_window_height_is_total(self) -> None:
        # Defensive guard: no ZeroDivisionError, returns the degenerate default.
        assert (
            vertical_position(sol_elev_deg=45.0, gamma_deg=0.0, distance=1.0, h_win=0.0)
            == 100.0
        )


class TestHorizontalInvariants:
    @pytest.mark.parametrize("awn_length", [0.5, 3.0, 10.0])
    @pytest.mark.parametrize("awn_angle", [0.0, 15.0, 45.0])
    @pytest.mark.parametrize("h_win", [0.5, 2.5, 5.0])
    def test_in_range_across_grid(
        self, awn_length: float, awn_angle: float, h_win: float
    ) -> None:
        for elev in _ELEVATIONS:
            for gamma in _GAMMAS:
                result = horizontal_position(
                    sol_elev_deg=elev,
                    gamma_deg=gamma,
                    h_win=h_win,
                    awn_length=awn_length,
                    awn_angle_deg=awn_angle,
                    distance=1.0,
                )
                assert _ok(result), (elev, gamma, awn_length, awn_angle, h_win, result)

    def test_past_90_off_axis_is_retracted(self) -> None:
        # cos_gamma <= 0 branch -- continuous with the formula's limit, returns 0.
        for gamma in [90.0, 95.0, 130.0, 179.0]:
            assert (
                horizontal_position(
                    sol_elev_deg=30.0,
                    gamma_deg=gamma,
                    h_win=2.5,
                    awn_length=3.0,
                    awn_angle_deg=15.0,
                    distance=1.0,
                )
                == 0.0
            )


class TestTiltInvariants:
    @pytest.mark.parametrize("bidirectional", [False, True])
    @pytest.mark.parametrize(
        ("width", "spacing"),
        [(80.0, 50.0), (80.0, 80.0), (200.0, 20.0), (25.0, 25.0)],
    )
    def test_in_range_across_grid(
        self, bidirectional: bool, width: float, spacing: float
    ) -> None:
        # Config enforces spacing <= width (ratio <= 1), so the discriminant is
        # always non-negative; the formula must still stay in range everywhere.
        for elev in _ELEVATIONS:
            for gamma in _GAMMAS:
                result = tilt_position(
                    sol_elev_deg=elev,
                    gamma_deg=gamma,
                    slat_width_mm=width,
                    slat_spacing_mm=spacing,
                    bidirectional=bidirectional,
                )
                assert _ok(result), (elev, gamma, width, spacing, bidirectional, result)

    def test_bidirectional_is_half_of_single_when_unclamped(self) -> None:
        for elev in [20.0, 25.0, 30.0, 35.0]:
            single = tilt_position(
                sol_elev_deg=elev,
                gamma_deg=0.0,
                slat_width_mm=80.0,
                slat_spacing_mm=50.0,
                bidirectional=False,
            )
            bidi = tilt_position(
                sol_elev_deg=elev,
                gamma_deg=0.0,
                slat_width_mm=80.0,
                slat_spacing_mm=50.0,
                bidirectional=True,
            )
            if 0.0 < single < 100.0:
                assert bidi == pytest.approx(single / 2.0, abs=0.1), elev
