"""Config flow for the MAX! Cube Manager integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import MaxCubeApi, MaxCubeApiError
from .const import API_PORT, DOMAIN


async def _validate_connection(hass: HomeAssistant, host: str, port: int) -> str:
    api = MaxCubeApi(async_get_clientsession(hass), host, port)
    state = await api.async_get_state()
    serial = state["cube"].get("serial")
    if not isinstance(serial, str) or not serial.strip():
        raise MaxCubeApiError("The Cube did not report its serial number")
    return serial


class MaxCubeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a connection to the MAX! Cube Manager app."""

    VERSION = 1

    async def async_step_hassio(
        self,
        discovery_info: HassioServiceInfo,
    ):
        config = discovery_info.config
        host = config.get("host")
        port = config.get("port", API_PORT)
        if (
            not isinstance(host, str)
            or not host.strip()
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            return self.async_abort(reason="invalid_discovery")

        self._discovered_host = host.strip()
        self._discovered_port = port
        try:
            self._discovered_serial = await _validate_connection(
                self.hass,
                self._discovered_host,
                self._discovered_port,
            )
        except MaxCubeApiError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(self._discovered_serial)
        self._abort_if_unique_id_configured()
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"MAX! Cube {self._discovered_serial}",
                data={
                    "host": self._discovered_host,
                    "port": self._discovered_port,
                    "serial": self._discovered_serial,
                },
            )

        return self.async_show_form(
            step_id="hassio_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"serial": self._discovered_serial},
        )

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input["host"].strip()
            try:
                serial = await _validate_connection(self.hass, host, API_PORT)
            except MaxCubeApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"MAX! Cube {serial}",
                    data={"host": host, "port": API_PORT, "serial": serial},
                )

        schema = vol.Schema(
            {
                vol.Required("host"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
