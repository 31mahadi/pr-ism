#!/usr/bin/env python3
"""Merge pr-review-toolkit agent findings into review.json.

Usage: merge_findings.py <review.json> --changes changes.json --agents agent-findings.jsonl
                         [--config effective.json] [--out PATH]

- agent-findings.jsonl: one JSON object per line
  {agent, file, line, severity, title, detail, suggestion, confidence}
- Drops findings below review.min_agent_confidence (a finding with no confidence is kept).
- Dedupes near-identical findings (same file, lines within 3, and a similar title or the same
  severity), including against findings Claude already wrote; the survivor records every agent
  in `also_found_by`.
- Maps agent severities onto the configured severity_scale.
- Attaches each finding to the row whose segment range (changes.json) contains its line via
  `row_ids`, and raises that row's severity, and its verdict when the new severity warrants it.
  Findings that match no row stay top-level without `row_ids`.
- pr-test-analyzer findings become test_gaps, never severity.
- Every finding gets `source`: "prism" or "toolkit:<agent>". Re-running (or merging a repeat
  review's new findings into carried-over ones) dedupes instead of duplicating.
Writes review.json in place unless --out is given. Rendering is still render_report.py's job.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import effective as effective_config  # noqa: E402

# common agent severity words -> position on a 5-step ladder (info .. critical)
LADDER = {
    "info": 0,
    "trivial": 0,
    "nit": 0,
    "low": 1,
    "minor": 1,
    "suggestion": 1,
    "medium": 2,
    "moderate": 2,
    "warning": 2,
    "high": 3,
    "major": 3,
    "important": 3,
    "error": 3,
    "critical": 4,
    "blocker": 4,
    "blocking": 4,
}
TEST_AGENTS = {"pr-test-analyzer"}
LINE_SLACK = 3
TITLE_SIMILARITY = 0.6
WORD_OVERLAP = 0.4


def map_severity(value: object, scale: list[str]) -> str:
    s = str(value or "").strip().lower()
    if s in scale:
        return s
    step = LADDER.get(s, 2)
    return scale[round(step * (len(scale) - 1) / 4)]


def load_agent_findings(path: Path) -> tuple[list[dict], int]:
    out, bad = [], 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            f = json.loads(raw)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(f, dict) or not f.get("title"):
            bad += 1
            continue
        if isinstance(f.get("line"), str) and f["line"].isdigit():
            f["line"] = int(f["line"])
        out.append(f)
    return out, bad


def word_overlap(a: str, b: str) -> float:
    """Share of content words (4-char stems) the shorter title has in common with the longer."""
    wa = {w[:4] for w in a.lower().split() if len(w) >= 3}
    wb = {w[:4] for w in b.lower().split() if len(w) >= 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def similar(a: dict, b: dict) -> bool:
    if (a.get("file") or "") != (b.get("file") or ""):
        return False
    la, lb = a.get("line"), b.get("line")
    if isinstance(la, int) and isinstance(lb, int) and abs(la - lb) > LINE_SLACK:
        return False
    if isinstance(la, int) != isinstance(lb, int):
        return False
    ratio = difflib.SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio()
    if ratio >= TITLE_SIMILARITY:
        return True
    # same spot, same severity, some shared words: two reviewers describing one issue differently
    return (
        isinstance(la, int)
        and a.get("severity") == b.get("severity")
        and word_overlap(a["title"], b["title"]) >= WORD_OVERLAP
    )


def row_ranges(row: dict, by_path: dict) -> list[tuple[int, int]]:
    """Line ranges (head side) a row covers: its function's segments, else its hunks, else its lines."""
    f = by_path.get(row["file"])
    if row["file"].endswith("/") or not f:
        return []
    ids = row.get("hunk_ids") or ([row["hunk_id"]] if row.get("hunk_id") else [])
    fn = (row.get("function") or "").strip()
    hunks = [h for h in f["hunks"] if h["id"] in ids]
    if not hunks and fn:
        hunks = [h for h in f["hunks"] if any(s["function"] == fn for s in h.get("segments", []))]
    out = []
    for h in hunks:
        segs = [s for s in h.get("segments", []) if s.get("new_range") and (not fn or s["function"] == fn)]
        out += [tuple(s["new_range"]) for s in segs] or ([tuple(h["new_range"])] if h.get("new_range") else [])
    if not out and isinstance(row.get("line_start"), int):
        out.append((row["line_start"], row.get("line_end") or row["line_start"]))
    return out


def match_row(finding: dict, rows: list[dict], by_path: dict) -> dict | None:
    line = finding.get("line")
    if not isinstance(line, int):
        return None
    best, width = None, None
    for r in rows:
        if r["file"] != finding.get("file"):
            continue
        for lo, hi in row_ranges(r, by_path):
            if lo <= line <= hi and (width is None or hi - lo < width):
                best, width = r, hi - lo
    return best


