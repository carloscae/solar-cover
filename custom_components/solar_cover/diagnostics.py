"""Diagnostics support for Solar Cover."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import ENTRY_TYPE_ZONE
from .coordinator import SolarCoverConfigEntry

# The home's exact coordinates are the only sensitive data this integration
# touches; everything else (geometry, thresholds, sun angles) is safe to share.
TO_REDACT = {"latitude", "longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarCoverConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    diagnostics: dict[str, Any] = {
        "entry_type": entry.data.get("entry_type", ENTRY_TYPE_ZONE),
        "title": entry.title,
        "data": dict(entry.data),
        "options": dict(entry.options),
        "home": {
            "latitude": hass.config.latitude,
            "longitude": hass.config.longitude,
            "elevation": hass.config.elevation,
            "time_zone": hass.config.time_zone,
        },
    }

    # Only zone entries carry a coordinator on runtime_data.
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None and coordinator.data is not None:
        d = coordinator.data
        diagnostics["state"] = {
            "intent": d.intent.value,
            "reason": d.reason,
            "reason_detail": d.reason_detail,
            "computed_position": d.computed_position,
            "commanded_position": d.commanded_position,
            "sun_elevation": d.sun_elevation,
            "sun_azimuth": d.sun_azimuth,
            "surface_azimuth": d.gamma,
            "fov_entry": d.fov_entry,
            "fov_exit": d.fov_exit,
            "stability_pending_until": d.stability_pending_until,
            "pending_intent": d.pending_intent,
            "manual_override_until": d.manual_override_until,
        }
        diagnostics["enabled"] = coordinator.enabled
        diagnostics["last_update_success"] = coordinator.last_update_success

    return async_redact_data(diagnostics, TO_REDACT)
