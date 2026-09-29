#!/usr/bin/env python3
"""Resolve a PR reference into a unified diff plus metadata.

Usage: fetch_pr.py <ref> [--out DIR] [--base BRANCH] [--since SHA] [--full]

Accepted refs
  https://github.com/o/r/pull/123          GitHub PR URL     (gh CLI, else GitHub REST API)
  o/r#123 | #123 | 123                     GitHub PR in repo (gh CLI; bare numbers use the current repo)
  https://gitlab.com/g/p/-/merge_requests/7  GitLab MR URL   (glab CLI)
  !7                                        GitLab MR in the current repo (glab CLI)
  feature/foo | a..b | a...b                local branch or commit range (git; base = --base, else origin default)
  path/to/change.diff | change.patch        a patch file
  -                                         a diff on stdin

Writes <out>/pr.diff and <out>/pr.json and prints both paths.

Repeat reviews: when <out>/pr.json already exists and the PR head moved, it also writes
<out>/pr.since.diff (only the commits since the last review), moves the old review.json to
review.prev.json and prints `incremental: <old>..<new>`. --since SHA forces the starting commit;
--full skips all of this. If the old head is unreachable (force-push), it says so and falls back
to a full review. Exit code 1 with a
plain-English reason when a ref cannot be resolved (missing CLI, auth, not a repo...).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

GH_PR_URL = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
GL_MR_URL = re.compile(r"^https?://([^/]+)/(.+?)/-/merge_requests/(\d+)")
GH_SHORT = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")


def die(msg: str) -> None:
    sys.exit(f"pr-ism fetch: {msg}")


def run(cmd: list[str], check: bool = True, input_text: str | None = None) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    except FileNotFoundError:
        die(f"'{cmd[0]}' is not installed")
    if check and res.returncode != 0:
        die(f"`{' '.join(cmd)}` failed: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def in_git_repo() -> bool:
    return subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True).returncode == 0


def repo_name_from_remote() -> str | None:
    if not in_git_repo():
        return None
    url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def default_base() -> str:
    for cmd in (["git", "symbolic-ref", "refs/remotes/origin/HEAD"],):
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        if out:
            return out.replace("refs/remotes/", "")
    for cand in ("origin/main", "origin/master", "main", "master"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", cand], capture_output=True).returncode == 0:
            return cand
    die("could not determine a base branch; pass --base <branch>")


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- GitHub


def fetch_github(owner: str, repo: str, number: str) -> tuple[str, dict]:
    full = f"{owner}/{repo}"
    if shutil.which("gh"):
        fields = "title,body,author,baseRefName,headRefName,headRefOid,baseRefOid,url,additions,deletions,changedFiles,state,isDraft"
        meta = json.loads(run(["gh", "pr", "view", number, "--repo", full, "--json", fields]))
        diff = run(["gh", "pr", "diff", number, "--repo", full])
        return diff, {
            "provider": "github",
            "repo": full,
            "number": int(number),
            "url": meta["url"],
            "title": meta["title"],
            "body": meta.get("body") or "",
            "author": (meta.get("author") or {}).get("login"),
            "base": meta["baseRefName"],
            "head": meta["headRefName"],
            "head_sha": meta["headRefOid"],
            "base_sha": meta.get("baseRefOid"),
            "state": meta.get("state"),
            "draft": meta.get("isDraft"),
            "additions": meta.get("additions"),
            "deletions": meta.get("deletions"),
            "changed_files": meta.get("changedFiles"),
            "web_base": f"https://github.com/{full}",
        }
    # REST fallback (public repos, or GITHUB_TOKEN for private)
    headers = {"User-Agent": "pr-ism", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api = f"https://api.github.com/repos/{full}/pulls/{number}"
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers)) as r:
            meta = json.load(r)
        with urllib.request.urlopen(
            urllib.request.Request(api, headers={**headers, "Accept": "application/vnd.github.diff"})
        ) as r:
            diff = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        fallback = fetch_via_git_ref(f"refs/pull/{number}/head", full, number, "github")
        if fallback:
            return fallback
        die(
            f"GitHub API {e.code} for {full}#{number} — install `gh` and run `gh auth login`, set GITHUB_TOKEN, or run inside a clone of {full}"
        )
    except urllib.error.URLError as e:
        fallback = fetch_via_git_ref(f"refs/pull/{number}/head", full, number, "github")
        if fallback:
            return fallback
        die(f"network error reaching api.github.com: {e.reason}")
    return diff, {
        "provider": "github",
        "repo": full,
        "number": int(number),
        "url": meta["html_url"],
        "title": meta["title"],
        "body": meta.get("body") or "",
        "author": (meta.get("user") or {}).get("login"),
        "base": meta["base"]["ref"],
        "head": meta["head"]["ref"],
        "head_sha": meta["head"]["sha"],
        "base_sha": meta["base"]["sha"],
        "state": meta.get("state"),
        "draft": meta.get("draft"),
        "additions": meta.get("additions"),
        "deletions": meta.get("deletions"),
        "changed_files": meta.get("changed_files"),
        "web_base": f"https://github.com/{full}",
    }


# ---------------------------------------------------------------- GitLab


def fetch_gitlab(host: str, project: str, iid: str) -> tuple[str, dict]:
    if not shutil.which("glab"):
        fallback = fetch_via_git_ref(
            f"refs/merge-requests/{iid}/head", project, iid, "gitlab", f"https://{host}/{project}"
        )
        if fallback:
            return fallback
        die(
            "GitLab MRs need the `glab` CLI (https://gitlab.com/gitlab-org/cli) — install it and run `glab auth login`, or run inside a clone of the project"
        )
    env_repo = f"{host}/{project}"
    meta = json.loads(run(["glab", "mr", "view", iid, "--repo", env_repo, "--output", "json"]))
    diff = run(["glab", "mr", "diff", iid, "--repo", env_repo, "--raw"])
    return diff, {
        "provider": "gitlab",
        "repo": project,
        "number": int(iid),
        "url": meta.get("web_url"),
        "title": meta.get("title"),
        "body": meta.get("description") or "",
        "author": (meta.get("author") or {}).get("username"),
        "base": meta.get("target_branch"),
        "head": meta.get("source_branch"),
        "head_sha": meta.get("sha"),
        "base_sha": (meta.get("diff_refs") or {}).get("base_sha"),
        "state": meta.get("state"),
        "draft": meta.get("draft"),
        "web_base": f"https://{host}/{project}",
    }


def fetch_via_git_ref(
    remote_ref: str, repo: str, number: str, provider: str, web_base: str | None = None
) -> tuple[str, dict] | None:
    """Private repo, no CLI, but we are inside a clone: fetch the PR head ref with the user's git credentials."""
    if not in_git_repo():
        return None
    local = repo_name_from_remote()
    if not local or local.lower() != repo.lower():
        return None
    r = subprocess.run(
        ["git", "fetch", "-q", "origin", f"{remote_ref}:refs/pr-ism/{number}"], capture_output=True, text=True
    )
    if r.returncode != 0:
        return None
    base = default_base()
    head = f"refs/pr-ism/{number}"
    diff = run(["git", "diff", "--find-renames", f"{base}...{head}"])
    head_sha = run(["git", "rev-parse", head]).strip()
    title = run(["git", "log", "-1", "--format=%s", head]).strip()
    return diff, {
        "provider": provider,
        "repo": repo,
        "number": int(number),
        "url": f"{web_base or 'https://github.com/' + repo}/{'pull' if provider == 'github' else '-/merge_requests'}/{number}",
        "title": title,
        "body": "",
        "author": run(["git", "log", "-1", "--format=%an", head]).strip(),
        "base": base,
        "head": head,
        "head_sha": head_sha,
        "base_sha": run(["git", "merge-base", base, head]).strip(),
        "web_base": web_base or f"https://github.com/{repo}",
        "root": run(["git", "rev-parse", "--show-toplevel"]).strip(),
        "via": "git fetch (metadata limited)",
    }


