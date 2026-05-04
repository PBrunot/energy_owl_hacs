"""Tests for the Energy OWL config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.data_entry_flow import AbortFlow

from custom_components.energy_owl.config_flow import CannotConnect, OwlConfigFlow, validate_input
from custom_components.energy_owl.const import (
    CONF_ENABLE_HISTORICAL,
    CONF_VOLTAGE,
    CONF_VOLTAGE_ENTITY,
    DEFAULT_VOLTAGE,
    DOMAIN,
)

# We test the flow class methods directly to avoid the HA integration loader,
# which would require the real owlsensor package to be installed.


def _make_mock_collector():
    collector = MagicMock()
    collector.connect = AsyncMock()
    collector.disconnect = AsyncMock()
    return collector


# ---------------------------------------------------------------------------
# validate_input helper
# ---------------------------------------------------------------------------


async def test_validate_input_success(hass):
    """validate_input must return the port on success."""
    collector = _make_mock_collector()
    with patch(
        "custom_components.energy_owl.config_flow.get_async_datacollector",
        return_value=collector,
    ):
        result = await validate_input(hass, {CONF_PORT: "/dev/ttyUSB0"})

    assert result == {CONF_PORT: "/dev/ttyUSB0"}
    collector.connect.assert_awaited_once()
    collector.disconnect.assert_awaited_once()


async def test_validate_input_raises_cannot_connect(hass):
    """validate_input must raise CannotConnect on any exception."""
    with (
        patch(
            "custom_components.energy_owl.config_flow.get_async_datacollector",
            side_effect=Exception("port not found"),
        ),
        pytest.raises(CannotConnect),
    ):
        await validate_input(hass, {CONF_PORT: "/dev/ttyUSB99"})


async def test_validate_input_always_disconnects(hass):
    """validate_input must disconnect even when connect() raises."""
    collector = _make_mock_collector()
    collector.connect.side_effect = Exception("timeout")
    with (
        patch(
            "custom_components.energy_owl.config_flow.get_async_datacollector",
            return_value=collector,
        ),
        pytest.raises(CannotConnect),
    ):
        await validate_input(hass, {CONF_PORT: "/dev/ttyUSB0"})

    collector.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# OwlConfigFlow.async_step_user
# ---------------------------------------------------------------------------


async def _init_flow(hass):
    """Create and initialise an OwlConfigFlow bound to hass."""
    flow = OwlConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow.handler = DOMAIN
    flow._progress_id = "test_flow"
    # Bind to the flow manager so async_create_entry / async_show_form work.
    hass.config_entries.flow._progress[flow._progress_id] = flow
    return flow


async def test_step_user_shows_form(hass):
    """Step user with no input must return a FORM result."""
    flow = await _init_flow(hass)
    result = await flow.async_step_user(None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_step_user_cannot_connect(hass):
    """A connection failure must set errors['base'] = 'cannot_connect'."""
    flow = await _init_flow(hass)

    with patch(
        "custom_components.energy_owl.config_flow.validate_input",
        side_effect=CannotConnect,
    ):
        result = await flow.async_step_user({CONF_PORT: "/dev/ttyUSB99"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_step_user_unexpected_exception(hass):
    """An unexpected exception must set errors['base'] = 'unknown'."""
    flow = await _init_flow(hass)

    with patch(
        "custom_components.energy_owl.config_flow.validate_input",
        side_effect=RuntimeError("unexpected"),
    ):
        result = await flow.async_step_user({CONF_PORT: "/dev/ttyUSB0"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "unknown"


async def test_step_user_already_configured(hass):
    """Configuring the same port twice must raise AbortFlow('already_configured').

    _abort_if_unique_id_configured() raises AbortFlow, which our config_flow
    re-raises (it must not be swallowed by the generic except Exception block).
    When called through the real HA flow manager this becomes a FORM/ABORT
    result; when called directly in tests we assert the exception propagates.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0"},
        unique_id="/dev/ttyUSB0",
    )
    existing.add_to_hass(hass)

    flow = await _init_flow(hass)

    with (
        patch(
            "custom_components.energy_owl.config_flow.validate_input",
            return_value={CONF_PORT: "/dev/ttyUSB0"},
        ),
        pytest.raises(AbortFlow) as exc_info,
    ):
        await flow.async_step_user({CONF_PORT: "/dev/ttyUSB0"})

    assert exc_info.value.reason == "already_configured"


async def test_step_user_success_creates_entry(hass):
    """A valid port must create a config entry."""
    flow = await _init_flow(hass)

    with patch(
        "custom_components.energy_owl.config_flow.validate_input",
        return_value={CONF_PORT: "/dev/ttyUSB0"},
    ):
        result = await flow.async_step_user({CONF_PORT: "/dev/ttyUSB0"})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PORT] == "/dev/ttyUSB0"
    assert "CM160" in result["title"]


# ---------------------------------------------------------------------------
# OwlOptionsFlowHandler — voltage configuration
# ---------------------------------------------------------------------------


async def test_options_flow_shows_voltage_fields(hass, mock_config_entry):
    """The options init step must expose enable_historical, voltage_entity and voltage."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert CONF_ENABLE_HISTORICAL in schema_keys
    assert CONF_VOLTAGE in schema_keys
    assert CONF_VOLTAGE_ENTITY in schema_keys


async def test_options_flow_default_voltage_is_230(hass, mock_config_entry):
    """Default voltage in the form must be DEFAULT_VOLTAGE."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    # Find the CONF_VOLTAGE key and check its default
    for key in result["data_schema"].schema:
        if str(key) == CONF_VOLTAGE:
            assert key.default() == pytest.approx(DEFAULT_VOLTAGE)
            break
    else:
        pytest.fail(f"{CONF_VOLTAGE!r} key not found in options schema")


async def test_options_flow_saves_custom_voltage(hass, mock_config_entry):
    """Submitting a custom voltage must persist it in options."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_ENABLE_HISTORICAL: True, CONF_VOLTAGE: 120.0},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VOLTAGE] == pytest.approx(120.0)


async def test_options_flow_saves_voltage_entity(hass, mock_config_entry):
    """Submitting a voltage entity must persist it in options."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ENABLE_HISTORICAL: True,
            CONF_VOLTAGE: 230.0,
            CONF_VOLTAGE_ENTITY: "sensor.grid_voltage",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VOLTAGE_ENTITY] == "sensor.grid_voltage"


async def test_options_flow_drops_empty_voltage_entity(hass, mock_config_entry):
    """An empty string for voltage_entity must be stripped from the saved options."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ENABLE_HISTORICAL: True,
            CONF_VOLTAGE: 230.0,
            # CONF_VOLTAGE_ENTITY omitted — entity selector sends no value when cleared
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_VOLTAGE_ENTITY not in result["data"]


async def test_options_flow_retains_existing_voltage_entity(hass):
    """Pre-existing voltage_entity in options must appear as suggested_value on re-open."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0"},
        options={CONF_VOLTAGE_ENTITY: "sensor.existing_voltage", CONF_VOLTAGE: 230.0},
        entry_id="entry_with_entity",
        unique_id="/dev/ttyUSB0",
        version=1,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    # Check that the suggested value is present for CONF_VOLTAGE_ENTITY
    for key in result["data_schema"].schema:
        if str(key) == CONF_VOLTAGE_ENTITY:
            description = key.description or {}
            assert description.get("suggested_value") == "sensor.existing_voltage"
            break
    else:
        pytest.fail(f"{CONF_VOLTAGE_ENTITY!r} key not found in options schema")
