#!/usr/bin/env python3
"""End-to-end smoke test: frontmatter → config → synthetic repo → fetch → parse → review → render."""
import json, os, re, subprocess, sys, tempfile
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
    body_lines = text[m.end():].count("\n")
    assert body_lines < 500, f"SKILL.md body is {body_lines} lines; keep it under 500"
    for f in ("references/review-rubric.md", "references/review-schema.md", "references/config-reference.md",
              "assets/report-template.html", "assets/default-config.json"):
        assert (SKILL / f).exists(), f"missing {f}"
    json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    print("ok  frontmatter + manifests")


def check_pipeline():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        sh(["git", "init", "-q", "-b", "main"], d)
        sh(["git", "config", "user.email", "t@t"], d); sh(["git", "config", "user.name", "t"], d)
        (d / "src").mkdir(); (d / "src" / "a.py").write_text("def f(x):\n    return x\n")
        (d / "yarn.lock").write_text("lock\n")
        sh(["git", "add", "-A"], d); sh(["git", "commit", "-qm", "init"], d)
        sh(["git", "checkout", "-qb", "feat"], d)
        (d / "src" / "a.py").write_text("def f(x):\n    if x is None:\n        return 0\n    return x\n\ndef g():\n    return 1\n")
        (d / "yarn.lock").write_text("lock2\n")
        sh(["git", "add", "-A"], d); sh(["git", "commit", "-qm", "Handle None in f, add g"], d)
        sh(["git", "checkout", "-q", "main"], d)
        w = d / ".pr-ism"; w.mkdir()
        eff = w / "effective.json"; eff.write_text(sh([sys.executable, S / "config.py", "show", "--json"], d).stdout)
        sh([sys.executable, S / "config.py", "set", "review.depth", "deep"], d)
        r = sh([sys.executable, S / "config.py", "set", "review.depth", "bogus"], d, check=False); assert r.returncode == 1
        sh([sys.executable, S / "fetch_pr.py", "feat", "--out", w / "work" / "x"], d)
        sh([sys.executable, S / "parse_diff.py", w / "work" / "x" / "pr.diff", "--meta", w / "work" / "x" / "pr.json", "--config", eff, "--out", w / "work" / "x" / "changes.json"], d)
        ch = json.loads((w / "work" / "x" / "changes.json").read_text())
        assert [f["path"] for f in ch["files"]] == ["src/a.py"], ch["files"]
        assert ch["skipped"][0]["path"] == "yarn.lock"
        fns = {s["function"] for h in ch["files"][0]["hunks"] for s in h["segments"]}
        assert fns == {"f", "g"}, fns
        assert (w / "work" / "x" / "changes.md").exists()
        shown = sh([sys.executable, S / "parse_diff.py", "show", w / "work" / "x" / "changes.json", "src/a.py:g"], d).stdout
        assert "def g" in shown
        # keyword false positives + rename detection
        sys.path.insert(0, str(S)); import parse_diff as pd  # noqa: E402
        assert pd.def_name("if (x) {", "javascript") is None and pd.def_name("} else if (v > hi) {", "java") is None
        assert pd.def_name("for (const it of o.items) {", "javascript") is None
        assert pd.def_name("export function newName(x) {", "javascript") == "newName" and pd.def_name("func (s *Svc) Handle(w http.ResponseWriter) {", "go") == "Handle"
        segs = pd.segments([{"t": "-", "text": "def old():", "old": 1}, {"t": "+", "text": "def new():", "new": 1}, {"t": " ", "text": "    pass", "old": 2, "new": 2}], None, "python")
        assert segs[0]["function"] == "old → new", segs
        review = {"meta": {"title": "t"}, "summary": {"overall_verdict": "approve-with-nits", "one_liner": "fine"},
                  "rows": [{"file": "src/a.py", "function": "f", "change_type": "bugfix", "logical": "amber", "what": "handles None", "verdict": "lgtm", "severity": "info"},
                           {"file": "src/a.py", "function": "g", "change_type": "added", "logical": "green", "what": "new helper", "verdict": "nit", "severity": "low"}]}
        (w / "work" / "x" / "review.json").write_text(json.dumps(review))
        out = sh([sys.executable, S / "render_report.py", w / "work" / "x" / "review.json", "--changes", w / "work" / "x" / "changes.json", "--config", eff, "--format", "both", "--no-open"], d).stdout
        html = next((d / ".pr-ism" / "reviews").glob("*.html")).read_text()
        assert "__PRISM_DATA__" not in html and '"line_start": 6' in html or '"line_start":6' in html, "row g should resolve to line 6"
        bad = dict(review); bad["rows"] = [dict(review["rows"][0], logical="blue")]
        (w / "bad.json").write_text(json.dumps(bad))
        r = sh([sys.executable, S / "render_report.py", w / "bad.json", "--validate-only"], d, check=False); assert r.returncode == 1 and "logical" in r.stdout
        print("ok  pipeline:", out.strip().splitlines()[-1])


if __name__ == "__main__":
    check_frontmatter(); check_pipeline(); print("all good")