# ---------------------------------------------------------------- local git


def fetch_local(ref: str, base: str | None) -> tuple[str, dict]:
    if not in_git_repo():
        die(f"'{ref}' looks like a branch or range but this is not a git repository")
    if ".." in ref:
        rng = ref
        left, right = re.split(r"\.{2,3}", ref, maxsplit=1)
    else:
        left = base or default_base()
        right = ref
        rng = f"{left}...{right}"
    for r in (left, right):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", r], capture_output=True).returncode != 0:
            die(f"unknown git ref '{r}' (fetch it first?)")
    diff = run(["git", "diff", "--find-renames", rng])
    head_sha = run(["git", "rev-parse", right]).strip()
    base_sha = run(["git", "merge-base", left, right]).strip()
    log = run(["git", "log", "--format=%s", f"{base_sha}..{right}"]).strip().splitlines()
    title = log[-1] if log else f"{right} vs {left}"
    return diff, {
        "provider": "local",
        "repo": repo_name_from_remote() or Path.cwd().name,
        "number": None,
        "url": None,
        "title": title,
        "body": "\n".join(log[:-1]) if len(log) > 1 else "",
        "author": run(["git", "log", "-1", "--format=%an", right]).strip(),
        "base": left,
        "head": right,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "commits": len(log),
        "web_base": None,
        "root": run(["git", "rev-parse", "--show-toplevel"]).strip(),
    }


