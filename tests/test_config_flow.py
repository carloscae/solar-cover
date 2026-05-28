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

# Step 1: name, entities, cover type
ZONE_STEP1_VERTICAL = {
    "name": "South Terrace",
    CONF_COVER_ENTITIES: ["cover.terrace_awning"],
    CONF_COVER_TYPE: CoverType.VERTICAL,
}

# Step 2: geometry fields (common to all types)
ZONE_STEP2_COMMON = {
    CONF_AZIMUTH: 180,
    CONF_FOV_LEFT: 90,
    CONF_FOV_RIGHT: 90,
    CONF_ELEVATION_THRESHOLD: 27.0,
    CONF_WINDOW_HEIGHT: 2.5,
    CONF_GLARE_DEPTH: 1.0,
}

ZONE_STEP2_HORIZONTAL = {
    **ZONE_STEP2_COMMON,
    CONF_ATTACH_HEIGHT: 2.5,
    CONF_AWN_LENGTH: 3.0,
    CONF_AWN_ANGLE: 15,
}

ZONE_STEP2_TILT = {
    **ZONE_STEP2_COMMON,
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

    async def test_zone_step1_routes_to_zone_configure(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=ZONE_STEP1_VERTICAL
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "zone_configure"

    async def test_horizontal_cover_shows_configure_step(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.HORIZONTAL}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=step1
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "zone_configure"

    async def test_tilt_cover_shows_configure_step(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.TILT}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=step1
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "zone_configure"


class TestZoneConfigureStep:
    async def test_creates_vertical_zone_entry(
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
            await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=ZONE_STEP1_VERTICAL
            )
            result3 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=ZONE_STEP2_COMMON
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result3["data"][CONF_AZIMUTH] == 180
        assert result3["data"]["name"] == "South Terrace"

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
            step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.HORIZONTAL}
            await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=step1
            )
            result3 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=ZONE_STEP2_HORIZONTAL
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"]["entry_type"] == ENTRY_TYPE_ZONE
        assert result3["data"][CONF_AWN_LENGTH] == 3.0
        assert result3["data"][CONF_COVER_TYPE] == CoverType.HORIZONTAL

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
            step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.TILT}
            await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=step1
            )
            result3 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=ZONE_STEP2_TILT
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
        step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.TILT}
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=step1
        )
        bad_tilt = {
            **ZONE_STEP2_COMMON,
            CONF_SLAT_WIDTH: 50.0,
            CONF_SLAT_SPACING: 60.0,  # spacing > width -- should fail
            CONF_TILT_RANGE: TiltRange.SINGLE,
        }
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_tilt
        )
        assert result3["type"] == FlowResultType.FORM
        assert CONF_SLAT_SPACING in result3.get("errors", {})
