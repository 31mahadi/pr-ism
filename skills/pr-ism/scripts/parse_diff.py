#!/usr/bin/env python3
"""Parse a unified diff into a structured, function-aware changes.json.

Usage: parse_diff.py <pr.diff> --meta <pr.json> [--config <effective-config.json>] [--out changes.json] [--stdout]
       parse_diff.py show <changes.json> <hunk-id | path | path:function>     # print one hunk / one function's segment

Also writes changes.md next to changes.json: a compact per-file index (functions, line ranges, hunk ids).
Read the index first; open individual hunks with `show` — changes.json can be large on big PRs.

For every file: status, language, hunks, +/- counts, red_path flag, links.
For every hunk : line ranges, the enclosing function (from the @@ header or the
nearest definition inside the hunk), definitions touched, and the raw lines.
Files matching review.ignore are dropped from `files` and listed in `skipped`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import effective as effective_config  # noqa: E402

LANG_BY_EXT = {
    ".go": "go",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sql": "sql",
    ".sh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".proto": "proto",
    ".tf": "terraform",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".html": "html",
    ".css": "css",
    ".vue": "vue",
}
KIND_BY_PATH = [
    (
        re.compile(
            r"(^|/)(test|tests|__tests__|spec|specs|testdata|fixtures)/|\.txtar$|_test\.\w+$|\.test\.\w+$|\.spec\.\w+$|Test\.\w+$"
        ),
        "test",
    ),
    (re.compile(r"(^|/)(migrations?|db/migrate)/"), "migration"),
    (re.compile(r"\.(md|rst|txt|adoc)$|(^|/)docs?/"), "docs"),
    (
        re.compile(
            r"(^|/)(package\.json|go\.mod|Cargo\.toml|pyproject\.toml|requirements[^/]*\.txt|Gemfile|composer\.json|pom\.xml|build\.gradle(\.kts)?)$"
        ),
        "deps",
    ),
    (re.compile(r"\.(ya?ml|toml|ini|env|cfg|conf|json)$|(^|/)(Dockerfile|Makefile|\.github/|\.gitlab-ci)"), "config"),
    (re.compile(r"\.(proto|graphql|gql)$|openapi\.\w+$|swagger\.\w+$"), "api"),
]

# Definition patterns: (language-or-*, regex with a `name` group)
DEF_PATTERNS = [
    (
        "go",
        re.compile(
            r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>\w+)\s*[\[(]|^\s*type\s+(?P<name2>\w+)(?:\[[^\]]*\])?\s+(?:struct|interface)\b"
        ),
    ),
    ("python", re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(?P<name>\w+)")),
    (
        "javascript",
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>\w+)|^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name2>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>|^\s*(?:export\s+)?(?:default\s+)?class\s+(?P<name3>\w+)|^\s*(?:public|private|protected|static|async|\s)*(?P<name4>\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{|^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum|namespace)\s+(?P<name5>\w+)"
        ),
    ),
    ("typescript", None),  # same as javascript
    (
        "java",
        re.compile(
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|native|\s)*[\w<>\[\],.? ]+\s+(?P<name>\w+)\s*\([^;]*$|^\s*(?:public|private|protected|abstract|final|\s)*(?:class|interface|enum|record)\s+(?P<name2>\w+)"
        ),
    ),
    (
        "kotlin",
        re.compile(
            r"^\s*(?:override\s+|private\s+|public\s+|internal\s+|suspend\s+|inline\s+|open\s+)*fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(?P<name>\w+)\s*\(|^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)?(?:class|object|interface)\s+(?P<name2>\w+)"
        ),
    ),
    (
        "rust",
        re.compile(
            r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>\w+)|^\s*(?:pub\s+)?(?:struct|enum|trait|impl(?:<[^>]*>)?)\s+(?P<name2>[\w:<>]+)"
        ),
    ),
    ("ruby", re.compile(r"^\s*def\s+(?:self\.)?(?P<name>[\w?!=]+)|^\s*(?:class|module)\s+(?P<name2>[\w:]+)")),
    (
        "php",
        re.compile(
            r"^\s*(?:public|private|protected|static|abstract|final|\s)*function\s+(?P<name>\w+)|^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+(?P<name2>\w+)"
        ),
    ),
    (
        "csharp",
        re.compile(
            r"^\s*(?:public|private|protected|internal|static|virtual|override|async|sealed|\s)*[\w<>\[\],.? ]+\s+(?P<name>\w+)\s*\([^;]*$|^\s*(?:public|internal|\s)*(?:class|interface|struct|record|enum)\s+(?P<name2>\w+)"
        ),
    ),
    ("c", re.compile(r"^[\w\s\*]+?\b(?P<name>\w+)\s*\([^;]*\)\s*\{?\s*$")),
    (
        "cpp",
        re.compile(
            r"^[\w\s\*&:<>~]+?\b(?P<name>[\w:~]+)\s*\([^;]*\)\s*(?:const)?\s*\{?\s*$|^\s*(?:class|struct|namespace)\s+(?P<name2>\w+)"
        ),
    ),
    (
        "swift",
        re.compile(
            r"^\s*(?:public|private|internal|fileprivate|open|static|override|final|\s)*func\s+(?P<name>\w+)|^\s*(?:public|private|internal|open|final|\s)*(?:class|struct|enum|protocol|extension)\s+(?P<name2>[\w.]+)"
        ),
    ),
    (
        "scala",
        re.compile(
            r"^\s*(?:override\s+|private\s+|protected\s+|implicit\s+)*def\s+(?P<name>\w+)|^\s*(?:case\s+|abstract\s+|sealed\s+)*(?:class|object|trait)\s+(?P<name2>\w+)"
        ),
    ),
    (
        "dart",
        re.compile(
            r"^\s*(?:static\s+|Future<[^>]*>\s+|void\s+|[\w<>?]+\s+)?(?P<name>\w+)\s*\([^;]*\)\s*(?:async\s*)?\{|^\s*(?:abstract\s+)?class\s+(?P<name2>\w+)"
        ),
    ),
    ("elixir", re.compile(r"^\s*(?:def|defp|defmacro)\s+(?P<name>\w+[?!]?)|^\s*defmodule\s+(?P<name2>[\w.]+)")),
    (
        "sql",
        re.compile(
            r"^\s*(?:CREATE|ALTER|DROP)\s+(?:OR\s+REPLACE\s+)?(?:TABLE|INDEX|FUNCTION|PROCEDURE|VIEW|TRIGGER)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?P<name>[\w.\"]+)",
            re.I,
        ),
    ),
    ("*", re.compile(r"^\s*(?:function|def|fn|func|class|struct|interface|module)\s+(?P<name>[\w:.]+)")),
]

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
NOT_A_FUNCTION = {
    "if",
    "else",
    "elif",
    "while",
    "for",
    "foreach",
    "switch",
    "case",
    "return",
    "catch",
    "try",
    "do",
    "with",
    "sizeof",
    "new",
    "throw",
    "using",
    "match",
    "when",
    "until",
    "unless",
    "yield",
    "await",
    "assert",
    "typeof",
    "select",
    "defer",
    "go",
    "lock",
    "synchronized",
    "print",
    "require",
    "import",
    "super",
    "this",
    "self",
    "constructor",
    "fn",
    "function",
    "def",
    "func",
    "class",
}
PREVIEW_CAP = 300
TEST_BLOCK = re.compile(r"^\s*(?:describe|it|test|context|suite)(?:\.\w+)?\(\s*['\"`]([^'\"`]{1,80})")
CONTAINER = re.compile(
    r"\b(class|struct|interface|impl|module|object|trait|enum|record|namespace|extension|protocol|defmodule|type)\b"
)
GENERIC_DIRS = {
    "src",
    "lib",
    "app",
    "pkg",
    "internal",
    "cmd",
    "core",
    "main",
    "utils",
    "util",
    "common",
    "source",
    "sources",
    ".",
}
DEF_KEYWORD = re.compile(
    r"\b(def|defp|defmacro|defmodule|func|fn|function|class|struct|interface|trait|enum|module|object|record|namespace|impl|extension|protocol|CREATE|ALTER|DROP)\b",
    re.I,
)


def lang_of(path: str) -> str:
    return LANG_BY_EXT.get(Path(path).suffix.lower(), "text")


def kind_of(path: str) -> str:
    for rx, kind in KIND_BY_PATH:
        if rx.search(path):
            return kind
    return "source"


def def_name(line: str, lang: str) -> str | None:
    text = line[1:] if line[:1] in "+- " else line
    if lang in ("javascript", "typescript") and (tb := TEST_BLOCK.match(text)):
        return tb.group(1)
    for plang, rx in DEF_PATTERNS:
        if rx is None:
            continue
        if plang in (lang, "*") or (lang == "typescript" and plang == "javascript"):
            m = rx.match(text)
            if m:
                for g in ("name", "name2", "name3", "name4", "name5"):
                    if g in m.groupdict() and m.group(g):
                        name = m.group(g)
                        if text.lstrip().startswith(("}", ")", "]", "//", "#", "*", "/*")):
                            return None
                        explicit = DEF_KEYWORD.search(text[: m.start(g)])  # `def new():` is fine; bare `new (` is not
                        if not explicit and name.lower() in NOT_A_FUNCTION:
                            return None
                        return name
    return None


def header_func(context: str, lang: str) -> str | None:
    if not context.strip():
        return None
    name = def_name(context, lang)
    if name:
        return name
    if tb := TEST_BLOCK.search(context):
        return tb.group(1)
    m = re.search(r"\b([A-Za-z_][\w$]*)\s*\(", context)
    return m.group(1) if m else None


def parse(diff_text: str) -> list[dict]:
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None
    old_ln = new_ln = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.*?) b/(.*)$", raw)
            cur = {
                "old_path": m.group(1) if m else None,
                "path": m.group(2) if m else raw,
                "status": "modified",
                "binary": False,
                "hunks": [],
                "additions": 0,
                "deletions": 0,
            }
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if raw.startswith("new file mode"):
            cur["status"] = "added"
        elif raw.startswith("deleted file mode"):
            cur["status"] = "removed"
        elif raw.startswith("rename from "):
            cur["status"] = "renamed"
            cur["old_path"] = raw[len("rename from ") :]
        elif raw.startswith("rename to "):
            cur["path"] = raw[len("rename to ") :]
        elif raw.startswith("Binary files") or raw.startswith("GIT binary patch"):
            cur["binary"] = True
        elif raw.startswith("--- ") or raw.startswith("+++ "):
            if raw.startswith("+++ b/"):
                cur["path"] = raw[6:]
            elif raw.startswith("--- a/") and cur["status"] != "renamed":
                cur["old_path"] = raw[6:]
            continue
        elif m := HUNK_RE.match(raw):
            old_ln, new_ln = int(m.group(1)), int(m.group(3))
            hunk = {
                "old_start": old_ln,
                "old_len": int(m.group(2) or 1),
                "new_start": new_ln,
                "new_len": int(m.group(4) or 1),
                "context": m.group(5).strip(),
                "lines": [],
                "additions": 0,
                "deletions": 0,
            }
            cur["hunks"].append(hunk)
        elif hunk is not None and raw[:1] in "+- \\":
            if raw.startswith("\\"):
                continue
            entry = {"t": raw[0], "text": raw[1:]}
            if raw[0] == "+":
                entry["new"] = new_ln
                new_ln += 1
                hunk["additions"] += 1
                cur["additions"] += 1
            elif raw[0] == "-":
                entry["old"] = old_ln
                old_ln += 1
                hunk["deletions"] += 1
                cur["deletions"] += 1
            else:
                entry["old"] = old_ln
                entry["new"] = new_ln
                old_ln += 1
                new_ln += 1
            hunk["lines"].append(entry)
    return files


def segments(lines: list[dict], enclosing: str | None, lang: str) -> list[dict]:
    """Split a hunk at definition lines so each function gets its own line range + preview."""
    segs: list[dict] = []
    cur = {"function": enclosing or "top-level", "lines": [], "indent": None, "container": True}
    for ln in lines:
        name = def_name(ln["text"], lang)
        indent = len(ln["text"]) - len(ln["text"].lstrip()) if name else 0
        # a definition nested deeper inside a function (inner class, closure) belongs to that function
        nested = name and cur["indent"] is not None and not cur["container"] and indent > cur["indent"]
        if name and not nested:
            container = bool(CONTAINER.search(ln["text"].split(name, 1)[0]))
            if name != cur["function"] and cur["lines"]:
                segs.append(cur)
                cur = {"function": name, "lines": []}
            cur.update(function=name, indent=indent, container=container)
        cur["lines"].append(ln)
    if cur["lines"]:
        segs.append(cur)
    merged: list[dict] = []
    for sg in segs:
        prev = merged[-1] if merged else None
        only_removed = prev and prev["lines"] and all(ln["t"] == "-" for ln in prev["lines"])
        starts_added_def = (
            sg["lines"] and sg["lines"][0]["t"] == "+" and def_name(sg["lines"][0]["text"], lang) == sg["function"]
        )
        if prev and prev["function"] == sg["function"]:
            prev["lines"].extend(sg["lines"])
        elif prev and only_removed and starts_added_def and "→" not in prev["function"]:
            prev["function"] = f"{prev['function']} → {sg['function']}"
            prev["lines"].extend(sg["lines"])
        else:
            merged.append(sg)
    out = []
    for sg in merged:
        ls = sg["lines"]
        if not any(ln["t"] in "+-" for ln in ls):
            continue  # pure context, nothing changed in this function
        news = [ln["new"] for ln in ls if "new" in ln]
        olds = [ln["old"] for ln in ls if "old" in ln]
        out.append(
            {
                "function": sg["function"],
                "new_range": [min(news), max(news)] if news else None,
                "old_range": [min(olds), max(olds)] if olds else None,
                "additions": sum(1 for ln in ls if ln["t"] == "+"),
                "deletions": sum(1 for ln in ls if ln["t"] == "-"),
                "preview": preview(ls),
            }
        )
    return out


def preview(ls: list[dict]) -> str:
    body = [("+" if ln["t"] == "+" else "-" if ln["t"] == "-" else " ") + ln["text"] for ln in ls]
    if len(body) > PREVIEW_CAP:
        body = body[:PREVIEW_CAP] + [
            f"… {len(ls) - PREVIEW_CAP} more lines — run `parse_diff.py show <changes.json> <hunk-id>` for all of them"
        ]
    return "\n".join(body)


def enrich(files: list[dict], meta: dict, cfg: dict) -> dict:
    ignore = cfg["review"]["ignore"]
    red_paths = cfg["review"]["red_paths"]
    link_cfg = cfg["links"]
    root = meta.get("root") or "."
    kept, skipped = [], []
    for f in files:
        path = f["path"]
        if any(fnmatch(path, g) or fnmatch("/" + path, g) for g in ignore):
            skipped.append(
                {
                    "path": path,
                    "reason": "ignored by review.ignore",
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                }
            )
            continue
        lang = lang_of(path)
        f["language"] = lang
        f["kind"] = kind_of(path)
        f["red_path"] = any(fnmatch(path, g) or fnmatch("/" + path, g) for g in red_paths)
        f["link"] = build_link(path, None, None, meta, link_cfg, root)
        for i, h in enumerate(f["hunks"]):
            h["id"] = f"{hashlib.sha1(path.encode()).hexdigest()[:6]}-h{i + 1}"
            first_new = next((ln["new"] for ln in h["lines"] if "new" in ln), h["new_start"])
            last_new = next(
                (ln["new"] for ln in reversed(h["lines"]) if "new" in ln), h["new_start"] + max(h["new_len"] - 1, 0)
            )
            h["new_range"] = [first_new, last_new]
            h["link"] = build_link(path, first_new, last_new, meta, link_cfg, root)
            enclosing = header_func(h["context"], lang)
            defs_touched, defs_added, defs_removed = [], [], []
            last_def = enclosing
            first_change_seen = False
            for ln in h["lines"]:
                name = def_name(ln["text"], lang)
                if name:
                    if ln["t"] == "+":
                        defs_added.append(name)
                    elif ln["t"] == "-":
                        defs_removed.append(name)
                    if name not in defs_touched:
                        defs_touched.append(name)
                    if not first_change_seen and ln["t"] != "+":
                        last_def = name
                if ln["t"] in "+-" and not first_change_seen:
                    first_change_seen = True
                    h["enclosing_function"] = last_def
            h.setdefault("enclosing_function", last_def)
            h["definitions_touched"] = defs_touched
            h["definitions_added"] = list(dict.fromkeys(d for d in defs_added if d not in defs_removed))
            h["definitions_removed"] = list(dict.fromkeys(d for d in defs_removed if d not in defs_added))
            h["definition_changed"] = sorted(set(defs_added) & set(defs_removed))
            h["segments"] = segments(h["lines"], enclosing, lang)
            if f["kind"] == "test":
                f.setdefault("_text", []).extend(ln["text"] for ln in h["lines"])
            h["preview"] = preview(h["lines"])
            h["line_count"] = len(h["lines"])
            del h["lines"]
        f["functions"] = list(dict.fromkeys(sg["function"] for h in f["hunks"] for sg in h["segments"]))
        kept.append(f)
    test_stems = set()
    for f in kept:
        if f["kind"] == "test":
            stem = re.sub(r"(_test|\.test|\.spec|_spec|Test|Tests|Spec|test_)", "", Path(f["path"]).stem)
            test_stems.add(stem.lower())
            test_stems.add(str(Path(f["path"]).parent).lower())
    test_text = "\n".join(f"{f['path']}\n" + "\n".join(f.pop("_text", [])) for f in kept if f["kind"] == "test").lower()
    for f in kept:
        f.pop("_text", None)
        if f["kind"] == "source":
            stem = Path(f["path"]).stem.lower()
            pkg = Path(f["path"]).parent.name.lower()
            mentioned = [
                w
                for w in (stem, pkg)
                if len(w) > 2 and w not in GENERIC_DIRS and re.search(rf"\b{re.escape(w)}\b", test_text)
            ]
            f["related_test_changed"] = (
                stem in test_stems or str(Path(f["path"]).parent).lower() in test_stems or bool(mentioned)
            )
            f["tests_required"] = any(
                fnmatch(f["path"], g) or fnmatch("/" + f["path"], g) for g in cfg["review"]["require_tests_for"]
            )
    stats = {
        "files": len(kept),
        "skipped": len(skipped),
        "hunks": sum(len(f["hunks"]) for f in kept),
        "additions": sum(f["additions"] for f in kept),
        "deletions": sum(f["deletions"] for f in kept),
        "red_path_files": [f["path"] for f in kept if f["red_path"]],
        "by_kind": {k: sum(1 for f in kept if f["kind"] == k) for k in sorted({f["kind"] for f in kept})},
        "test_files": [f["path"] for f in kept if f["kind"] == "test"],
        "source_files_without_tests": [
            f["path"]
            for f in kept
            if f["kind"] == "source" and f.get("tests_required") and not f.get("related_test_changed")
        ],
    }
    return {"meta": meta, "config_links": link_cfg, "stats": stats, "files": kept, "skipped": skipped}


def build_link(path: str, start: int | None, end: int | None, meta: dict, link_cfg: dict, root: str) -> dict:
    style = link_cfg.get("style", "auto")
    provider = meta.get("provider")
    if style == "auto":
        style = (
            provider
            if provider in ("github", "gitlab") and meta.get("web_base")
            else (link_cfg.get("editor") if link_cfg.get("editor") not in (None, "none") else "relative")
        )
    abs_path = str(Path(root) / path).replace("\\", "/")
    frag = f"#L{start}" + (f"-L{end}" if end and end != start else "") if start else ""
    if style == "custom" and link_cfg.get("template"):
        tok = {
            "web_base": meta.get("web_base") or "",
            "sha": meta.get("head_sha") or meta.get("head") or "",
            "path": path,
            "line": start or 1,
            "end": end or start or 1,
            "number": meta.get("number") or "",
            "url": meta.get("url") or "",
        }
        href = link_cfg["template"].format(**tok)
        review = (link_cfg.get("review_template") or link_cfg["template"]).format(**tok)
        return {
            "style": "custom",
            "href": href,
            "review_href": review,
            "label": f"{path}{':' + str(start) if start else ''}",
        }
    if style == "github" and meta.get("web_base"):
        blob = f"{meta['web_base']}/blob/{meta.get('head_sha') or meta.get('head')}/{path}{frag}"
        anchor = f"{meta['url']}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}" if meta.get("url") else blob
        return {
            "style": "github",
            "href": blob,
            "review_href": anchor,
            "label": f"{path}{':' + str(start) if start else ''}",
        }
    if style == "gitlab" and meta.get("web_base"):
        gl_frag = f"#L{start}" + (f"-{end}" if end and end != start else "") if start else ""
        blob = f"{meta['web_base']}/-/blob/{meta.get('head_sha') or meta.get('head')}/{path}{gl_frag}"
        anchor = f"{meta['url']}/diffs#{hashlib.sha1(path.encode()).hexdigest()}" if meta.get("url") else blob
        return {
            "style": "gitlab",
            "href": blob,
            "review_href": anchor,
            "label": f"{path}{':' + str(start) if start else ''}",
        }
    if style in ("vscode", "cursor", "idea"):
        scheme = {"vscode": "vscode://file", "cursor": "cursor://file", "idea": "idea://open?file="}[style]
        p = abs_path if abs_path.startswith("/") else "/" + abs_path.replace("\\", "/")
        href = f"{scheme}{p}" + (f":{start}" if start and style != "idea" else (f"&line={start}" if start else ""))
        return {
            "style": style,
            "href": href,
            "review_href": href,
            "label": f"{path}{':' + str(start) if start else ''}",
        }
    if style == "file":
        return {
            "style": "file",
            "href": f"file://{abs_path}",
            "review_href": f"file://{abs_path}",
            "label": f"{path}{':' + str(start) if start else ''}",
        }
    return {
        "style": "relative",
        "href": None,
        "review_href": None,
        "label": f"{path}{':' + str(start) if start else ''}",
    }


def index_md(result: dict) -> str:
    """Compact per-file index — read this first; open hunks with `show` only when needed."""
    s, lines = result["stats"], []
    m = result["meta"]
    lines.append(
        f"# {m.get('title', 'change')}  ({s['files']} files, {s['hunks']} hunks, +{s['additions']} -{s['deletions']}, {s['skipped']} skipped)"
    )
    if s["red_path_files"]:
        lines.append(f"red paths: {', '.join(s['red_path_files'])}")
    if s["source_files_without_tests"]:
        lines.append(f"no related test change: {', '.join(s['source_files_without_tests'])}")
    lines += ["", "| file | status | kind | red | +/- | functions [new lines] hunk |", "|---|---|---|---|---|---|"]
    cap = 12
    for f in result["files"]:
        segs = list(
            dict.fromkeys(
                f"{sg['function']} [{sg['new_range'][0]}-{sg['new_range'][1]}] {h['id']}"
                if sg.get("new_range")
                else f"{sg['function']} {h['id']}"
                for h in f["hunks"]
                for sg in h["segments"]
            )
        )
        cell = ", ".join(segs[:cap]) + (f", +{len(segs) - cap} more (`show <path>`)" if len(segs) > cap else "")
        lines.append(
            f"| {f['path']} | {f['status']} | {f['kind']} | {'yes' if f['red_path'] else ''} | +{f['additions']} -{f['deletions']} | {cell or '—'} |"
        )
    if result["skipped"]:
        lines += ["", "skipped: " + ", ".join(x["path"] for x in result["skipped"])]
    return "\n".join(lines) + "\n"


def cmd_show(argv: list[str]) -> None:
    """parse_diff.py show <changes.json> <hunk-id | path | path:function>"""
    if len(argv) < 2:
        sys.exit(cmd_show.__doc__)
    result = json.loads(Path(argv[0]).read_text())
    want = argv[1]
    diff_text = None
    if result["meta"].get("diff_path") and Path(result["meta"]["diff_path"]).exists():
        diff_text = Path(result["meta"]["diff_path"]).read_text(encoding="utf-8", errors="replace")
    full = {
        h_id: h
        for f in (parse(diff_text) if diff_text else [])
        for i, h in enumerate(f["hunks"])
        for h_id in [f"{hashlib.sha1(f['path'].encode()).hexdigest()[:6]}-h{i + 1}"]
    }
    path, _, fn = want.partition(":")
    found = False
    for f in result["files"]:
        for h in f["hunks"]:
            if h["id"] == want or f["path"] == path:
                if fn:
                    for sg in h["segments"]:
                        if sg["function"] == fn:
                            found = True
                            print(f"## {f['path']} :: {sg['function']}  lines {sg.get('new_range')}\n{sg['preview']}\n")
                    continue
                found = True
                body = full.get(h["id"])
                text = (
                    "\n".join(
                        ("+" if ln["t"] == "+" else "-" if ln["t"] == "-" else " ") + ln["text"] for ln in body["lines"]
                    )
                    if body
                    else h["preview"]
                )
                print(
                    f"## {f['path']} {h['id']}  @@ -{h['old_start']},{h['old_len']} +{h['new_start']},{h['new_len']} @@ {h['context']}\n{text}\n"
                )
    if not found:
        sys.exit(f"no hunk or segment matches '{want}'; see changes.md for hunk ids and function names")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    if argv[0] == "show":
        cmd_show(argv[1:])
        return
    diff_path = Path(argv[0])
    meta = json.loads(Path(argv[argv.index("--meta") + 1]).read_text()) if "--meta" in argv else {}
    cfg = json.loads(Path(argv[argv.index("--config") + 1]).read_text()) if "--config" in argv else effective_config()
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else diff_path.with_name("changes.json")
    meta["diff_path"] = str(diff_path.resolve())
    result = enrich(parse(diff_path.read_text(encoding="utf-8", errors="replace")), meta, cfg)
    if "--stdout" in argv:
        print(json.dumps(result, indent=2))
        return
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    idx = out.with_name("changes.md")
    idx.write_text(index_md(result), encoding="utf-8")
    s = result["stats"]
    print(
        f"changes: {out}\nindex:   {idx}\nfiles: {s['files']} (+{s['skipped']} skipped)  hunks: {s['hunks']}  +{s['additions']} -{s['deletions']}"
    )
    if s["red_path_files"]:
        print(f"red paths touched: {', '.join(s['red_path_files'])}")
    if s["source_files_without_tests"]:
        print(f"no related test change: {', '.join(s['source_files_without_tests'])}")
    print("next: read changes.md")


if __name__ == "__main__":
    main(sys.argv[1:])