def fetch_patch(path: str) -> tuple[str, dict]:
    p = Path(path)
    diff = sys.stdin.read() if path == "-" else p.read_text(encoding="utf-8", errors="replace")
    if not diff.strip():
        die("the patch is empty")
    return diff, {
        "provider": "patch",
        "repo": repo_name_from_remote() or Path.cwd().name,
        "number": None,
        "url": None,
        "title": p.stem if path != "-" else "pasted diff",
        "body": "",
        "author": None,
        "base": None,
        "head": None,
        "head_sha": None,
        "base_sha": None,
        "web_base": None,
        "root": run(["git", "rev-parse", "--show-toplevel"]).strip() if in_git_repo() else str(Path.cwd()),
    }


# ---------------------------------------------------------------- repeat reviews


def since_diff(meta: dict, old: str, new: str) -> str | None:
    """Diff of just the commits between two heads, or None when the old head is gone (force-push)."""
    if in_git_repo():
        have = all(
            subprocess.run(["git", "cat-file", "-e", f"{c}^{{commit}}"], capture_output=True).returncode == 0
            for c in (old, new)
        )
        if have:
            return subprocess.run(["git", "diff", "--find-renames", old, new], capture_output=True, text=True).stdout
    if meta.get("provider") == "github" and shutil.which("gh"):
        r = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.diff", f"repos/{meta['repo']}/compare/{old}...{new}"],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return r.stdout
    return None


# ---------------------------------------------------------------- dispatch


def resolve(ref: str, base: str | None) -> tuple[str, dict]:
    if ref == "-" or ref.endswith((".diff", ".patch")):
        return fetch_patch(ref)
    if m := GH_PR_URL.match(ref):
        return fetch_github(m.group(1), m.group(2).removesuffix(".git"), m.group(3))
    if m := GL_MR_URL.match(ref):
        return fetch_gitlab(m.group(1), m.group(2), m.group(3))
    if m := GH_SHORT.match(ref):
        return fetch_github(m.group(1), m.group(2), m.group(3))
    if re.fullmatch(r"!\d+", ref):
        repo = repo_name_from_remote()
        if not repo:
            die("'!N' needs to be run inside a GitLab repo clone")
        host = "gitlab.com"
        return fetch_gitlab(host, repo, ref[1:])
    if re.fullmatch(r"#?\d+", ref):
        repo = repo_name_from_remote()
        if not repo:
            die(f"'{ref}' needs to be run inside a repo clone, or use owner/repo#{ref.lstrip('#')}")
        owner, name = repo.split("/", 1)
        return fetch_github(owner, name, ref.lstrip("#"))
    return fetch_local(ref, base)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    ref = argv[0]
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    base = argv[argv.index("--base") + 1] if "--base" in argv else None
    since = argv[argv.index("--since") + 1] if "--since" in argv else None
    diff, meta = resolve(ref, base)
    if not diff.strip():
        die("no changes between the requested refs")
    ident = str(meta.get("number") or (meta.get("head") or "diff").replace("/", "-"))
    out = out or Path(".pr-ism") / "work" / ident
    out.mkdir(parents=True, exist_ok=True)
    prev = json.loads((out / "pr.json").read_text(encoding="utf-8")) if (out / "pr.json").exists() else {}
    (out / "pr.since.diff").unlink(missing_ok=True)
    notes = []
    old, new = since or prev.get("head_sha"), meta.get("head_sha")
    if "--full" not in argv and old and new and old != new:
        inc = since_diff(meta, old, new)
        if inc and inc.strip():
            (out / "pr.since.diff").write_text(inc, encoding="utf-8")
            meta.update({"incremental": True, "previous_head_sha": old})
            if (out / "review.json").exists():
                (out / "review.json").replace(out / "review.prev.json")
            notes.append(f"incremental: {old[:10]}..{new[:10]} -> {out / 'pr.since.diff'}")
        else:
            notes.append(f"previous head {old[:10]} is not reachable (force-push?); doing a full review")
    elif "--full" not in argv and old and old == new:
        notes.append("unchanged since the last review (same head commit)")
    (out / "pr.diff").write_text(diff, encoding="utf-8")
    meta.update(
        {
            "id": ident,
            "fetched_at": stamp(),
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest()[:12],
            "root": meta.get("root")
            or (run(["git", "rev-parse", "--show-toplevel"]).strip() if in_git_repo() else str(Path.cwd())),
        }
    )
    (out / "pr.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"diff: {out / 'pr.diff'}\nmeta: {out / 'pr.json'}\ntitle: {meta['title']}\nrepo: {meta['repo']}  base: {meta.get('base')}  head: {meta.get('head')}"
    )
    for n in notes:
        print(n)


if __name__ == "__main__":
    main(sys.argv[1:])
