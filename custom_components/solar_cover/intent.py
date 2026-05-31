"""Intent model -- sequential gate returning intent + computed position.

No HA imports permitted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import CoverType, Intent, ReasonCode, TiltRange
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


@dataclass
class ReasonTrigger:
    """One condition that contributed to the current intent.

    ``measured`` / ``threshold`` / ``margin`` are the live value, the limit it
    was tested against, and ``measured - threshold`` (signed: how far over or
    under). ``text`` is a human phrase; ``unit`` annotates the numbers.
    """

    code: ReasonCode
    text: str
    measured: float | None = None
    threshold: float | None = None
    unit: str = ""
    margin: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict for entity attributes."""
        return {
            "code": str(self.code),
            "text": self.text,
            "measured": self.measured,
            "threshold": self.threshold,
            "unit": self.unit,
            "margin": self.margin,
        }


@dataclass
class IntentResult:
    """Outcome of the gate model: intent, position, and the reasons behind it."""

    intent: Intent
    position: float | None
    reason: str
    triggers: list[ReasonTrigger] = field(default_factory=list)


def _round(value: float) -> float:
    return round(value, 1)


def _num(value: float) -> str:
    """Format a number for human text, rounded to match the structured fields.

    Rounds to one decimal (like ``_round``) then drops trailing zeros, so the
    reason sentence never disagrees with the ``measured``/``threshold`` numbers
    (45.0 -> '45', 12.53 -> '12.5').
    """
    return f"{_round(value):g}"


def evaluate_intent(inp: IntentInput) -> IntentResult:
    """Run the sequential gate model and return an :class:`IntentResult`.

    Gates evaluated in order:
    1. Weather safety -- rain, high wind, or low temperature force retraction.
       All active conditions are reported, not just the first one.
    2. Manual override -- user has taken manual control. Holds against the
       comfort gates below, but loses to weather safety above so wind/rain can
       still retract for protection.
    3. Elevation -- is sun high enough to shade?
    4. FOV -- is sun in front of this opening?
    5. Overcast -- is solar radiation/cloud coverage too high to bother shading?
    6. Shading -- compute geometry position.
    """
    # Gate 1: weather safety -- must win over manual override. Collect every
    # active trigger so the user sees all the limits they crossed.
    weather = _weather_triggers(inp)
    if weather:
        joined = "; ".join(t.text for t in weather)
        return IntentResult(
            Intent.INACTIVE_WEATHER, None, f"Retracted (weather): {joined}", weather
        )

    # Gate 2: manual override -- holds the user's position against comfort gates
    if inp.manual_override_until is not None and inp.now < inp.manual_override_until:
        mins = _round((inp.manual_override_until - inp.now).total_seconds() / 60)
        trigger = ReasonTrigger(
            code=ReasonCode.MANUAL_OVERRIDE,
            text=f"holding for {_num(mins)} more min",
            measured=mins,
            unit="min",
        )
        return IntentResult(
            Intent.MANUAL_OVERRIDE, None, f"Manual override: {trigger.text}", [trigger]
        )

    # Gate 3: elevation
    if inp.sol_elev_deg <= inp.elevation_threshold:
        margin = _round(inp.sol_elev_deg - inp.elevation_threshold)
        trigger = ReasonTrigger(
            code=ReasonCode.SUN_LOW,
            text=(
                f"elevation {_num(inp.sol_elev_deg)}° is below the "
                f"{_num(inp.elevation_threshold)}° threshold "
                f"({_num(abs(margin))}° to go)"
            ),
            measured=_round(inp.sol_elev_deg),
            threshold=_round(inp.elevation_threshold),
            unit="°",
            margin=margin,
        )
        return IntentResult(
            Intent.INACTIVE_SUN_LOW,
            None,
            f"Idle (sun too low): {trigger.text}",
            [trigger],
        )

    # Gate 4: FOV
    gamma = _gamma(inp.win_azimuth_deg, inp.sol_azimuth_deg)
    if not (gamma < inp.fov_left and gamma > -inp.fov_right):
        # Positive gamma = sun to the left; negative = sun to the right. Report
        # the off-axis magnitude against the (positive) edge limit so measured,
        # threshold, and margin all stay on the same scale as the text.
        if gamma >= inp.fov_left:
            code, edge, limit = ReasonCode.FOV_LEFT, "left", inp.fov_left
        else:
            code, edge, limit = ReasonCode.FOV_RIGHT, "right", inp.fov_right
        off_axis = _round(abs(gamma))
        limit = _round(limit)
        margin = _round(off_axis - limit)
        # At the exact boundary the sun sits *on* the edge, not past it
        # (the FOV gate uses strict inequalities), so margin is 0 -> say "at".
        position_word = "past" if margin > 0 else "at"
        trigger = ReasonTrigger(
            code=code,
            text=(
                f"sun {_num(off_axis)}° off-axis, "
                f"{position_word} the {_num(limit)}° {edge} edge"
            ),
            measured=off_axis,
            threshold=limit,
            unit="°",
            margin=margin,
        )
        return IntentResult(
            Intent.INACTIVE_OUTSIDE_FOV,
            None,
            f"Idle (out of view): {trigger.text}",
            [trigger],
        )

    # Gate 5: overcast / low radiation -- radiation wins when both are configured
    overcast = _overcast_trigger(inp)
    if overcast is not None:
        return IntentResult(
            Intent.INACTIVE_OVERCAST,
            None,
            f"Idle (overcast): {overcast.text}",
            [overcast],
        )

    # Gate 6: shading -- compute position
    position = _compute_position(inp, gamma)
    trigger = ReasonTrigger(
        code=ReasonCode.SHADING,
        text=(
            f"sun {_num(inp.sol_elev_deg)}° elevation, "
            f"{_num(abs(gamma))}° off-axis, target {_num(position)}%"
        ),
        measured=_round(position),
        unit="%",
    )
    return IntentResult(Intent.SHADING, position, f"Shading: {trigger.text}", [trigger])


