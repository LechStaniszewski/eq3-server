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


if __name__ == "__main__":
    unittest.main()
