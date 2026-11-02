#!/usr/bin/env python3
"""Check commit messages against the repository convention. Standard library only.

Usage:
  python3 tools/check_commit_msg.py <message-file>     # commit-msg hook
  python3 tools/check_commit_msg.py --range A..B       # every commit in a range (CI)

Convention (Conventional Commits): "<type>(<optional scope>): <subject>", subject <= 72 characters.
"""

import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "test", "refactor", "perf", "ci", "chore", "revert")
PATTERN = re.compile(r"^(%s)(\([a-z0-9-]+\))?!?: \S.*$" % "|".join(TYPES))
MAX_SUBJECT = 72


def problems(message):
    """Return a list of problems with one commit message (empty if it is fine)."""
    subject = message.strip().splitlines()[0] if message.strip() else ""
    if subject.startswith(("Merge ", "Revert \"")):
        return []  # created by GitHub when merging or reverting a PR
    errors = []
    if not PATTERN.match(subject):
        errors.append("subject must look like \"feat(lawyer-video): ...\"; allowed types: %s" % ", ".join(TYPES))
    if len(subject) > MAX_SUBJECT:
        errors.append("subject is %d characters, limit is %d" % (len(subject), MAX_SUBJECT))
    return errors


def main(argv):
    """Check a message file, or every commit in --range; exit non-zero on any problem."""
    if len(argv) == 2 and argv[0] == "--range":
        out = subprocess.run(["git", "log", "--format=%H%x00%B%x01", argv[1]],
                             check=True, capture_output=True, text=True).stdout
        commits = [c.strip().split("\0", 1) for c in out.split("\x01") if c.strip()]
    elif len(argv) == 1:
        with open(argv[0], encoding="utf-8") as f:
            text = "\n".join(line for line in f.read().splitlines() if not line.startswith("#"))
        commits = [("commit", text)]
    else:
        print(__doc__, file=sys.stderr)
        return 2
    failed = False
    for sha, message in commits:
        for err in problems(message):
            failed = True
            print("%s: %s" % (sha[:12], err), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
