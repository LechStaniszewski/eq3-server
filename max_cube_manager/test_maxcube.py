import base64
import unittest
from unittest.mock import Mock, patch

from .maxcube import (
    CubeClient,
    CubeError,
    DAY_ORDER,
    _encode_day_program,
    apply_schedule,
    parse_schedule,
)


class MemoryCubeClient(CubeClient):
    def __init__(self):
        super().__init__("192.0.2.1")
        self.sent = []

    def _send_line(self, line):
        self.sent.append(line)

    def _wait_for(self, prefix, timeout=None):
        if prefix == b"S:":
            return b"00,0,31"
        return b""


class CubeMetadataTests(unittest.TestCase):
    def test_room_and_device_metadata_round_trip(self):
        cube = MemoryCubeClient()
        cube.rooms[7] = {"id": 7, "name": "Office", "address": "010203"}
        cube.devices["19EF41"] = {
            "address": "19EF41",
            "type_code": 2,
            "serial": "OEQ165628",
            "name": "North",
            "room_id": 7,
        }

        cube._write_metadata()

        payload = cube.sent[0].split(b",", 1)[1]
        restored = MemoryCubeClient()
        restored._parse_metadata(base64.b64decode(payload))
        self.assertEqual(restored.rooms[7]["name"], "Office")
        self.assertEqual(restored.devices["19EF41"]["name"], "North")
        self.assertEqual(restored.devices["19EF41"]["room_id"], 7)

    def test_room_delete_rejects_nonempty_room(self):
        cube = MemoryCubeClient()
        cube.rooms[7] = {"id": 7, "name": "Office", "address": "000000"}
        cube.devices["19EF41"] = {"address": "19EF41", "room_id": 7}
        with self.assertRaises(CubeError):
            cube.delete_room(7)
        self.assertIn(7, cube.rooms)

    def test_pair_thermostat_can_remain_unassigned(self):
        cube = MemoryCubeClient()
        pairing = bytes([2]) + bytes.fromhex("19EF41") + b"SERIAL1234" + b"\x00"
        cube._wait_for = Mock(side_effect=[base64.b64encode(pairing), b""])

        device = cube.pair_thermostat(0)

        self.assertEqual(device["room_id"], 0)
        self.assertEqual(device["address"], "19EF41")
        self.assertEqual(len(cube.sent), 2)
        self.assertEqual(cube.sent[0], b"n:")
        self.assertTrue(cube.sent[1].startswith(b"m:"))


class CubeMessageTests(unittest.TestCase):
    def test_exchange_message_sends_one_crlf_line_and_returns_reply(self):
        cube = CubeClient("192.0.2.1")
        cube.sock = Mock()
        cube._file = Mock()
        cube._file.readline.return_value = b"A:accepted\r\n"

        reply = cube.exchange_message("m:01,block")

        self.assertEqual(reply, "A:accepted")
        cube.sock.sendall.assert_called_once_with(b"m:01,block\r\n")

    def test_exchange_message_rejects_line_breaks_and_non_ascii(self):
        cube = CubeClient("192.0.2.1")

        for message in ("m:01\r\nn:", "é"):
            with self.subTest(message=message), self.assertRaises(ValueError):
                cube.exchange_message(message)


class CubeStatusTests(unittest.TestCase):
    def test_status_parses_target_and_marks_unreported_radiator_temperature(self):
        cube = MemoryCubeClient()
        cube.devices["19EF41"] = {"address": "19EF41", "type_code": 2}
        record = bytes.fromhex("19ef410112390f2f000000")

        cube._parse_status(base64.b64encode(bytes([len(record)]) + record))

        status = cube.devices["19EF41"]["status"]
        self.assertEqual(status["target_temperature"], 23.5)
        self.assertEqual(status["mode"], "manual")
        self.assertEqual(status["valve_position"], 15)
        self.assertIsNone(status["current_temperature"])

    def test_status_parses_measured_temperature_when_present(self):
        cube = MemoryCubeClient()
        cube.devices["19EF41"] = {"address": "19EF41", "type_code": 3}
        record = bytes.fromhex("19ef410112390faf00000020")

        cube._parse_status(base64.b64encode(bytes([len(record)]) + record))

        status = cube.devices["19EF41"]["status"]
        self.assertEqual(status["target_temperature"], 23.5)
        self.assertEqual(status["current_temperature"], 28.8)


