"""Config flow integration tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.config_flow import SolarCoverConfigFlow
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
    CONF_HYSTERESIS,
    CONF_MAX_POSITION,
    CONF_MIN_POSITION,
    CONF_SLAT_SPACING,
    CONF_SLAT_WIDTH,
    CONF_STABILITY_DELAY,
    CONF_STABILITY_DELAY_ON_RECOVERY,
    CONF_STABILITY_DELAY_ON_WORSENING,
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

# Geometry fields shared by all cover types in zone_configure step
_ZONE_STEP2_BASE = {
    CONF_AZIMUTH: 180,
    CONF_FOV_LEFT: 90,
    CONF_FOV_RIGHT: 90,
    CONF_ELEVATION_THRESHOLD: 27.0,
}

# Each cover type gets only the fields its formula actually uses
ZONE_STEP2_VERTICAL = {
    **_ZONE_STEP2_BASE,
    CONF_WINDOW_HEIGHT: 2.5,
    CONF_GLARE_DEPTH: 1.0,
}

ZONE_STEP2_HORIZONTAL = {
    **_ZONE_STEP2_BASE,
    CONF_GLARE_DEPTH: 1.0,
    CONF_ATTACH_HEIGHT: 2.5,
    CONF_AWN_LENGTH: 3.0,
    CONF_AWN_ANGLE: 15,
}

ZONE_STEP2_TILT = {
    **_ZONE_STEP2_BASE,
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


def _zone_entry(hass: HomeAssistant, cover_type: CoverType) -> MockConfigEntry:
    """A zone config entry (not set up) for driving its options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": ENTRY_TYPE_ZONE,
            "name": "South",
            CONF_COVER_TYPE: cover_type,
            CONF_AZIMUTH: 180,
            CONF_FOV_LEFT: 90,
            CONF_FOV_RIGHT: 90,
            CONF_ELEVATION_THRESHOLD: 27.0,
            CONF_COVER_ENTITIES: [],
        },
        title="Zone: South",
    )
    entry.add_to_hass(hass)
    return entry


