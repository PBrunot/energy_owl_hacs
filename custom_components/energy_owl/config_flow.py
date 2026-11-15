"""Config flow for Energy OWL CM160 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from owlsensor import get_async_datacollector
from serialx import SerialException

from .const import (
    CONF_ENABLE_HISTORICAL,
    CONF_VOLTAGE,
    CONF_VOLTAGE_ENTITY,
    DEFAULT_ENABLE_HISTORICAL,
    DEFAULT_VOLTAGE,
    DOMAIN,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_PORT): str})


async def validate_input(hass: HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    collector = None
    try:
        # Test connection by creating a collector instance
        collector = await hass.async_add_executor_job(
            get_async_datacollector, data[CONF_PORT], MODEL
        )
        # Quick connection test
        if not await collector.connect():
            raise SerialException(f"Could not open serial port {data[CONF_PORT]}")

    except SerialException as err:
        _LOGGER.error("Error connecting to OWL controller at %s: %s", data[CONF_PORT], err)
        raise CannotConnect from err
    except Exception as err:
        _LOGGER.error("Unexpected error testing OWL connection at %s: %s", data[CONF_PORT], err)
        raise CannotConnect from err
    finally:
        # Always ensure the test collector is disconnected to clean up background tasks
        if collector:
            await collector.disconnect()

    # Return info that you want to store in the config entry.
    return {CONF_PORT: data[CONF_PORT]}


class OwlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy OWL energy meter."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OwlOptionsFlowHandler:
        """Return the options flow handler."""
        return OwlOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                # Reject duplicates before opening a port owned by a loaded entry.
                await self.async_set_unique_id(user_input[CONF_PORT])
                self._abort_if_unique_id_configured()
                if any(entry.data[CONF_PORT] == user_input[CONF_PORT] for entry in self._async_current_entries()):
                    raise AbortFlow("already_configured")
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(
                    title=f"Energy OWL CM160 ({user_input[CONF_PORT]})",
                    data=info
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AbortFlow:
                raise
            except Exception:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Change the connection port while keeping the original device identity."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            if any(other.entry_id != entry.entry_id and other.data[CONF_PORT] == user_input[CONF_PORT]
                   for other in self._async_current_entries()):
                return self.async_abort(reason="already_configured")
            try:
                if user_input[CONF_PORT] != entry.data[CONF_PORT]:
                    await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_and_abort(
                    entry,
                    data_updates={CONF_PORT: user_input[CONF_PORT],
                                  "identity_port": entry.data.get("identity_port", entry.data[CONF_PORT])},
                    reason="reconfigure_successful",
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): str}),
            errors=errors,
        )


class OwlOptionsFlowHandler(OptionsFlow):
    """Handle options for Energy OWL."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options form."""
        if user_input is not None:
            # Drop voltage_entity key when left empty so _get_voltage falls through to default.
            cleaned: dict[str, Any] = {}
            for key, value in user_input.items():
                if key == CONF_VOLTAGE_ENTITY and not value:
                    continue
                cleaned[key] = value
            return self.async_create_entry(data=cleaned)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_HISTORICAL,
                    default=options.get(CONF_ENABLE_HISTORICAL, DEFAULT_ENABLE_HISTORICAL),
                ): bool,
                vol.Optional(
                    CONF_VOLTAGE_ENTITY,
                    description={"suggested_value": options.get(CONF_VOLTAGE_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="voltage",
                    )
                ),
                vol.Optional(
                    CONF_VOLTAGE,
                    default=options.get(CONF_VOLTAGE, DEFAULT_VOLTAGE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100.0,
                        max=260.0,
                        step=0.5,
                        unit_of_measurement="V",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
