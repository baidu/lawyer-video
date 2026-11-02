# Lawyer video OpenAPI reference

Base URL: `https://lvlin.baidu.com/bp/openapi/v1/video` (the script default; `LAWYER_VIDEO_BASE_URL` overrides it for testing). All paths below are relative to it.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/lawyers` | uids this API key is authorized to act for |
| GET | `/avatars?uid=` | the lawyer's usable avatars: `avatar_id`, `name`, `cover_url`, `screen`, `platform` |
| GET | `/voices?uid=` | the lawyer's usable voices: `voice_id`, `name`, `platform`, `source` (`avatar` = the avatar's own voice, `clone` = the lawyer's cloned voice), `avatar_id` |
| POST | `/tasks` | submit; body `{uid, avatar_id, voice_id?, title, script, idempotent_key?}`; returns `{task_id, status}` within seconds |
| GET | `/tasks/{task_id}` | `{task_id, status, video_url, download_url, cover_url, duration, fail_code, fail_reason}`; `download_url` is the same file with a download header, named after the title |
| GET | `/quota` | `{quota_daily, used_today, remaining, succeeded_today}` |

- `status`: `processing` / `succeeded` / `failed`. `fail_code`: `audit_rejected` / `production_failed` / `timeout`.
- `voice_id` is a string: `av_<n>` (an avatar's own voice) or `vc_<n>` (cloned voice). It must belong to the same lawyer and the same `platform` as the avatar. Omit it to use the chosen avatar's own voice.
- `idempotent_key`: within one API key, resubmitting the same key returns the same task instead of creating a new one. Letters, digits and `_ . : -`, up to 64 characters.
- Daily quota counts tasks that are processing or succeeded; rejected, failed and timed-out tasks do not count.

## Response envelope

```json
{"errno": 0, "errmsg": "", "data": {}, "request_id": "..."}
```
The HTTP status follows the errno range (401xx → 401, 403xx → 403, …); rely on `errno`.

## Request signing

Every request carries four headers:

| Header | Value |
|---|---|
| `X-App-Id` | the `<app_id>` part of the key `ovk_<app_id>.<secret>` |
| `X-Timestamp` | current Unix time in seconds |
| `X-Nonce` | random string of 16–64 characters from `[A-Za-z0-9_-]`, never reused |
| `X-Sign` | `hex(HMAC-SHA256(secret, METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + hex(SHA256(body))))` |

- `PATH` is the full request path **including the query string exactly as sent**, e.g. `/bp/openapi/v1/video/avatars?uid=566984289`.
- For GET the body is empty, so the last line is the SHA-256 of the empty string.
- A signature is valid for one request only: the timestamp must be within ±300 s of server time and each nonce is accepted once. Sign every request freshly; how long the video takes to generate does not matter.

## Error codes

| errno | Meaning | Typical fix |
|---|---|---|
| 40101 | signature invalid, or signing headers missing | check the key value and that PATH includes the query string; with the script, ask the user to copy the key again and rerun `configure` |
| 40102 | timestamp outside ±300 s; `data.server_time` holds server time | correct for the clock offset and re-sign once (the script does this automatically) |
| 40103 | nonce reused | generate a new nonce per request |
| 40104 | API key unknown or disabled | the key was reset or disabled; ask the user for the current key from the lawyer console and rerun `configure` |
| 40301 | key not authorized for this lawyer | use a uid from `/lawyers` |
| 40302 | lawyer not practice-certified or not available | the lawyer must complete certification in Faxingbao |
| 40303 | avatar or voice missing, unusable or not owned by the lawyer | re-list avatars / voices and pick again |
| 40001 | avatar and voice are on different platforms | pick a voice with the same `platform` |
| 40002 | invalid parameter (missing field, title > 64 or script > 300 characters, bad `voice_id`, …) | fix the request |
| 40401 | task not found (or belongs to another key) | check the `task_id` |
| 42901 | too many requests per second | slow down |
| 42902 | daily quota not enabled or used up | wait until tomorrow or contact Faxingbao operations |
| 50001 | internal error | retry queries later; for submit, retry only with the same `idempotent_key` |