class SetpointTests(unittest.TestCase):
    def test_radio_command_retries_when_cube_queue_is_full(self):
        cube = MemoryCubeClient()
        cube._wait_for = Mock(side_effect=[b"64,1,00", b"00,0,31"])

        with patch("max_cube_manager.maxcube.time.sleep") as sleep:
            cube._send_radio_command(b"command", "test command")

        self.assertEqual(len(cube.sent), 2)
        self.assertEqual(cube.radio_state["duty_cycle"], 0)
        self.assertEqual(cube.radio_state["status"], 0)
        self.assertEqual(cube.radio_state["free_slots"], 49)
        self.assertIsInstance(cube.radio_state["updated_at"], float)
        sleep.assert_called_once_with(10.0)

    def test_radio_command_retries_when_no_slots_below_duty_limit(self):
        cube = MemoryCubeClient()
        cube._wait_for = Mock(side_effect=[b"13,1,00", b"00,0,31"])

        with patch("max_cube_manager.maxcube.time.sleep") as sleep:
            cube._send_radio_command(b"command", "test command")

        self.assertEqual(len(cube.sent), 2)
        sleep.assert_called_once_with(10.0)

    def test_radio_command_reports_rejection_when_queue_stays_full(self):
        cube = MemoryCubeClient()
        cube._wait_for = Mock(return_value=b"64,1,00")

        with patch("max_cube_manager.maxcube.RADIO_QUEUE_RETRY_SECONDS", 0):
            with self.assertRaisesRegex(CubeError, "queue stayed full.*S:64,1,00"):
                cube._send_radio_command(b"command", "test command")

        self.assertEqual(len(cube.sent), 1)

    def test_room_setpoint_error_includes_cube_rejection_response(self):
        cube = MemoryCubeClient()
        cube.rooms[19] = {"id": 19}
        cube.devices["19EF41"] = {
            "address": "19EF41",
            "type_code": 2,
            "room_id": 19,
            "minimum temperature": 4.5,
            "maximum temperature": 30.5,
            "status": {"target_temperature": 21.0},
        }
        cube._wait_for = Mock(return_value=b"00,1,31")

        with self.assertRaisesRegex(CubeError, r"response S:00,1,31"):
            cube.adjust_room_setpoint(19, 0.5, address="19EF41")

    def test_room_setpoint_adjustment_broadcasts_to_all_room_thermostats(self):
        cube = MemoryCubeClient()
        cube.rooms[19] = {"id": 19}
        cube.devices = {
            "19EF41": {
                "address": "19EF41",
                "type_code": 2,
                "room_id": 19,
                "minimum temperature": 4.5,
                "maximum temperature": 30.5,
                "status": {"target_temperature": 21.0},
            },
            "1A6878": {
                "address": "1A6878",
                "type_code": 1,
                "room_id": 19,
                "status": {"target_temperature": 21.0},
            },
        }

        result = cube.adjust_room_setpoint(19, 0.5)

        self.assertEqual(result["temperature"], 21.5)
        self.assertEqual(result["thermostats"], ["19EF41", "1A6878"])
        packet = base64.b64decode(cube.sent[0][2:])
        self.assertEqual(packet, b"\x00\x04\x40" + b"\x00" * 6 + bytes([19, 0x6B]))

    def test_room_setpoint_adjustment_respects_device_limits(self):
        cube = MemoryCubeClient()
        cube.rooms[19] = {"id": 19}
        cube.devices["19EF41"] = {
            "address": "19EF41",
            "type_code": 2,
            "room_id": 19,
            "minimum temperature": 4.5,
            "maximum temperature": 21.0,
            "status": {"target_temperature": 21.0},
        }

        with self.assertRaisesRegex(CubeError, "between 4.5°C and 21°C"):
            cube.adjust_room_setpoint(19, 0.5)
        self.assertEqual(cube.sent, [])

    def test_thermostat_adjustment_uses_its_reported_target(self):
        cube = MemoryCubeClient()
        cube.rooms[19] = {"id": 19}
        cube.devices = {
            "19EF41": {
                "address": "19EF41",
                "type_code": 2,
                "room_id": 19,
                "status": {"target_temperature": 23.5},
            },
            "1A6878": {
                "address": "1A6878",
                "type_code": 1,
                "room_id": 19,
                "status": {"target_temperature": 23.0},
            },
        }

        result = cube.adjust_room_setpoint(19, 0.5, address="1A6878")

        self.assertEqual(result["temperature"], 23.5)
        packet = base64.b64decode(cube.sent[0][2:])
        self.assertEqual(packet[-1], 0x6F)


