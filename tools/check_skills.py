#!/usr/bin/env python3
"""Release gate: validate every skill under skills/ and scan for credentials and internal hosts. Standard library only.

Usage: python3 tools/check_skills.py   (works from any directory)
Exits non-zero if any check fails. Frontmatter rules mirror Anthropic's official quick_validate;
running the official validator before release is still recommended.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
MAX_BODY_LINES = 500

# Credentials and internal infrastructure details: any hit blocks a public release
FORBIDDEN = [
    (re.compile(r"ovk_[a-z0-9]{8,}\.[0-9a-f]{16,}"), "疑似真实 API Key"),
    (re.compile(r"ALTAK[A-Za-z0-9]{10,}"), "疑似 BCE AccessKey"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
    (re.compile(r"(?i)(password|passwd|secret_key|access_token)\s*[:=]\s*['\"][^'\"<>{}]{6,}['\"]"), "疑似明文口令"),
    (re.compile(r"(?i)baidu-int\.com|\.all\.serv\b|\bbns://|icode\.baidu\.com"), "内网域名 / 服务名"),
    (re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "内网 IP"),
]
SCAN_SUFFIXES = {".md", ".py", ".sh", ".txt", ".json", ".yaml", ".yml", ".toml", ".env", ""}


def parse_frontmatter(text):
    """Parse the SKILL.md frontmatter; returns (top-level fields, body), fields is None if malformed."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    fields, current = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            if current is None:
                return None, text
            continue  # nested field (e.g. version under metadata)
        key, sep, value = line.partition(":")
        if not sep:
            return None, text
        current = key.strip()
        fields[current] = value.strip()
    return fields, text[m.end():]


def check_skill(skill_dir):
    """Validate one skill directory against the Agent Skills spec; returns a list of problems."""
    errors = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ["缺少 SKILL.md"]
    fields, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    if fields is None:
        return ["frontmatter 缺失或格式错误"]
    extra = set(fields) - ALLOWED_KEYS
    if extra:
        errors.append("frontmatter 含非 spec 字段 %s（version 等请放 metadata 下）" % sorted(extra))
    name = fields.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("name 须 kebab-case 且 ≤64 字符：%r" % name)
    if name != skill_dir.name:
        errors.append("name %r 与目录名 %r 不一致" % (name, skill_dir.name))
    desc = fields.get("description", "")
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        errors.append("description 须非空、≤1024 字符且不含 < >（当前 %d 字符）" % len(desc))
    if len(fields.get("compatibility", "")) > 500:
        errors.append("compatibility 超过 500 字符")
    if body.count("\n") >= MAX_BODY_LINES:
        errors.append("SKILL.md 正文超过 %d 行" % MAX_BODY_LINES)
    for sub in ("references", "assets"):
        for f in sorted((skill_dir / sub).glob("*")) if (skill_dir / sub).is_dir() else []:
            if "%s/%s" % (sub, f.name) not in body:
                errors.append("%s/%s 未在 SKILL.md 正文中引用，Agent 不会知道它存在" % (sub, f.name))
    return errors


def scan_forbidden():
    """Scan text files in the repo for credentials and internal hosts; returns the hit locations."""
    hits = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or ".git" in path.parts or path.suffix not in SCAN_SUFFIXES:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for pattern, label in FORBIDDEN:
                if pattern.search(line):
                    hits.append("%s:%d %s" % (path.relative_to(ROOT), lineno, label))
    return hits


def run_tests(skill_dir):
    """Run the skill's tests/ suite; returns whether everything passed."""
    tests = skill_dir / "tests"
    if not tests.is_dir():
        return True
    suite = unittest.defaultTestLoader.discover(str(tests), top_level_dir=str(tests))
    return unittest.TextTestRunner(verbosity=0).run(suite).wasSuccessful()


def main():
    """Validate each skill, run its tests and scan for secrets; returns 1 on any failure."""
    ok = True
    skills = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    for skill_dir in skills:
        errors = check_skill(skill_dir)
        for e in errors:
            print("FAIL %s: %s" % (skill_dir.name, e))
        if not run_tests(skill_dir):
            errors.append("tests")
            print("FAIL %s: 单测未通过" % skill_dir.name)
        ok = ok and not errors
        if not errors:
            print("ok   %s" % skill_dir.name)
    for hit in scan_forbidden():
        ok = False
        print("FAIL 敏感信息 %s" % hit)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