def merge(review: dict, changes: dict, agent_findings: list[dict], cfg: dict) -> dict:
    scale, verdicts = cfg["severity_scale"], cfg["verdicts"]
    rank = {s: i for i, s in enumerate(scale)}
    vrank = {v: i for i, v in enumerate(verdicts)}
    mid = len(scale) // 2
    threshold = cfg["review"].get("min_agent_confidence", 80)
    by_path = {f["path"]: f for f in changes.get("files", [])}
    rows = review["rows"]
    taken = {r["id"] for r in rows if r.get("id")}
    n = 0
    for r in rows:
        if not r.get("id"):
            n += 1
            while f"r{n}" in taken:
                n += 1
            r["id"] = f"r{n}"
            taken.add(r["id"])

    # findings from a previous merge (or carried over from review.prev.json) stay; a rerun dedupes against them
    findings: list[dict] = []
    for f in review.get("findings") or []:
        # findings already in the file may duplicate each other (a prism one restating an agent's)
        dup = next((k for k in findings if similar(k, f)), None)
        if dup is None:
            findings.append(f)
            continue
        for src in [f.get("source") or "prism", *(f.get("also_found_by") or [])]:
            if src != dup.get("source", "prism") and src not in dup.setdefault("also_found_by", []):
                dup["also_found_by"].append(src)
        if f.get("row_ids") and not dup.get("row_ids"):
            dup["row_ids"] = f["row_ids"]
    gaps = list(review.get("test_gaps") or [])
    for f in findings:
        f.setdefault("source", "prism")
    for g in gaps:
        g.setdefault("source", "prism")

    stats = {"read": len(agent_findings), "low_confidence": 0, "duplicates": 0, "attached": 0, "unattached": 0}
    stats.update({"test_gaps": 0, "rows_raised": 0})
    kept: list[dict] = []
    for a in sorted(agent_findings, key=lambda x: -(x.get("confidence") or 0)):
        conf = a.get("confidence")
        if isinstance(conf, (int, float)) and conf < threshold:
            stats["low_confidence"] += 1
            continue
        agent = str(a.get("agent") or "unknown")
        f = {
            "severity": map_severity(a.get("severity"), scale),
            "title": a["title"].strip(),
            "detail": a.get("detail") or "",
            "suggestion": a.get("suggestion") or "",
            "file": a.get("file"),
            "line": a.get("line"),
            "source": f"toolkit:{agent}",
        }
        if isinstance(conf, (int, float)):
            f["confidence"] = conf
        f = {k: v for k, v in f.items() if v not in (None, "")}
        if agent in TEST_AGENTS:
            row = match_row(f, rows, by_path)
            gap = {
                k: v
                for k, v in {
                    "file": f.get("file") or "",
                    "function": row.get("function") if row else None,
                    "reason": f["title"] + (f": {f['detail']}" if f.get("detail") else ""),
                    "source": f["source"],
                }.items()
                if v
            }
            if not any(g.get("file") == gap.get("file") and g.get("reason") == gap["reason"] for g in gaps):
                gaps.append(gap)
                stats["test_gaps"] += 1
            continue
        dup = next((k for k in findings + kept if similar(k, f)), None)
        if dup is not None:
            stats["duplicates"] += 1
            if f["source"] != dup["source"] and f["source"] not in dup.get("also_found_by", []):
                dup.setdefault("also_found_by", []).append(f["source"])
            if rank[f["severity"]] > rank.get(dup["severity"], 0) and dup["source"] != "prism":
                dup["severity"] = f["severity"]
            continue
        kept.append(f)

    for f in kept:
        row = match_row(f, rows, by_path)
        if row is None:
            stats["unattached"] += 1
            continue
        stats["attached"] += 1
        f["row_ids"] = [row["id"]]
        raised = False
        if rank[f["severity"]] > rank.get(row["severity"], 0):
            row["severity"] = f["severity"]
            raised = True
        if rank[row["severity"]] >= mid and len(verdicts) >= 2:
            floor = verdicts[-2]  # needs-changes on the default scale; never auto-blocking
            if vrank.get(row["verdict"], 0) < vrank[floor]:
                row["verdict"] = floor
                raised = True
        stats["rows_raised"] += raised

    review["findings"] = findings + kept
    review["test_gaps"] = gaps
    return {"review": review, "stats": stats}


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help") or "--changes" not in argv or "--agents" not in argv:
        print(__doc__)
        sys.exit(0 if argv and argv[0] in ("-h", "--help") else 2)
    review_path = Path(argv[0])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    changes = json.loads(Path(argv[argv.index("--changes") + 1]).read_text(encoding="utf-8"))
    agents_path = Path(argv[argv.index("--agents") + 1])
    cfg = (
        json.loads(Path(argv[argv.index("--config") + 1]).read_text(encoding="utf-8"))
        if "--config" in argv
        else effective_config()
    )
    agent_findings, bad = load_agent_findings(agents_path) if agents_path.exists() else ([], 0)
    result = merge(review, changes, agent_findings, cfg)
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else review_path
    out.write_text(json.dumps(result["review"], indent=2) + "\n", encoding="utf-8")
    st = result["stats"]
    by_source: dict[str, int] = {}
    for f in result["review"]["findings"]:
        by_source[f["source"]] = by_source.get(f["source"], 0) + 1
    print(
        f"merged: {st['read']} agent findings → {st['attached']} on rows, {st['unattached']} top-level, "
        f"{st['test_gaps']} test gaps; dropped {st['low_confidence']} below confidence, {st['duplicates']} duplicates"
    )
    print("findings by source: " + ", ".join(f"{k} {v}" for k, v in sorted(by_source.items())))
    if st["rows_raised"]:
        print(f"rows raised: {st['rows_raised']}. Re-check summary.overall_verdict and the narrative")
    if bad:
        print(f"warning: skipped {bad} malformed line(s) in {agents_path.name}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
