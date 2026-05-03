"""Tests for the Energy OWL config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl.const import DOMAIN


async def test_config_flow_success(hass):
    """A valid port must create a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    mock_collector = MagicMock()
    mock_collector.connect = AsyncMock()
    mock_collector.disconnect = AsyncMock()

    with patch(
        "custom_components.energy_owl.config_flow.get_async_datacollector",
        return_value=mock_collector,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PORT: "/dev/ttyUSB0"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PORT] == "/dev/ttyUSB0"


async def test_config_flow_cannot_connect(hass):
    """A SerialException must surface as a 'cannot_connect' form error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.energy_owl.config_flow.get_async_datacollector",
        side_effect=Exception("port not found"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PORT: "/dev/ttyUSB99"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_config_flow_already_configured(hass):
    """Configuring the same port twice must abort with 'already_configured'."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0"},
        unique_id="/dev/ttyUSB0",
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    mock_collector = MagicMock()
    mock_collector.connect = AsyncMock()
    mock_collector.disconnect = AsyncMock()

    with patch(
        "custom_components.energy_owl.config_flow.get_async_datacollector",
        return_value=mock_collector,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PORT: "/dev/ttyUSB0"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
