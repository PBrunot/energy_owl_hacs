"""Config flow for Monoprice 6-Zone Amplifier integration."""

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
    try:
        await hass.async_add_executor_job(
            get_async_datacollector, data[CONF_PORT], MODEL
        )
    except SerialException as err:
        _LOGGER.error("Error connecting to OWL controller")
        raise CannotConnect from err

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

                return self.async_create_entry(title=user_input[CONF_PORT], data=info)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


@callback
def _key_for_source(index, source, previous_sources):
    if str(index) in previous_sources:
        key = vol.Optional(
            source, description={"suggested_value": previous_sources[str(index)]}
        )
    else:
        key = vol.Optional(source)

    return key


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
