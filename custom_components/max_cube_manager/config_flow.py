"""Config flow for the MAX! Cube Manager integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MaxCubeApi, MaxCubeApiError
from .const import DOMAIN


async def _validate_connection(hass: HomeAssistant, host: str) -> str:
    api = MaxCubeApi(async_get_clientsession(hass), host)
    state = await api.async_get_state()
    serial = state["cube"].get("serial")
    if not isinstance(serial, str) or not serial.strip():
        raise MaxCubeApiError("The Cube did not report its serial number")
    return serial


class MaxCubeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a connection to the MAX! Cube Manager app."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input["host"].strip()
            try:
                serial = await _validate_connection(self.hass, host)
            except MaxCubeApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"MAX! Cube {serial}",
                    data={"host": host, "serial": serial},
                )

        schema = vol.Schema(
            {
                vol.Required("host"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
