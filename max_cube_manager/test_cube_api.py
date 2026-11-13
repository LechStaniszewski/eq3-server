import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from .cube_api import CubeMessageAPIServer


class FakeCube:
    def __init__(self):
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def exchange_message(self, message):
        self.messages.append(message)
        return "A:accepted"


class CubeMessageAPITests(unittest.TestCase):
    def setUp(self):
        self.server = CubeMessageAPIServer(
            ("127.0.0.1", 0),
            "192.0.2.10",
            62910,
            threading.Lock(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/cube/message"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post_message(self, message):
        request = Request(
            self.url,
            data=json.dumps({"message": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(request, timeout=5)

    def test_forwards_message_to_cube_and_returns_reply_json(self):
        cube = FakeCube()

        with patch("max_cube_manager.cube_api.CubeClient", return_value=cube) as client:
            with self.post_message("m:01,block") as response:
                result = json.loads(response.read())

        self.assertEqual(result, {"reply": "A:accepted"})
        self.assertEqual(cube.messages, ["m:01,block"])
        client.assert_called_once_with("192.0.2.10", 62910)

    def test_rejects_multiline_message_without_connecting_to_cube(self):
        with patch("max_cube_manager.cube_api.CubeClient") as client:
            with self.assertRaises(HTTPError) as error:
                self.post_message("m:01\r\nn:")

        self.assertEqual(error.exception.code, 400)
        self.assertFalse(client.called)


if __name__ == "__main__":
    unittest.main()
