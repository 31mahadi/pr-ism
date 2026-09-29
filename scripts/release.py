#!/usr/bin/env python3
"""Cut a pr-ism release in one command.

Usage:
  python3 scripts/release.py 1.8.0            # dry run: shows what would change
  python3 scripts/release.py 1.8.0 --push     # bump, test, commit, tag, push
  python3 scripts/release.py patch|minor|major [--push]

Steps:
  1. Checks: on main, clean tree, up to date with origin, tag not taken, version goes up.
  2. CHANGELOG.md must have a `## X.Y.Z` section. If it doesn't, a draft is written from the
     commit subjects since the last tag and the script stops so you can edit it.
  3. Bumps the version in SKILL.md, plugin.json and marketplace.json.
  4. Runs ruff and the smoke test.
  5. With --push: commits "vX.Y.Z", tags it, pushes main and the tag. CI then builds the zip
     and publishes the GitHub release with the changelog section as its notes.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "pr-ism" / "SKILL.md"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKET = ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = ROOT / "CHANGELOG.md"
ATTRIBUTION = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def run(*cmd: str, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"release: `{' '.join(cmd)}` failed\n{r.stdout}{r.stderr}")
    return r.stdout.strip()


def current() -> str:
    return json.loads(PLUGIN.read_text())["version"]


def parse(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        sys.exit(f"release: '{v}' is not X.Y.Z, patch, minor or major")
    return int(m[1]), int(m[2]), int(m[3])


def target(arg: str, cur: str) -> str:
    ma, mi, pa = parse(cur)
    bumps = {"patch": (ma, mi, pa + 1), "minor": (ma, mi + 1, 0), "major": (ma + 1, 0, 0)}
    new = ".".join(map(str, bumps[arg])) if arg in bumps else arg
    if parse(new) <= parse(cur):
        sys.exit(f"release: {new} is not above the current {cur}")
    return new


def check_repo(new: str) -> None:
    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        sys.exit("release: switch to main first")
    if run("git", "status", "--porcelain"):
        sys.exit("release: commit or stash your changes first (the release commit only bumps versions)")
    run("git", "fetch", "-q", "origin", "main", "--tags")
    if run("git", "rev-list", "--count", "HEAD..origin/main") != "0":
        sys.exit("release: main is behind origin/main; pull first")
    if run("git", "tag", "-l", f"v{new}"):
        sys.exit(f"release: tag v{new} already exists")


def changelog_section(new: str) -> str | None:
    m = re.search(rf"^## {re.escape(new)}\b.*?$(.*?)(?=^## |\Z)", CHANGELOG.read_text(), re.M | re.S)
    return m.group(1).strip() if m else None


def draft_changelog(new: str) -> None:
    last = run("git", "describe", "--tags", "--abbrev=0", check=False)
    rng = f"{last}..HEAD" if last else "HEAD"
    subjects = [s for s in run("git", "log", "--format=%s", rng).splitlines() if not re.fullmatch(r"v\d+\.\d+\.\d+", s)]
    body = "\n".join(f"- {s}" for s in subjects) or "- "
    text = CHANGELOG.read_text()
    head = f"## {new} — {dt.date.today().isoformat()}\n{body}\n\n"
    CHANGELOG.write_text(text.replace("# Changelog\n\n", "# Changelog\n\n" + head, 1))
    print(f"CHANGELOG.md had no {new} section; drafted one from {len(subjects)} commit(s) since {last or 'the start'}.")
    print("Edit it into user-facing notes, commit it, and run this again.")


def bump(new: str) -> list[Path]:
    cur = current()
    edits = [
        (SKILL_MD, f'version: "{cur}"', f'version: "{new}"'),
        (PLUGIN, f'"version": "{cur}"', f'"version": "{new}"'),
        (MARKET, f'"version": "{cur}"', f'"version": "{new}"'),
    ]
    for path, old, rep in edits:
        text = path.read_text()
        if text.count(old) != 1:
            sys.exit(f"release: expected one `{old}` in {path.relative_to(ROOT)}; versions are out of sync")
        path.write_text(text.replace(old, rep))
    return [p for p, _, _ in edits]


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    push = "--push" in argv
    cur = current()
    new = target(argv[0], cur)
    print(f"release: {cur} → {new}{'' if push else '  (dry run; add --push to release)'}")
    check_repo(new)
    notes = changelog_section(new)
    if notes is None:
        draft_changelog(new)
        sys.exit(1)
    print(f"changelog: {len(notes.splitlines())} line(s) for {new}")
    if not push:
        print("would bump: SKILL.md, plugin.json, marketplace.json; run ruff + smoke test; commit, tag, push")
        return
    files = bump(new)
    for cmd in (
        ("uvx", "ruff", "check", "skills", "tests", "scripts"),
        ("uvx", "ruff", "format", "--check", "skills", "tests", "scripts"),
        (sys.executable, "tests/smoke_test.py"),
    ):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            run("git", "checkout", "--", *map(str, files))
            sys.exit(f"release: `{' '.join(cmd)}` failed; version bump reverted\n{r.stdout}{r.stderr}")
    run("git", "add", *map(str, files))
    run("git", "commit", "-q", "-m", f"v{new}\n\n{ATTRIBUTION}")
    run("git", "tag", "-a", f"v{new}", "-m", f"v{new}")
    run("git", "push", "-q", "origin", "main", f"v{new}")
    print(f"pushed v{new}. CI builds pr-ism.skill.zip and publishes the release.")
    print("update your install: claude plugin marketplace update pr-ism && claude plugin update pr-ism@pr-ism")


if __name__ == "__main__":
    main(sys.argv[1:])
