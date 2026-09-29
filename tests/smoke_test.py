#!/usr/bin/env python3
"""End-to-end smoke test: frontmatter → config → synthetic repo → fetch → parse → review → render."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pr-ism"
S = SKILL / "scripts"


def sh(cmd, cwd=None, check=True, **kw):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        sys.exit(f"FAIL {' '.join(map(str, cmd))}\n{r.stdout}{r.stderr}")
    return r


def check_frontmatter():
    text = (SKILL / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    fm = m.group(1)
    name = re.search(r"^name:\s*(\S+)", fm, re.M).group(1)
    assert name == SKILL.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64, f"bad name {name}"
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1)
    assert 0 < len(desc) <= 1024, f"description length {len(desc)}"
    body_lines = text[m.end() :].count("\n")
    assert body_lines < 500, f"SKILL.md body is {body_lines} lines; keep it under 500"
    for f in (
        "references/review-rubric.md",
        "references/review-schema.md",
        "references/config-reference.md",
        "references/toolkit-engine.md",
        "references/chat-modes.md",
        "assets/report-template.html",
        "assets/default-config.json",
    ):
        assert (SKILL / f).exists(), f"missing {f}"
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    skill_v = re.search(r'^\s*version:\s*"([^"]+)"', fm, re.M).group(1)
    versions = {
        "SKILL.md": skill_v,
        "plugin.json": plugin["version"],
        "marketplace.json": market["plugins"][0]["version"],
    }
    assert len(set(versions.values())) == 1, f"versions out of sync: {versions}"
    assert re.search(rf"^## {re.escape(skill_v)}\b", (ROOT / "CHANGELOG.md").read_text(), re.M), (
        f"CHANGELOG.md has no section for {skill_v}"
    )
    print("ok  frontmatter + manifests")


def check_pipeline():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        sh(["git", "init", "-q", "-b", "main"], d)
        sh(["git", "config", "user.email", "t@t"], d)
        sh(["git", "config", "user.name", "t"], d)
        sh(["git", "config", "core.hooksPath", "/dev/null"], d)  # ignore the developer's global hooks
        (d / ".git" / "info" / "exclude").write_text(".pr-ism/\n")
        (d / "src").mkdir()
        (d / "src" / "a.py").write_text("def f(x):\n    return x\n")
        (d / "yarn.lock").write_text("lock\n")
        sh(["git", "add", "-A"], d)
        sh(["git", "commit", "-qm", "init"], d)
        sh(["git", "checkout", "-qb", "feat"], d)
        (d / "src" / "a.py").write_text(
            "def f(x):\n    if x is None:\n        return 0\n    return x\n\ndef g():\n    return 1\n"
        )
        (d / "yarn.lock").write_text("lock2\n")
        sh(["git", "add", "-A"], d)
        sh(["git", "commit", "-qm", "Handle None in f, add g"], d)
        sh(["git", "checkout", "-q", "main"], d)
        w = d / ".pr-ism"
        w.mkdir()
        eff = w / "effective.json"
        eff.write_text(sh([sys.executable, S / "config.py", "show", "--json"], d).stdout)
        sh([sys.executable, S / "config.py", "set", "review.depth", "deep"], d)
        r = sh([sys.executable, S / "config.py", "set", "review.depth", "bogus"], d, check=False)
        assert r.returncode == 1
        sh([sys.executable, S / "fetch_pr.py", "feat", "--out", w / "work" / "x"], d)
        sh(
            [
                sys.executable,
                S / "parse_diff.py",
                w / "work" / "x" / "pr.diff",
                "--meta",
                w / "work" / "x" / "pr.json",
                "--config",
                eff,
                "--out",
                w / "work" / "x" / "changes.json",
            ],
            d,
        )
        ch = json.loads((w / "work" / "x" / "changes.json").read_text())
        assert [f["path"] for f in ch["files"]] == ["src/a.py"], ch["files"]
        assert ch["skipped"][0]["path"] == "yarn.lock"
        fns = {s["function"] for h in ch["files"][0]["hunks"] for s in h["segments"]}
        assert fns == {"f", "g"}, fns
        assert (w / "work" / "x" / "changes.md").exists()
        shown = sh(
            [sys.executable, S / "parse_diff.py", "show", w / "work" / "x" / "changes.json", "src/a.py:g"], d
        ).stdout
        assert "def g" in shown
        # keyword false positives + rename detection
        sys.path.insert(0, str(S))
        import parse_diff as pd  # noqa: E402

        assert pd.def_name("if (x) {", "javascript") is None and pd.def_name("} else if (v > hi) {", "java") is None
        assert pd.def_name("for (const it of o.items) {", "javascript") is None
        assert (
            pd.def_name("export function newName(x) {", "javascript") == "newName"
            and pd.def_name("func (s *Svc) Handle(w http.ResponseWriter) {", "go") == "Handle"
        )
        segs = pd.segments(
            [
                {"t": "-", "text": "def old():", "old": 1},
                {"t": "+", "text": "def new():", "new": 1},
                {"t": " ", "text": "    pass", "old": 2, "new": 2},
            ],
            None,
            "python",
        )
        assert segs[0]["function"] == "old → new", segs
        review = {
            "meta": {"title": "t"},
            "summary": {"overall_verdict": "approve-with-nits", "one_liner": "fine"},
            "rows": [
                {
                    "file": "src/a.py",
                    "function": "f",
                    "change_type": "bugfix",
                    "logical": "amber",
                    "what": "handles None",
                    "verdict": "lgtm",
                    "severity": "info",
                },
                {
                    "file": "src/a.py",
                    "function": "g",
                    "change_type": "added",
                    "logical": "green",
                    "what": "new helper",
                    "verdict": "nit",
                    "severity": "low",
                },
            ],
        }
        (w / "work" / "x" / "review.json").write_text(json.dumps(review))
        out = sh(
            [
                sys.executable,
                S / "render_report.py",
                w / "work" / "x" / "review.json",
                "--changes",
                w / "work" / "x" / "changes.json",
                "--config",
                eff,
                "--format",
                "both",
                "--no-open",
            ],
            d,
        ).stdout
        html = next((d / ".pr-ism" / "reviews").glob("*.html")).read_text()
        assert "__PRISM_DATA__" not in html and '"line_start": 6' in html or '"line_start":6' in html, (
            "row g should resolve to line 6"
        )
        bad = dict(review)
        bad["rows"] = [dict(review["rows"][0], logical="blue")]
        (w / "bad.json").write_text(json.dumps(bad))
        r = sh([sys.executable, S / "render_report.py", w / "bad.json", "--validate-only"], d, check=False)
        assert r.returncode == 1 and "logical" in r.stdout
        # post_review: local changes have nowhere to post; a GitHub-shaped one yields inline + overflow comments
        r = sh(
            [
                sys.executable,
                S / "post_review.py",
                w / "work" / "x" / "review.json",
                "--changes",
                w / "work" / "x" / "changes.json",
                "--config",
                eff,
            ],
            d,
            check=False,
        )
        assert r.returncode == 1 and "nothing to post to" in (r.stdout + r.stderr), r.stdout + r.stderr
        gh = dict(ch, meta={**ch["meta"], "provider": "github", "repo": "o/r", "number": 7, "head_sha": "abc"})
        (w / "gh.json").write_text(json.dumps(gh))
        rv = dict(
            review,
            findings=[
                {"severity": "high", "title": "None path untested", "file": "src/a.py", "line": 2},
                {"severity": "medium", "title": "off-diff", "file": "src/a.py", "line": 999},
            ],
            rows=[dict(review["rows"][0], verdict="needs-changes", severity="high"), review["rows"][1]],
        )
        (w / "rv.json").write_text(json.dumps(rv))
        dry = sh(
            [sys.executable, S / "post_review.py", w / "rv.json", "--changes", w / "gh.json", "--config", eff], d
        ).stdout
        assert "dry run" in dry and "inline comments: 2" in dry and "in summary only: 1" in dry, dry
        payload = json.loads((w / "comments.json").read_text())
        assert payload["event"] == "COMMENT" and payload["commit_id"] == "abc" and "off-diff" in payload["body"], (
            payload
        )
        check_merge(d, w, eff, review)
        # repeat review: second fetch after a new commit writes pr.since.diff with only the new change
        (w / "work" / "x" / "review.json").write_text(json.dumps(review))
        sh(["git", "checkout", "-q", "feat"], d)
        (d / "src" / "b.py").write_text("def h():\n    return 2\n")
        sh(["git", "add", "-A"], d)
        sh(["git", "commit", "-qm", "add h"], d)
        sh(["git", "checkout", "-q", "main"], d)
        again = sh([sys.executable, S / "fetch_pr.py", "feat", "--out", w / "work" / "x"], d).stdout
        assert "incremental:" in again, again
        since = (w / "work" / "x" / "pr.since.diff").read_text()
        assert "src/b.py" in since and "src/a.py" not in since, since
        assert (w / "work" / "x" / "review.prev.json").exists() and not (w / "work" / "x" / "review.json").exists()
        same = sh([sys.executable, S / "fetch_pr.py", "feat", "--out", w / "work" / "x"], d).stdout
        assert "unchanged since the last review" in same and not (w / "work" / "x" / "pr.since.diff").exists(), same
        print("ok  pipeline:", out.strip().splitlines()[-1])


def check_merge(d, w, eff, review):
    """merge_findings.py with a fake agent-findings.jsonl; no model involved."""
    x = w / "work" / "x"
    changes = x / "changes.json"

    def merge(agents_lines, name):
        (w / f"{name}.jsonl").write_text("\n".join(agents_lines) + "\n")
        src = w / f"{name}-review.json"
        src.write_text(json.dumps(dict(review, findings=[{"severity": "low", "title": "g could be inlined"}])))
        cmd = [sys.executable, S / "merge_findings.py", src, "--changes", changes, "--agents", w / f"{name}.jsonl"]
        out = sh([*cmd, "--config", eff], d).stdout
        return json.loads(src.read_text()), out, cmd

    # prism-only: an empty agents file changes nothing but tags findings with source
    merged, out, _ = merge([], "none")
    assert merged["rows"] == [dict(r, id=f"r{i + 1}") for i, r in enumerate(review["rows"])], merged["rows"]
    assert [f["source"] for f in merged["findings"]] == ["prism"], merged["findings"]

    def fnd(**kw):
        return json.dumps({"file": "src/a.py", "detail": "d", "suggestion": "s", **kw})

    agents = [
        fnd(agent="code-reviewer", line=3, severity="high", title="None input silently returns 0", confidence=92),
        fnd(
            agent="silent-failure-hunter",
            line=4,
            severity="medium",
            title="None input silently returns zero",
            confidence=85,
        ),
        fnd(agent="code-reviewer", line=999, severity="medium", title="Module docstring is stale", confidence=90),
        fnd(
            agent="type-design-analyzer", line=6, severity="high", title="g should return a typed value", confidence=50
        ),
        fnd(agent="pr-test-analyzer", line=2, severity="important", title="No test for the None branch", confidence=95),
        "this is not json",
    ]
    merged, out, cmd = merge(agents, "agents")
    rows = {r["function"]: r for r in merged["rows"]}
    by_title = {f["title"]: f for f in merged["findings"]}
    hit = by_title["None input silently returns 0"]
    assert hit["source"] == "toolkit:code-reviewer" and hit["row_ids"] == [rows["f"]["id"]], hit
    assert hit["also_found_by"] == ["toolkit:silent-failure-hunter"], hit  # the duplicate folded in
    assert "None input silently returns zero" not in by_title
    assert rows["f"]["severity"] == "high" and rows["f"]["verdict"] == "needs-changes", rows["f"]  # raised
    assert rows["g"]["severity"] == "low" and rows["g"]["verdict"] == "nit", rows["g"]  # untouched
    stray = by_title["Module docstring is stale"]
    assert "row_ids" not in stray, stray  # lands in no segment: stays top-level
    assert "g should return a typed value" not in by_title  # below confidence 80
    gap = merged["test_gaps"][0]
    assert gap["source"] == "toolkit:pr-test-analyzer" and gap["function"] == "f", gap
    assert "malformed" in out and "rows raised: 1" in out, out
    # rerunning the merge on its own output adds nothing
    sh([*cmd, "--config", eff], d)
    rerun = json.loads(Path(cmd[2]).read_text())
    assert rerun["findings"] == merged["findings"], (rerun["findings"], merged["findings"])
    # renderer accepts the sources and labels them
    sh(
        [
            sys.executable,
            S / "render_report.py",
            cmd[2],
            "--changes",
            changes,
            "--config",
            eff,
            "--out",
            w / "merged.html",
            "--format",
            "html",
            "--no-open",
        ],
        d,
    )
    html = (w / "merged.html").read_text()
    assert "toolkit:code-reviewer" in html and 'id="src"' in html
    check_path_and_decisions(d, w, eff, cmd[2], changes)
    bad = dict(merged, findings=[dict(hit, source="gpt")])
    (w / "badsrc.json").write_text(json.dumps(bad))
    r = sh([sys.executable, S / "render_report.py", w / "badsrc.json", "--validate-only"], d, check=False)
    assert r.returncode == 1 and "source" in r.stdout, r.stdout
    print("ok  merge:", out.strip().splitlines()[0])


def check_path_and_decisions(d, w, eff, review_path, changes):
    """Renderer: stations, ids, hashes, tiles. post_review: --decisions."""
    sys.path.insert(0, str(S))
    import render_report as rr  # noqa: E402

    cfg = json.loads(Path(eff).read_text())
    rv = rr.fill(json.loads(Path(review_path).read_text()), json.loads(Path(changes).read_text()), cfg)
    rows = {r["function"]: r for r in rv["rows"]}
    assert rows["f"]["station"] == 1 and rows["g"]["station"] == 5, [(r["function"], r["station"]) for r in rv["rows"]]
    assert rows["f"]["hunk_hash"] and rows["f"]["id"] == "r1" and rv["findings"][0]["id"] == "f1"
    assert rv["summary"]["load_bearing"] == ["r1"], rv["summary"]["load_bearing"]  # fallback: the top non-lgtm row
    assert [t["name"] for t in rv["render"]["dirs"]] == ["src/"] and rv["render"]["dirs"][0]["findings"] >= 1
    assert rv["summary"]["stats"]["sessions"] == 1 and [s["n"] for s in rv["render_stations"]] == [1, 2, 3, 4, 5]
    # an explicit load_bearing wins and a bad one is rejected
    rev2 = json.loads(Path(review_path).read_text())
    rev2["summary"]["load_bearing"] = ["r2"]
    rev2["summary"]["verify"] = ["call f(None); expect 0"]
    assert rr.fill(rev2, json.loads(Path(changes).read_text()), cfg)["rows"][1]["station"] == 1
    rev2["summary"]["verify"] = "not a list"
    assert any("verify" in e for e in rr.validate(rev2, cfg))
    # decisions: dismissed findings are dropped from the post, fixed ones listed
    gh = json.loads(Path(changes).read_text())
    gh["meta"].update(provider="github", repo="o/r", number=7, head_sha="abc")
    (w / "gh2.json").write_text(json.dumps(gh))
    (w / "dec.json").write_text(
        json.dumps({"head_sha": "abc", "decisions": {"f2": {"state": "dismiss"}, "f3": {"state": "fixed"}}})
    )
    out = sh(
        [
            sys.executable,
            S / "post_review.py",
            review_path,
            "--changes",
            w / "gh2.json",
            "--config",
            eff,
            "--decisions",
            w / "dec.json",
            "--out",
            w / "dec-payload.json",
        ],
        d,
    ).stdout
    payload = json.loads((w / "dec-payload.json").read_text())
    titles = [f["title"] for f in rv["findings"]]
    assert (
        titles[1] not in payload["body"] and titles[2] in payload["body"] and "Already addressed" in payload["body"]
    ), (out, payload["body"])
    assert "already fixed: 1" in out, out
    print("ok  review path + decisions")


if __name__ == "__main__":
    check_frontmatter()
    check_pipeline()
    print("all good")
