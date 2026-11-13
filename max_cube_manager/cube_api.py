"""Internal HTTP API for Home Assistant integrations and trusted apps."""

from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlsplit

if __package__:
    from .maxcube import CubeClient, CubeError, encode_cube_message
else:
    from maxcube import CubeClient, CubeError, encode_cube_message


CUBE_MESSAGE_API_PORT = 62910
_LOGGER = logging.getLogger(__name__)


class CubeMessageAPIHandler(BaseHTTPRequestHandler):
    server: "CubeMessageAPIServer"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 0 or length > 4096:
            raise ValueError("Request body must be at most 4 KiB")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Request body must use application/json")
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must contain valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _read_message(self) -> str:
        data = self._read_json()
        message = data.get("message")
        if not isinstance(message, str):
            raise ValueError("The message field must be a string")
        encode_cube_message(message)
        return message

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/api/state":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            with self.server.cube_lock:
                with CubeClient(self.server.cube_host, self.server.cube_port) as cube:
                    snapshot = cube.snapshot()
        except (CubeError, OSError) as exc:
            self._send_json(502, {"error": str(exc)})
            return
        self._send_json(200, snapshot)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/api/cube/message":
                message = self._read_message()
                started = time.monotonic()
                with self.server.cube_lock:
                    with CubeClient(self.server.cube_host, self.server.cube_port) as cube:
                        reply = cube.exchange_message(message)
                if self.server.debug:
                    _LOGGER.debug(
                        "Cube message API exchange completed: request_bytes=%d reply_bytes=%d elapsed=%.3fs",
                        len(message.encode("ascii")),
                        len(reply.encode("ascii", errors="replace")),
                        time.monotonic() - started,
                    )
                self._send_json(200, {"reply": reply})
                return

            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "thermostats"]:
                self._send_json(404, {"error": "Not found"})
                return
            address, action = parts[2], parts[3]
            if action not in {"setpoint", "mode"}:
                self._send_json(404, {"error": "Not found"})
                return
            data = self._read_json()
            with self.server.cube_lock:
                with CubeClient(self.server.cube_host, self.server.cube_port) as cube:
                    if action == "setpoint":
                        result = cube.set_thermostat_temperature(
                            address,
                            data.get("temperature"),
                        )
                    elif action == "mode":
                        result = cube.set_thermostat_mode(address, data.get("mode"))
            self._send_json(200, result)
        except ValueError as exc:
            if self.server.debug:
                _LOGGER.debug("Rejected Cube API request: %s", exc)
            self._send_json(400, {"error": str(exc)})
        except (CubeError, OSError) as exc:
            if self.server.debug:
                _LOGGER.debug("Cube API operation failed", exc_info=True)
            self._send_json(502, {"error": str(exc)})


class CubeMessageAPIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        cube_host: str,
        cube_port: int,
        cube_lock,
        debug: bool = False,
    ) -> None:
        super().__init__(address, CubeMessageAPIHandler)
        self.cube_host = cube_host
        self.cube_port = cube_port
        self.cube_lock = cube_lock
        self.debug = debug