def _weather_triggers(inp: IntentInput) -> list[ReasonTrigger]:
    """Collect every active weather-safety trigger (rain, wind, cold)."""
    triggers: list[ReasonTrigger] = []
    if inp.raining:
        triggers.append(ReasonTrigger(code=ReasonCode.WEATHER_RAIN, text="raining"))
    if (
        inp.wind_speed is not None
        and inp.wind_threshold is not None
        and inp.wind_speed > inp.wind_threshold
    ):
        triggers.append(
            ReasonTrigger(
                code=ReasonCode.WEATHER_WIND,
                text=(
                    f"wind {_num(inp.wind_speed)} km/h exceeds "
                    f"{_num(inp.wind_threshold)} km/h limit"
                ),
                measured=_round(inp.wind_speed),
                threshold=_round(inp.wind_threshold),
                unit="km/h",
                margin=_round(inp.wind_speed - inp.wind_threshold),
            )
        )
    if (
        inp.outdoor_temp is not None
        and inp.min_temp is not None
        and inp.outdoor_temp < inp.min_temp
    ):
        triggers.append(
            ReasonTrigger(
                code=ReasonCode.WEATHER_COLD,
                text=(
                    f"temperature {_num(inp.outdoor_temp)}°C below "
                    f"{_num(inp.min_temp)}°C minimum"
                ),
                measured=_round(inp.outdoor_temp),
                threshold=_round(inp.min_temp),
                unit="°C",
                margin=_round(inp.outdoor_temp - inp.min_temp),
            )
        )
    return triggers


def _overcast_trigger(inp: IntentInput) -> ReasonTrigger | None:
    """Return the overcast trigger, if any. Radiation wins when both configured."""
    if inp.radiation is not None and inp.radiation_threshold is not None:
        if inp.radiation < inp.radiation_threshold:
            return ReasonTrigger(
                code=ReasonCode.OVERCAST_RADIATION,
                text=(
                    f"radiation {_num(inp.radiation)} W/m² below "
                    f"{_num(inp.radiation_threshold)} W/m² threshold"
                ),
                measured=_round(inp.radiation),
                threshold=_round(inp.radiation_threshold),
                unit="W/m²",
                margin=_round(inp.radiation - inp.radiation_threshold),
            )
        # Radiation configured and OK -- fall through; cloud may still block.
    if inp.cloud_coverage is not None and inp.cloud_threshold is not None:
        if inp.cloud_coverage > inp.cloud_threshold:
            return ReasonTrigger(
                code=ReasonCode.OVERCAST_CLOUD,
                text=(
                    f"cloud cover {_num(inp.cloud_coverage)}% exceeds "
                    f"{_num(inp.cloud_threshold)}% threshold"
                ),
                measured=_round(inp.cloud_coverage),
                threshold=_round(inp.cloud_threshold),
                unit="%",
                margin=_round(inp.cloud_coverage - inp.cloud_threshold),
            )
    return None


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
