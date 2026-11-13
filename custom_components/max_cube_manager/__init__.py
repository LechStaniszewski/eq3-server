"""MAX! Cube Manager Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MaxCubeApi, MaxCubeApiError
from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL


class MaxCubeCoordinator(DataUpdateCoordinator[dict]):
    """Fetch thermostat states from the MAX! Cube Manager app."""

    def __init__(self, hass: HomeAssistant, api: MaxCubeApi, serial: str) -> None:
        self.api = api
        self.serial = serial
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name="MAX! Cube Manager",
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        try:
            state = await self.api.async_get_state()
        except MaxCubeApiError as exc:
            raise UpdateFailed(str(exc)) from exc
        if state["cube"].get("serial") != self.serial:
            raise UpdateFailed("The configured app is now connected to a different MAX! Cube")
        return state


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = MaxCubeApi(
        async_get_clientsession(hass),
        entry.data["host"],
        entry.data.get("port", 62910),
    )
    coordinator = MaxCubeCoordinator(hass, api, entry.data["serial"])
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id)
    return True
