"""Coordinator -- one per Cover Zone.

Runs on a 5-minute timer and on weather entity state_changed events.
Computes sun position, evaluates intent, applies hysteresis, commands entities.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ATTACH_HEIGHT,
    CONF_AWN_ANGLE,
    CONF_AWN_LENGTH,
    CONF_AZIMUTH,
    CONF_CLOUD_ENTITY,
    CONF_CLOUD_THRESHOLD,
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
    CONF_OVERRIDE_DURATION,
    CONF_OVERRIDE_DURATION_OVERRIDE,
    CONF_RADIATION_ENTITY,
    CONF_RADIATION_THRESHOLD,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_STABILITY_DELAY,
    CONF_STABILITY_DELAY_ON_RECOVERY,
    CONF_STABILITY_DELAY_ON_WORSENING,
    CONF_TILT_RANGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_THRESHOLD,
    CONF_WINDOW_HEIGHT,
    DEFAULT_HYSTERESIS,
    DEFAULT_INACTIVE_POSITION,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_STABILITY_DELAY,
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
_COMMAND_DEBOUNCE_SECONDS = 30


def zone_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Shared device descriptor for every entity belonging to a zone."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Solar Cover",
    )


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
        reason: str,
        reason_detail: list[dict[str, Any]],
        stability_pending_until: str | None,
        pending_intent: str | None,
        manual_override_until: str | None,
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
        self.reason = reason
        self.reason_detail = reason_detail
        self.stability_pending_until = stability_pending_until
        self.pending_intent = pending_intent
        self.manual_override_until = manual_override_until


class SolarCoverCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator for a single Cover Zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        zone_data: dict[str, Any],
        integration_data: dict[str, Any],
        solar_engine: SolarEngine,
        entry_id: str = "",
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
        self._last_intent: Intent | None = None
        self._last_computed_position: float | None = None
        self._last_reason: str = ""
        self._last_triggers: list[dict[str, Any]] = []
        self._pending_intent: Intent | None = None
        self._pending_since: datetime | None = None
        self._enabled: bool = True
        self._manual_override_until: datetime | None = None
        self._unsub_sensors: Any = None
        self._unsub_covers: Any = None
        self._last_command_time: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"solar_cover.{entry_id}")

        watch = [
            e
            for e in (
                integration_data.get(CONF_WEATHER_ENTITY),
                integration_data.get(CONF_CLOUD_ENTITY),
                integration_data.get(CONF_RADIATION_ENTITY),
            )
            if e
        ]
        if watch:
            self._unsub_sensors = async_track_state_change_event(
                hass, watch, self._on_sensor_change
            )

    @callback
    def _on_sensor_change(self, event: Any) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    @property
    def _stability_delay(self) -> int:
        """Configured stability delay in minutes (0 = feature disabled)."""
        return int(self._integration.get(CONF_STABILITY_DELAY, DEFAULT_STABILITY_DELAY))

    def _get_override_duration(self) -> int:
        """Return the manual override duration in minutes from config."""
        return int(
            self._zone.get(
                CONF_OVERRIDE_DURATION_OVERRIDE,
                self._integration.get(
                    CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION
                ),
            )
        )

    @property
    def enabled(self) -> bool:
        """Return whether automation is active for this zone."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable automation. Triggers an immediate coordinator refresh."""
        self._enabled = enabled
        # Drop any in-flight stability hold so re-enabling starts from a clean slate.
        self._clear_pending()
        self.hass.async_create_task(self.async_request_refresh())

    def _clear_pending(self) -> None:
        """Drop any in-flight stability hold."""
        self._pending_intent = None
        self._pending_since = None

    async def async_restore_state(self) -> None:
        """Load persisted last-commanded position from storage."""
        data = await self._store.async_load()
        if data and "last_commanded" in data:
            self._last_commanded = float(data["last_commanded"])

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

        if weather_state:
            attrs = weather_state.attributes
            wind_speed = attrs.get("wind_speed")
            outdoor_temp = attrs.get("temperature")
            if weather_state.state not in ("unavailable", "unknown"):
                raining = weather_state.state in (
                    "rainy",
                    "pouring",
                    "snowy",
                    "lightning-rainy",
                )

        cloud_coverage: float | None = self._read_sensor(
            self._integration.get(CONF_CLOUD_ENTITY)
        )
        radiation: float | None = self._read_sensor(
            self._integration.get(CONF_RADIATION_ENTITY)
        )

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
            cloud_coverage=cloud_coverage,
            cloud_threshold=self._integration.get(CONF_CLOUD_THRESHOLD),
            radiation=radiation,
            radiation_threshold=self._integration.get(CONF_RADIATION_THRESHOLD),
            manual_override_until=self._manual_override_until,
            now=now,
            cover_type=CoverType(self._zone[CONF_COVER_TYPE]),
            window_height=self._zone.get(CONF_WINDOW_HEIGHT, 2.5),
            glare_depth=self._zone.get(CONF_GLARE_DEPTH, 1.0),
            attach_height=self._zone.get(CONF_ATTACH_HEIGHT, 2.5),
            awn_length=self._zone.get(CONF_AWN_LENGTH, 3.0),
            awn_angle_deg=self._zone.get(CONF_AWN_ANGLE, 15.0),
            slat_width_mm=self._zone.get(CONF_SLAT_WIDTH, 80.0),
            slat_spacing_mm=self._zone.get(CONF_SLAT_SPACING, 50.0),
            tilt_range=TiltRange(self._zone.get(CONF_TILT_RANGE, TiltRange.SINGLE)),
        )

        result = evaluate_intent(inp)
        intent = result.intent
        computed_pos = result.position

        # Resolve final position
        inactive_pos = self._zone.get(
            CONF_INACTIVE_POSITION_OVERRIDE,
            self._integration.get(CONF_INACTIVE_POSITION, DEFAULT_INACTIVE_POSITION),
        )
        raw_position: float = (
            computed_pos
            if intent == Intent.SHADING and computed_pos is not None
            else float(inactive_pos)
        )

        # Apply min/max clamp -- only when shading; inactive rest position is unclamped
        min_pos = self._zone.get(CONF_MIN_POSITION)
        max_pos = self._zone.get(CONF_MAX_POSITION)
        clamped: float = raw_position
        if intent == Intent.SHADING:
            if min_pos is not None:
                clamped = max(clamped, float(min_pos))
            if max_pos is not None:
                clamped = min(clamped, float(max_pos))

        # Apply hysteresis -- skip only when intent is unchanged AND delta is small
        hysteresis = float(
            self._zone.get(
                CONF_HYSTERESIS,
                self._integration.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
            )
        )

        # Stability delay: an intent change is only acted on once the new intent
        # has held continuously for the configured number of minutes. This damps
        # cover oscillation on partly-cloudy or gusty days where sensors flip
        # across a threshold repeatedly.
        prev_committed = self._last_intent
        should_commit = self._evaluate_stability(intent, now)

        if should_commit:
            intent_changed = intent != prev_committed
            self._last_intent = intent
            self._last_computed_position = computed_pos
            self._last_reason = result.reason
            self._last_triggers = [t.to_dict() for t in result.triggers]
            last = self._last_commanded
            delta: float | None = abs(clamped - last) if last is not None else None

            # Only command covers when: automation enabled, sun is above the
            # horizon, and either intent changed or the position shift exceeds
            # hysteresis. Suppressing commands below the horizon prevents an HA
            # restart at night from re-opening covers the user closed manually.
            # While a manual override is in effect the user owns the position --
            # hold whatever they last set and never drive to the inactive rest
            # position, otherwise the override would be silently undone.
            above_horizon = sol_el > 0
            if (
                self._enabled
                and above_horizon
                and intent != Intent.MANUAL_OVERRIDE
                and (delta is None or delta >= hysteresis or intent_changed)
            ):
                await self._command_covers(clamped)
                self._last_commanded = clamped
                await self._store.async_save({"last_commanded": clamped})

        # Expose the last committed intent/position/reason -- a pending candidate
        # that has not held long enough is internal state only. The reason must
        # track the committed intent so the two never disagree on the panel.
        effective_intent: Intent = (
            self._last_intent if self._last_intent is not None else intent
        )
        effective_computed: float | None = (
            computed_pos if should_commit else self._last_computed_position
        )
        # _last_reason / _last_triggers were already updated to the current
        # result inside the should_commit block, so they hold the committed
        # values in both branches -- no need to re-serialise here.
        effective_reason: str = self._last_reason
        effective_triggers: list[dict[str, Any]] = self._last_triggers
        commanded: float = (
            self._last_commanded if self._last_commanded is not None else clamped
        )

        # Timer visibility: when a stability hold is active, surface when the
        # pending change will commit and what it is; otherwise None.
        stability_pending_until: str | None = None
        pending_intent: str | None = None
        if self._pending_since is not None:
            stability_pending_until = (
                self._pending_since + timedelta(minutes=self._stability_delay)
            ).isoformat()
            pending_intent = (
                str(self._pending_intent) if self._pending_intent is not None else None
            )

        manual_until = self._manual_override_until
        manual_override_until: str | None = (
            manual_until.isoformat()
            if manual_until is not None and now < manual_until
            else None
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
            intent=effective_intent,
            computed_position=effective_computed,
            commanded_position=commanded,
            sun_azimuth=sol_az,
            sun_elevation=sol_el,
            gamma=gamma,
            position_curve=[dict(s) for s in curve],
            fov_entry=entry.isoformat() if entry else None,
            fov_exit=exit_.isoformat() if exit_ else None,
            reason=effective_reason,
            reason_detail=effective_triggers,
            stability_pending_until=stability_pending_until,
            pending_intent=pending_intent,
            manual_override_until=manual_override_until,
        )

    def _evaluate_stability(self, new_intent: Intent, now: datetime) -> bool:
        """Decide whether ``new_intent`` should be acted on now.

        Returns True to commit (and clears pending state), False to hold the
        last committed intent until the candidate has persisted long enough.
        Mutates ``_pending_intent`` / ``_pending_since`` as a side effect.
        """
        if new_intent == self._last_intent:
            self._pending_intent = None
            self._pending_since = None
            return True

        delay = self._stability_delay
        if delay <= 0:
            self._pending_intent = None
            self._pending_since = None
            return True

        direction = self._classify_transition(new_intent)
        delay_on_worsening = bool(
            self._integration.get(CONF_STABILITY_DELAY_ON_WORSENING, True)
        )
        delay_on_recovery = bool(
            self._integration.get(CONF_STABILITY_DELAY_ON_RECOVERY, True)
        )
        delay_applies = (direction == "worsening" and delay_on_worsening) or (
            direction == "recovery" and delay_on_recovery
        )
        if not delay_applies:
            self._pending_intent = None
            self._pending_since = None
            return True

        # Measure time since we first diverged from the committed intent, not
        # since this specific candidate appeared. A different candidate of the
        # same delayed direction (e.g. overcast then wind, both "worsening" from
        # SHADING) keeps the clock running so alternating sensors cannot pin the
        # hold open forever. The clock only resets when we return to the
        # committed intent (handled by the equality branch above).
        if self._pending_since is None:
            self._pending_since = now
        self._pending_intent = new_intent
        if now - self._pending_since >= timedelta(minutes=delay):
            self._pending_intent = None
            self._pending_since = None
            return True
        return False

    def _classify_transition(self, new_intent: Intent) -> str:
        """Classify an intent transition as worsening, recovery, or other."""
        last = self._last_intent
        inactive = (
            Intent.INACTIVE_SUN_LOW,
            Intent.INACTIVE_OUTSIDE_FOV,
            Intent.INACTIVE_WEATHER,
            Intent.INACTIVE_OVERCAST,
        )
        if last == Intent.SHADING and new_intent in inactive:
            return "worsening"
        if (
            last in (Intent.INACTIVE_OVERCAST, Intent.INACTIVE_WEATHER)
            and new_intent == Intent.SHADING
        ):
            return "recovery"
        return "other"

    def _read_sensor(self, entity_id: str | None) -> float | None:
        """Read a numeric sensor state; return None if unavailable or not configured."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

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
        self._last_command_time = datetime.now(tz=UTC)

    def clear_manual_override(self) -> None:
        self._manual_override_until = None
        self._clear_pending()
        self.hass.async_create_task(self.async_request_refresh())

    def async_setup_cover_listeners(self) -> None:
        """Subscribe to state-changed events on the zone's physical cover entities.

        Called once after the first coordinator refresh so _last_commanded is
        already populated and the listener has a valid baseline to compare against.
        """
        entities = self._zone.get(CONF_COVER_ENTITIES, [])
        if not entities:
            return
        self._unsub_covers = async_track_state_change_event(
            self.hass, entities, self._handle_cover_state_change
        )

    def cancel_cover_listeners(self) -> None:
        """Unsubscribe the physical cover state listeners."""
        if self._unsub_covers is not None:
            self._unsub_covers()
            self._unsub_covers = None

    def cancel_sensor_listeners(self) -> None:
        """Unsubscribe the weather/cloud/radiation state listeners."""
        if self._unsub_sensors is not None:
            self._unsub_sensors()
            self._unsub_sensors = None

    @callback
    def _handle_cover_state_change(self, event: Any) -> None:
        """Detect external cover moves and set a manual override automatically.

        Filters out:
        - Covers that are still travelling (is_opening / is_closing attributes)
        - State echoes from coordinator's own commands (30-second debounce window)
        - Position changes smaller than hysteresis (noise / rounding)
        - Events while automation is disabled
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Skip unavailable / unknown states -- current_position attribute is unreliable.
        if new_state.state in ("unavailable", "unknown"):
            return

        if not self._enabled:
            return

        # Skip while the cover is still travelling to a commanded position.
        attrs = new_state.attributes
        if attrs.get("is_opening") or attrs.get("is_closing"):
            return

        # Debounce: ignore state echoes that arrive shortly after a coordinator command.
        now = datetime.now(tz=UTC)
        elapsed = (
            (now - self._last_command_time).total_seconds()
            if self._last_command_time is not None
            else None
        )
        if elapsed is not None and elapsed < _COMMAND_DEBOUNCE_SECONDS:
            return

        try:
            new_pos = float(attrs.get("current_position", 0))
        except (TypeError, ValueError):
            return

        last = self._last_commanded
        if last is None:
            return

        hysteresis = float(
            self._zone.get(
                CONF_HYSTERESIS,
                self._integration.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
            )
        )
        if abs(new_pos - last) < hysteresis:
            return

        # External move confirmed -- set a manual override.
        until = now + timedelta(minutes=self._get_override_duration())
        self._manual_override_until = until
        self._clear_pending()
        self._last_commanded = new_pos
        self.hass.async_create_task(self._store.async_save({"last_commanded": new_pos}))
        self.hass.async_create_task(self.async_request_refresh())

    def reset_timers(self) -> None:
        """Clear both the stability hold and the manual override.

        After this the current live evaluation takes effect on the next refresh
        -- no waiting out a stability delay or a manual hold. Dropping the
        committed intent (``_last_intent``) as well is essential: clearing only
        the pending state would let the next refresh immediately re-open a fresh
        hold for the same still-pending transition (it is still a "worsening"/
        "recovery" change relative to the old committed intent), which would
        merely restart the delay. With no committed intent the next transition
        classifies as "other" and commits at once.
        """
        self._clear_pending()
        self._last_intent = None
        self._manual_override_until = None
        self.hass.async_create_task(self.async_request_refresh())
