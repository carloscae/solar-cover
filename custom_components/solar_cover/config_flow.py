"""Config flow for Solar Cover - integration step then zone step."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.selector import NumberSelectorMode

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
    CONF_INACTIVE_POSITION,
    CONF_MIN_TEMP,
    CONF_OVERRIDE_DURATION,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_TILT_RANGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_THRESHOLD,
    CONF_WINDOW_HEIGHT,
    DEFAULT_ELEVATION_THRESHOLD_FACTOR,
    DEFAULT_INACTIVE_POSITION,
    DEFAULT_OVERRIDE_DURATION,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    CoverType,
    TiltRange,
)


def _auto_elevation_threshold(hass_config: Any) -> float:
    """Compute elevation threshold from home latitude."""
    lat: float = float(getattr(hass_config, "latitude", 48.0))
    return round((90.0 - abs(lat)) * DEFAULT_ELEVATION_THRESHOLD_FACTOR, 1)


class SolarCoverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step config flow: integration (global) then zone."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Route to integration step or zone step depending on existing entries."""
        existing = [
            e
            for e in self._async_current_entries()
            if e.data.get("entry_type") == ENTRY_TYPE_INTEGRATION
        ]
        if existing:
            return await self.async_step_zone()
        return await self.async_step_integration()

    async def async_step_integration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle integration-level (global) settings."""
        if user_input is not None:
            data = {
                "entry_type": ENTRY_TYPE_INTEGRATION,
                **user_input,
            }
            return self.async_create_entry(title="Solar Cover", data=data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_WIND_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=50,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m/s",
                    )
                ),
                vol.Optional(CONF_MIN_TEMP): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-20,
                        max=30,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="C",
                    )
                ),
                vol.Optional(
                    CONF_INACTIVE_POSITION, default=DEFAULT_INACTIVE_POSITION
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=1,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional(
                    CONF_OVERRIDE_DURATION, default=DEFAULT_OVERRIDE_DURATION
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=15,
                        max=480,
                        step=15,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="integration", data_schema=schema)

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle zone-level settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cover_type = user_input.get(CONF_COVER_TYPE)
            if cover_type == CoverType.TILT:
                slat_width = float(user_input.get(CONF_SLAT_WIDTH, 80.0))
                slat_spacing = float(user_input.get(CONF_SLAT_SPACING, 50.0))
                if slat_spacing > slat_width:
                    errors[CONF_SLAT_SPACING] = "spacing_exceeds_width"

            if not errors:
                data = {
                    "entry_type": ENTRY_TYPE_ZONE,
                    **user_input,
                }
                title = str(user_input.get("name", "Cover Zone"))
                return self.async_create_entry(title=title, data=data)

        auto_threshold = _auto_elevation_threshold(self.hass.config)
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required(CONF_COVER_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="cover", multiple=True)
                ),
                vol.Required(CONF_COVER_TYPE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[e.value for e in CoverType],
                        translation_key=CONF_COVER_TYPE,
                    )
                ),
                vol.Required(CONF_AZIMUTH, default=180): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=359,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="deg",
                    )
                ),
                vol.Required(CONF_FOV_LEFT, default=90): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=180,
                        step=1,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="deg",
                    )
                ),
                vol.Required(CONF_FOV_RIGHT, default=90): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=180,
                        step=1,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="deg",
                    )
                ),
                vol.Required(
                    CONF_ELEVATION_THRESHOLD, default=auto_threshold
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=45,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="deg",
                    )
                ),
                vol.Optional(CONF_WINDOW_HEIGHT, default=2.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=5.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m",
                    )
                ),
                vol.Optional(CONF_GLARE_DEPTH, default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=5.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m",
                    )
                ),
                vol.Optional(
                    CONF_ATTACH_HEIGHT, default=2.5
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=5.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m",
                    )
                ),
                vol.Optional(CONF_AWN_LENGTH, default=3.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=10.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m",
                    )
                ),
                vol.Optional(CONF_AWN_ANGLE, default=15): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=45,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="deg",
                    )
                ),
                vol.Optional(CONF_SLAT_WIDTH, default=80): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20,
                        max=200,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Optional(CONF_SLAT_SPACING, default=50): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=200,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Optional(
                    CONF_TILT_RANGE, default=TiltRange.SINGLE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[e.value for e in TiltRange]
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="zone", data_schema=schema, errors=errors
        )
