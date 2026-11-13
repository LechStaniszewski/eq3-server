"""Local MAX! Cube protocol client."""

from __future__ import annotations

import base64
import binascii
import math
import socket
import struct
import time
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


DEFAULT_PORT = 62910
DISCOVERY_PORT = 23272
DISCOVERY_PACKET = b"eQ3Max*\x00**********I"
RADIO_QUEUE_RETRY_SECONDS = 30.0
RADIO_QUEUE_RETRY_INTERVAL = 10.0
DEVICE_TYPE_MAP = {
    0: "Cube",
    1: "RadiatorThermostat",
    2: "RadiatorThermostat_Plus",
    3: "WallThermostat",
    4: "Shutter_Contact",
    5: "Eco_Button",
    99: "Unknown",
}
MODE_MAP = {0: "auto", 1: "manual", 2: "vacation", 3: "boost"}
DAY_ORDER = ("Sa", "Su", "Mo", "Tu", "We", "Th", "Fr")
DAY_TO_CODE = {"Mo": 2, "Tu": 3, "We": 4, "Th": 5, "Fr": 6, "Sa": 0, "Su": 1}
CODE_TO_DAY = {value: key for key, value in DAY_TO_CODE.items()}


class CubeError(RuntimeError):
    pass


def encode_cube_message(message: str) -> bytes:
    if not isinstance(message, str):
        raise ValueError("Cube message must be a string")
    try:
        encoded = message.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Cube messages must contain only ASCII characters") from exc
    if not encoded or len(encoded) > 1024:
        raise ValueError("Cube messages must contain between 1 and 1024 bytes")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError("Cube messages must be a single printable protocol line")
    return encoded


