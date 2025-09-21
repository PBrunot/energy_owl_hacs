"""Config flow for Energy OWL CM160 integration."""

from __future__ import annotations

import logging
from typing import Any

from owlsensor import get_async_datacollector
from serial import SerialException
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, MODEL

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
        await collector.connect()

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Check for existing entries with the same port
                await self.async_set_unique_id(user_input[CONF_PORT])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Energy OWL CM160 ({user_input[CONF_PORT]})",
                    data=info
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )




class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