# Common fields the zone options-flow "init" step requires.
_ZONE_OPTIONS_INIT = {
    CONF_COVER_ENTITIES: [],
    CONF_AZIMUTH: 200,
    CONF_FOV_LEFT: 80,
    CONF_FOV_RIGHT: 70,
    CONF_ELEVATION_THRESHOLD: 20.0,
    CONF_MIN_POSITION: 0,
    CONF_MAX_POSITION: 100,
}


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

    async def test_creates_integration_entry_with_stability_fields(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        user_input = {
            CONF_STABILITY_DELAY: 20,
            CONF_STABILITY_DELAY_ON_WORSENING: True,
            CONF_STABILITY_DELAY_ON_RECOVERY: False,
        }
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=user_input
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_STABILITY_DELAY] == 20
        assert result2["data"][CONF_STABILITY_DELAY_ON_WORSENING] is True
        assert result2["data"][CONF_STABILITY_DELAY_ON_RECOVERY] is False

    async def test_first_integration_entry_sets_unique_id(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        entry = hass.config_entries.async_get_entry(result2["result"].entry_id)
        assert entry is not None
        assert entry.unique_id == DOMAIN

    async def test_second_integration_entry_aborts(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import AbortFlow

        # Pre-existing integration entry carries the integration unique id so
        # the guard can detect the collision.
        hass.config_entries.async_update_entry(integration_entry, unique_id=DOMAIN)

        # Drive the integration step directly (bypassing async_step_user's
        # routing) to exercise the unique-id guard. The manager normally
        # converts AbortFlow into an ABORT result; here we assert it fires.
        flow = SolarCoverConfigFlow()
        flow.hass = hass
        flow.handler = DOMAIN
        flow.context = {"source": "user"}
        with pytest.raises(AbortFlow) as exc:
            await flow.async_step_integration(user_input={})
        assert exc.value.reason == "already_configured"


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
                result["flow_id"], user_input=ZONE_STEP2_VERTICAL
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
            **_ZONE_STEP2_BASE,
            CONF_SLAT_WIDTH: 50.0,
            CONF_SLAT_SPACING: 60.0,  # spacing > width -- should fail
            CONF_TILT_RANGE: TiltRange.SINGLE,
        }
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_tilt
        )
        assert result3["type"] == FlowResultType.FORM
        assert CONF_SLAT_SPACING in result3.get("errors", {})

    async def test_min_exceeds_max_validation(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=ZONE_STEP1_VERTICAL
        )
        bad_range = {
            **ZONE_STEP2_VERTICAL,
            CONF_MIN_POSITION: 80,
            CONF_MAX_POSITION: 50,  # min > max -- should fail
        }
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_range
        )
        assert result3["type"] == FlowResultType.FORM
        assert CONF_MIN_POSITION in result3.get("errors", {})

    def _fov_max_for(self, schema: vol.Schema, key: str) -> float:
        """Pull the configured NumberSelector max for the FOV field `key`."""
        for marker in schema.schema:
            if marker == key:
                config = schema.schema[marker].config
                return float(config["max"])
        raise AssertionError(f"{key} not found in schema")

    async def test_vertical_caps_fov_at_90(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=ZONE_STEP1_VERTICAL
        )
        schema = result2["data_schema"]
        assert self._fov_max_for(schema, CONF_FOV_LEFT) == 90
        assert self._fov_max_for(schema, CONF_FOV_RIGHT) == 90

    async def test_horizontal_allows_fov_up_to_180(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        step1 = {**ZONE_STEP1_VERTICAL, CONF_COVER_TYPE: CoverType.HORIZONTAL}
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=step1
        )
        schema = result2["data_schema"]
        assert self._fov_max_for(schema, CONF_FOV_LEFT) == 180
        assert self._fov_max_for(schema, CONF_FOV_RIGHT) == 180

    async def test_error_form_preserves_user_input(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=ZONE_STEP1_VERTICAL
        )
        bad_range = {
            **ZONE_STEP2_VERTICAL,
            CONF_AZIMUTH: 222,
            CONF_MIN_POSITION: 80,
            CONF_MAX_POSITION: 50,  # min > max -- should fail
        }
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_range
        )
        assert result3["type"] == FlowResultType.FORM
        # The re-rendered form must carry back the user's submitted values.
        suggested = {
            str(marker): marker.description.get("suggested_value")
            for marker in result3["data_schema"].schema
            if marker.description
        }
        assert suggested.get(CONF_AZIMUTH) == 222
        assert suggested.get(CONF_MIN_POSITION) == 80
        assert suggested.get(CONF_MAX_POSITION) == 50

    async def test_per_zone_hysteresis_round_trip(
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
                result["flow_id"],
                user_input={**ZONE_STEP2_VERTICAL, CONF_HYSTERESIS: 5.0},
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"][CONF_HYSTERESIS] == 5.0

    async def test_zone_hysteresis_unset_by_default(
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
                result["flow_id"], user_input=ZONE_STEP2_VERTICAL
            )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        # Unset: integration global remains the fallback.
        assert CONF_HYSTERESIS not in result3["data"]


class TestIntegrationOptionsFlow:
    async def test_stability_fields_round_trip(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.options.async_init(
            integration_entry.entry_id
        )
        assert result["type"] == FlowResultType.FORM

        user_input = {
            CONF_STABILITY_DELAY: 15,
            CONF_STABILITY_DELAY_ON_WORSENING: False,
            CONF_STABILITY_DELAY_ON_RECOVERY: True,
        }
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=user_input
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_STABILITY_DELAY] == 15
        assert result2["data"][CONF_STABILITY_DELAY_ON_WORSENING] is False
        assert result2["data"][CONF_STABILITY_DELAY_ON_RECOVERY] is True

    async def test_stability_delay_zero_round_trips(
        self, hass: HomeAssistant, integration_entry: MockConfigEntry
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        result = await hass.config_entries.options.async_init(
            integration_entry.entry_id
        )
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_STABILITY_DELAY: 0}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_STABILITY_DELAY] == 0


