#!/usr/bin/env python3
"""Command-line client for the lawyer video OpenAPI (the single entry point of the lawyer-video skill).

Standard library only. The API key never appears in any output.
Results are printed to stdout as JSON; errors go to stderr with a non-zero exit code.

API key (ovk_<app_id>.<secret>), first match wins:
  LAWYER_VIDEO_API_KEY   environment variable
  credentials file       written by `configure` (key read from stdin, verified, saved with mode 0600) at
                         $XDG_CONFIG_HOME/lawyer-video/credentials, default ~/.config/lawyer-video/credentials
Optional:
  LAWYER_VIDEO_BASE_URL  overrides the default OpenAPI base URL (for testing); --base-url overrides both
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY_ENV = "LAWYER_VIDEO_API_KEY"
BASE_URL_ENV = "LAWYER_VIDEO_BASE_URL"
DEFAULT_BASE_URL = "https://lvlin.baidu.com/bp/openapi/v1/video"
KEY_PREFIX = "ovk_"
HTTP_TIMEOUT = 15
MAX_SCRIPT_CHARS = 300
MAX_TITLE_CHARS = 64
DEFAULT_WAIT_SECONDS = 30 * 60
TERMINAL = ("succeeded", "failed")

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 2        # bad arguments or local config: fix them and retry
EXIT_API = 3          # the API rejected the request (see errno)
EXIT_NETWORK = 4      # network error / service unavailable
EXIT_TIMEOUT = 5      # wait timed out; the task is still processing


class CliError(Exception):
    """Expected failure carrying an exit code and the JSON payload shown to the caller."""
    def __init__(self, exit_code, payload):
        """Store the exit code and error payload."""
        super().__init__(payload.get("errmsg", ""))
        self.exit_code = exit_code
        self.payload = payload


def fail(exit_code, errmsg, **extra):
    """Raise CliError with the standard error payload."""
    raise CliError(exit_code, dict({"ok": False, "errmsg": errmsg}, **extra))


def credentials_path():
    """Location of the saved API key: $XDG_CONFIG_HOME/lawyer-video/credentials, default under ~/.config."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "lawyer-video", "credentials")


def split_key(raw, source):
    """Validate the ovk_<app_id>.<secret> format and split it; error messages never include the value."""
    app_id, _, secret = raw[len(KEY_PREFIX):].partition(".") if raw.startswith(KEY_PREFIX) else ("", "", "")
    if not app_id or not secret or any(c.isspace() for c in raw):
        fail(EXIT_USAGE, "%s 中的 API Key 格式不对，应为 ovk_ 开头的完整 Key（值不在此显示）。" % source)
    return app_id, secret


def load_key():
    """Read the API key from the environment, else from the saved credentials file; returns (app_id, secret)."""
    raw = os.environ.get(KEY_ENV, "").strip()
    if raw:
        return split_key(raw, "环境变量 " + KEY_ENV)
    path = credentials_path()
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        fail(EXIT_USAGE, "尚未配置 API Key：请向用户索取法行宝律师工作台里的 API Key，再用 configure 命令保存。",
             need_api_key=True)
    except OSError as e:
        fail(EXIT_USAGE, "读取 API Key 文件失败：%s" % e.strerror, need_api_key=True)
    return split_key(raw, "已保存的配置文件")


def save_key(raw):
    """Write the key to the credentials file, readable by the current user only (dir 0700, file 0600)."""
    path = credentials_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(raw + "\n")
    os.chmod(tmp, 0o600)  # in case the temp file already existed with wider permissions
    os.replace(tmp, path)
    return path