class ScheduleTests(unittest.TestCase):
    def test_schedule_error_includes_cube_rejection_response(self):
        cube = MemoryCubeClient()
        cube.devices["19EF41"] = {"address": "19EF41", "type_code": 2, "room_id": 0}
        cube._wait_for = Mock(return_value=b"00,1,31")
        schedule = {day: [(24 * 3600, 20.0)] for day in DAY_ORDER}

        with self.assertRaisesRegex(CubeError, r"response S:00,1,31"):
            cube.set_schedule("19EF41", schedule)

    def test_program_is_encoded_as_thirteen_words(self):
        program = _encode_day_program([(6 * 3600, 17.0), (22 * 3600, 21.0)])
        self.assertEqual(len(program), 26)

    def test_program_preserves_final_time_and_extends_temperature_to_midnight(self):
        program = _encode_day_program([(16 * 3600, 21.0)])
        points = [
            (
                (int.from_bytes(program[offset:offset + 2], "big") & 0x1FF) * 300,
                (int.from_bytes(program[offset:offset + 2], "big") >> 9) / 2.0,
            )
            for offset in range(0, 4, 2)
        ]

        self.assertEqual(points, [(16 * 3600, 21.0), (24 * 3600, 21.0)])

    def test_program_rejects_non_half_degree_temperatures(self):
        with self.assertRaises(CubeError):
            _encode_day_program([(24 * 3600, 20.25)])

    def test_program_rejects_non_five_minute_final_time(self):
        with self.assertRaisesRegex(CubeError, "five-minute increments"):
            _encode_day_program([(23 * 3600 + 59 * 60, 20.0)])

    def test_schedule_rejects_invalid_json_shapes(self):
        for value in (None, [], {"Mo": None}):
            with self.subTest(value=value):
                with self.assertRaises(CubeError):
                    parse_schedule(value)

    def test_schedule_rejects_times_outside_five_minute_increments(self):
        with self.assertRaisesRegex(CubeError, "five-minute increments"):
            parse_schedule({"Mo": [{"time": "06:01", "temperature": 20.0}]})

    def test_apply_schedule_targets_only_selected_room(self):
        class FakeCube:
            rooms = {1: {}, 2: {}}
            devices = {
                "111111": {"type_code": 1, "room_id": 1},
                "222222": {"type_code": 2, "room_id": 2},
                "333333": {"type_code": 0, "room_id": 1},
            }

            def __init__(self):
                self.applied = []

            def set_schedule(self, address, schedule):
                self.applied.append(address)

        cube = FakeCube()
        schedule = {day: [(24 * 3600, 18.0)] for day in DAY_ORDER}
        applied = apply_schedule(cube, {"scope": "room", "room_id": 1}, schedule)
        self.assertEqual(applied, ["111111"])
        self.assertEqual(cube.applied, ["111111"])


if __name__ == "__main__":
    unittest.main()
