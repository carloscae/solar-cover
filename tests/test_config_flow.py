"""Config flow integration tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.const import (
    CONF_AZIMUTH,
    CONF_COVER_ENTITIES,
    CONF_COVER_TYPE,
    CONF_ELEVATION_THRESHOLD,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_GLARE_DEPTH,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_WINDOW_HEIGHT,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    CoverType,
)

ZONE_INPUT = {
    "name": "South Terrace",
    CONF_COVER_ENTITIES: ["cover.terrace_awning"],
    CONF_COVER_TYPE: CoverType.VERTICAL,
    CONF_AZIMUTH: 180,
    CONF_FOV_LEFT: 90,
    CONF_FOV_RIGHT: 90,
    CONF_ELEVATION_THRESHOLD: 27.0,
    CONF_WINDOW_HEIGHT: 2.5,
    CONF_GLARE_DEPTH: 1.0,
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:  # noqa: PT004
    """Activate the custom component loader for every test in this module."""


@pytest.fixture
def integration_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": ENTRY_TYPE_INTEGRATION},
        title="Solar Cover",
    )
    entry.add_to_hass(hass)
    return entry


class TestIntegrationStep:
    async def test_shows_integration_form_when_no_entry_exists(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "integration"

    async def test_creates_integration_entry(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["entry_type"] == ENTRY_TYPE_INTEGRATION


class TestZoneStep:
    async def test_shows_zone_form_when_integration_exists(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "zone"

    async def test_creates_zone_entry(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        with patch(
            "custom_components.solar_cover.coordinator.SolarCoverCoordinator"
            ".async_config_entry_first_refresh",
            return_value=None,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "user"}
            )
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=ZONE_INPUT
            )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result2["data"][CONF_AZIMUTH] == 180

    async def test_tilt_spacing_validation(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        bad_input = {
            **ZONE_INPUT,
            CONF_COVER_TYPE: CoverType.TILT,
            CONF_SLAT_WIDTH: 50.0,
            CONF_SLAT_SPACING: 60.0,  # spacing > width -- should fail
        }
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_input
        )
        assert result2["type"] == FlowResultType.FORM
        assert CONF_SLAT_SPACING in result2.get("errors", {})
