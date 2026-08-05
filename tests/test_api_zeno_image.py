from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "api_zeno_image.py"
SPEC = importlib.util.spec_from_file_location("api_zeno_image", SCRIPT)
assert SPEC and SPEC.loader
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class MockHandler(BaseHTTPRequestHandler):
    requests = []
    status = 200
    response = {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.requests.append(
            {
                "path": self.path,
                "body": body,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
            }
        )
        payload = json.dumps(self.__class__.response).encode()
        self.send_response(self.__class__.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class ApiZenoImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        MockHandler.requests = []
        MockHandler.status = 200
        MockHandler.response = {
            "data": [{"b64_json": base64.b64encode(b"image-bytes").decode()}]
        }
        self.env = mock.patch.dict(
            os.environ,
            {
                "API_ZENO_KEY": "test-key",
                "API_ZENO_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
                "API_ZENO_CONFIG_DIR": str(Path(self.temp.name) / "config"),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_main(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = CLIENT.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_generate_sends_one_request_and_saves_base64(self):
        output = Path(self.temp.name) / "result.png"
        code, stdout, stderr = self.run_main(
            [
                "generate",
                "--prompt",
                "studio product photo",
                "--model",
                "gpt-image-2",
                "--size",
                "1024x1024",
                "--quality",
                "high",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(0, code, stderr)
        self.assertEqual(b"image-bytes", output.read_bytes())
        self.assertEqual([str(output.resolve())], json.loads(stdout)["outputs"])
        self.assertEqual(1, len(MockHandler.requests))
        request = MockHandler.requests[0]
        self.assertEqual("/v1/images/generations", request["path"])
        self.assertEqual("Bearer test-key", request["authorization"])
        payload = json.loads(request["body"])
        self.assertEqual("studio product photo", payload["prompt"])
        self.assertEqual("high", payload["quality"])

    def test_generate_does_not_overwrite_existing_output(self):
        output = Path(self.temp.name) / "result.png"
        output.write_bytes(b"existing")
        code, stdout, stderr = self.run_main(
            [
                "generate",
                "--prompt",
                "new image",
                "--model",
                "gpt-image-2",
                "--size",
                "1024x1024",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(0, code, stderr)
        self.assertEqual(b"existing", output.read_bytes())
        saved = Path(json.loads(stdout)["outputs"][0])
        self.assertEqual("result-1.png", saved.name)
        self.assertEqual(b"image-bytes", saved.read_bytes())

    def test_edit_uses_multipart_and_local_image(self):
        source = Path(self.temp.name) / "source.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nlocal-image")
        output = Path(self.temp.name) / "edited.png"
        code, _, stderr = self.run_main(
            [
                "edit",
                "--image",
                str(source),
                "--prompt",
                "make the background white",
                "--model",
                "gpt-image-2",
                "--size",
                "1024x1024",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(0, code, stderr)
        request = MockHandler.requests[0]
        self.assertEqual("/v1/images/edits", request["path"])
        self.assertTrue(request["content_type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="image"', request["body"])
        self.assertIn(b"local-image", request["body"])

    def test_rejects_edit_with_text_only_model_before_request(self):
        source = Path(self.temp.name) / "source.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nlocal-image")
        code, _, stderr = self.run_main(
            [
                "edit",
                "--image",
                str(source),
                "--prompt",
                "edit",
                "--model",
                "gemini-3.1-flash-image-1k",
            ]
        )
        self.assertEqual(1, code)
        self.assertIn("does not support edit", stderr)
        self.assertEqual([], MockHandler.requests)

    def test_api_error_is_not_retried(self):
        MockHandler.status = 401
        MockHandler.response = {
            "error": {"code": "key_expired", "message": "The API key expired"},
            "request_id": "request-123",
        }
        code, _, stderr = self.run_main(
            ["generate", "--prompt", "test", "--model", "gpt-image-2", "--size", "1024x1024"]
        )
        self.assertEqual(1, code)
        self.assertIn("key_expired", stderr)
        self.assertEqual(1, len(MockHandler.requests))

    def test_url_result_rejects_private_network_download(self):
        MockHandler.response = {
            "data": [{"url": f"http://127.0.0.1:{self.server.server_port}/image.png"}]
        }
        output = Path(self.temp.name) / "unsafe.png"
        code, _, stderr = self.run_main(
            [
                "generate",
                "--prompt",
                "test",
                "--model",
                "gpt-image-2",
                "--size",
                "1024x1024",
                "--response-format",
                "url",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(1, code)
        self.assertIn("non-public address", stderr)
        self.assertFalse(output.exists())

    def test_status_never_prints_key(self):
        code, stdout, stderr = self.run_main(["status"])
        self.assertEqual(0, code, stderr)
        self.assertNotIn("test-key", stdout)
        self.assertIn('"key_source": "environment"', stdout)

    def test_default_base_url_uses_api_zeno_domain(self):
        with mock.patch.dict(os.environ, {"API_ZENO_BASE_URL": ""}, clear=False):
            self.assertEqual("https://api-zeno.com/v1", CLIENT._base_url())

    def test_rejects_non_image_input_before_request(self):
        source = Path(self.temp.name) / "source.png"
        source.write_bytes(b"not-an-image")
        code, _, stderr = self.run_main(
            [
                "edit",
                "--image",
                str(source),
                "--prompt",
                "edit",
                "--model",
                "gpt-image-2",
                "--size",
                "1024x1024",
            ]
        )
        self.assertEqual(1, code)
        self.assertIn("must be PNG, JPEG, or WebP", stderr)
        self.assertEqual([], MockHandler.requests)

    def test_models_lists_api_zeno_catalog(self):
        code, stdout, stderr = self.run_main(["models"])
        self.assertEqual(0, code, stderr)
        catalog = json.loads(stdout)
        self.assertIn("gpt-image-2", catalog["models"])
        self.assertIn("gemini-3.1-flash-image-4k", catalog["models"])

    def test_configure_reads_key_from_stdin_and_clear_key_removes_it(self):
        with mock.patch.dict(os.environ, {"API_ZENO_KEY": ""}, clear=False):
            with mock.patch.object(CLIENT.sys, "stdin", io.StringIO("saved-key\n")):
                code, stdout, stderr = self.run_main(["configure"])
            self.assertEqual(0, code, stderr)
            self.assertNotIn("saved-key", stdout)
            credentials = json.loads(CLIENT.credential_path().read_text(encoding="utf-8"))
            self.assertEqual("saved-key", credentials["api_key"])
            code, stdout, stderr = self.run_main(["clear-key"])
            self.assertEqual(0, code, stderr)
            self.assertTrue(json.loads(stdout)["removed"])
            credentials = json.loads(CLIENT.credential_path().read_text(encoding="utf-8"))
            self.assertNotIn("api_key", credentials)


if __name__ == "__main__":
    unittest.main()
