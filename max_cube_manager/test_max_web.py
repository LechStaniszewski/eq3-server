import io
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from .max_web import (
    AutomationSettings,
    Handler,
    HourlyAutoModeJob,
    PAGE,
    main as web_main,
)
from .maxcube import CubeError, DAY_ORDER


class FakeCube:
    def __init__(self):
        self.saved_schedules = []
        self.updates = []
        self.snapshot_count = 0
        self.radio_state = {"duty_cycle": 100, "status": 1, "free_slots": 0, "updated_at": 1}
        self.devices = {
            "19EF41": {"address": "19EF41", "type_code": 2, "room_id": 7}
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def snapshot(self):
        self.snapshot_count += 1
        return {}

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

    def pair_thermostat(self, room_id):
        self.updates.append(("pair", room_id))
        return {"address": "19EF41", "room_id": room_id}

    def set_thermostat_mode(self, address, mode):
        self.updates.append(("thermostat_mode", address, mode))
        return {"address": address, "mode": mode, "thermostats": [address]}

    def set_room_mode(self, room_id, mode):
        self.updates.append(("room_mode", room_id, mode))
        return {"room_id": room_id, "mode": mode, "thermostats": ["19EF41"]}

    def set_all_thermostats_mode(self, mode):
        self.updates.append(("all_mode", mode))
        return {"mode": mode, "thermostats": ["19EF41", "1A6878"]}


class WebScheduleTests(unittest.TestCase):
    def make_handler(self):
        handler = object.__new__(Handler)
        handler.command = "POST"
        handler.server = SimpleNamespace(
            cube_lock=threading.Lock(),
            cube_host="192.0.2.1",
            cube_port=62910,
            debug=False,
            radio_state=None,
        )
        return handler

    def test_cube_operation_publishes_latest_radio_state(self):
        handler = self.make_handler()
        cube = FakeCube()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            handler._with_cube(lambda client: None)

        self.assertEqual(handler.server.radio_state, cube.radio_state)

    def test_radio_state_route_returns_last_cube_response(self):
        handler = object.__new__(Handler)
        handler.path = "/api/radio/state"
        handler.server = SimpleNamespace(
            radio_state={"duty_cycle": 100, "status": 1, "free_slots": 0}
        )
        handler._check_origin = lambda: True
        handler._send_json = lambda status, data: setattr(handler, "sent", (status, data))

        handler.do_GET()

        self.assertEqual(handler.sent, (200, {"radio": handler.server.radio_state}))

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
        self.assertIn("Schedule sent", result["message"])
        self.assertEqual(len(cube.saved_schedules), 1)
        self.assertEqual(cube.saved_schedules[0][0], "19EF41")

    def test_schedule_route_rejects_broad_target_payloads(self):
        handler = self.make_handler()

        with self.assertRaisesRegex(ValueError, "thermostat address is required"):
            handler._route_mutation(
                "/api/schedules/apply",
                {"target": {"scope": "all"}, "schedule": {}},
            )

    def test_pair_route_defaults_new_thermostat_to_unassigned(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation("/api/thermostats/pair", {})

        self.assertEqual(result["thermostat"]["room_id"], 0)
        self.assertIn("Unassigned", result["message"])
        self.assertEqual(cube.updates, [("pair", 0)])

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

    def test_thermostat_mode_route_sets_one_thermostat(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation(
                "/api/thermostats/19EF41/mode",
                {"mode": "auto"},
            )

        self.assertEqual(result["thermostats"], ["19EF41"])
        self.assertIn("auto", result["message"])
        self.assertEqual(cube.updates, [("thermostat_mode", "19EF41", "auto")])

    def test_room_mode_route_sets_room_thermostats(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation("/api/rooms/7/mode", {"mode": "manual"})

        self.assertEqual(result["thermostats"], ["19EF41"])
        self.assertIn("room 7", result["message"])
        self.assertEqual(cube.updates, [("room_mode", 7, "manual")])

    def test_all_mode_route_sets_every_thermostat(self):
        cube = FakeCube()
        handler = self.make_handler()

        with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
            result = handler._route_mutation("/api/thermostats/mode", {"mode": "auto"})

        self.assertEqual(result["thermostats"], ["19EF41", "1A6878"])
        self.assertIn("all 2 thermostat(s)", result["message"])
        self.assertEqual(cube.updates, [("all_mode", "auto")])

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

    def test_mode_controls_use_refreshed_status_and_highlight_active_mode(self):
        self.assertIn('mode==="auto"?"Auto":"Manual"', PAGE)
        self.assertIn("function activeMode(devices)", PAGE)
        self.assertIn("device.status?.mode===mode", PAGE)
        self.assertIn("activeMode(state.thermostats)", PAGE)
        self.assertIn("if(await refreshAfterUpdate())setStatus(result.message)", PAGE)
        self.assertIn(
            ".mode-button.active,.mode-button.active:hover{background:#1769d2",
            PAGE,
        )

    def test_ui_polls_status_and_waits_after_cube_updates(self):
        self.assertIn('id="force-auto-hourly">Force switch to auto every 1h', PAGE)
        self.assertIn("setInterval(()=>refresh(),STATUS_REFRESH_INTERVAL_SECONDS*1000)", PAGE)
        self.assertIn("setTimeout(resolve,5000)", PAGE)
        self.assertIn(".menu-content>input,.menu-content>select{grid-column:1}", PAGE)


class AutomationSettingsTests(unittest.TestCase):
    def test_hourly_auto_setting_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automation.json"
            settings = AutomationSettings(path)

            self.assertEqual(settings.snapshot(), {"force_auto_hourly": False})
            self.assertEqual(
                settings.set_force_auto_hourly(True),
                {"force_auto_hourly": True},
            )
            self.assertEqual(
                AutomationSettings(path).snapshot(),
                {"force_auto_hourly": True},
            )

    def test_state_route_exposes_persisted_hourly_auto_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AutomationSettings(Path(directory) / "automation.json")
            settings.set_force_auto_hourly(True)
            handler = object.__new__(Handler)
            handler.command = "GET"
            handler.path = "/api/state"
            handler.server = SimpleNamespace(
                cube_lock=threading.Lock(),
                cube_host="192.0.2.1",
                cube_port=62910,
                debug=False,
                radio_state=None,
                automation_settings=settings,
            )
            handler._check_origin = lambda: True
            handler._send_json = lambda status, data: setattr(handler, "sent", (status, data))

            with patch("max_cube_manager.max_web.CubeClient", return_value=FakeCube()):
                handler.do_GET()

            self.assertEqual(handler.sent[0], 200)
            self.assertEqual(
                handler.sent[1]["automation"],
                {"force_auto_hourly": True},
            )

    def test_auto_hourly_route_persists_checkbox_state(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AutomationSettings(Path(directory) / "automation.json")
            handler = object.__new__(Handler)
            handler.command = "POST"
            handler.server = SimpleNamespace(
                automation_settings=settings,
                auto_mode_job=None,
            )

            result = handler._route_mutation(
                "/api/automation/auto-hourly",
                {"enabled": True},
            )

            self.assertEqual(result["automation"], {"force_auto_hourly": True})
            self.assertTrue(settings.snapshot()["force_auto_hourly"])

    def test_hourly_job_switches_to_auto_then_refreshes_status(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AutomationSettings(Path(directory) / "automation.json")
            settings.set_force_auto_hourly(True)
            cube = FakeCube()
            server = SimpleNamespace(
                cube_lock=threading.Lock(),
                cube_host="192.0.2.1",
                cube_port=62910,
                radio_state=None,
            )
            job = HourlyAutoModeJob(server, settings)

            with patch("max_cube_manager.max_web.CubeClient", return_value=cube):
                with patch.object(job._stop, "wait", return_value=False) as wait:
                    job._switch_all_to_auto()

            self.assertEqual(cube.updates, [("all_mode", "auto")])
            self.assertEqual(cube.snapshot_count, 2)
            wait.assert_called_once_with(5)

    def test_hourly_auto_setting_rejects_non_boolean_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automation.json"
            path.write_text('{"force_auto_hourly":"yes"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid force_auto_hourly"):
                AutomationSettings(path)


if __name__ == "__main__":
    unittest.main()