def discover_cube(timeout: float = 2.0) -> Tuple[str, Dict[str, str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", DISCOVERY_PORT))
        sock.sendto(DISCOVERY_PACKET, ("255.255.255.255", DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CubeError("No MAX! Cube found on the local network")
            sock.settimeout(remaining)
            try:
                data, address = sock.recvfrom(1024)
            except socket.timeout as exc:
                raise CubeError("No MAX! Cube found on the local network") from exc
            if len(data) != 26 or not data.startswith(b"eQ3MaxAp"):
                continue
            return address[0], {
                "serial": data[8:18].decode("ascii", errors="replace").rstrip("*\x00"),
                "rf_address": data[21:24].hex().upper(),
                "firmware": f"{data[24]:02x}{data[25]:02x}",
            }
    finally:
        sock.close()


def _decode_address(value: str) -> bytes:
    text = value.strip().replace(":", "")
    if text.lower().startswith("0x"):
        text = text[2:]
    if len(text) != 6:
        raise CubeError("A thermostat address must contain six hexadecimal digits")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise CubeError(f"Invalid thermostat address: {value!r}") from exc


def _format_address(value: bytes) -> str:
    return value.hex().upper()


def _encode_day_program(points: Sequence[Tuple[int, float]]) -> bytes:
    if not points or len(points) > 13:
        raise CubeError("Each day needs between 1 and 13 schedule entries")

    encoded_points = list(points)
    if int(encoded_points[-1][0]) < 24 * 60 * 60:
        if len(encoded_points) == 13:
            raise CubeError("A schedule ending before midnight can have at most 12 entries")
        encoded_points.append((24 * 60 * 60, encoded_points[-1][1]))

    encoded = bytearray()
    previous = -1
    for last_seconds, temperature in encoded_points:
        last_seconds = int(last_seconds)
        if last_seconds <= previous or not 0 <= last_seconds <= 24 * 60 * 60:
            raise CubeError("Schedule times must be strictly ascending and within one day")
        if last_seconds % 300:
            raise CubeError("Schedule times must be in five-minute increments")
        previous = last_seconds

        scaled_temperature = float(temperature) * 2
        if not 0 < scaled_temperature <= 63:
            raise CubeError("Thermostat temperatures must be greater than 0 and at most 31.5°C")
        if not scaled_temperature.is_integer():
            raise CubeError("Thermostat temperatures must use 0.5°C increments")
        temp_half_degrees = int(scaled_temperature)
        word = last_seconds // 300 | (temp_half_degrees << 9)
        encoded.extend(struct.pack("!H", word))

    while len(encoded) < 26:
        encoded.extend(encoded[-2:])
    return bytes(encoded[:26])


def _parse_thermostat_config(config: bytes) -> Dict[str, Any]:
    if len(config) < 11:
        raise CubeError("Thermostat configuration is incomplete")

    def temperature(index: int) -> float:
        return config[index] / 2.0

    boost = config[7]
    decalc = config[8]
    result: Dict[str, Any] = {
        "comfort temperature": temperature(0),
        "eco temperature": temperature(1),
        "maximum temperature": temperature(2),
        "minimum temperature": temperature(3),
        "temperature offset": temperature(4) - 3.5,
        "airing temperature": temperature(5),
        "airing mode delay": config[6] * 5 * 60.0,
        "boost duration": 3600.0 if boost >> 5 == 7 else (boost >> 5) * 300.0,
        "boost valve position": (boost & 0x1F) * 0.05,
        "decalcification time": {
            "day": CODE_TO_DAY.get((decalc >> 5) & 0x7, "Sa"),
            "time": (decalc & 0x1F) * 3600.0,
        },
        "maximum valve position": config[9] / 255.0,
        "valve offset": config[10] / 255.0,
        "schedule": {},
    }

    schedule_data = config[11:]
    for day_index, day_name in enumerate(DAY_ORDER):
        day_points: List[Dict[str, Any]] = []
        day_data = schedule_data[day_index * 26:(day_index + 1) * 26]
        for offset in range(0, len(day_data) - 1, 2):
            word = int.from_bytes(day_data[offset:offset + 2], "big")
            end_time = (word & 0x1FF) * 300
            day_points.append({
                "time": end_time,
                "temperature": (word >> 9) / 2.0,
            })
            if end_time >= 24 * 60 * 60:
                break
        result["schedule"][day_name] = day_points
    return result


class CubeClient:
    def __init__(
        self,
        host: str | None = None,
        port: int = DEFAULT_PORT,
        timeout: float = 5.0,
        pair_timeout: float = 60.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.pair_timeout = float(pair_timeout)
        self.sock: socket.socket | None = None
        self._file = None
        self.info: Dict[str, str] = {}
        self.rooms: Dict[int, Dict[str, Any]] = {}
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.radio_state: Dict[str, Any] | None = None
        self._metadata_parts: Dict[int, bytes] = {}
        self._metadata_count = 0

    def __enter__(self) -> "CubeClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def connect(self) -> None:
        if self.sock is not None:
            return
        if self.host is None:
            self.host, self.info = discover_cube(timeout=self.timeout)

        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.settimeout(self.timeout)
            self._file = self.sock.makefile("rb")
            self._read_initial_state()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _read_line(self, timeout: float | None = None) -> bytes:
        if self.sock is None or self._file is None:
            raise CubeError("Not connected to a MAX! Cube")
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            line = self._file.readline()
        except socket.timeout as exc:
            raise CubeError("Timed out waiting for the MAX! Cube") from exc
        if not line:
            raise CubeError("The MAX! Cube closed the connection")
        return line.rstrip(b"\r\n")

    def _read_initial_state(self) -> None:
        while True:
            line = self._read_line()
            if line.startswith(b"H:"):
                self._parse_hello(line[2:])
            elif line.startswith(b"M:"):
                self._parse_metadata_part(line[2:])
            elif line.startswith(b"C:"):
                self._parse_configuration(line[2:])
            elif line.startswith(b"L:"):
                self._parse_status(line[2:])
                return

    def _parse_hello(self, payload: bytes) -> None:
        fields = payload.split(b",")
        if len(fields) < 3:
            raise CubeError("Malformed MAX! Cube hello response")
        self.info.update({
            "serial": fields[0].decode("ascii", errors="replace"),
            "rf_address": fields[1].decode("ascii", errors="replace"),
            "firmware": fields[2].decode("ascii", errors="replace"),
        })

    def _parse_metadata_part(self, payload: bytes) -> None:
        if not payload:
            return
        fields = payload.split(b",", 2)
        if len(fields) != 3:
            raise CubeError("Malformed Cube metadata response")
        try:
            index = int(fields[0], 16)
            count = int(fields[1], 16)
            part = fields[2]
        except ValueError as exc:
            raise CubeError("Invalid Cube metadata part number") from exc

        self._metadata_count = count
        self._metadata_parts[index] = part
        if len(self._metadata_parts) == count:
            self._parse_metadata(base64.b64decode(b"".join(
                self._metadata_parts[i] for i in range(count)
            )))

    def _parse_metadata(self, data: bytes) -> None:
        if len(data) < 3 or data[:2] != b"V\x02":
            raise CubeError("Unsupported MAX! Cube metadata version")
        offset = 2
        room_count = data[offset]
        offset += 1
        for _ in range(room_count):
            if offset + 2 > len(data):
                raise CubeError("Truncated room metadata")
            room_id = data[offset]
            name_length = data[offset + 1]
            offset += 2
            end = offset + name_length
            if end + 3 > len(data):
                raise CubeError("Truncated room metadata")
            self.rooms[room_id] = {
                "id": room_id,
                "name": data[offset:end].decode("utf-8", errors="replace"),
                "address": _format_address(data[end:end + 3]),
            }
            offset = end + 3

        if offset >= len(data):
            raise CubeError("Truncated thermostat metadata")
        device_count = data[offset]
        offset += 1
        for _ in range(device_count):
            if offset + 15 > len(data):
                raise CubeError("Truncated thermostat metadata")
            device_type = data[offset]
            address = _format_address(data[offset + 1:offset + 4])
            serial = data[offset + 4:offset + 14].decode("utf-8", errors="replace").rstrip("\x00* ")
            name_length = data[offset + 14]
            offset += 15
            end = offset + name_length
            if end + 1 > len(data):
                raise CubeError("Truncated thermostat metadata")
            name = data[offset:end].decode("utf-8", errors="replace")
            room_id = data[end]
            offset = end + 1
            self.devices.setdefault(address, {}).update({
                "address": address,
                "type_code": device_type,
                "serial": serial,
                "name": name,
                "room_id": room_id,
            })

    def _parse_configuration(self, payload: bytes) -> None:
        try:
            _, encoded = payload.split(b",", 1)
            data = base64.b64decode(encoded)
        except (ValueError, binascii.Error) as exc:
            raise CubeError("Malformed thermostat configuration response") from exc
        if len(data) < 18:
            raise CubeError("Thermostat configuration response is too short")

        address = _format_address(data[1:4])
        device_type, room_id, firmware, test_result = data[4:8]
        serial = data[8:18].decode("utf-8", errors="replace").rstrip("\x00* ")
        device = self.devices.setdefault(address, {})
        device.update({
            "address": address,
            "type_code": device_type,
            "type": DEVICE_TYPE_MAP.get(device_type, "Unknown"),
            "room_id": room_id,
            "serial": serial,
            "firmware": firmware,
            "test_result": test_result,
        })
        if device_type in {1, 2, 3}:
            device.update(_parse_thermostat_config(data[18:]))
        if room_id > 0 and room_id not in self.rooms:
            self.rooms[room_id] = {"id": room_id, "name": "", "address": "000000"}

    def _parse_status(self, payload: bytes) -> None:
        if not payload:
            return
        try:
            data = base64.b64decode(payload)
        except binascii.Error as exc:
            raise CubeError("Malformed thermostat status response") from exc
        offset = 0
        while offset < len(data):
            record_length = data[offset]
            end = offset + record_length + 1
            if record_length < 8 or end > len(data):
                raise CubeError("Truncated thermostat status record")
            record = data[offset + 1:end]
            address = _format_address(record[:3])
            device = self.devices.setdefault(address, {"address": address})
            flags = int.from_bytes(record[4:6], "big")
            raw_setpoint = record[7]
            mode_code = flags & 0x03
            status: Dict[str, Any] = {
                "mode": MODE_MAP[mode_code],
                "target_temperature": (raw_setpoint & 0x7F) / 2.0,
                "valve_position": record[6],
                "current_temperature": None,
            }
            device_type = device.get("type_code")
            if device_type in {1, 2} and record_length >= 10 and mode_code in {0, 1}:
                temperature = int.from_bytes(record[8:10], "big")
                if temperature:
                    status["current_temperature"] = temperature / 10.0
            elif device_type == 3 and record_length >= 12:
                temperature = ((raw_setpoint & 0x80) << 1) | record[11]
                status["current_temperature"] = temperature / 10.0
            device["status"] = status
            offset = end

    def snapshot(self) -> Dict[str, Any]:
        thermostats = [
            dict(device)
            for device in self.devices.values()
            if device.get("type_code") in {1, 2, 3}
        ]
        rooms = []
        for room_id, room in sorted(self.rooms.items()):
            rooms.append({
                **room,
                "thermostats": [
                    device["address"]
                    for device in thermostats
                    if device.get("room_id") == room_id
                ],
            })
        return {
            "cube": dict(self.info),
            "rooms": rooms,
            "thermostats": thermostats,
        }

    def _send(self, payload: bytes) -> None:
        if self.sock is None:
            raise CubeError("Not connected to a MAX! Cube")
        self.sock.sendall(payload)

    def _send_line(self, line: bytes) -> None:
        self._send(line + b"\r\n")

    def exchange_message(self, message: str) -> str:
        self._send_line(encode_cube_message(message))
        return self._read_line().decode("ascii", errors="replace")

    def _wait_for(self, prefix: bytes, timeout: float | None = None) -> bytes:
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CubeError(f"Timed out waiting for Cube response {prefix.decode('ascii')}")
            line = self._read_line(timeout=remaining)
            if line.startswith(prefix):
                return line[len(prefix):]

    def _write_metadata(self) -> None:
        metadata = bytearray(b"V\x02")
        if len(self.rooms) > 255 or len(self.devices) > 255:
            raise CubeError("The Cube supports at most 255 rooms and devices")

        metadata.append(len(self.rooms))
        for room_id, room in sorted(self.rooms.items()):
            name = _name_bytes(room.get("name", ""))
            address = _decode_address(room.get("address", "000000"))
            metadata.extend((room_id, len(name)))
            metadata.extend(name)
            metadata.extend(address)

        metadata.append(len(self.devices))
        for address, device in sorted(self.devices.items()):
            name = _name_bytes(device.get("name", ""))
            serial = str(device.get("serial", "")).encode("utf-8")[:10].ljust(10, b"\x00")
            metadata.append(int(device.get("type_code", 99)))
            metadata.extend(_decode_address(address))
            metadata.extend(serial)
            metadata.append(len(name))
            metadata.extend(name)
            metadata.append(int(device.get("room_id", 0)))

        encoded = base64.b64encode(metadata).decode("ascii")
        blocks = [encoded[i:i + 1900] for i in range(0, len(encoded), 1900)] or [""]
        for index, block in enumerate(blocks):
            self._send_line(f"m:{index:02x},{block}".encode("ascii"))
            self._wait_for(b"A:")

    def create_room(self, room_id: int, name: str) -> Dict[str, Any]:
        if not 1 <= int(room_id) <= 255:
            raise CubeError("Room ID must be between 1 and 255")
        room_id = int(room_id)
        if room_id in self.rooms:
            raise CubeError(f"Room {room_id} already exists")
        self.rooms[room_id] = {
            "id": room_id,
            "name": _clean_name(name),
            "address": "000000",
        }
        self._write_metadata()
        return self.rooms[room_id].copy()

    def delete_room(self, room_id: int) -> None:
        room_id = int(room_id)
        if room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        if any(device.get("room_id") == room_id for device in self.devices.values()):
            raise CubeError("Move or forget the room's thermostats before deleting the room")
        del self.rooms[room_id]
        self._write_metadata()

    def rename_room(self, room_id: int, name: str) -> Dict[str, Any]:
        room_id = int(room_id)
        if room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        self.rooms[room_id]["name"] = _clean_name(name)
        self._write_metadata()
        return self.rooms[room_id].copy()

    def rename_thermostat(self, address: str, name: str) -> Dict[str, Any]:
        address = address.strip().upper()
        if address not in self.devices:
            raise CubeError(f"Thermostat {address} does not exist")
        self.devices[address]["name"] = _clean_name(name)
        self._write_metadata()
        return self.devices[address].copy()

    def assign_thermostat(self, address: str, room_id: int) -> None:
        address = address.strip().upper()
        room_id = int(room_id)
        device = self.devices.get(address)
        if device is None or device.get("type_code") not in {1, 2, 3}:
            raise CubeError(f"Thermostat {address} does not exist")
        if room_id != 0 and room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        self._send_radio(0x22, address, room_id, bytes([room_id]))
        device["room_id"] = room_id
        self._write_metadata()

    def _send_radio(self, command: int, address: str, room_id: int, data: bytes) -> None:
        packet = (
            bytes([0, 0, command])
            + b"\x00\x00\x00"
            + _decode_address(address)
            + bytes([room_id])
            + data
        )
        self._send_radio_command(packet, f"command {command:02X} for thermostat {address}")

    def _send_radio_command(self, packet: bytes, description: str) -> None:
        deadline = time.monotonic() + RADIO_QUEUE_RETRY_SECONDS
        while True:
            self._send_line(b"s:" + base64.b64encode(packet))
            response = self._wait_for(b"S:")
            fields = response.split(b",", 2)
            if len(fields) != 3:
                raise CubeError(f"Malformed Cube radio response S:{response.decode('ascii', errors='replace')}")
            try:
                duty_cycle = int(fields[0], 16)
                status = int(fields[1])
                free_slots = int(fields[2], 16)
            except ValueError as exc:
                raise CubeError(
                    f"Malformed Cube radio response S:{response.decode('ascii', errors='replace')}"
                ) from exc
            self.radio_state = {
                "duty_cycle": duty_cycle,
                "status": status,
                "free_slots": free_slots,
                "updated_at": time.time(),
            }
            if status == 0:
                return

            response_text = response.decode("ascii", errors="replace")
            if status == 1 and free_slots == 0:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(RADIO_QUEUE_RETRY_INTERVAL, remaining))
                    continue
                raise CubeError(
                    f"Cube radio queue stayed full while sending {description} "
                    f"(response S:{response_text})"
                )
            raise CubeError(f"Cube rejected {description} (response S:{response_text})")

    def adjust_room_setpoint(
        self,
        room_id: int,
        delta: float,
        address: str | None = None,
    ) -> Dict[str, Any]:
        room_id = int(room_id)
        if room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        try:
            delta = float(delta)
        except (TypeError, ValueError) as exc:
            raise CubeError("Setpoint adjustment must be -0.5°C or +0.5°C") from exc
        if not math.isfinite(delta) or delta not in (-0.5, 0.5):
            raise CubeError("Setpoint adjustment must be -0.5°C or +0.5°C")

        thermostats = [
            device for device in self.devices.values()
            if device.get("type_code") in {1, 2, 3} and device.get("room_id") == room_id
        ]
        if not thermostats:
            raise CubeError(f"Room {room_id} has no thermostats")

        if address is not None:
            address = address.strip().upper()
            candidates = [
                device for device in thermostats if device.get("address") == address
            ]
            if not candidates:
                raise CubeError(f"Thermostat {address} is not assigned to room {room_id}")
        else:
            candidates = sorted(thermostats, key=lambda device: device.get("type_code") != 3)
        current = next(
            (
                float(device["status"]["target_temperature"])
                for device in candidates
                if isinstance(device.get("status", {}).get("target_temperature"), (int, float))
                and device["status"]["target_temperature"] > 0
            ),
            None,
        )
        if current is None:
            raise CubeError(f"Cube has not reported a target temperature for room {room_id}")

        minimum = max(float(device.get("minimum temperature", 4.5)) for device in thermostats)
        maximum = min(float(device.get("maximum temperature", 30.5)) for device in thermostats)
        target = current + delta
        if minimum > maximum:
            raise CubeError(f"Thermostats in room {room_id} have incompatible temperature limits")
        if target < minimum or target > maximum:
            raise CubeError(f"Room target must remain between {minimum:g}°C and {maximum:g}°C")

        half_degrees = target * 2
        if not half_degrees.is_integer():
            raise CubeError("Thermostat temperatures must use 0.5°C increments")
        packet = (
            b"\x00\x04\x40"
            + b"\x00" * 6
            + bytes([room_id, int(half_degrees) | 0x40])
        )
        self._send_radio_command(packet, f"setpoint update for room {room_id}")

        return {
            "room_id": room_id,
            "temperature": target,
            "thermostats": [device["address"] for device in thermostats],
        }

    def set_thermostat_mode(self, address: str, mode: str) -> Dict[str, Any]:
        address = address.strip().upper()
        result = self._set_thermostat_modes([address], mode)
        result["address"] = address
        return result

    def set_room_mode(self, room_id: int, mode: str) -> Dict[str, Any]:
        room_id = int(room_id)
        if room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        addresses = [
            str(device["address"])
            for device in self.devices.values()
            if device.get("type_code") in {1, 2, 3} and device.get("room_id") == room_id
        ]
        return {"room_id": room_id, **self._set_thermostat_modes(addresses, mode)}

    def set_all_thermostats_mode(self, mode: str) -> Dict[str, Any]:
        addresses = [
            str(device["address"])
            for device in self.devices.values()
            if device.get("type_code") in {1, 2, 3}
        ]
        return self._set_thermostat_modes(addresses, mode)

    def _set_thermostat_modes(self, addresses: Sequence[str], mode: str) -> Dict[str, Any]:
        mode_codes = {"auto": 0, "manual": 1}
        if not isinstance(mode, str) or mode not in mode_codes:
            raise CubeError("Thermostat mode must be auto or manual")

        commands = []
        for raw_address in addresses:
            address = raw_address.strip().upper()
            device = self.devices.get(address)
            if device is None or device.get("type_code") not in {1, 2, 3}:
                raise CubeError(f"Thermostat {address} does not exist")

            target = device.get("status", {}).get("target_temperature")
            if not isinstance(target, (int, float)) or not math.isfinite(target) or target <= 0:
                raise CubeError(f"Cube has not reported a target temperature for thermostat {address}")
            half_degrees = float(target) * 2
            if not half_degrees.is_integer() or not 0 < half_degrees <= 63:
                raise CubeError(f"Thermostat {address} target must use 0.5°C increments")

            room_id = int(device.get("room_id", 0))
            if room_id not in self.rooms and room_id != 0:
                raise CubeError(f"Thermostat {address} has unknown room {room_id}")
            temperature_and_mode = int(half_degrees) | (mode_codes[mode] << 6)
            packet = (
                b"\x00\x00\x40"
                + b"\x00" * 3
                + _decode_address(address)
                + bytes([room_id, temperature_and_mode])
            )
            commands.append((address, packet, float(target)))

        if not commands:
            raise CubeError("No thermostats are available for the mode change")

        applied = []
        for address, packet, _ in commands:
            try:
                self._send_radio_command(packet, f"{mode} mode change for thermostat {address}")
            except CubeError as exc:
                if applied:
                    raise CubeError(
                        f"Mode change partially applied to {', '.join(applied)}; "
                        f"failed for {address}: {exc}"
                    ) from exc
                raise
            applied.append(address)
        return {"mode": mode, "thermostats": applied}

    def pair_thermostat(self, room_id: int, name: str = "") -> Dict[str, Any]:
        room_id = int(room_id)
        if room_id != 0 and room_id not in self.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        self._send_line(b"n:")
        encoded = self._wait_for(b"N:", timeout=self.pair_timeout)
        try:
            response = base64.b64decode(encoded)
        except base64.binascii.Error as exc:
            raise CubeError("Malformed thermostat pairing response") from exc
        if len(response) < 15:
            raise CubeError("Thermostat pairing response is too short")
        device_type = response[0]
        address = _format_address(response[1:4])
        serial = response[4:14].decode("utf-8", errors="replace").rstrip("\x00* ")
        device = {
            "address": address,
            "type_code": device_type,
            "type": DEVICE_TYPE_MAP.get(device_type, "Unknown"),
            "serial": serial,
            "name": _clean_name(name),
            "room_id": 0,
        }
        self.devices[address] = device
        if room_id:
            try:
                self.assign_thermostat(address, room_id)
            except (CubeError, OSError) as exc:
                raise CubeError(
                    f"Thermostat {address} paired, but assigning it to room {room_id} failed: {exc}"
                ) from exc
        else:
            self._write_metadata()
        return self.devices[address].copy()

    def forget_thermostat(self, address: str) -> None:
        address = address.strip().upper()
        device = self.devices.get(address)
        if device is None or device.get("type_code") not in {1, 2, 3}:
            raise CubeError(f"Thermostat {address} does not exist")
        self._send_line(f"t:01,1,{address}".encode("ascii"))
        self._wait_for(b"A:")
        del self.devices[address]
        self._write_metadata()

    def set_schedule(
        self,
        address: str,
        schedule: Mapping[str, Sequence[Tuple[int, float]]],
        room_id: int | None = None,
    ) -> None:
        address = address.strip().upper()
        device = self.devices.get(address)
        if device is None or device.get("type_code") not in {1, 2, 3}:
            raise CubeError(f"Thermostat {address} does not exist")
        room_id = int(device.get("room_id", 0) if room_id is None else room_id)
        if room_id not in self.rooms and room_id != 0:
            raise CubeError(f"Thermostat {address} has unknown room {room_id}")
        missing = [day for day in DAY_ORDER if day not in schedule]
        if missing:
            raise CubeError("Missing schedule for " + ", ".join(missing))

        address_bytes = _decode_address(address)
        for day_name in DAY_ORDER:
            program = _encode_day_program(schedule[day_name])
            day_code = DAY_TO_CODE[day_name]
            for code, chunk in ((day_code, program[:14]), (day_code + 16, program[14:])):
                packet = (
                    b"\x00\x04\x10\x00\x00\x00"
                    + address_bytes
                    + bytes([room_id, code])
                    + chunk
                )
                self._send_radio_command(
                    packet,
                    f"schedule update for thermostat {address} on {day_name}",
                )


def _clean_name(value: str) -> str:
    name = str(value).strip()
    _name_bytes(name)
    return name


def _name_bytes(value: str) -> bytes:
    name = str(value).strip()
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CubeError("Names must be valid UTF-8 text") from exc
    if len(encoded) > 32:
        raise CubeError("Names must be at most 32 UTF-8 bytes")
    if any(ord(char) < 32 for char in name):
        raise CubeError("Names cannot contain control characters")
    return encoded


def parse_schedule(data: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, List[Tuple[int, float]]]:
    if not isinstance(data, Mapping):
        raise CubeError("Schedule must be an object keyed by weekday")

    result: Dict[str, List[Tuple[int, float]]] = {}
    for day in DAY_ORDER:
        if day not in data:
            continue
        entries = data[day]
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            raise CubeError(f"Schedule entries for {day} must be a list")
        points: List[Tuple[int, float]] = []
        for item in entries:
            if isinstance(item, Mapping):
                time_value = item.get("time")
                temperature_value = item.get("temperature")
            else:
                try:
                    time_value, temperature_value = item
                except (TypeError, ValueError) as exc:
                    raise CubeError(f"Invalid schedule entry for {day}") from exc
            if isinstance(time_value, str):
                try:
                    hours, minutes = time_value.split(":", 1)
                    hours = int(hours)
                    minutes = int(minutes)
                    if not 0 <= minutes < 60 or not 0 <= hours <= 24 or (hours == 24 and minutes):
                        raise ValueError
                    seconds = hours * 3600 + minutes * 60
                except (ValueError, AttributeError) as exc:
                    raise CubeError(f"Invalid schedule time: {time_value!r}") from exc
            else:
                seconds = int(time_value)
            if seconds % 300:
                raise CubeError("Schedule times must be in five-minute increments")
            try:
                temperature = float(temperature_value)
            except (TypeError, ValueError) as exc:
                raise CubeError(f"Invalid temperature for {day}") from exc
            points.append((seconds, temperature))
        result[day] = points
    return result


def apply_schedule(
    cube: CubeClient,
    target: Mapping[str, Any],
    schedule: Mapping[str, Sequence[Tuple[int, float]]],
) -> List[str]:
    scope = target.get("scope")
    if scope == "thermostat":
        addresses = [str(target.get("address", "")).upper()]
    elif scope == "room":
        room_id = int(target.get("room_id", 0))
        if room_id not in cube.rooms:
            raise CubeError(f"Room {room_id} does not exist")
        addresses = [
            address for address, device in cube.devices.items()
            if device.get("type_code") in {1, 2, 3} and device.get("room_id") == room_id
        ]
    elif scope == "all":
        addresses = [
            address for address, device in cube.devices.items()
            if device.get("type_code") in {1, 2, 3}
        ]
    else:
        raise CubeError("Schedule target must be thermostat, room, or all")

    if not addresses:
        raise CubeError("The selected target contains no thermostats")

    completed: List[str] = []
    for address in addresses:
        try:
            cube.set_schedule(address, schedule)
        except (CubeError, OSError) as exc:
            raise CubeError(
                f"Schedule applied to {len(completed)} thermostat(s); failed on {address}: {exc}"
            ) from exc
        completed.append(address)
    return completed
