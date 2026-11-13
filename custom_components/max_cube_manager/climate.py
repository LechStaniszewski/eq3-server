"""Climate entities for MAX! Cube thermostats."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MaxCubeCoordinator
from .const import DOMAIN


def _thermostats(coordinator: MaxCubeCoordinator) -> dict[str, dict[str, Any]]:
    return {
        device["address"]: device
        for device in coordinator.data.get("thermostats", [])
        if isinstance(device, dict)
        and device.get("type_code") in {1, 2, 3}
        and isinstance(device.get("address"), str)
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MaxCubeCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_addresses: set[str] = set()

    def add_new_thermostats() -> None:
        devices = _thermostats(coordinator)
        new_addresses = set(devices) - known_addresses
        if new_addresses:
            known_addresses.update(new_addresses)
            async_add_entities(
                [
                    MaxCubeThermostat(coordinator, address)
                    for address in sorted(new_addresses)
                ]
            )

    add_new_thermostats()
    entry.async_on_unload(coordinator.async_add_listener(add_new_thermostats))


class MaxCubeThermostat(CoordinatorEntity[MaxCubeCoordinator], ClimateEntity):
    """Represent one thermostat paired to a MAX! Cube."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT]
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: MaxCubeCoordinator, address: str) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{coordinator.serial}_{address}"

    @property
    def _device(self) -> dict[str, Any] | None:
        return _thermostats(self.coordinator).get(self._address)

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device or {}
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.serial}_{self._address}")},
            name=device.get("name") or device.get("serial") or self._address,
            manufacturer="eQ-3",
            model=device.get("type"),
            serial_number=device.get("serial"),
        )

    @property
    def name(self) -> str | None:
        device = self._device
        return device.get("name") if device else self._address

    @property
    def current_temperature(self) -> float | None:
        return self._status_value("current_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._status_value("target_temperature")

    @property
    def min_temp(self) -> float:
        device = self._device or {}
        return float(device.get("minimum temperature", 4.5))

    @property
    def max_temp(self) -> float:
        device = self._device or {}
        return float(device.get("maximum temperature", 30.5))

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = (self._device or {}).get("status", {}).get("mode")
        if mode == "auto":
            return HVACMode.AUTO
        if mode == "manual":
            return HVACMode.HEAT
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device or {}
        status = device.get("status", {})
        return {
            "thermostat_address": self._address,
            "room_id": device.get("room_id"),
            "valve_position": status.get("valve_position"),
        }

    def _status_value(self, key: str) -> float | None:
        value = (self._device or {}).get("status", {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        await self.coordinator.api.async_set_temperature(self._address, temperature)
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mode = "auto" if hvac_mode == HVACMode.AUTO else "manual"
        await self.coordinator.api.async_set_mode(self._address, mode)
        await asyncio.sleep(5)
        await self.coordinator.async_request_refresh()
