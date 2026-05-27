"""Coordinator -- one per Cover Zone.

Runs on a 5-minute timer and on weather entity state_changed events.
Computes sun position, evaluates intent, applies hysteresis, commands entities.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

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
    CONF_MIN_TEMP,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_TILT_RANGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_THRESHOLD,
    DEFAULT_HYSTERESIS,
    DEFAULT_INACTIVE_POSITION,
    DOMAIN,
    UPDATE_INTERVAL_MINUTES,
    CoverType,
    Intent,
    TiltRange,
)
from .intent import IntentInput, evaluate_intent
from .solar import SolarEngine
from .solar import _gamma as compute_gamma

_LOGGER = logging.getLogger(__name__)

_COVER_DOMAIN = "cover"
_SERVICE_SET_COVER_POSITION = "set_cover_position"


class CoordinatorData:
    """Snapshot of coordinator state, shared with entities as attributes."""

    def __init__(
        self,
        intent: Intent,
        computed_position: float | None,
        commanded_position: float,
        sun_azimuth: float,
        sun_elevation: float,
        gamma: float,
        position_curve: list[dict[str, Any]],
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
        zone_data: dict[str, Any],
        integration_data: dict[str, Any],
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
        self._unsub_weather: Any = None

        weather_entity = integration_data.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            self._unsub_weather = async_track_state_change_event(
                hass, [weather_entity], self._on_weather_change
            )

    @callback
    def _on_weather_change(self, event: Any) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> CoordinatorData:
        now = datetime.now(tz=UTC)
        sol_az, sol_el = self._solar.sun_position(now)

        weather_state = None
        weather_entity = self._integration.get(CONF_WEATHER_ENTITY)
        if weather_entity:
            weather_state = self.hass.states.get(weather_entity)

        raining = False
        wind_speed: float | None = None
        outdoor_temp: float | None = None

        if weather_state and weather_state.state not in ("unavailable", "unknown"):
            raining = weather_state.state in (
                "rainy", "pouring", "snowy", "lightning-rainy"
            )
            attrs = weather_state.attributes
            wind_speed = attrs.get("wind_speed")
            outdoor_temp = attrs.get("temperature")

        win_az = self._zone[CONF_AZIMUTH]
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
        raw_position: float = (
            computed_pos if intent == Intent.SHADING and computed_pos is not None
            else float(inactive_pos)
        )

        # Apply min/max clamp
        min_pos = self._zone.get(CONF_MIN_POSITION)
        max_pos = self._zone.get(CONF_MAX_POSITION)
        clamped: float = raw_position
        if min_pos is not None:
            clamped = max(clamped, float(min_pos))
        if max_pos is not None:
            clamped = min(clamped, float(max_pos))

        # Apply hysteresis -- only command if delta exceeds threshold
        hysteresis = float(self._zone.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS))
        last = self._last_commanded
        delta: float | None = abs(clamped - last) if last is not None else None
        if delta is None or delta >= hysteresis:
            await self._command_covers(clamped)
            self._last_commanded = clamped

        commanded: float = (
            self._last_commanded if self._last_commanded is not None else clamped
        )

        # Build hourly curve for entity attribute
        curve = self._solar.hourly_curve(now.date())

        entry, exit_ = self._solar.fov_window(
            azimuth_deg=float(win_az),
            fov_left=float(self._zone[CONF_FOV_LEFT]),
            fov_right=float(self._zone[CONF_FOV_RIGHT]),
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
            _COVER_DOMAIN,
            _SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entities, "position": round(position)},
            blocking=False,
        )

    def set_manual_override(self, until: datetime) -> None:
        self._manual_override_until = until
        self.hass.async_create_task(self.async_request_refresh())

    def clear_manual_override(self) -> None:
        self._manual_override_until = None
        self.hass.async_create_task(self.async_request_refresh())