class TestZoneOptionsFlow:
    async def test_vertical_round_trip(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.VERTICAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**_ZONE_OPTIONS_INIT, CONF_COVER_TYPE: CoverType.VERTICAL},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "geometry_vertical"

        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={CONF_WINDOW_HEIGHT: 3.0, CONF_GLARE_DEPTH: 1.5},
        )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        # Options carry both the init fields and the geometry fields.
        assert result3["data"][CONF_AZIMUTH] == 200
        assert result3["data"][CONF_WINDOW_HEIGHT] == 3.0
        assert result3["data"][CONF_GLARE_DEPTH] == 1.5

    async def test_horizontal_round_trip(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.HORIZONTAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**_ZONE_OPTIONS_INIT, CONF_COVER_TYPE: CoverType.HORIZONTAL},
        )
        assert result2["step_id"] == "geometry_horizontal"

        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={
                CONF_GLARE_DEPTH: 2.0,
                CONF_ATTACH_HEIGHT: 2.8,
                CONF_AWN_LENGTH: 4.0,
                CONF_AWN_ANGLE: 20,
            },
        )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"][CONF_AWN_LENGTH] == 4.0

    async def test_tilt_round_trip(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.TILT)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**_ZONE_OPTIONS_INIT, CONF_COVER_TYPE: CoverType.TILT},
        )
        assert result2["step_id"] == "geometry_tilt"

        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={
                CONF_SLAT_WIDTH: 90,
                CONF_SLAT_SPACING: 60,
                CONF_TILT_RANGE: TiltRange.BIDIRECTIONAL,
            },
        )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"][CONF_SLAT_WIDTH] == 90
        assert result3["data"][CONF_TILT_RANGE] == TiltRange.BIDIRECTIONAL

    async def test_init_min_exceeds_max_errors(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.VERTICAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                **_ZONE_OPTIONS_INIT,
                CONF_COVER_TYPE: CoverType.VERTICAL,
                CONF_MIN_POSITION: 90,
                CONF_MAX_POSITION: 40,
            },
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "init"
        assert CONF_MIN_POSITION in result2.get("errors", {})

    async def test_tilt_spacing_validation_errors(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.TILT)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**_ZONE_OPTIONS_INIT, CONF_COVER_TYPE: CoverType.TILT},
        )
        assert result2["step_id"] == "geometry_tilt"

        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={
                CONF_SLAT_WIDTH: 50,
                CONF_SLAT_SPACING: 70,  # spacing > width -- invalid
                CONF_TILT_RANGE: TiltRange.SINGLE,
            },
        )
        assert result3["type"] == FlowResultType.FORM
        assert result3["step_id"] == "geometry_tilt"
        assert CONF_SLAT_SPACING in result3.get("errors", {})

    def _fov_max_for(self, schema: vol.Schema, key: str) -> float:
        for marker in schema.schema:
            if marker == key:
                return float(schema.schema[marker].config["max"])
        raise AssertionError(f"{key} not found in schema")

    async def test_init_caps_fov_at_90_for_vertical(self, hass: HomeAssistant) -> None:
        zone = _zone_entry(hass, CoverType.VERTICAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        schema = result["data_schema"]
        assert self._fov_max_for(schema, CONF_FOV_LEFT) == 90
        assert self._fov_max_for(schema, CONF_FOV_RIGHT) == 90

    async def test_init_allows_fov_180_for_horizontal(
        self, hass: HomeAssistant
    ) -> None:
        zone = _zone_entry(hass, CoverType.HORIZONTAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        schema = result["data_schema"]
        assert self._fov_max_for(schema, CONF_FOV_LEFT) == 180
        assert self._fov_max_for(schema, CONF_FOV_RIGHT) == 180

    async def test_init_rejects_fov_over_90_when_switching_to_vertical(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        # Zone is currently horizontal (FOV up to 180 allowed). The form is
        # rendered with the horizontal cap, so submitting fov_left=120 passes
        # selector validation; the user simultaneously switches to vertical,
        # which the server-side guard must then reject.
        zone = _zone_entry(hass, CoverType.HORIZONTAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                **_ZONE_OPTIONS_INIT,
                CONF_COVER_TYPE: CoverType.VERTICAL,
                CONF_FOV_LEFT: 120,  # > 90 for a vertical cover -- invalid
            },
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "init"
        assert CONF_FOV_LEFT in result2.get("errors", {})

    async def test_init_error_form_preserves_user_input(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.VERTICAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                **_ZONE_OPTIONS_INIT,
                CONF_COVER_TYPE: CoverType.VERTICAL,
                CONF_AZIMUTH: 222,
                CONF_MIN_POSITION: 90,
                CONF_MAX_POSITION: 40,  # min > max -- should fail
            },
        )
        assert result2["type"] == FlowResultType.FORM
        suggested = {
            str(marker): marker.description.get("suggested_value")
            for marker in result2["data_schema"].schema
            if marker.description
        }
        assert suggested.get(CONF_AZIMUTH) == 222
        assert suggested.get(CONF_MIN_POSITION) == 90
        assert suggested.get(CONF_MAX_POSITION) == 40

    async def test_tilt_error_form_preserves_user_input(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.TILT)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**_ZONE_OPTIONS_INIT, CONF_COVER_TYPE: CoverType.TILT},
        )
        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={
                CONF_SLAT_WIDTH: 50,
                CONF_SLAT_SPACING: 70,  # invalid
                CONF_TILT_RANGE: TiltRange.SINGLE,
            },
        )
        assert result3["type"] == FlowResultType.FORM
        suggested = {
            str(marker): marker.description.get("suggested_value")
            for marker in result3["data_schema"].schema
            if marker.description
        }
        assert suggested.get(CONF_SLAT_SPACING) == 70
        assert suggested.get(CONF_SLAT_WIDTH) == 50

    async def test_hysteresis_round_trip(self, hass: HomeAssistant) -> None:
        from homeassistant.data_entry_flow import FlowResultType

        zone = _zone_entry(hass, CoverType.VERTICAL)
        result = await hass.config_entries.options.async_init(zone.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                **_ZONE_OPTIONS_INIT,
                CONF_COVER_TYPE: CoverType.VERTICAL,
                CONF_HYSTERESIS: 7.5,
            },
        )
        assert result2["step_id"] == "geometry_vertical"
        result3 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            user_input={CONF_WINDOW_HEIGHT: 3.0, CONF_GLARE_DEPTH: 1.5},
        )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"][CONF_HYSTERESIS] == 7.5
