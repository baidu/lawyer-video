# Contributing

`github.com/baidu/lawyer-video` is the only development repository. Every change reaches `master`
through a pull request reviewed by a maintainer; nobody pushes to `master` directly.

## Workflow

**Team members** (write access):

1. Clone the repository and enable the hooks once: `git config core.hooksPath .githooks`
2. Create a branch from the latest `master`, e.g. `feat/voice-preview` or `fix/download-link`
3. Commit your changes, push the branch and open a pull request
4. A maintainer reviews and merges it; delete the branch afterwards

**External contributors**:

1. Open an issue describing the problem or proposal first
2. Fork the repository, create a branch, commit and open a pull request that links the issue (`Closes #123`)
3. A maintainer reviews and merges it

## Merge requirements

A pull request is merged only when all of these hold:

- **CI is green**: `tools/check_skills.py` (spec validation, tests, credential and internal-host scan) on
  Python 3.8 and 3.12, the commit-message check, and the changelog check
- **Docs follow behavior**: if a change alters what a skill does, update its `SKILL.md`, `references/`
  and the README in the same pull request, and add an entry to `CHANGELOG.md`.
  Changes users will not notice (CI, refactors, typo fixes) may use the `no-changelog` label instead
- **A maintainer has approved it**

The hooks run the same checks locally: `pre-commit` runs `tools/check_skills.py`, `commit-msg` runs
`tools/check_commit_msg.py`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <subject>`

- `type`: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`, `chore`, `revert`
- `scope`: optional, usually the skill name, e.g. `lawyer-video`
- `subject`: at most 72 characters, describing what changes; explain why in the body

```
feat(lawyer-video): let the agent save the API key with configure

Asking users to export an environment variable and restart the agent was the most common setup failure.
```

## Releasing a skill version

Bump `metadata.version` in the skill's `SKILL.md` (semantic versioning) and move the `Unreleased`
entries in `CHANGELOG.md` under the new version with the date.

## Security

Never commit API keys, tokens, internal hostnames or real user data, including in tests and examples.
Report vulnerabilities privately to the maintainers instead of opening a public issue.
