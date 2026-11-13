"""Client for the MAX! Cube Manager app's internal API."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API_PORT


class MaxCubeApiError(Exception):
    """Raised when the MAX! Cube Manager app cannot be reached."""


class MaxCubeApi:
    def __init__(self, session: ClientSession, host: str) -> None:
        self._session = session
        self._base_url = f"http://{host}:{API_PORT}"

    async def async_get_state(self) -> dict[str, Any]:
        data = await self._request("GET", "/api/state")
        if not isinstance(data.get("cube"), dict) or not isinstance(data.get("thermostats"), list):
            raise MaxCubeApiError("The app returned an invalid state response")
        return data

    async def async_set_temperature(self, address: str, temperature: float) -> None:
        await self._request(
            "POST",
            f"/api/thermostats/{address}/setpoint",
            {"temperature": temperature},
        )

    async def async_set_mode(self, address: str, mode: str) -> None:
        await self._request(
            "POST",
            f"/api/thermostats/{address}/mode",
            {"mode": mode},
        )

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                json=payload,
                timeout=ClientTimeout(total=15),
            ) as response:
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    raise MaxCubeApiError("The app returned an invalid response")
                if response.status >= 400:
                    message = data.get("error", f"HTTP {response.status}")
                    raise MaxCubeApiError(str(message))
                return data
        except (ClientError, TimeoutError, ValueError) as exc:
            raise MaxCubeApiError(str(exc)) from exc
