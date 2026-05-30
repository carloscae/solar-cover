"""Intent model -- sequential gate returning intent + computed position.

No HA imports permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    fov_left: float
    fov_right: float
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
    # Overcast / radiation sensors (both optional)
    cloud_coverage: float | None = None
    cloud_threshold: float | None = None
    radiation: float | None = None
    radiation_threshold: float | None = None
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
    1. Elevation -- is sun high enough to shade?
    2. FOV -- is sun in front of this opening?
    3. Weather -- are conditions safe for deployment?
    4. Overcast -- is solar radiation/cloud coverage too high to bother shading?
    5. Manual override -- has user taken manual control?
    6. Shading -- compute geometry position.
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

    # Gate 4: overcast / low radiation -- radiation wins when both are configured
    if inp.radiation is not None and inp.radiation_threshold is not None:
        if inp.radiation < inp.radiation_threshold:
            return Intent.INACTIVE_OVERCAST, None
    if inp.cloud_coverage is not None and inp.cloud_threshold is not None:
        if inp.cloud_coverage > inp.cloud_threshold:
            return Intent.INACTIVE_OVERCAST, None

    # Gate 5: manual override
    if inp.manual_override_until is not None and inp.now < inp.manual_override_until:
        return Intent.MANUAL_OVERRIDE, None

    # Gate 6: shading -- compute position
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
