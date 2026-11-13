import io
import threading
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

from .max_web import Handler, PAGE, main as web_main
from .maxcube import CubeError, DAY_ORDER


class FakeCube:
    def __init__(self):
        self.saved_schedules = []
        self.updates = []
        self.devices = {
            "19EF41": {"address": "19EF41", "type_code": 2, "room_id": 7}
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def set_schedule(self, address, schedule):
        self.saved_schedules.append((address, schedule))

    def assign_thermostat(self, address, room_id):
        self.updates.append(("room", address, room_id))

    def rename_thermostat(self, address, name):
        self.updates.append(("thermostat_name", address, name))
        return {"address": address, "name": name, "room_id": 7}

    def rename_room(self, room_id, name):
        self.updates.append(("room_name", room_id, name))
        return {"id": room_id, "name": name}

    def adjust_room_setpoint(self, room_id, delta, address=None):
        self.updates.append(("setpoint", room_id, delta, address))
        return {
            "room_id": room_id,
            "temperature": 21.5,
            "thermostats": ["19EF41", "1A6878"],
        }


class WebScheduleTests(unittest.TestCase):
    def make_handler(self):
        handler = object.__new__(Handler)
        handler.command = "POST"
        handler.server = SimpleNamespace(
            cube_lock=threading.Lock(),
            cube_host="192.0.2.1",
            cube_port=62910,
            debug=False,
        )
        return handler

    def test_schedule_route_saves_only_the_named_thermostat(self):
        cube = FakeCube()
        handler = self.make_handler()
        schedule = {
            day: [{"time": "24:00", "temperature": 18}]
            for day in DAY_ORDER
        }

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation(
                "/api/schedules/apply",
                {"address": "19EF41", "schedule": schedule},
            )

        self.assertEqual(result["address"], "19EF41")
        self.assertEqual(len(cube.saved_schedules), 1)
        self.assertEqual(cube.saved_schedules[0][0], "19EF41")

    def test_schedule_route_rejects_broad_target_payloads(self):
        handler = self.make_handler()

        with self.assertRaisesRegex(ValueError, "thermostat address is required"):
            handler._route_mutation(
                "/api/schedules/apply",
                {"target": {"scope": "all"}, "schedule": {}},
            )

    def test_thermostat_update_saves_name_and_room(self):
        cube = FakeCube()
        handler = self.make_handler()
        handler.command = "PATCH"

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation(
                "/api/thermostats/19EF41",
                {"name": "North", "room_id": 7},
            )

        self.assertEqual(result["thermostat"]["name"], "North")
        self.assertEqual(
            cube.updates,
            [("room", "19EF41", 7), ("thermostat_name", "19EF41", "North")],
        )

    def test_room_update_saves_name(self):
        cube = FakeCube()
        handler = self.make_handler()
        handler.command = "PATCH"

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation("/api/rooms/7", {"name": "Office"})

        self.assertEqual(result["room"]["name"], "Office")
        self.assertEqual(cube.updates, [("room_name", 7, "Office")])

    def test_room_temperature_route_reports_shared_effect(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation(
                "/api/rooms/7/setpoint",
                {"delta": 0.5},
            )

        self.assertIn("affects all 2 thermostat(s)", result["message"])
        self.assertEqual(cube.updates, [("setpoint", 7, 0.5, None)])

    def test_thermostat_temperature_route_uses_its_room_setpoint(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation(
                "/api/thermostats/19EF41/setpoint",
                {"delta": -0.5},
            )

        self.assertEqual(result["room_id"], 7)
        self.assertEqual(cube.updates, [("setpoint", 7, -0.5, "19EF41")])

    def test_debug_mode_logs_cube_operation_timing(self):
        handler = self.make_handler()
        handler.server.debug = True

        with patch("max_cube_manager.max_web.CubeClient", return_value=FakeCube()):
            with self.assertLogs("max_cube_manager.max_web", level="DEBUG") as captured:
                handler._with_cube(lambda cube: None)

        self.assertTrue(any("completed in" in message for message in captured.output))

    def test_debug_mode_logs_cube_operation_errors(self):
        handler = self.make_handler()
        handler.server.debug = True

        with patch(
            "max_cube_manager.max_web.CubeClient",
            side_effect=CubeError("Cube timeout"),
        ):
            with self.assertLogs("max_cube_manager.max_web", level="DEBUG") as captured:
                with self.assertRaisesRegex(CubeError, "Cube timeout"):
                    handler._with_cube(lambda cube: None)

        self.assertTrue(any("failed after" in message for message in captured.output))


class IngressSecurityTests(unittest.TestCase):
    def make_handler(
        self,
        client_ip="172.30.32.2",
        host="ha.local:8123",
        origin="http://ha.local:8123",
    ):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(allow_home_assistant_ingress=True)
        handler.client_address = (client_ip, 1234)
        handler.headers = {"Host": host}
        if origin is not None:
            handler.headers["Origin"] = origin
        return handler

    def test_allows_same_origin_supervisor_ingress_request(self):
        handler = self.make_handler()

        self.assertTrue(handler._check_origin())

    def test_rejects_requests_not_from_supervisor_ingress(self):
        handler = self.make_handler(client_ip="192.0.2.10")

        with patch.object(handler, "_send_json") as send_json:
            self.assertFalse(handler._check_origin())

        send_json.assert_called_once_with(
            403, {"error": "Only Home Assistant ingress requests are allowed"}
        )

    def test_rejects_cross_origin_supervisor_ingress_request(self):
        handler = self.make_handler(origin="http://attacker.example")

        with patch.object(handler, "_send_json") as send_json:
            self.assertFalse(handler._check_origin())

        send_json.assert_called_once_with(
            403, {"error": "Cross-origin requests are not allowed"}
        )

    def test_rejects_supervisor_ingress_origin_with_different_port(self):
        handler = self.make_handler(origin="http://ha.local:8124")

        with patch.object(handler, "_send_json") as send_json:
            self.assertFalse(handler._check_origin())

        send_json.assert_called_once_with(
            403, {"error": "Cross-origin requests are not allowed"}
        )

    def test_non_loopback_bind_requires_home_assistant_ingress_mode(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            web_main(["--bind", "0.0.0.0"])

        self.assertEqual(error.exception.code, 2)


class IngressFrontendTests(unittest.TestCase):
    def test_api_requests_resolve_under_the_current_ingress_path(self):
        self.assertIn(
            'new URL(path.replace(/^\\/+/',
            PAGE,
        )
        self.assertIn("document.baseURI)", PAGE)
        self.assertIn("fetch(requestUrl", PAGE)

    def test_connection_errors_replace_the_connecting_indicator(self):
        self.assertIn("Connection failed · ${error.message}", PAGE)


if __name__ == "__main__":
    unittest.main()
