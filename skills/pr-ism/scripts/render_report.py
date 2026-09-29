#!/usr/bin/env python3
"""Render review.json into the HTML report (and/or markdown).

Usage: render_report.py <review.json> [--changes changes.json] [--config effective.json]
                        [--out PATH] [--format html|markdown|both] [--open] [--validate-only]

- Validates required fields and enum values; exits 1 with every problem listed.
- Fills in stats, file/line links (from changes.json when present) and ids the reviewer omitted.
- Output path defaults to <config.output.dir>/<config.output.filename> resolved against the repo root.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import effective as effective_config  # noqa: E402
from config import git_root  # noqa: E402

TEMPLATE = HERE.parent / "assets" / "report-template.html"
LOGICAL = {"green", "amber", "red"}
OVERALL = {"approve", "approve-with-nits", "comment", "request-changes"}
CHANGE_TYPES = {
    "added",
    "modified",
    "removed",
    "renamed",
    "moved",
    "signature-change",
    "refactor",
    "behavior-change",
    "bugfix",
    "feature",
    "perf",
    "test",
    "docs",
    "config",
    "deps",
    "generated",
    "formatting",
    "migration",
    "api",
}
IMPACTS = {"local", "module", "service", "system"}
ROW_REQUIRED = ("file", "change_type", "logical", "what", "verdict", "severity")


def validate(review: dict, cfg: dict) -> list[str]:
    errs: list[str] = []
    sev = set(cfg["severity_scale"])
    verdicts = set(cfg["verdicts"])
    if "meta" not in review or "title" not in review.get("meta", {}):
        errs.append("meta.title is required")
    s = review.get("summary") or {}
    if s.get("overall_verdict") not in OVERALL:
        errs.append(f"summary.overall_verdict must be one of {sorted(OVERALL)} (got {s.get('overall_verdict')!r})")
    if not s.get("one_liner"):
        errs.append("summary.one_liner is required")
    rows = review.get("rows")
    if not isinstance(rows, list) or not rows:
        errs.append("rows must be a non-empty list")
        return errs
    for i, r in enumerate(rows):
        where = f"rows[{i}]" + (f" ({r.get('file')}::{r.get('function')})" if isinstance(r, dict) else "")
        if not isinstance(r, dict):
            errs.append(f"{where} is not an object")
            continue
        for k in ROW_REQUIRED:
            if not r.get(k):
                errs.append(f"{where}: '{k}' is required")
        if r.get("logical") not in LOGICAL:
            errs.append(f"{where}: logical must be green|amber|red")
        if r.get("verdict") and r["verdict"] not in verdicts:
            errs.append(f"{where}: verdict '{r['verdict']}' not in configured verdicts {sorted(verdicts)}")
        if r.get("severity") and r["severity"] not in sev:
            errs.append(f"{where}: severity '{r['severity']}' not in configured scale {cfg['severity_scale']}")
        if r.get("change_type") and r["change_type"] not in CHANGE_TYPES:
            errs.append(f"{where}: change_type '{r['change_type']}' not in {sorted(CHANGE_TYPES)}")
        if r.get("impact") and r["impact"] not in IMPACTS:
            errs.append(f"{where}: impact '{r['impact']}' not in {sorted(IMPACTS)}")
    for i, f in enumerate(review.get("findings") or []):
        if not f.get("title") or f.get("severity") not in sev:
            errs.append(f"findings[{i}]: needs title and a severity from {cfg['severity_scale']}")
    return errs


def fill(review: dict, changes: dict | None, cfg: dict) -> dict:
    meta = review.setdefault("meta", {})
    if changes:
        for k in ("url", "repo", "number", "author", "base", "head", "head_sha", "provider", "web_base", "root"):
            meta.setdefault(k, changes.get("meta", {}).get(k))
    meta.setdefault("generated_at", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    meta.setdefault("reviewer", "pr-ism")
    meta["config_hash"] = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:8]
    by_path = {f["path"]: f for f in (changes or {}).get("files", [])}
    from parse_diff import build_link  # noqa: WPS433

    for i, r in enumerate(review["rows"]):
        r.setdefault("id", f"r{i + 1}")
        for k in ("line_start", "line_end", "additions", "deletions"):
            if isinstance(r.get(k), str) and r[k].isdigit():
                r[k] = int(r[k])
        f = by_path.get(r["file"])
        if r["file"].endswith("/") and changes:
            # directory summary row: totals over the files under it, link to the PR's file list
            under = [x for p, x in by_path.items() if p.startswith(r["file"])]
            r.setdefault("additions", sum(x["additions"] for x in under))
            r.setdefault("deletions", sum(x["deletions"] for x in under))
            if changes["meta"].get("url"):
                r.setdefault(
                    "file_link",
                    changes["meta"]["url"] + ("/files" if changes["meta"].get("provider") == "github" else "/diffs"),
                )
            continue
        if f and r.get("hunk_ids"):
            # one row merged from several hunks of the same function
            hs = [h for h in f["hunks"] if h["id"] in r["hunk_ids"]]
            if hs:
                r.setdefault("file_link", (f.get("link") or {}).get("href"))
                r.setdefault("review_link", (f.get("link") or {}).get("review_href"))
                r.setdefault("line_start", min(h["new_range"][0] for h in hs))
                r.setdefault("line_end", max(h["new_range"][1] for h in hs))
                r.setdefault("additions", sum(h["additions"] for h in hs))
                r.setdefault("deletions", sum(h["deletions"] for h in hs))
                if cfg["report"].get("show_diff_snippets", True):
                    r.setdefault("diff_snippet", "\n⋯\n".join(h["preview"] for h in hs))
        if f:
            r.setdefault("file_link", (f.get("link") or {}).get("href"))
            r.setdefault("review_link", (f.get("link") or {}).get("review_href"))
            hunks = f["hunks"]
            hunk = next((h for h in hunks if h["id"] == r.get("hunk_id")), None) if r.get("hunk_id") else None
            if hunk is None and r.get("line_start"):
                hunk = next((h for h in hunks if h["new_range"][0] <= r["line_start"] <= h["new_range"][1]), None)
            # prefer the per-function segment when the row names a function
            seg = None
            fn = (r.get("function") or "").strip()
            pool = [hunk] if hunk else hunks
            if fn:
                seg = next((s for h in pool for s in h.get("segments", []) if s["function"] == fn), None)
                if seg is None and hunk is None:
                    hunk = next(
                        (
                            h
                            for h in hunks
                            if fn in h.get("definitions_touched", []) or h.get("enclosing_function") == fn
                        ),
                        None,
                    )
            src = seg or hunk or (hunks[0] if len(hunks) == 1 else None)
            if src:
                rng = src.get("new_range") or src.get("old_range") or [None, None]
                if rng[0]:
                    r.setdefault("line_start", rng[0])
                    r.setdefault("line_end", rng[1])
                r.setdefault("additions", src["additions"])
                r.setdefault("deletions", src["deletions"])
                if cfg["report"].get("show_diff_snippets", True):
                    r.setdefault("diff_snippet", src["preview"])
            if not r.get("line_link") and r.get("line_start"):
                r["line_link"] = build_link(
                    r["file"],
                    r["line_start"],
                    r.get("line_end"),
                    changes["meta"],
                    cfg["links"],
                    changes["meta"].get("root") or ".",
                ).get("href")
    s = review.setdefault("summary", {})
    st = s.setdefault("stats", {})
    rows = review["rows"]
    st.setdefault("files", len({r["file"] for r in rows}))
    st.setdefault("functions", len({(r["file"], r.get("function")) for r in rows if r.get("function")}))
    if changes:
        st.setdefault("additions", changes["stats"]["additions"])
        st.setdefault("deletions", changes["stats"]["deletions"])
        st.setdefault("skipped", changes["stats"]["skipped"])
    for k in ("green", "amber", "red"):
        st[k] = sum(1 for r in rows if r["logical"] == k)
    for fnd in review.get("findings") or []:
        f = by_path.get(fnd.get("file", ""))
        if f and not fnd.get("link"):
            fnd["link"] = build_link(
                fnd["file"], fnd.get("line"), None, changes["meta"], cfg["links"], changes["meta"].get("root") or "."
            ).get("href")
    review["render"] = {
        "sections": cfg["report"]["sections"],
        "columns": cfg["report"]["columns"],
        "group_by": cfg["report"]["group_by"],
        "sort": cfg["report"]["sort"],
        "severity_scale": cfg["severity_scale"],
    }
    return review


def warnings(review: dict, cfg: dict) -> list[str]:
    """Contradictions worth a second look; they do not block rendering."""
    scale, out = cfg["severity_scale"], []
    mid = scale[len(scale) // 2] if scale else None
    for i, r in enumerate(review.get("rows") or []):
        if (
            mid
            and r.get("verdict") == (cfg["verdicts"][0] if cfg.get("verdicts") else "lgtm")
            and r.get("severity") in scale
            and scale.index(r["severity"]) >= scale.index(mid)
        ):
            out.append(
                f"rows[{i}] ({r.get('file')}::{r.get('function')}): severity '{r['severity']}' with verdict '{r['verdict']}'. Lower the severity or change the verdict"
            )
    return out


def to_markdown(review: dict, cfg: dict) -> str:
    m, s = review["meta"], review["summary"]
    out = [f"# {m['title']}", ""]
    line = [
        x
        for x in [
            m.get("repo") and f"{m['repo']}{' #' + str(m['number']) if m.get('number') else ''}",
            m.get("url"),
            m.get("author") and f"by {m['author']}",
        ]
        if x
    ]
    if line:
        out += [" · ".join(line), ""]
    out += [f"**Verdict:** {s['overall_verdict']}  ", f"**{s['one_liner']}**", ""]
    out += [f"🟢 {s['stats']['green']} · 🟡 {s['stats']['amber']} · 🔴 {s['stats']['red']}", ""]
    for p in s.get("narrative") or []:
        out += [p, ""]
    cols = cfg["report"]["columns"]
    head = {
        "file": "File",
        "function": "Function",
        "change_type": "Change",
        "logical": "Logical",
        "what": "What changed",
        "why": "Why",
        "verdict": "Verdict",
        "severity": "Severity",
        "impact": "Impact",
        "lines": "Lines",
    }
    out += [
        "## Changes by function",
        "",
        "| " + " | ".join(head.get(c, c) for c in cols) + " |",
        "|" + "---|" * len(cols),
    ]
    emoji = {"green": "🟢", "amber": "🟡", "red": "🔴"}
    for r in review["rows"]:
        cells = []
        for c in cols:
            if c == "file":
                cells.append(f"[{r['file']}]({r['file_link']})" if r.get("file_link") else r["file"])
            elif c == "function":
                fn = r.get("function") or "—"
                cells.append(f"[{fn}]({r['line_link']})" if r.get("line_link") else fn)
            elif c == "logical":
                cells.append(f"{emoji[r['logical']]} {r['logical']}")
            elif c == "lines":
                cells.append(
                    f"{r.get('line_start', '')}{'–' + str(r['line_end']) if r.get('line_end') and r.get('line_end') != r.get('line_start') else ''}"
                )
            else:
                cells.append(str(r.get(c) or "").replace("|", "\\|").replace("\n", " "))
        out.append("| " + " | ".join(cells) + " |")
    if review.get("findings"):
        out += ["", "## Findings", ""]
        for f in review["findings"]:
            loc = f" (`{f['file']}{':' + str(f['line']) if f.get('line') else ''}`)" if f.get("file") else ""
            out += [
                f"- **{f['severity']}** — {f['title']}{loc}: {f.get('detail', '')}"
                + (f" _Suggestion: {f['suggestion']}_" if f.get("suggestion") else "")
            ]
    if review.get("test_gaps"):
        out += ["", "## Test gaps", ""] + [
            f"- `{g['file']}`{' · ' + g['function'] if g.get('function') else ''} — {g['reason']}"
            for g in review["test_gaps"]
        ]
    if review.get("questions"):
        out += ["", "## Questions for the author", ""] + [
            f"- {q if isinstance(q, str) else q.get('text')}" for q in review["questions"]
        ]
    return "\n".join(out) + "\n"


def output_path(review: dict, cfg: dict, ext: str) -> Path:
    m = review["meta"]
    name = cfg["output"]["filename"].format(
        repo=(m.get("repo") or "repo").replace("/", "-"),
        id=m.get("number") or (m.get("head") or "diff").replace("/", "-"),
        date=dt.date.today().isoformat(),
        branch=(m.get("head") or "").replace("/", "-"),
    )
    name = str(Path(name).with_suffix(ext))
    base = Path(m.get("root") or git_root())
    return base / cfg["output"]["dir"] / name


def open_file(path: Path) -> None:
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        print(f"(could not open automatically: {e})")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    review = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    changes = json.loads(Path(argv[argv.index("--changes") + 1]).read_text()) if "--changes" in argv else None
    cfg = json.loads(Path(argv[argv.index("--config") + 1]).read_text()) if "--config" in argv else effective_config()
    errs = validate(review, cfg)
    if errs:
        print("review.json has problems:\n  - " + "\n  - ".join(errs))
        sys.exit(1)
    if "--validate-only" in argv:
        print("review.json is valid")
        return
    for w in warnings(review, cfg):
        print(f"warning: {w}")
    review = fill(review, changes, cfg)
    fmt = argv[argv.index("--format") + 1] if "--format" in argv else cfg["output"]["format"]
    explicit = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    written = []
    if fmt in ("html", "both"):
        public = {
            **review,
            "meta": {k: v for k, v in review["meta"].items() if k not in ("root", "diff_path")},
        }  # no local paths in a shareable file
        data = json.dumps(public).replace("</", "<\\/")
        html = (
            TEMPLATE.read_text(encoding="utf-8")
            .replace("__PRISM_DATA__", data)
            .replace("__PRISM_TITLE__", review["meta"]["title"].replace("<", "&lt;"))
        )
        p = explicit if explicit and explicit.suffix == ".html" else output_path(review, cfg, ".html")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        written.append(p)
    if fmt in ("markdown", "both"):
        p = explicit if explicit and explicit.suffix == ".md" else output_path(review, cfg, ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(to_markdown(review, cfg), encoding="utf-8")
        written.append(p)
    st = review["summary"]["stats"]
    for p in written:
        print(f"report: {p}")
    print(
        f"verdict: {review['summary']['overall_verdict']}  rows: {len(review['rows'])}  🟢{st['green']} 🟡{st['amber']} 🔴{st['red']}  findings: {len(review.get('findings') or [])}"
    )
    if (
        ("--open" in argv or cfg["output"]["open"])
        and written
        and written[0].suffix == ".html"
        and "--no-open" not in argv
    ):
        open_file(written[0])


if __name__ == "__main__":
    main(sys.argv[1:])
