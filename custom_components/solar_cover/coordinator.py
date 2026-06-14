"""Coordinator -- one per Cover Zone.

Runs on a 5-minute timer and on weather entity state_changed events.
Computes sun position, evaluates intent, applies hysteresis, commands entities.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.unit_conversion import SpeedConverter, TemperatureConverter

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
from .solar import gamma as compute_gamma

_LOGGER = logging.getLogger(__name__)

_COVER_DOMAIN = "cover"
_SERVICE_SET_COVER_POSITION = "set_cover_position"
_SERVICE_SET_COVER_TILT_POSITION = "set_cover_tilt_position"
_COMMAND_DEBOUNCE_SECONDS = 30


def _wind_to_kmh(value: Any, unit: str | None) -> float | None:
    """Convert a weather entity's wind speed to km/h (the canonical unit).

    The wind threshold the user configures is in km/h, but weather entities
    report ``wind_speed`` in their own ``wind_speed_unit`` (often m/s or mph).
    Comparing the two without converting silently retracts covers at the wrong
    speed. Falls back to the raw value if the unit is missing or unknown.
    """
    if value is None:
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return None
    if not unit or unit == UnitOfSpeed.KILOMETERS_PER_HOUR:
        return speed
    try:
        return SpeedConverter.convert(speed, unit, UnitOfSpeed.KILOMETERS_PER_HOUR)
    except (HomeAssistantError, ValueError):
        return speed


def _temp_to_celsius(value: Any, unit: str | None) -> float | None:
    """Convert a weather entity's temperature to °C (the canonical unit).

    The minimum-temperature threshold is in °C; weather entities report
    ``temperature`` in their own ``temperature_unit``. Falls back to the raw
    value if the unit is missing or unknown.
    """
    if value is None:
        return None
    try:
        temp = float(value)
    except (TypeError, ValueError):
        return None
    if not unit or unit == UnitOfTemperature.CELSIUS:
        return temp
    try:
        return TemperatureConverter.convert(temp, unit, UnitOfTemperature.CELSIUS)
    except (HomeAssistantError, ValueError):
        return temp


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
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{zone_data.get('name', 'zone')}",
            config_entry=config_entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        entry_id = config_entry.entry_id
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
        # The user's manual target, remembered so it can be restored if a
        # transient weather retraction overwrites _last_commanded mid-override.
        self._manual_position: float | None = None
        self._unsub_sensors: Any = None
        self._unsub_covers: Any = None
        self._last_command_time: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"solar_cover.{entry_id}")
        # Serialises the mutate-and-command section of _async_update_data so a
        # burst of sensor state_changed events (each scheduling a refresh) cannot
        # interleave mutations of _last_commanded / _pending_since.
        self._update_lock = asyncio.Lock()

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

    def restore_enabled(self, value: bool) -> None:
        """Set the enabled flag without triggering a refresh.

        Used by the switch entity to restore its persisted on/off state during
        startup, where firing a refresh (and re-commanding covers) would be
        wrong. Unlike :meth:`set_enabled` this is a pure state assignment and
        does not touch the stability hold.
        """
        self._enabled = value

    def _clear_pending(self) -> None:
        """Drop any in-flight stability hold."""
        self._pending_intent = None
        self._pending_since = None

    def _store_payload(self) -> dict[str, Any]:
        """Build the persisted-state payload.

        ``last_commanded`` survives a restart so a night-time reboot does not
        re-open a manually-closed cover. ``manual_position`` and
        ``manual_override_until`` survive too, so a restart mid-override does not
        silently drop the user's manual hold.
        """
        return {
            "last_commanded": self._last_commanded,
            "manual_position": self._manual_position,
            "manual_override_until": (
                self._manual_override_until.isoformat()
                if self._manual_override_until is not None
                else None
            ),
        }

    async def async_restore_state(self) -> None:
        """Load persisted last-commanded position and manual override from storage."""
        data = await self._store.async_load()
        if not data:
            return
        if data.get("last_commanded") is not None:
            self._last_commanded = float(data["last_commanded"])
        if data.get("manual_position") is not None:
            self._manual_position = float(data["manual_position"])
        until_raw = data.get("manual_override_until")
        if until_raw is not None:
            until = datetime.fromisoformat(until_raw)
            # Drop an override that already expired while HA was down -- restoring
            # a stale hold would needlessly suppress automation after a reboot.
            if until > datetime.now(tz=UTC):
                self._manual_override_until = until
            else:
                self._manual_position = None

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
            wind_speed = _wind_to_kmh(
                attrs.get("wind_speed"), attrs.get("wind_speed_unit")
            )
            outdoor_temp = _temp_to_celsius(
                attrs.get("temperature"), attrs.get("temperature_unit")
            )
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
        #
        # Serialise the mutate-and-command section: a burst of sensor
        # state_changed events each schedule a refresh, and interleaving their
        # mutations of _last_commanded / _pending_since here would corrupt the
        # stability state machine and re-issue conflicting commands.
        async with self._update_lock:
            prev_committed = self._last_intent
            should_commit = self._evaluate_stability(intent, now)

            if should_commit:
                intent_changed = intent != prev_committed
                self._last_intent = intent
                self._last_computed_position = computed_pos
                self._last_reason = result.reason
                self._last_triggers = [t.to_dict() for t in result.triggers]
                last = self._last_commanded

                # Resolve the target position for this intent. During a manual
                # override the user owns the position: the target is their
                # remembered manual setting, re-asserted only if it has drifted
                # (e.g. a transient weather retraction earlier in the override
                # window moved the cover off the manual position). We never drive
                # to the inactive rest position while an override holds.
                if intent == Intent.MANUAL_OVERRIDE:
                    target = self._manual_position
                    needs_command = (
                        target is not None
                        and last is not None
                        and abs(target - last) >= hysteresis
                    )
                else:
                    target = clamped
                    delta = abs(clamped - last) if last is not None else None
                    needs_command = (
                        delta is None or delta >= hysteresis or intent_changed
                    )

                # Suppressing commands below the horizon prevents an HA restart
                # at night from re-opening covers the user closed manually. A
                # manual override is exempt: restoring the user's explicit
                # position (e.g. after a transient weather retraction cleared)
                # must work regardless of the sun, and it only fires when the
                # position has actually drifted.
                above_horizon = sol_el > 0
                allow_command = above_horizon or intent == Intent.MANUAL_OVERRIDE
                if (
                    self._enabled
                    and allow_command
                    and target is not None
                    and needs_command
                ):
                    # Only record the new position when the command actually
                    # succeeded. Recording a failed move as committed would let
                    # hysteresis suppress every retry, stranding the cover.
                    if await self._command_covers(target):
                        self._last_commanded = target
                        await self._store.async_save(self._store_payload())

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

        # Safety wins immediately: a transition into the weather-retract intent
        # must never wait out the stability window. Holding a genuine high-wind
        # or rain retraction would defeat the protection the gate exists for.
        if new_intent == Intent.INACTIVE_WEATHER:
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

    def _is_tilt(self) -> bool:
        """Whether this zone drives venetian slat tilt rather than position."""
        return CoverType(self._zone[CONF_COVER_TYPE]) == CoverType.TILT

    async def _command_covers(self, position: float) -> bool:
        """Command the zone's covers. Return True on success (or no-op), False if
        the service call failed -- the caller uses this to decide whether to record
        the new position as committed."""
        entities = self._zone.get(CONF_COVER_ENTITIES, [])
        if not entities:
            # Observe-only zone: nothing to move, but the computed position is
            # still the intended one, so treat it as a successful no-op.
            return True
        # Venetian blinds expose the slat angle on a separate axis: the geometry
        # output is a tilt percentage, so it must be sent via set_cover_tilt_position.
        # Sending it as a position would raise/lower the blind instead of angling it.
        if self._is_tilt():
            service = _SERVICE_SET_COVER_TILT_POSITION
            data = {ATTR_ENTITY_ID: entities, "tilt_position": round(position)}
        else:
            service = _SERVICE_SET_COVER_POSITION
            data = {ATTR_ENTITY_ID: entities, "position": round(position)}
        # Stamp the command time before the call so the 30-second echo debounce
        # in _handle_cover_state_change covers the resulting state change even if
        # the service call is slow. If the call fails, clear the stamp again: a
        # failed command produces no echo, so leaving the debounce window open
        # would swallow a real manual move toward the failed target.
        self._last_command_time = datetime.now(tz=UTC)
        try:
            await self.hass.services.async_call(
                _COVER_DOMAIN, service, data, blocking=True
            )
        except HomeAssistantError as err:
            self._last_command_time = None
            _LOGGER.warning(
                "Failed to command covers %s to %d%%: %s",
                entities,
                round(position),
                err,
            )
            return False
        return True

    def clear_manual_override(self) -> None:
        self._manual_override_until = None
        self._manual_position = None
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
        - Position changes smaller than hysteresis (noise / rounding)
        - State echoes from coordinator's own commands: changes within the
          30-second debounce window that are also within a coasting margin
          (2 × hysteresis) of the commanded position. A large divergence from
          the commanded position is treated as an immediate manual countermand
          and sets an override even within the debounce window.
        - Events while automation is disabled
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Skip unavailable / unknown states -- the position attribute is unreliable.
        if new_state.state in ("unavailable", "unknown"):
            return

        if not self._enabled:
            return

        # Skip while the cover is still travelling to a commanded position.
        attrs = new_state.attributes
        if attrs.get("is_opening") or attrs.get("is_closing"):
            return

        # Read the axis this zone actually drives: slat tilt for venetian
        # blinds, otherwise the cover position.
        pos_attr = "current_tilt_position" if self._is_tilt() else "current_position"

        # Read position before the debounce check so we can distinguish a
        # genuine echo (position near commanded) from an immediate manual
        # countermand (position far from commanded).
        raw_pos = attrs.get(pos_attr)
        if raw_pos is None:
            return
        try:
            new_pos = float(raw_pos)
        except (TypeError, ValueError):
            return

        hysteresis = float(
            self._zone.get(
                CONF_HYSTERESIS,
                self._integration.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
            )
        )
        now = datetime.now(tz=UTC)
        elapsed = (
            (now - self._last_command_time).total_seconds()
            if self._last_command_time is not None
            else None
        )
        in_debounce = elapsed is not None and elapsed < _COMMAND_DEBOUNCE_SECONDS

        last = self._last_commanded
        if last is None:
            # No baseline yet (e.g. HA restarted at night with the sun below the
            # threshold all morning, so the coordinator never commanded a
            # position). A genuine external move still deserves an override --
            # dropping it would silently ignore the user's remote. The only
            # echo we could see here is one inside the post-command debounce
            # window, so suppress that and adopt anything else.
            if in_debounce:
                return
        else:
            delta = abs(new_pos - last)
            if delta < hysteresis:
                return

            # Debounce: suppress echoes of a coordinator command that arrive
            # shortly after the command. Only suppress when the delta is also
            # within a coasting margin (2 × hysteresis) -- a motor coasting a few
            # percent past the target is still an echo. A move well outside that
            # margin is a genuine immediate countermand and must set an override
            # right away.
            if in_debounce and delta < hysteresis * 2:
                return

        # External move confirmed -- set a manual override and remember the
        # position the user chose, so it can be restored if a transient weather
        # retraction moves the cover off it before the override expires.
        until = now + timedelta(minutes=self._get_override_duration())
        self._manual_override_until = until
        self._manual_position = new_pos
        self._clear_pending()
        self._last_commanded = new_pos
        self.hass.async_create_task(self._store.async_save(self._store_payload()))
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
        self._manual_position = None
        self.hass.async_create_task(self.async_request_refresh())


# A zone config entry carries its coordinator on runtime_data. Integration
# (global-settings) entries do not set runtime_data.
type SolarCoverConfigEntry = ConfigEntry[SolarCoverCoordinator]
