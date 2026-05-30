"""Geometry engine -- pure functions for cover position calculation.

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
        # Oblique sun (gamma > 90 deg) -- blind_height clips to 0, full extension needed
        return 100.0

    blind_height = min(max((distance / cos_gamma) * math.tan(sol_elev), 0.0), h_win)
    a_angle = math.pi / 2.0 - sol_elev
    c_angle = sol_elev + awn_angle

    if abs(math.sin(c_angle)) < 1e-9:
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
        bidirectional: True for 0-180 deg range, False for 0-90 deg.

    Returns:
        Position percentage (0 = flat/open, 100 = fully closed).
    """
    sol_elev = math.radians(sol_elev_deg)
    gamma = math.radians(gamma_deg)

    cos_gamma = math.cos(gamma)
    if abs(cos_gamma) < 1e-9:
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
