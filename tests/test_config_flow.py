"""Config flow integration tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.const import (
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
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_TILT_RANGE,
    CONF_WINDOW_HEIGHT,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    CoverType,
    TiltRange,
)

ZONE_BASIC_INPUT = {
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

HORIZONTAL_INPUT = {
    CONF_ATTACH_HEIGHT: 2.5,
    CONF_AWN_LENGTH: 3.0,
    CONF_AWN_ANGLE: 15,
}

TILT_INPUT = {
    CONF_SLAT_WIDTH: 80.0,
    CONF_SLAT_SPACING: 50.0,
    CONF_TILT_RANGE: TiltRange.SINGLE,
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


class TestZoneBasicStep:
    async def test_shows_zone_basic_form_when_integration_exists(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "zone_basic"

    async def test_vertical_cover_creates_entry_directly(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        """Vertical blinds need no extra step - entry created after zone_basic."""
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
                result["flow_id"], user_input=ZONE_BASIC_INPUT
            )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result2["data"][CONF_AZIMUTH] == 180
        assert result2["data"]["name"] == "South Terrace"

    async def test_horizontal_cover_routes_to_zone_horizontal(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        basic_input = {**ZONE_BASIC_INPUT, CONF_COVER_TYPE: CoverType.HORIZONTAL}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=basic_input
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "zone_horizontal"

    async def test_tilt_cover_routes_to_zone_tilt(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        basic_input = {**ZONE_BASIC_INPUT, CONF_COVER_TYPE: CoverType.TILT}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=basic_input
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "zone_tilt"


class TestZoneHorizontalStep:
    async def test_creates_horizontal_zone_entry(
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
            basic_input = {**ZONE_BASIC_INPUT, CONF_COVER_TYPE: CoverType.HORIZONTAL}
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=basic_input
            )
            assert result2["step_id"] == "zone_horizontal"
            result3 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=HORIZONTAL_INPUT
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result3["data"][CONF_AWN_LENGTH] == 3.0
        assert result3["data"][CONF_COVER_TYPE] == CoverType.HORIZONTAL


class TestZoneTiltStep:
    async def test_creates_tilt_zone_entry(
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
            basic_input = {**ZONE_BASIC_INPUT, CONF_COVER_TYPE: CoverType.TILT}
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=basic_input
            )
            assert result2["step_id"] == "zone_tilt"
            result3 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=TILT_INPUT
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result3["data"][CONF_SLAT_WIDTH] == 80.0
        assert result3["data"][CONF_COVER_TYPE] == CoverType.TILT

    async def test_tilt_spacing_validation(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        basic_input = {**ZONE_BASIC_INPUT, CONF_COVER_TYPE: CoverType.TILT}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=basic_input
        )
        assert result2["step_id"] == "zone_tilt"

        bad_tilt = {
            CONF_SLAT_WIDTH: 50.0,
            CONF_SLAT_SPACING: 60.0,  # spacing > width -- should fail
            CONF_TILT_RANGE: TiltRange.SINGLE,
        }
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_tilt
        )
        assert result3["type"] == FlowResultType.FORM
        assert CONF_SLAT_SPACING in result3.get("errors", {})
