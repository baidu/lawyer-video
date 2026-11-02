# lawyer-video

Agent Skills for legal professionals, maintained by Baidu.

Each skill lives in its own directory under `skills/` and follows the open
[Agent Skills](https://agentskills.io) format, so it works with Claude Code and other
skill-compatible AI agents.

## Install

```bash
npx skills add baidu/lawyer-video -g
```

## Skills

| Skill | Description |
|---|---|
| [lawyer-video](skills/lawyer-video/SKILL.md) | Turn a script into a talking-head video of a certified lawyer's own digital human (requires a Faxingbao API key) |

## Development

Run the release gate before every commit (validates each skill against the Agent Skills spec, runs its tests and scans for credentials or internal hosts):

```bash
python3 tools/check_skills.py
```

To run it, and the commit-message check, automatically on every commit:

```bash
git config core.hooksPath .githooks
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pull request workflow and merge requirements, and
[CHANGELOG.md](CHANGELOG.md) for release notes.

## Security

Skills in this repository never contain credentials. When a skill needs an API key, the agent asks
you for it and saves it on your machine in a file only your user can read (or reads it from an
environment variable you set). The skill's scripts never print it.

## License

[Apache License 2.0](LICENSE)
