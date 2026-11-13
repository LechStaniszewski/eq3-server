import unittest

from .home_assistant import build_web_args


class HomeAssistantAppTests(unittest.TestCase):
    def test_builds_ingress_arguments_with_configured_cube(self):
        args = build_web_args({"cube_host": " 192.0.2.10 ", "cube_port": 63000})

        self.assertEqual(
            args,
            [
                "--cube-host",
                "192.0.2.10",
                "--cube-port",
                "63000",
                "--bind",
                "0.0.0.0",
                "--port",
                "8765",
                "--home-assistant-ingress",
                "--auto-mode-interval-hours",
                "1",
            ],
        )

    def test_requires_cube_host(self):
        with self.assertRaisesRegex(ValueError, "Set the MAX! Cube address"):
            build_web_args({"cube_port": 62910})

    def test_rejects_invalid_cube_port(self):
        for port in (0, 65536, True, "not-a-port"):
            with self.subTest(port=port), self.assertRaisesRegex(
                ValueError, "MAX! Cube port"
            ):
                build_web_args({"cube_host": "192.0.2.10", "cube_port": port})

    def test_debug_option_enables_detailed_logging(self):
        args = build_web_args({"cube_host": "192.0.2.10", "debug": True})

        self.assertEqual(args[-1], "--debug")

    def test_rejects_invalid_debug_option(self):
        with self.assertRaisesRegex(ValueError, "Debug logging"):
            build_web_args({"cube_host": "192.0.2.10", "debug": "yes"})

    def test_auto_mode_defaults_to_enabled_with_one_hour_interval(self):
        args = build_web_args({"cube_host": "192.0.2.10"})

        self.assertIn("--auto-mode-interval-hours", args)
        self.assertEqual(args[args.index("--auto-mode-interval-hours") + 1], "1")
        self.assertNotIn("--disable-auto-mode", args)

    def test_auto_mode_configuration_can_disable_job_and_set_period(self):
        args = build_web_args({
            "cube_host": "192.0.2.10",
            "auto_mode_enabled": False,
            "auto_mode_interval_hours": 3,
        })

        self.assertIn("--disable-auto-mode", args)
        self.assertEqual(args[args.index("--auto-mode-interval-hours") + 1], "3")

    def test_rejects_invalid_auto_mode_options(self):
        invalid_options = (
            {"auto_mode_enabled": "yes"},
            {"auto_mode_interval_hours": 0},
            {"auto_mode_interval_hours": 25},
            {"auto_mode_interval_hours": True},
            {"auto_mode_interval_hours": "2"},
        )
        for option in invalid_options:
            with self.subTest(option=option), self.assertRaises(ValueError):
                build_web_args({"cube_host": "192.0.2.10", **option})


if __name__ == "__main__":
    unittest.main()
