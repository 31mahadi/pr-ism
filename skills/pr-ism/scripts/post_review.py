#!/usr/bin/env python3
"""Post a finished review back to the PR as comments.

Usage: post_review.py <review.json> --changes changes.json [--post] [--event comment|request-changes|approve]
                      [--min-severity SEV] [--out payload.json]

Without --post it only prints what would be posted (dry run) and writes the payload.

GitHub: one pull-request review — a summary body plus inline comments on the exact lines, via `gh api`.
        Findings and rows whose line is not inside a diff hunk go into the summary body instead
        (GitHub rejects inline comments outside the diff).
GitLab: one MR note with the same markdown (via `glab mr note`); no inline comments.
Other providers (local branch, patch): nothing to post to — exits 1.

Inline comments are made for findings, and for rows whose verdict is needs-changes, blocking or
question, at or above --min-severity (default: the second-lowest configured severity).
The review event defaults to `comment`; it never approves or requests changes unless asked.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import effective as effective_config  # noqa: E402

EVENTS = {"comment": "COMMENT", "request-changes": "REQUEST_CHANGES", "approve": "APPROVE"}
ROW_VERDICTS = {"needs-changes", "blocking", "question"}
EMOJI = {"green": "🟢", "amber": "🟡", "red": "🔴"}
MARKER = "<!-- pr-ism -->"


def die(msg: str) -> None:
    sys.exit(f"pr-ism post: {msg}")


def in_diff(by_path: dict, path: str, line: int | None) -> bool:
    f = by_path.get(path)
    return bool(f and line and any(h.get("new_range") and h["new_range"][0] <= line <= h["new_range"][1] for h in f["hunks"]))


def collect(review: dict, changes: dict, cfg: dict, min_sev: str) -> tuple[list[dict], list[str]]:
    """Return (inline comments, overflow bullets that could not be placed on a diff line)."""
    scale = cfg["severity_scale"]
    rank = {s: i for i, s in enumerate(scale)}
    floor = rank.get(min_sev, 0)
    by_path = {f["path"]: f for f in changes.get("files", [])}
    inline, overflow, seen = [], [], set()

    def place(path: str | None, line: int | None, body: str, bullet: str) -> None:
        if path and in_diff(by_path, path, line) and (path, line) not in seen:
            seen.add((path, line))
            inline.append({"path": path, "line": line, "side": "RIGHT", "body": body})
        else:
            overflow.append(bullet)

    for f in review.get("findings") or []:
        if rank.get(f["severity"], 0) < floor:
            continue
        body = f"**{f['severity']}: {f['title']}**\n\n{f.get('detail', '')}".strip()
        if f.get("suggestion"):
            body += f"\n\n_Suggestion:_ {f['suggestion']}"
        loc = f" (`{f['file']}{':' + str(f['line']) if f.get('line') else ''}`)" if f.get("file") else ""
        place(f.get("file"), f.get("line"), body, f"- **{f['severity']}**: {f['title']}{loc}: {f.get('detail', '')}")
    for r in review["rows"]:
        if r["verdict"] not in ROW_VERDICTS or rank.get(r["severity"], 0) < floor:
            continue
        body = f"**{r['verdict']}** · {r['severity']} · `{r.get('function') or 'top-level'}`\n\n{r['what']}"
        if r.get("why"):
            body += f"\n\n{r['why']}"
        if r.get("suggestion"):
            body += f"\n\n_Suggestion:_ {r['suggestion']}"
        place(r["file"], r.get("line_start"), body, f"- **{r['verdict']}** `{r['file']}` · `{r.get('function') or 'top-level'}`: {r['what']}")
    return inline, overflow


def summary_body(review: dict, overflow: list[str], report_note: str | None) -> str:
    s = review["summary"]
    st = s.get("stats", {})
    rows = review["rows"]
    counts = {k: st.get(k, sum(1 for r in rows if r["logical"] == k)) for k in EMOJI}
    out = [MARKER, f"### pr-ism review: {s['overall_verdict']}", "", s["one_liner"], "",
           " · ".join(f"{EMOJI[k]} {counts[k]}" for k in EMOJI)]
    for p in s.get("narrative") or []:
        out += ["", p]
    if overflow:
        out += ["", "**Findings not attached to a diff line**", *overflow]
    if review.get("test_gaps"):
        out += ["", "**Test gaps**"] + [f"- `{g['file']}`{' · ' + g['function'] if g.get('function') else ''}: {g['reason']}" for g in review["test_gaps"]]
    if review.get("questions"):
        out += ["", "**Questions**"] + [f"- {q if isinstance(q, str) else q.get('text')}" for q in review["questions"]]
    if report_note:
        out += ["", f"_{report_note}_"]
    return "\n".join(out)


def gh_api(path: str, payload: dict) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump(payload, t)
    r = subprocess.run(["gh", "api", "-X", "POST", path, "--input", t.name], capture_output=True, text=True)
    Path(t.name).unlink(missing_ok=True)
    if r.returncode != 0:
        die(f"GitHub rejected the review: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout or "{}")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return
    review = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    if "--changes" not in argv:
        die("--changes changes.json is required (it says which lines are inside the diff)")
    changes = json.loads(Path(argv[argv.index("--changes") + 1]).read_text(encoding="utf-8"))
    cfg = json.loads(Path(argv[argv.index("--config") + 1]).read_text()) if "--config" in argv else effective_config()
    meta = {**changes.get("meta", {}), **{k: v for k, v in review.get("meta", {}).items() if v}}
    event = argv[argv.index("--event") + 1] if "--event" in argv else "comment"
    if event not in EVENTS:
        die(f"--event must be one of {sorted(EVENTS)}")
    scale = cfg["severity_scale"]
    min_sev = argv[argv.index("--min-severity") + 1] if "--min-severity" in argv else scale[min(1, len(scale) - 1)]
    if min_sev not in scale:
        die(f"--min-severity must be one of {scale}")

    # lines come from the renderer's fill step; run it so rows without line_start get one
    from render_report import fill  # noqa: E402
    review = fill(review, changes, cfg)
    inline, overflow = collect(review, changes, cfg, min_sev)
    provider, number, repo = meta.get("provider"), meta.get("number"), meta.get("repo")

    if provider == "github":
        payload = {"body": summary_body(review, overflow, None), "event": EVENTS[event], "comments": inline}
        if meta.get("head_sha"):
            payload["commit_id"] = meta["head_sha"]
    elif provider == "gitlab":
        payload = {"body": summary_body(review, overflow + [f"- `{c['path']}:{c['line']}`: {c['body'].splitlines()[0]}" for c in inline], None)}
        inline = []
    else:
        die(f"nothing to post to: this review is of a {provider or 'local'} change, not a GitHub PR or GitLab MR")

    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path(argv[0]).with_name("comments.json")
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    target = f"{repo}#{number}" if provider == "github" else f"{repo}!{number}"
    print(f"target: {target}  event: {event}  inline comments: {len(inline)}  in summary only: {len(overflow)}")
    print(f"payload: {out}")
    if "--post" not in argv:
        print("dry run: nothing posted (add --post to send)")
        return
    if provider == "github":
        if not shutil.which("gh"):
            die("posting to GitHub needs the `gh` CLI, logged in (`gh auth login`)")
        res = gh_api(f"repos/{repo}/pulls/{number}/reviews", payload)
        print(f"posted: {res.get('html_url') or 'ok'}")
    else:
        if not shutil.which("glab"):
            die("posting to GitLab needs the `glab` CLI, logged in (`glab auth login`)")
        r = subprocess.run(["glab", "mr", "note", str(number), "--repo", repo, "--message", payload["body"]], capture_output=True, text=True)
        if r.returncode != 0:
            die(f"GitLab rejected the note: {r.stderr.strip() or r.stdout.strip()}")
        print("posted: MR note added")


if __name__ == "__main__":
    main(sys.argv[1:])
