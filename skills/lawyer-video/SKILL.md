---
name: lawyer-video
description: This skill should be used when a certified lawyer (or an agent acting for one) asks to "生成一条口播视频", "用我的数字人讲一下…", "做个讲工伤认定的短视频", "查看我的数字人形象 / 声音", "视频生成好了吗", or otherwise wants a talking-head video of a real, practice-certified lawyer's digital human reading a given script. It lists the lawyer's avatars and voices, submits a script, waits for the result and returns the video URL. Do not use it for generic avatars of arbitrary people, live / real-time digital humans, video editing, or for lawyers the API key is not authorized for.
license: Apache-2.0
compatibility: Requires Python 3.8+ (standard library only), outbound HTTPS to lvlin.baidu.com, and a Faxingbao API key, which the agent saves with the script's configure command (the environment variable LAWYER_VIDEO_API_KEY, if set, takes precedence).
metadata:
  version: "0.1.0"
  author: Baidu Faxingbao
---

# Lawyer digital-human video

Generate a talking-head (口播) video of a certified lawyer's own digital human from a script. Generation is asynchronous and usually takes a few minutes, up to 30 minutes.

## Standing rules

- **The API key is the lawyer's identity.** Anyone holding it can generate videos in the lawyer's name and use up their quota. Ask for it only when the script reports `need_api_key`, and state the risks when asking (step 1). Save it only through `configure` on stdin. Never repeat it in replies, pass it as a command-line argument, write it anywhere else, or include it in summaries. If the user thinks it may have leaked, tell them to reset it in the Faxingbao lawyer console and send you the new one.
- **Never resubmit automatically.** Submitting is not idempotent across new keys: a blind retry may produce a second video and consume quota twice. If a submit fails with a network error, retry only with the `idempotent_key` printed by the failed attempt.
- **Only act for authorized lawyers.** The `uid` must come from `lawyers` output. Avatar and voice IDs must come from that lawyer's `avatars` / `voices` output; never guess or reuse IDs from another lawyer.
- **Talk to the lawyer in plain, friendly language; keep internals out of the conversation.** Never show uids, `avatar_id` / `voice_id` codes, `platform` values, error codes, or counts of avatars / voices. Refer to avatars as "形象 1 / 形象 2" with their cover image, and to voices as "形象原声" or "你本人的声音". Translate errors into what the lawyer should do next.
- **Pass video links through exactly as returned.** Copy `video_url` and `download_url` character for character from the script output: do not decode `%XX` sequences, re-encode, shorten, wrap in a link shortener, or rebuild them. `download_url` stops working if, for example, `%3B` is turned back into `;`.
- **Keep the script ≤ 300 characters and the title ≤ 64.** Shorten the text with the user before submitting rather than letting the call fail.
- **The content is published under a real lawyer's name and must comply with lawyer advertising rules.** Before submitting, check the script yourself and rewrite anything that promises an outcome ("包赢", "百分百胜诉", "打不赢退款"), claims rankings or superlatives ("第一", "最好"), implies special relationships with courts or officials, disparages other lawyers, or uses fee inducements and urgency tactics ("免费", "名额有限"). The service's automated review only screens generic prohibited words and does not catch these, so this check is the agent's responsibility.

## Running the script