def load_base_url(cli_value):
    """Resolve the OpenAPI base URL: CLI argument, then environment, then the public default; fail if invalid."""
    base = (cli_value or os.environ.get(BASE_URL_ENV, "") or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        fail(EXIT_USAGE, "OpenAPI 地址不是合法的 http(s) 地址：请检查 %s 或 --base-url。" % BASE_URL_ENV)
    return base


def canonical_string(method, path, timestamp, nonce, body):
    """Build the string to sign: METHOD, PATH (with query), timestamp, nonce and SHA-256 of the body."""
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join([method.upper(), path, str(timestamp), nonce, body_hash])


def sign(secret, canonical):
    """HMAC-SHA256 of the canonical string, hex encoded."""
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class Client:
    """Signing OpenAPI client. Every request is signed freshly; a signature is valid for one request only."""
    def __init__(self, base_url, app_id, secret, opener=None, clock=time.time):
        """Keep endpoint and credentials; opener and clock are injectable for tests."""
        self.base_url = base_url
        self.app_id = app_id
        self._secret = secret
        self._open = opener or urllib.request.urlopen
        self._clock = clock
        self.clock_offset = 0

    def _send(self, method, path_and_query, body):
        """Sign and send one request, returning the decoded JSON."""
        url = self.base_url + path_and_query
        signed_path = urllib.parse.urlsplit(url)
        signed_path = signed_path.path + ("?" + signed_path.query if signed_path.query else "")
        ts = int(self._clock()) + self.clock_offset
        nonce = secrets.token_hex(16)
        headers = {
            "Content-Type": "application/json",
            "X-App-Id": self.app_id,
            "X-Timestamp": str(ts),
            "X-Nonce": nonce,
            "X-Sign": sign(self._secret, canonical_string(method, signed_path, ts, nonce, body)),
        }
        req = urllib.request.Request(url, data=body if method != "GET" else None, headers=headers, method=method)
        try:
            with self._open(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        except (urllib.error.URLError, OSError) as e:
            fail(EXIT_NETWORK, "网络异常：%s" % getattr(e, "reason", e))
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            fail(EXIT_NETWORK, "服务返回了非 JSON 内容")

    def call(self, method, path_and_query, payload=None):
        """Send a request and handle API errors; on clock skew (40102) correct the offset and re-sign once."""
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        resp = self._send(method, path_and_query, body)
        # 40102: local clock is off by more than 5 minutes. The server rejects before consuming the nonce,
        # so re-signing once with the returned server time is safe
        if resp.get("errno") == 40102 and isinstance(resp.get("data"), dict) and resp["data"].get("server_time"):
            self.clock_offset = int(resp["data"]["server_time"]) - int(self._clock())
            resp = self._send(method, path_and_query, body)
        if resp.get("errno") != 0:
            fail(EXIT_API, resp.get("errmsg") or "请求失败", errno=resp.get("errno"), request_id=resp.get("request_id"))
        return resp.get("data")


def poll_delays():
    """First check 60 s after submit, then back off 30 s -> 60 s -> 120 s (same cadence as the server)."""
    yield 60
    yield 30
    yield 60
    while True:
        yield 120


def cmd_lawyers(client, args):
    """List the lawyer uids this API key is authorized for."""
    return client.call("GET", "/lawyers")


def cmd_avatars(client, args):
    """List the lawyer's usable avatars."""
    return client.call("GET", "/avatars?uid=%d" % args.uid)


def cmd_voices(client, args):
    """List the lawyer's usable voices."""
    return client.call("GET", "/voices?uid=%d" % args.uid)


def read_script(args):
    """Read the script: --script-file takes precedence over --script."""
    if args.script_file:
        with open(args.script_file, encoding="utf-8") as f:
            return f.read().strip()
    return (args.script or "").strip()


def cmd_submit(client, args):
    """Validate lengths and submit one task; on network failure, return the idempotency key for a safe retry."""
    script = read_script(args)
    title = args.title.strip()
    if not title or not script:
        fail(EXIT_USAGE, "标题和口播脚本都不能为空")
    if len(title) > MAX_TITLE_CHARS:
        fail(EXIT_USAGE, "标题超过 %d 字（当前 %d 字）" % (MAX_TITLE_CHARS, len(title)))
    if len(script) > MAX_SCRIPT_CHARS:
        fail(EXIT_USAGE, "口播脚本超过 %d 字（当前 %d 字），请先精简" % (MAX_SCRIPT_CHARS, len(script)))
    idem = args.idempotent_key or "lv-" + secrets.token_hex(12)
    payload = {"uid": args.uid, "avatar_id": args.avatar_id, "title": title, "script": script, "idempotent_key": idem}
    if args.voice_id:
        payload["voice_id"] = args.voice_id
    try:
        data = client.call("POST", "/tasks", payload)
    except CliError as e:
        if e.exit_code == EXIT_NETWORK:
            # The request may have reached the server: resubmitting with the same key returns the same task
            e.payload["idempotent_key"] = idem
            e.payload["hint"] = "提交结果未知。重试时必须带上 --idempotent-key %s，避免重复生成" % idem
        raise
    data = dict(data or {}, idempotent_key=idem)
    return data


def cmd_status(client, args):
    """Query a task's status once."""
    return client.call("GET", "/tasks/%s" % urllib.parse.quote(args.task_id, safe=""))


def cmd_wait(client, args, sleep=time.sleep, clock=time.monotonic):
    """Poll with back-off until the task succeeds, fails or times out. Queries are retried; submits never are."""
    deadline = clock() + args.timeout
    for delay in poll_delays():
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleep(min(delay, remaining))
        try:
            data = cmd_status(client, args)
        except CliError as e:
            if e.exit_code != EXIT_NETWORK:
                raise
            continue  # queries are safe to retry; a network blip does not end the wait
        if (data or {}).get("status") in TERMINAL:
            return data
    fail(EXIT_TIMEOUT, "等待超时，任务仍在处理中，可稍后用 status 继续查询", task_id=args.task_id)


def cmd_quota(client, args):
    """Query today's quota and usage."""
    return client.call("GET", "/quota")


def cmd_configure(base_url, stdin):
    """Read the key from stdin, verify it against the API, then save it. A rejected key is not stored."""
    raw = stdin.read().strip()
    if not raw:
        fail(EXIT_USAGE, "没有从标准输入读到 API Key")
    app_id, secret = split_key(raw, "输入")
    quota = Client(base_url, app_id, secret).call("GET", "/quota")
    data = {"saved_to": save_key(raw), "quota": quota}
    if os.environ.get(KEY_ENV, "").strip():
        data["warning"] = "环境变量 %s 已设置，会优先于刚保存的 Key 生效" % KEY_ENV
    return data


def build_parser():
    """Build the argument parser."""
    p = argparse.ArgumentParser(prog="lawyer_video.py", description="律师数字人口播视频 OpenAPI 客户端")
    p.add_argument("--base-url", help="OpenAPI 地址（一般不需要传），默认取环境变量 %s，再默认 %s" % (BASE_URL_ENV, DEFAULT_BASE_URL))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("configure", help="从标准输入读取 API Key，校验通过后保存到本机（仅当前用户可读）")
    sub.add_parser("lawyers", help="当前 API Key 被授权的律师 uid 列表")
    for name, helptext in (("avatars", "律师可用形象"), ("voices", "律师可用声音")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--uid", type=int, required=True)

    sp = sub.add_parser("submit", help="提交生成任务，立即返回 task_id")
    sp.add_argument("--uid", type=int, required=True)
    sp.add_argument("--avatar-id", type=int, required=True)
    sp.add_argument("--voice-id", help="av_<n> 或 vc_<n>；不传则用形象自带音色")
    sp.add_argument("--title", required=True)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--script", help="口播脚本（≤300 字）")
    g.add_argument("--script-file", help="从 UTF-8 文本文件读取口播脚本")
    sp.add_argument("--idempotent-key", help="重试提交时必须复用上次输出里的值")

    sp = sub.add_parser("status", help="查询一次任务状态")
    sp.add_argument("--task-id", required=True)

    sp = sub.add_parser("wait", help="轮询直到任务成功 / 失败或超时")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--timeout", type=int, default=DEFAULT_WAIT_SECONDS, help="最长等待秒数，默认 1800")

    sub.add_parser("quota", help="今日额度与用量")
    return p


COMMANDS = {
    "lawyers": cmd_lawyers, "avatars": cmd_avatars, "voices": cmd_voices, "submit": cmd_submit,
    "status": cmd_status, "wait": cmd_wait, "quota": cmd_quota,
}


def main(argv=None, client=None, stdin=None):
    """CLI entry: success goes to stdout; failures go to stderr with a non-zero exit code."""
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "configure":
            data = cmd_configure(load_base_url(args.base_url), stdin or sys.stdin)
        else:
            if client is None:
                base = load_base_url(args.base_url)
                app_id, secret = load_key()
                client = Client(base, app_id, secret)
            data = COMMANDS[args.cmd](client, args)
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
        return EXIT_OK
    except CliError as e:
        print(json.dumps(e.payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())
