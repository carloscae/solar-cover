"""Coordinator -- one per Cover Zone.

Runs on a 5-minute timer and on weather entity state_changed events.
Computes sun position, evaluates intent, applies hysteresis, commands entities.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class CoverSnapshot:
    """Per-cover slice of the coordinator snapshot, one per configured cover."""

    commanded_position: float
    manual_override_until: str | None
    intent: Intent


class _SolarCoverStore(Store[dict[str, Any]]):
    """Persisted per-cover override state for a zone (schema version 2).

    v1 stored a single zone-wide scalar override that was never tied to a
    specific entity_id, so it cannot be reattached in a multi-cover zone. Any
    pre-v2 payload migrates to no active overrides -- this is transient runtime
    state, not user configuration.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate an older stored payload to the current per-cover shape."""
        if old_major_version < 2:
            return {"covers": {}}
        return old_data


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
        covers: dict[str, CoverSnapshot] | None = None,
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
        self.covers = covers if covers is not None else {}


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
        # Override-related state is per cover, keyed by cover entity_id. Shared
        # automatic intent and the stability clock stay zone-level below.
        self._last_commanded: dict[str, float] = {}
        self._last_intent: Intent | None = None
        self._last_computed_position: float | None = None
        self._last_reason: str = ""
        self._last_triggers: list[dict[str, Any]] = []
        self._pending_intent: Intent | None = None
        self._pending_since: datetime | None = None
        self._enabled: bool = True
        self._manual_override_until: dict[str, datetime] = {}
        # The user's manual target per cover, remembered so it can be restored
        # if a transient weather retraction overwrites _last_commanded mid-hold.
        self._manual_position: dict[str, float] = {}
        self._unsub_sensors: Any = None
        self._unsub_covers: Any = None
        # Per cover: answers "did we recently command THIS cover?" A shared stamp
        # would open a false debounce window on an uncommanded sibling.
        self._last_command_time: dict[str, datetime] = {}
        self._store: Store[dict[str, Any]] = _SolarCoverStore(
            hass, 2, f"solar_cover.{entry_id}"
        )
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

    @property
    def cover_entities(self) -> list[str]:
        """The configured physical cover entity_ids for this zone."""
        return list(self._zone.get(CONF_COVER_ENTITIES, []))

    def _hysteresis(self) -> float:
        """Resolve the effective hysteresis (zone override, else global, else
        default)."""
        return float(
            self._zone.get(
                CONF_HYSTERESIS,
                self._integration.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
            )
        )

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
        """Build the persisted per-cover state payload.

        Each configured cover's ``last_commanded`` survives a restart so a
        night-time reboot does not re-open a manually-closed cover;
        ``manual_position``/``manual_override_until`` survive so a restart
        mid-hold does not silently drop the user's manual hold.
        """
        covers: dict[str, Any] = {}
        for eid in self.cover_entities:
            until = self._manual_override_until.get(eid)
            covers[eid] = {
                "last_commanded": self._last_commanded.get(eid),
                "manual_position": self._manual_position.get(eid),
                "manual_override_until": (
                    until.isoformat() if until is not None else None
                ),
            }
        return {"covers": covers}

    async def async_restore_state(self) -> None:
        """Load persisted per-cover state; prune keys no longer configured."""
        data = await self._store.async_load()
        if not data:
            return
        stored = data.get("covers", {})
        configured = set(self.cover_entities)
        now = datetime.now(tz=UTC)
        pruned = False
        for eid, cover in stored.items():
            if eid not in configured:
                # A cover dropped from cover_entities: do not rehydrate it, and
                # re-save below so the stale key does not linger forever.
                pruned = True
                continue
            last = cover.get("last_commanded")
            if last is not None:
                self._last_commanded[eid] = float(last)
            until_raw = cover.get("manual_override_until")
            if until_raw is not None:
                until = datetime.fromisoformat(until_raw)
                # Drop a hold that already expired while HA was down.
                if until > now:
                    self._manual_override_until[eid] = until
                    manual = cover.get("manual_position")
                    if manual is not None:
                        self._manual_position[eid] = float(manual)
        if pruned:
            await self._store.async_save(self._store_payload())

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

        # Always evaluate the PURE automatic intent: pass manual_override_until
        # =None so intent.py never returns MANUAL_OVERRIDE. Override handling is
        # entirely in the per-cover resolver below.
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
            manual_override_until=None,
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
        auto_intent = result.intent
        computed_pos = result.position

        inactive_pos = self._zone.get(
            CONF_INACTIVE_POSITION_OVERRIDE,
            self._integration.get(CONF_INACTIVE_POSITION, DEFAULT_INACTIVE_POSITION),
        )
        raw_position: float = (
            computed_pos
            if auto_intent == Intent.SHADING and computed_pos is not None
            else float(inactive_pos)
        )

        min_pos = self._zone.get(CONF_MIN_POSITION)
        max_pos = self._zone.get(CONF_MAX_POSITION)
        auto_target: float = raw_position
        if auto_intent == Intent.SHADING:
            if min_pos is not None:
                auto_target = max(auto_target, float(min_pos))
            if max_pos is not None:
                auto_target = min(auto_target, float(max_pos))

        hysteresis = self._hysteresis()

        async with self._update_lock:
            prev_committed = self._last_intent
            should_commit = self._evaluate_stability(auto_intent, now)
            intent_changed = auto_intent != prev_committed
            if should_commit:
                self._last_intent = auto_intent
                self._last_computed_position = computed_pos
                self._last_reason = result.reason
                self._last_triggers = [t.to_dict() for t in result.triggers]

            above_horizon = sol_el > 0

            # Per-cover target resolution. Weather safety first (unconditionally),
            # then an active per-cover hold (restore path), then automatic.
            targets: dict[str, float] = {}
            for eid in self.cover_entities:
                last = self._last_commanded.get(eid)
                held_until = self._manual_override_until.get(eid)
                held = held_until is not None and now < held_until
                if auto_intent == Intent.INACTIVE_WEATHER:
                    # Retract for safety regardless of the hold; do NOT clear the
                    # hold -- it resumes once weather clears.
                    target = auto_target
                    needs = (
                        last is None
                        or abs(target - last) >= hysteresis
                        or intent_changed
                    )
                    allow = above_horizon and should_commit
                elif held:
                    manual = self._manual_position.get(eid)
                    if manual is None:
                        continue
                    target = manual
                    # Re-assert only if it drifted (e.g. an earlier weather
                    # retraction moved this cover off the manual position). The
                    # restore is exempt from below-horizon and stability gating.
                    needs = last is not None and abs(manual - last) >= hysteresis
                    allow = True
                else:
                    target = auto_target
                    delta = abs(auto_target - last) if last is not None else None
                    needs = delta is None or delta >= hysteresis or intent_changed
                    allow = above_horizon and should_commit
                if self._enabled and allow and needs:
                    targets[eid] = target

            if targets:
                failed = await self._command_covers(targets)
                if len(failed) < len(targets):
                    await self._store.async_save(self._store_payload())

        effective_intent: Intent = (
            self._last_intent if self._last_intent is not None else auto_intent
        )
        effective_computed: float | None = (
            computed_pos if should_commit else self._last_computed_position
        )
        effective_reason: str = self._last_reason
        effective_triggers: list[dict[str, Any]] = self._last_triggers

        # Zone-level aggregation: report MANUAL_OVERRIDE only when EVERY configured
        # cover is currently held; otherwise the shared automatic value.
        configured = self.cover_entities
        all_held = bool(configured) and all(
            (self._manual_override_until.get(eid) is not None)
            and (now < self._manual_override_until[eid])
            for eid in configured
        )
        zone_intent = Intent.MANUAL_OVERRIDE if all_held else effective_intent
        zone_reason = "Manual override" if all_held else effective_reason
        zone_triggers: list[dict[str, Any]] = [] if all_held else effective_triggers

        # Per-cover snapshot.
        covers_snapshot: dict[str, CoverSnapshot] = {}
        for eid in configured:
            until = self._manual_override_until.get(eid)
            held = until is not None and now < until
            cmd = self._last_commanded.get(eid)
            covers_snapshot[eid] = CoverSnapshot(
                commanded_position=cmd if cmd is not None else auto_target,
                manual_override_until=(
                    until.isoformat() if held and until is not None else None
                ),
                intent=Intent.MANUAL_OVERRIDE if held else effective_intent,
            )

        # Transitional zone-level commanded_position / manual_override_until,
        # derived from the first configured cover. Removed in the sensor task
        # once the sensors read the per-cover snapshot directly.
        first = configured[0] if configured else None
        zone_commanded: float = (
            self._last_commanded.get(first, auto_target)
            if first is not None
            else auto_target
        )
        zone_manual_until: str | None = None
        if first is not None:
            first_until = self._manual_override_until.get(first)
            if first_until is not None and now < first_until:
                zone_manual_until = first_until.isoformat()

        stability_pending_until: str | None = None
        pending_intent: str | None = None
        if self._pending_since is not None:
            stability_pending_until = (
                self._pending_since + timedelta(minutes=self._stability_delay)
            ).isoformat()
            pending_intent = (
                str(self._pending_intent) if self._pending_intent is not None else None
            )

        curve = self._solar.hourly_curve(now.date())
        entry, exit_ = self._solar.fov_window(
            azimuth_deg=float(win_az),
            fov_left=float(self._zone[CONF_FOV_LEFT]),
            fov_right=float(self._zone[CONF_FOV_RIGHT]),
            date_=now.date(),
        )

        return CoordinatorData(
            intent=zone_intent,
            computed_position=effective_computed,
            commanded_position=zone_commanded,
            sun_azimuth=sol_az,
            sun_elevation=sol_el,
            gamma=gamma,
            position_curve=[dict(s) for s in curve],
            fov_entry=entry.isoformat() if entry else None,
            fov_exit=exit_.isoformat() if exit_ else None,
            reason=zone_reason,
            reason_detail=zone_triggers,
            stability_pending_until=stability_pending_until,
            pending_intent=pending_intent,
            manual_override_until=zone_manual_until,
            covers=covers_snapshot,
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

    async def _command_covers(self, targets: dict[str, float]) -> set[str]:
        """Command each cover to its target, grouped by rounded position.

        Returns the set of entity_ids whose service call failed (empty on full
        success or a no-op). Commits ``_last_commanded`` and stamps
        ``_last_command_time`` for EVERY entity up front, before the first
        group's await, so a genuine manual move landing during an earlier
        group's await is not silently overwritten when a later group is sent.
        """
        if not targets:
            return set()

        now = datetime.now(tz=UTC)
        prev_commanded: dict[str, float | None] = {}
        for eid, target in targets.items():
            prev_commanded[eid] = self._last_commanded.get(eid)
            self._last_commanded[eid] = target
            self._last_command_time[eid] = now

        groups: dict[int, list[str]] = {}
        for eid, target in targets.items():
            groups.setdefault(round(target), []).append(eid)

        is_tilt = self._is_tilt()
        service = (
            _SERVICE_SET_COVER_TILT_POSITION if is_tilt else _SERVICE_SET_COVER_POSITION
        )
        pos_key = "tilt_position" if is_tilt else "position"

        failed: set[str] = set()
        for rounded, eids in groups.items():
            data = {ATTR_ENTITY_ID: eids, pos_key: rounded}
            try:
                await self.hass.services.async_call(
                    _COVER_DOMAIN, service, data, blocking=True
                )
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Failed to command covers %s to %d%%: %s", eids, rounded, err
                )
                for eid in eids:
                    prev = prev_commanded[eid]
                    if prev is None:
                        self._last_commanded.pop(eid, None)
                    else:
                        self._last_commanded[eid] = prev
                    self._last_command_time.pop(eid, None)
                failed.update(eids)
        return failed

    def clear_manual_override(self) -> None:
        """Clear every per-cover manual hold and the zone stability hold."""
        self._manual_override_until.clear()
        self._manual_position.clear()
        self._clear_pending()
        self.hass.async_create_task(self._store.async_save(self._store_payload()))
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
        """Detect an external move of a specific cover and arm its own override.

        Reads the moved cover from ``event.data['entity_id']`` and keys every
        piece of state off it, so a move of one cover never perturbs a sibling.
        Filters out travelling covers, sub-hysteresis noise, own-command echoes
        (30 s debounce + coasting margin), and events while disabled.
        """
        eid = event.data.get("entity_id")
        if eid is None or eid not in self.cover_entities:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state in ("unavailable", "unknown"):
            return
        if not self._enabled:
            return

        attrs = new_state.attributes

        now = datetime.now(tz=UTC)
        stamp = self._last_command_time.get(eid)
        elapsed = (now - stamp).total_seconds() if stamp is not None else None
        in_debounce = elapsed is not None and elapsed < _COMMAND_DEBOUNCE_SECONDS

        # Still travelling: extend only THIS cover's debounce window so a slow
        # motor's final settle is not mis-read as a manual move.
        if new_state.state in ("opening", "closing"):
            if in_debounce:
                self._last_command_time[eid] = now
            return

        pos_attr = "current_tilt_position" if self._is_tilt() else "current_position"
        raw_pos = attrs.get(pos_attr)
        if raw_pos is None:
            return
        try:
            new_pos = float(raw_pos)
        except (TypeError, ValueError):
            return

        hysteresis = self._hysteresis()
        last = self._last_commanded.get(eid)
        if last is None:
            # No baseline for this cover: adopt any move outside the debounce.
            if in_debounce:
                return
        else:
            delta = abs(new_pos - last)
            if delta < hysteresis:
                return
            # A move well outside the coasting margin is an immediate manual
            # countermand and arms even inside the debounce window.
            if in_debounce and delta < hysteresis * 2:
                return

        # External move confirmed for this cover only. The zone stability hold is
        # about the automatic intent that still governs the other covers, so it
        # is deliberately left untouched.
        until = now + timedelta(minutes=self._get_override_duration())
        self._manual_override_until[eid] = until
        self._manual_position[eid] = new_pos
        self._last_commanded[eid] = new_pos
        self.hass.async_create_task(self._store.async_save(self._store_payload()))
        self.hass.async_create_task(self.async_request_refresh())

    def reset_timers(self) -> None:
        """Reset all: clear the zone stability hold, drop the committed intent,
        and clear every per-cover manual override.

        Dropping ``_last_intent`` (not just the pending state) is load-bearing:
        with no committed intent the next transition classifies as "other" and
        commits at once, so the button bypasses (not merely restarts) the
        stability delay.
        """
        self._clear_pending()
        self._last_intent = None
        self._manual_override_until.clear()
        self._manual_position.clear()
        self.hass.async_create_task(self._store.async_save(self._store_payload()))
        self.hass.async_create_task(self.async_request_refresh())

    def reset_cover_override(self, entity_id: str) -> None:
        """Clear only this cover's manual hold.

        Leaves sibling covers and the zone stability hold untouched.
        """
        self._manual_override_until.pop(entity_id, None)
        self._manual_position.pop(entity_id, None)
        self.hass.async_create_task(self._store.async_save(self._store_payload()))
        self.hass.async_create_task(self.async_request_refresh())


# A zone config entry carries its coordinator on runtime_data. Integration
# (global-settings) entries do not set runtime_data.
type SolarCoverConfigEntry = ConfigEntry[SolarCoverCoordinator]