All operations go through one script located at `scripts/lawyer_video.py`, **relative to the directory containing this SKILL.md** (resolve the absolute path from where this file was loaded; the shell's working directory is usually somewhere else). Below it is written as `<skill_dir>/scripts/lawyer_video.py`.

Each command prints `{"ok": true, "data": ...}` to stdout, or an error JSON to stderr with a non-zero exit code:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | success | — |
| 2 | local config or argument problem | fix arguments; if the output has `need_api_key: true`, ask the user for the key (step 1) |
| 3 | API rejected the request (`errno` in output) | look the code up in `references/api.md` and explain it to the user |
| 4 | network / service unavailable | queries may be retried; for `submit`, see the standing rule above |
| 5 | `wait` timed out, task still processing | tell the user and offer to check again later with `status` |

## Workflow

1. **Check setup.** Run `quota`. If it succeeds, the key is already configured. If it exits 2 with `need_api_key: true`, ask the user for the key yourself; do not tell them to set environment variables. Ask in one message that also covers the risks, for example:
   > 请把法行宝律师工作台里的 API Key 发给我，我来配置。提醒一下：这个 Key 相当于你的账号身份，拿到它的人可以用你的形象和名义生成视频；它会以明文留在本次对话记录里，请不要转发给别人。担心泄露的话，随时可以在律师工作台重置，旧 Key 立即失效，把新的发我就行。

   Save the key the user sends by passing it on stdin, never as an argument:
   ```bash
   python3 <skill_dir>/scripts/lawyer_video.py configure <<'EOF'
   <key>
   EOF
   ```
   `configure` checks the key with the service, then saves it to the user's config directory, readable only by them; no restart is needed. If it exits 3, the key is wrong or has been reset: ask the user to copy it again. Do not ask for an API address: the script uses the official one by default (`LAWYER_VIDEO_BASE_URL` only overrides it for testing). When connected, confirm in one short friendly sentence, e.g. "已连接好，今天还能生成 3 条视频，告诉我想讲什么吧"; do not print a status table.
2. **Pick the lawyer.**
   ```bash
   python3 <skill_dir>/scripts/lawyer_video.py lawyers
   ```
   Usually the list contains only the user's own uid; use it without mentioning it. If there are several, ask which lawyer by name, not by uid.
3. **Pick avatar and voice — the user chooses, never the agent.**
   ```bash
   python3 <skill_dir>/scripts/lawyer_video.py avatars --uid <uid>
   python3 <skill_dir>/scripts/lawyer_video.py voices --uid <uid>
   ```
   - **One avatar:** use it, and name it when confirming in step 4.
   - **Several avatars:** list every one with its `name`, `screen` (landscape / portrait) and `cover_url` (render the image if the agent can). Avatar names are often meaningless (e.g. "9" or empty), so the cover is what lets the user tell them apart. Then **wait for the user to pick**; do not choose on their behalf and do not default to the first one. Only if the user explicitly says it does not matter, take the first and say which one was used.
   - **Voice: do not make the lawyer pick from a list** (voices cannot be previewed). Default to the avatar's own voice by omitting `--voice-id`, and mention it in the step 4 confirmation: "声音用形象原声；想换成你本人录的声音可以告诉我". Only if the lawyer asks for their own voice, use the **first** `source: clone` entry whose `platform` matches the chosen avatar's (the service lists the most recent recording first and names it "本人复刻音色（最新）"). If there is none, say that no recording of their own voice is available yet.
   - Within one conversation, reuse the avatar and voice the user already picked for later videos instead of asking again, unless they ask to change.
4. **Prepare the script.** The `script` field is read aloud word for word; it is not a prompt. If the user gives a brief (topic, audience, tone, call to action) instead of finished text, write the spoken script from it — never submit the brief itself. Apply the content rules above and keep within the limits. Before submitting, show the user **avatar, voice, title and script together** and get one explicit confirmation. For long or multi-line text, write it to a temporary UTF-8 file and pass `--script-file`.
5. **Submit once.**
   ```bash
   python3 <skill_dir>/scripts/lawyer_video.py submit --uid <uid> --avatar-id <avatar_id> \
     [--voice-id <voice_id>] --title "<title>" --script-file <path>
   ```
   Note the returned `task_id` and `idempotent_key`.
6. **Wait for the result.**
   ```bash
   python3 <skill_dir>/scripts/lawyer_video.py wait --task-id <task_id>
   ```
   This polls with back-off (60 s, then 30 s, 60 s, 120 s …) for up to 30 minutes; tell the user it may take several minutes. If the agent cannot run long commands, call `status --task-id <task_id>` periodically instead, at least 30 seconds apart.
7. **Report in plain words.** On `succeeded`, reply briefly with the duration in minutes and seconds, a watch link (`video_url`) and a download link (`download_url`, which saves the file instead of playing it), then offer a next step. For example:
   > 视频做好了，时长 1 分 02 秒。
   > ▶ 在线观看：<video_url>
   > ⬇ 下载到本地：<download_url>
   > 需要改稿子或换个形象再做一条，直接告诉我。

   Do not list fields, task IDs or the cover link unless asked. On `failed`, say what happened and offer to help, without showing `fail_code`: if the script failed review (`audit_rejected`), name the problem from `fail_reason` in plain words and offer a revised script; if generation failed or timed out (`production_failed`, `timeout`), apologise and offer to submit again.

Check remaining daily quota at any time with `quota`. Error `42902` means the daily quota is used up or not yet enabled for this key; the lawyer has to contact Faxingbao operations.

## Additional resources

- `references/api.md` — read when a command returns exit code 3 and the `errno` needs explaining, or when calling the HTTP API directly without the script (endpoints, request signing, field definitions).
