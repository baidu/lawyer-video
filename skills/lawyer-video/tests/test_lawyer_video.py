"""Tests for lawyer_video.py against a local mock server that verifies signatures like the real API.

Run: python3 -m unittest discover -s tests
"""

import hashlib
import hmac
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import lawyer_video as lv  # noqa: E402

APP_ID, SECRET = "abcd1234efgh5678", "s3cret"
ENV_KEYS = (lv.KEY_ENV, lv.BASE_URL_ENV, "XDG_CONFIG_HOME")


@contextmanager
def isolated_env(base_url):
    """No key in the environment, the mock server as base URL, and an empty temporary config directory."""
    saved = {k: os.environ.pop(k) for k in ENV_KEYS if k in os.environ}
    with tempfile.TemporaryDirectory() as d:
        os.environ["XDG_CONFIG_HOME"] = d
        os.environ[lv.BASE_URL_ENV] = base_url
        try:
            yield
        finally:
            for k in ENV_KEYS:
                os.environ.pop(k, None)
            os.environ.update(saved)


class FakeServer(BaseHTTPRequestHandler):
    """Mock API applying the server rules.

    Timestamp within ±300 s, single-use nonce, HMAC(METHOD\\nPATH\\nTS\\nNONCE\\nsha256(body)).
    """

    server_time = None  # when set, used instead of real time to simulate client clock skew
    nonces = set()
    tasks = {}
    polls = {}
    log = []

    def log_message(self, *a):
        pass

    def _reply(self, errno, data=None, status=200):
        body = json.dumps({"errno": errno, "errmsg": "" if errno == 0 else "err%d" % errno, "data": data,
                           "request_id": "r1"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self, body):
        h = self.headers
        now = FakeServer.server_time or int(__import__("time").time())
        ts = int(h["X-Timestamp"])
        if abs(now - ts) > 300:
            return self._reply(40102, {"server_time": now}, 401) or False
        canonical = "\n".join([self.command, self.path, h["X-Timestamp"], h["X-Nonce"],
                               hashlib.sha256(body).hexdigest()])
        want = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if h["X-App-Id"] != APP_ID or not hmac.compare_digest(want, h["X-Sign"]):
            return self._reply(40101, None, 401) or False
        if h["X-Nonce"] in FakeServer.nonces:
            return self._reply(40103, None, 401) or False
        FakeServer.nonces.add(h["X-Nonce"])
        return True

    def do_GET(self):
        FakeServer.log.append(("GET", self.path))
        if not self._auth(b""):
            return
        if self.path.startswith("/bp/openapi/v1/video/avatars?uid=42"):
            return self._reply(0, {"list": [{"avatar_id": 7, "platform": "type_a"}]})
        if self.path == "/bp/openapi/v1/video/quota":
            return self._reply(0, {"quota_daily": 10, "succeeded_today": 0})
        if self.path.startswith("/bp/openapi/v1/video/tasks/"):
            tid = self.path.rsplit("/", 1)[1]
            FakeServer.polls[tid] = FakeServer.polls.get(tid, 0) + 1
            status = "succeeded" if FakeServer.polls[tid] >= 2 else "processing"
            url = "https://v/1.mp4" if status == "succeeded" else ""
            return self._reply(0, {"task_id": tid, "status": status, "video_url": url})
        return self._reply(40401, None, 404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        FakeServer.log.append(("POST", self.path))
        if not self._auth(body):
            return
        p = json.loads(body)
        key = p["idempotent_key"]
        tid = FakeServer.tasks.setdefault(key, "ov%d" % (len(FakeServer.tasks) + 1))
        return self._reply(0, {"task_id": tid, "status": "processing"})


class LawyerVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), FakeServer)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/bp/openapi/v1/video" % cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        FakeServer.server_time = None
        FakeServer.log.clear()

    def client(self):
        return lv.Client(self.base, APP_ID, SECRET)

    def run_cli(self, argv, client=None, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = lv.main(argv, client=client, stdin=stdin)
        return code, out.getvalue(), err.getvalue()

    def test_sign_vector(self):
        # Shared test vector with the server; the expected value was computed independently
        # with `openssl dgst -sha256 -hmac secret`
        c = lv.canonical_string("post", "/openapi/v1/video/tasks", 1761100000, "abcdefghijklmnop", b"")
        self.assertEqual(c, "POST\n/openapi/v1/video/tasks\n1761100000\nabcdefghijklmnop\n"
                            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(lv.sign("secret", c), "8de1571bac9f30b4a8b0e6a312b09cc0dcd82977e763bb718cf5992e386d1212")

    def test_signed_get_with_query(self):
        code, out, _ = self.run_cli(["avatars", "--uid", "42"], client=self.client())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["data"]["list"][0]["avatar_id"], 7)

    def test_clock_skew_recovers_once(self):
        FakeServer.server_time = int(__import__("time").time()) + 3600
        code, out, _ = self.run_cli(["avatars", "--uid", "42"], client=self.client())
        self.assertEqual(code, 0, out)
        self.assertEqual(len(FakeServer.log), 2)  # first attempt gets 40102, then one re-signed request

    def test_submit_is_idempotent_and_returns_key(self):
        c = self.client()
        code, out, _ = self.run_cli(["submit", "--uid", "42", "--avatar-id", "7", "--title", "t", "--script", "s",
                                     "--idempotent-key", "k1"], client=c)
        code2, out2, _ = self.run_cli(["submit", "--uid", "42", "--avatar-id", "7", "--title", "t", "--script", "s",
                                       "--idempotent-key", "k1"], client=c)
        self.assertEqual((code, code2), (0, 0))
        self.assertEqual(json.loads(out)["data"]["task_id"], json.loads(out2)["data"]["task_id"])
        _, out3, _ = self.run_cli(["submit", "--uid", "42", "--avatar-id", "7", "--title", "t", "--script", "s"],
                                  client=c)
        self.assertTrue(json.loads(out3)["data"]["idempotent_key"].startswith("lv-"))

    def test_submit_rejects_long_script_locally(self):
        code, _, err = self.run_cli(["submit", "--uid", "1", "--avatar-id", "1", "--title", "t",
                                     "--script", "字" * 301], client=self.client())
        self.assertEqual(code, lv.EXIT_USAGE)
        self.assertEqual(FakeServer.log, [])

    def test_wait_until_succeeded(self):
        args = lv.build_parser().parse_args(["wait", "--task-id", "ov9", "--timeout", "600"])
        slept = []
        data = lv.cmd_wait(self.client(), args, sleep=slept.append, clock=lambda: sum(slept))
        self.assertEqual(data["status"], "succeeded")
        self.assertEqual(slept, [60, 30])

    def test_wait_timeout(self):
        args = lv.build_parser().parse_args(["wait", "--task-id", "ov-never", "--timeout", "50"])
        FakeServer.polls["ov-never"] = -100
        slept = []
        with self.assertRaises(lv.CliError) as ctx:
            lv.cmd_wait(self.client(), args, sleep=slept.append, clock=lambda: sum(slept))
        self.assertEqual(ctx.exception.exit_code, lv.EXIT_TIMEOUT)

    def test_api_error_maps_exit_code(self):
        code, _, err = self.run_cli(["avatars", "--uid", "999"], client=self.client())
        self.assertEqual(code, lv.EXIT_API)
        self.assertEqual(json.loads(err)["errno"], 40401)

    def test_missing_key_and_no_secret_leak(self):
        with isolated_env(self.base):
            os.environ.pop(lv.BASE_URL_ENV)
            code, _, err = self.run_cli(["quota"])
            self.assertEqual(code, lv.EXIT_USAGE)
            self.assertTrue(json.loads(err)["need_api_key"])
            self.assertIn("configure", err)
            self.assertNotIn(lv.BASE_URL_ENV, err)  # only the API key is required
            os.environ[lv.BASE_URL_ENV] = self.base
            os.environ[lv.KEY_ENV] = "bad-key-value-SHOULD-NOT-ECHO"
            code, out, err = self.run_cli(["quota"])
            self.assertEqual(code, lv.EXIT_USAGE)
            self.assertNotIn("SHOULD-NOT-ECHO", out + err)

    def test_configure_verifies_saves_and_is_used(self):
        key = "ovk_%s.%s" % (APP_ID, SECRET)
        with isolated_env(self.base):
            code, out, err = self.run_cli(["configure"], stdin=io.StringIO(key + "\n"))
            self.assertEqual(code, 0, err)
            self.assertNotIn(SECRET, out + err)
            path = Path(lv.credentials_path())
            self.assertEqual(json.loads(out)["data"]["saved_to"], str(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            code, out, _ = self.run_cli(["quota"])  # no env var: the saved key is used
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["data"]["quota_daily"], 10)

    def test_configure_rejected_key_is_not_saved(self):
        with isolated_env(self.base):
            code, out, err = self.run_cli(["configure"], stdin=io.StringIO("ovk_%s.wrong-REJECTED" % APP_ID))
            self.assertEqual(code, lv.EXIT_API)
            self.assertEqual(json.loads(err)["errno"], 40101)
            self.assertNotIn("REJECTED", out + err)
            self.assertFalse(Path(lv.credentials_path()).exists())
            code, _, err = self.run_cli(["configure"], stdin=io.StringIO("not-a-key-HIDDEN"))
            self.assertEqual(code, lv.EXIT_USAGE)
            self.assertNotIn("HIDDEN", err)

    def test_default_base_url(self):
        env = {k: os.environ.pop(k) for k in (lv.BASE_URL_ENV,) if k in os.environ}
        try:
            self.assertEqual(lv.load_base_url(None), lv.DEFAULT_BASE_URL)
            os.environ[lv.BASE_URL_ENV] = "http://127.0.0.1:1/x/"
            self.assertEqual(lv.load_base_url(None), "http://127.0.0.1:1/x")
            self.assertEqual(lv.load_base_url("https://a.example/v"), "https://a.example/v")
            with self.assertRaises(lv.CliError):
                lv.load_base_url("ftp://bad")
        finally:
            os.environ.pop(lv.BASE_URL_ENV, None)
            os.environ.update(env)


if __name__ == "__main__":
    unittest.main()
