#!/usr/bin/env python3
"""pr-ism configuration.

Layers (later wins): bundled defaults -> global file -> project file.

  global : $PR_ISM_CONFIG, else $XDG_CONFIG_HOME/pr-ism/config.json, else ~/.pr-ism/config.json
  project: <git root or cwd>/.pr-ism/config.json

Usage:
  config.py show [--effective|--global|--project] [--json]
  config.py get <dotted.key>
  config.py set <dotted.key> <value> [--global|--project]   # value parsed as JSON when possible
  config.py unset <dotted.key> [--global|--project]
  config.py reset [--global|--project]
  config.py init [--global|--project]
  config.py path [--global|--project]
  config.py schema                                          # every key, its type, allowed values

Only keys that exist in default-config.json are accepted; types and enums are checked.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULTS_PATH = HERE.parent / "assets" / "default-config.json"

ENUMS = {
    "output.format": ["html", "markdown", "both"],
    "report.group_by": ["file", "severity", "logical", "change_type", "none"],
    "report.sort": ["severity_desc", "severity_asc", "file", "logical", "none"],
    "report.tone": ["concise", "detailed"],
    "links.style": ["auto", "github", "gitlab", "custom", "vscode", "file", "relative"],
    "links.editor": ["vscode", "cursor", "idea", "none"],
    "review.depth": ["quick", "standard", "deep"],
    "review.engine": ["auto", "prism", "toolkit"],
}
LIST_ENUMS = {
    "report.sections": ["summary", "risk_overview", "table", "findings", "test_gaps", "questions"],
    "report.columns": [
        "file",
        "function",
        "change_type",
        "logical",
        "what",
        "why",
        "verdict",
        "severity",
        "impact",
        "lines",
    ],
    "review.focus": [
        "correctness",
        "security",
        "performance",
        "tests",
        "readability",
        "api",
        "data",
        "concurrency",
        "observability",
    ],
}
DOCS = {
    "output.format": "What to write: html (interactive report), markdown, or both.",
    "output.dir": "Where reports are written, relative to the repo root.",
    "output.filename": "Filename pattern. Tokens: {repo} {id} {date} {branch}.",
    "output.open": "Open the HTML report after rendering (Claude Code only).",
    "report.sections": "Which sections appear, in order.",
    "report.columns": "Table columns, in order.",
    "report.group_by": "Group table rows by file, severity, logical (RAG), change_type, or none.",
    "report.sort": "Row order inside a group.",
    "report.language": "Language for narrative text (ISO code, e.g. en, bn, ja).",
    "report.tone": "concise = one line per cell; detailed = fuller explanations.",
    "report.show_diff_snippets": "Include the relevant diff hunk in each expandable row.",
    "links.style": "auto picks github/gitlab when the PR has a web URL, else the editor scheme, else relative paths.",
    "links.editor": "Editor URL scheme used for local links (vscode://, cursor://, idea://).",
    "links.template": "With links.style=custom: URL pattern for a file at the head commit. Tokens: {web_base} {sha} {path} {line} {end} {number} {url}. Example (Bitbucket): {web_base}/src/{sha}/{path}#lines-{line}",
    "links.review_template": "With links.style=custom: optional pattern for the 'Open in review' link (defaults to links.template).",
    "review.engine": "Who finds issues: auto = pr-review-toolkit agents when available (Claude Code with the plugin installed), else pr-ism's rubric; prism = rubric only; toolkit = agents, fail if unavailable.",
    "review.min_agent_confidence": "Toolkit findings below this confidence (0-100) are dropped when merged.",
    "review.depth": "quick = diff only; standard = read surrounding source when a hunk is ambiguous; deep = trace callers/callees and tests.",
    "review.focus": "Review lenses to apply. Order = priority.",
    "review.ignore": "Glob patterns excluded from the table (still counted as skipped).",
    "review.red_paths": "Globs whose changes are always rated red (auth, billing, migrations ...).",
    "review.require_tests_for": "Globs where a production change without a test change is flagged as a test gap.",
    "review.max_files_inline": "Above this many files, group minor files and review the rest at summary level.",
    "review.read_source_context": "Allow reading the full file around a hunk when the diff alone is unclear.",
    "severity_scale": "Ordered severity labels, lowest to highest.",
    "verdicts": "Allowed per-row verdicts, mildest to strongest.",
}


def load_defaults() -> dict:
    with open(DEFAULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def git_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except Exception:
        return Path.cwd()


def global_path() -> Path:
    if os.environ.get("PR_ISM_CONFIG"):
        return Path(os.environ["PR_ISM_CONFIG"]).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "pr-ism" / "config.json"
    return Path.home() / ".pr-ism" / "config.json"


def project_path() -> Path:
    return git_root() / ".pr-ism" / "config.json"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective() -> dict:
    return deep_merge(deep_merge(load_defaults(), read_json(global_path())), read_json(project_path()))


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def get_path(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def set_path(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def unset_path(d: dict, dotted: str) -> bool:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur:
            return False
        cur = cur[p]
    return cur.pop(parts[-1], None) is not None


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if "," in raw:
            return [s.strip() for s in raw.split(",") if s.strip()]
        return raw


def validate(dotted: str, value) -> None:
    defaults = flatten(load_defaults())
    if dotted not in defaults:
        near = [k for k in defaults if k.split(".")[-1] == dotted.split(".")[-1]]
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        sys.exit(f"error: unknown key '{dotted}'.{hint} Run `config.py schema` for the full list.")
    expected = defaults[dotted]
    if isinstance(expected, bool) and not isinstance(value, bool):
        sys.exit(f"error: {dotted} expects true/false, got {value!r}")
    if isinstance(expected, int) and not isinstance(expected, bool) and not isinstance(value, int):
        sys.exit(f"error: {dotted} expects an integer, got {value!r}")
    if isinstance(expected, str) and not isinstance(value, str):
        sys.exit(f"error: {dotted} expects a string, got {value!r}")
    if isinstance(expected, list) and not isinstance(value, list):
        sys.exit(f"error: {dotted} expects a list (JSON array or comma-separated), got {value!r}")
    if dotted in ENUMS and value not in ENUMS[dotted]:
        sys.exit(f"error: {dotted} must be one of {ENUMS[dotted]}")
    if dotted in LIST_ENUMS:
        bad = [v for v in value if v not in LIST_ENUMS[dotted]]
        if bad:
            sys.exit(f"error: {dotted} contains unknown values {bad}; allowed: {LIST_ENUMS[dotted]}")


def target(args: list[str]) -> Path:
    return global_path() if "--global" in args else project_path()


def cmd_show(args: list[str]) -> None:
    if "--global" in args:
        data, label = read_json(global_path()), f"global ({global_path()})"
    elif "--project" in args:
        data, label = read_json(project_path()), f"project ({project_path()})"
    else:
        data, label = effective(), "effective (defaults + global + project)"
    if "--json" in args:
        print(json.dumps(data, indent=2))
        return
    print(f"# pr-ism config — {label}")
    if not data:
        print("(empty — defaults apply)")
        return
    for k, v in flatten(data).items():
        print(f"{k} = {json.dumps(v)}")


def cmd_schema() -> None:
    defaults = flatten(load_defaults())
    for k, v in defaults.items():
        typ = "list" if isinstance(v, list) else ("bool" if isinstance(v, bool) else type(v).__name__)
        allowed = ENUMS.get(k) or LIST_ENUMS.get(k)
        line = f"{k:<28} {typ:<5} default={json.dumps(v)}"
        if allowed:
            line += f"\n{'':<28} allowed: {', '.join(allowed)}"
        if k in DOCS:
            line += f"\n{'':<28} {DOCS[k]}"
        print(line)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "show":
        cmd_show(rest)
    elif cmd == "schema":
        cmd_schema()
    elif cmd == "path":
        print(target(rest))
    elif cmd == "get":
        if not rest:
            sys.exit("usage: config.py get <dotted.key>")
        try:
            print(json.dumps(get_path(effective(), rest[0])))
        except KeyError:
            sys.exit(f"error: unknown key '{rest[0]}'")
    elif cmd == "set":
        positional = [a for a in rest if not a.startswith("--")]
        if len(positional) < 2:
            sys.exit("usage: config.py set <dotted.key> <value> [--global|--project]")
        key, value = positional[0], parse_value(" ".join(positional[1:]))
        validate(key, value)
        path = target(rest)
        data = read_json(path)
        set_path(data, key, value)
        write_json(path, data)
        print(f"set {key} = {json.dumps(value)}  ({path})")
    elif cmd == "unset":
        positional = [a for a in rest if not a.startswith("--")]
        if not positional:
            sys.exit("usage: config.py unset <dotted.key> [--global|--project]")
        path = target(rest)
        data = read_json(path)
        if unset_path(data, positional[0]):
            write_json(path, data)
            print(f"unset {positional[0]}  ({path})")
        else:
            print(f"{positional[0]} was not set in {path}")
    elif cmd == "reset":
        path = target(rest)
        if path.exists():
            path.unlink()
            print(f"removed {path}; defaults apply")
        else:
            print(f"nothing to reset at {path}")
    elif cmd == "init":
        path = target(rest)
        if path.exists():
            print(f"already exists: {path}")
        else:
            write_json(path, {"version": 1})
            print(f"created {path} — add overrides with `config.py set <key> <value>`")
    else:
        sys.exit(f"unknown command '{cmd}'\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
