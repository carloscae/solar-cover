"""Integration setup/unload and diagnostics tests.

Exercises the runtime_data wiring end to end: a zone entry must set up its
coordinator on entry.runtime_data, register entities, and unload cleanly without
any reliance on hass.data.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover import (
    _async_update_integration_listener,
    async_migrate_entry,
)
from custom_components.solar_cover.const import (
    CONF_WIND_THRESHOLD,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
)
from custom_components.solar_cover.coordinator import SolarCoverCoordinator
from custom_components.solar_cover.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:  # noqa: PT004
    """Activate the custom component loader for every test in this module."""


def _integration_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": ENTRY_TYPE_INTEGRATION},
        title="Global Settings",
    )
    entry.add_to_hass(hass)
    return entry


def _zone_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": ENTRY_TYPE_ZONE,
            "name": "South",
            "cover_type": "vertical",
            "azimuth": 180,
            "fov_left": 90,
            "fov_right": 90,
            "elevation_threshold": 25.0,
            "cover_entities": [],
            "window_height": 2.5,
            "glare_depth": 1.0,
        },
        title="Zone: South",
    )
    entry.add_to_hass(hass)
    return entry


class TestSetupUnload:
    async def test_zone_setup_populates_runtime_data_and_unloads(
        self, hass: HomeAssistant
    ) -> None:
        _integration_entry(hass)
        zone = _zone_entry(hass)

        assert await hass.config_entries.async_setup(zone.entry_id)
        await hass.async_block_till_done()

        assert zone.state is ConfigEntryState.LOADED
        assert isinstance(zone.runtime_data, SolarCoverCoordinator)

        # The diagnostic sensors, switch, and button are registered.
        ent_reg = hass.config_entries.async_entries(DOMAIN)
        assert zone in ent_reg

        assert await hass.config_entries.async_unload(zone.entry_id)
        await hass.async_block_till_done()
        assert zone.state is ConfigEntryState.NOT_LOADED


class TestDiagnostics:
    async def test_zone_diagnostics_redacts_location(self, hass: HomeAssistant) -> None:
        _integration_entry(hass)
        zone = _zone_entry(hass)
        await hass.config_entries.async_setup(zone.entry_id)
        await hass.async_block_till_done()

        diag = await async_get_config_entry_diagnostics(hass, zone)

        # Home coordinates must be redacted; structural data must be present.
        assert diag["home"]["latitude"] == "**REDACTED**"
        assert diag["home"]["longitude"] == "**REDACTED**"
        assert diag["home"]["elevation"] != "**REDACTED**"
        assert diag["entry_type"] == ENTRY_TYPE_ZONE
        assert "state" in diag
        assert diag["state"]["intent"]

    async def test_integration_diagnostics_has_no_state(
        self, hass: HomeAssistant
    ) -> None:
        entry = _integration_entry(hass)
        # Integration entries carry no coordinator -> no state block, no crash.
        entry.runtime_data = None  # type: ignore[assignment]
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry_type"] == ENTRY_TYPE_INTEGRATION
        assert "state" not in diag


class TestDiagnosticsUnit:
    """Redaction logic without a full HA setup, using a stub coordinator."""

    async def test_redaction_with_fake_coordinator(self, hass: HomeAssistant) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_ZONE, "name": "X"},
            title="Zone: X",
        )
        entry.add_to_hass(hass)
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.async_request_refresh = AsyncMock()
        entry.runtime_data = coordinator  # type: ignore[assignment]

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["home"]["latitude"] == "**REDACTED**"
        # data.None coordinator -> no state block
        assert "state" not in diag


class TestCascadeReloadResilience:
    """A global-settings change reloads the integration entry plus every zone.
    One zone failing to reload must not strand the rest on stale settings."""

    async def test_one_zone_failure_does_not_block_others(
        self, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        integration = _integration_entry(hass)
        zone_a = _zone_entry(hass)
        zone_b = MockConfigEntry(
            domain=DOMAIN,
            data={
                "entry_type": ENTRY_TYPE_ZONE,
                "name": "North",
                "cover_type": "vertical",
                "azimuth": 0,
                "fov_left": 90,
                "fov_right": 90,
                "elevation_threshold": 25.0,
                "cover_entities": [],
            },
            title="Zone: North",
        )
        zone_b.add_to_hass(hass)

        reloaded: list[str] = []

        async def fake_reload(entry_id: str) -> bool:
            reloaded.append(entry_id)
            if entry_id == zone_a.entry_id:
                raise RuntimeError("zone A blew up")
            return True

        with (
            patch.object(hass.config_entries, "async_reload", side_effect=fake_reload),
            caplog.at_level("ERROR"),
        ):
            await _async_update_integration_listener(hass, integration)

        # The integration entry and BOTH zones were attempted despite zone A
        # raising -- the loop did not abort on the first failure.
        assert integration.entry_id in reloaded
        assert zone_a.entry_id in reloaded
        assert zone_b.entry_id in reloaded
        assert zone_a.entry_id in caplog.text


class TestMigration:
    async def test_v1_wind_threshold_converted_to_kmh(
        self, hass: HomeAssistant
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_INTEGRATION, CONF_WIND_THRESHOLD: 10},
            title="Global Settings",
            version=1,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry)
        assert entry.version == 2
        # 10 m/s -> 36.0 km/h, preserving the user's original intent.
        assert entry.data[CONF_WIND_THRESHOLD] == 36.0

    async def test_v1_wind_threshold_in_options_converted(
        self, hass: HomeAssistant
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_INTEGRATION},
            options={CONF_WIND_THRESHOLD: 5},
            title="Global Settings",
            version=1,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry)
        assert entry.version == 2
        assert entry.options[CONF_WIND_THRESHOLD] == 18.0

    async def test_v1_without_wind_threshold_just_bumps_version(
        self, hass: HomeAssistant
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_ZONE, "name": "Z"},
            title="Zone: Z",
            version=1,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry)
        assert entry.version == 2
        assert CONF_WIND_THRESHOLD not in entry.data

    async def test_v2_entry_is_noop(self, hass: HomeAssistant) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_INTEGRATION, CONF_WIND_THRESHOLD: 40},
            title="Global Settings",
            version=2,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry)
        assert entry.version == 2
        # Already km/h -- must NOT be rescaled again.
        assert entry.data[CONF_WIND_THRESHOLD] == 40

    async def test_downgrade_from_v3_refused_and_logged(
        self, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A config entry written by a newer integration version (schema > 2)
        # cannot be safely downgraded; migration must refuse and explain why.
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"entry_type": ENTRY_TYPE_INTEGRATION},
            title="Global Settings",
            version=3,
        )
        entry.add_to_hass(hass)

        with caplog.at_level("ERROR"):
            assert await async_migrate_entry(hass, entry) is False
        assert "downgrade" in caplog.text.lower()
        assert entry.entry_id in caplog.text
