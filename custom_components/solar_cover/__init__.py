"""Solar Cover integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_WIND_THRESHOLD,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
)
from .coordinator import (
    SolarCoverConfigEntry,
    SolarCoverCoordinator,
    cover_slug,
)
from .solar import SolarEngine

_LOGGER = logging.getLogger(__name__)

PLATFORMS_ZONE = ["button", "sensor", "switch"]

# m/s -> km/h. v1 stored wind_threshold under an m/s UI label; v2 makes km/h the
# canonical unit (and converts the measured wind), so legacy values are scaled.
_MS_TO_KMH = 3.6


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry to the current schema version."""
    if entry.version > 2:
        # Downgrade from a newer schema is not supported: a future version may
        # store keys this code does not understand, so refuse rather than risk
        # corrupting them.
        _LOGGER.error(
            "Cannot downgrade Solar Cover config entry %s from schema version %s "
            "to 2; this version of the integration does not support that schema. "
            "Upgrade the integration again or remove and re-add the entry.",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version < 2:
        # v1 -> v2: reinterpret the stored wind threshold from m/s to km/h so an
        # existing user's intent (the value they typed under the old m/s label)
        # is preserved rather than silently treated as a much lower km/h limit.
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        for store in (new_data, new_options):
            value = store.get(CONF_WIND_THRESHOLD)
            if value is not None:
                store[CONF_WIND_THRESHOLD] = round(float(value) * _MS_TO_KMH, 1)
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2
        )

    return True


def _integration_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return the merged global settings from the integration config entry.

    Read live from the integration entry rather than cached in ``hass.data`` so
    a zone reload always picks up the current global settings (the cascade in
    ``_async_update_integration_listener`` reloads zones on a global change).
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("entry_type") == ENTRY_TYPE_INTEGRATION:
            return {**entry.data, **entry.options}
    return {}


def _async_cleanup_legacy_cover_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """One-time migration: remove now-obsolete per-cover devices.

    Before per-cover entities were aggregated onto the shared zone device,
    each configured cover got its own HA device (identifier
    ``f"{entry_id}_{cover_slug(eid)}"``, nested under the zone device). Their
    entities move to the zone device automatically on upgrade (unique_id is
    unchanged), but HA does not delete a device just because it lost its last
    entity -- left alone, every existing install would keep an empty ghost
    device per cover forever, which is exactly the clutter the aggregation
    was meant to remove. Idempotent: a no-op once the ghosts are gone.
    """
    dev_reg = dr.async_get(hass)
    zone_identifier = entry.entry_id
    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier != zone_identifier:
                dev_reg.async_remove_device(device.id)
                break


def _async_cleanup_stale_cover_entities(
    hass: HomeAssistant, entry: ConfigEntry, cover_entities: list[str]
) -> None:
    """Remove per-cover entities for covers no longer in ``cover_entities``.

    Per-cover entities live on the shared zone device (not their own device),
    so there is no device to cascade-remove them. Their unique_id is
    ``f"{entry_id}_{cover_slug(eid)}_{key}"``; HA does not auto-remove entities
    dropped from a config entry's ``async_add_entities``, so a cover removed
    from the zone would otherwise leave orphaned entities in the registry.
    """
    ent_reg = er.async_get(hass)
    valid_prefixes = tuple(
        f"{entry.entry_id}_{cover_slug(eid)}_" for eid in cover_entities
    )
    stale_marker = f"{entry.entry_id}_cover_"
    for entity in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        uid = entity.unique_id
        if uid.startswith(stale_marker) and not uid.startswith(valid_prefixes):
            ent_reg.async_remove(entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        if entry.title != "Global Settings":
            hass.config_entries.async_update_entry(entry, title="Global Settings")
        entry.async_on_unload(
            entry.add_update_listener(_async_update_integration_listener)
        )
        return True

    # Zone entry
    zone_data = {**entry.data, **entry.options}
    zone_name = zone_data.get("name", "Cover Zone")
    expected_title = f"Zone: {zone_name}"
    if entry.title != expected_title:
        hass.config_entries.async_update_entry(entry, title=expected_title)
    solar = SolarEngine(
        lat=hass.config.latitude,
        lon=hass.config.longitude,
        elev=hass.config.elevation,
    )

    coordinator = SolarCoverCoordinator(
        hass=hass,
        zone_data=zone_data,
        integration_data=_integration_data(hass),
        solar_engine=solar,
        config_entry=entry,
    )
    await coordinator.async_restore_state()
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_cover_listeners()
    entry.async_on_unload(coordinator.cancel_cover_listeners)
    entry.async_on_unload(coordinator.cancel_sensor_listeners)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ZONE)
    _async_cleanup_legacy_cover_devices(hass, entry)
    _async_cleanup_stale_cover_entities(
        hass, entry, list(zone_data.get("cover_entities", []))
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        return True

    # Zone entry: unload platforms. runtime_data is dropped automatically and
    # listeners registered with async_on_unload are cancelled by the framework.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS_ZONE)


async def _async_update_listener(
    hass: HomeAssistant, entry: SolarCoverConfigEntry
) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_update_integration_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload integration entry and all zone entries when global options change.

    Zone coordinators hold a snapshot of integration_data at construction time.
    Without this cascade, changing the weather entity (or cloud/radiation sensors)
    in global settings would be silently ignored by running zone coordinators.
    """
    await hass.config_entries.async_reload(entry.entry_id)
    for zone_entry in hass.config_entries.async_entries(DOMAIN):
        if zone_entry.data.get("entry_type", ENTRY_TYPE_ZONE) == ENTRY_TYPE_ZONE:
            try:
                await hass.config_entries.async_reload(zone_entry.entry_id)
            except Exception:  # noqa: BLE001 -- resilience: one bad zone must not
                # strand every other zone on stale global settings. Log and move on.
                _LOGGER.exception(
                    "Failed to reload zone entry %s after a global settings change; "
                    "continuing with the remaining zones",
                    zone_entry.entry_id,
                )
