# pr-ism

Function-level pull request review for Claude, delivered as an interactive HTML report.

```
/pr-ism https://github.com/acme/api/pull/482
/pr-ism #482                 # inside the repo clone
/pr-ism feature/retry-cap    # local branch vs default branch
/pr-ism main..HEAD           # any commit range
/pr-ism change.patch         # a patch file
/pr-ism config               # customise the output
```

pr-ism fetches the change, splits it into per-function rows, reads the surrounding code when the
diff alone is not enough, and renders a self-contained HTML page you can open, share or keep:

- **Summary** — verdict, one-liner, short narrative, themes
- **Spectrum bar** — how much of the PR is 🟢 no behaviour change / 🟡 intended change / 🔴 high blast radius; click to filter
- **Changes by function** — file (linked to the PR or your editor), function, change type, logical rating, what changed, verdict, severity; expandable rows with *why it matters*, notes, suggestion and the diff hunk; group by file / severity / rating / type; search; keyboard navigation; dark mode
- **Findings**, **test gaps**, **questions for the author**

Markdown output is available too (`output.format`).

## Install

Pick whichever surface you use. All of them read the same `skills/pr-ism` folder.

**Claude Code — plugin marketplace (versioned, updatable)**
```
/plugin marketplace add 31mahadi/pr-ism
/plugin install pr-ism@pr-ism
```
Invoke as `/pr-ism:pr-ism <ref>` (plugin skills are namespaced).

**Claude Code / Codex / Cursor / OpenCode and others — `skills` CLI**
```
npx skills add 31mahadi/pr-ism            # project scope
npx skills add 31mahadi/pr-ism -g         # user scope
```
Invoke as `/pr-ism <ref>`.

**Manual** — copy `skills/pr-ism` into `.claude/skills/` (project) or `~/.claude/skills/` (user).

**claude.ai / Claude Desktop** — download `pr-ism.skill.zip` from the latest release and upload it under *Settings → Skills*. Then just say "review this PR" with a link or paste the diff.

**Claude API** — upload the same folder via the Skills API.

The frontmatter uses only Agent Skills spec fields so the same folder uploads cleanly to claude.ai; if you want Claude Code's autocomplete hint, add `argument-hint: "PR-REF | config"` to your local copy.

Requirements: `python3` 3.9+, `git`; `gh` (logged in) for GitHub PRs — without it, public repos work over the REST API and private ones need `GITHUB_TOKEN`; `glab` for GitLab MRs.

## Configure

```
/pr-ism config                         # interactive
/pr-ism config set report.group_by severity
/pr-ism config set report.columns file,function,logical,what,why,verdict
/pr-ism config set review.red_paths "**/tier/**,**/limits/**" --global
/pr-ism config reset
```

Config is layered: bundled defaults → `~/.pr-ism/config.json` → `<repo>/.pr-ism/config.json`
(commit the project file to share team defaults). Every key, default and allowed value is in
[`skills/pr-ism/references/config-reference.md`](skills/pr-ism/references/config-reference.md);
`config.py schema` prints the same list.

Most-used keys: `output.format`, `report.columns`, `report.group_by`, `report.tone`, `links.style`
(GitHub/GitLab web links, or `vscode://` / `cursor://` deep links for local reviews),
`review.depth`, `review.red_paths`, `review.ignore`, `severity_scale`.

## How a review works

1. `config.py show --json` — effective settings
2. `fetch_pr.py <ref>` — resolves the ref and writes `pr.diff` + `pr.json`
3. `parse_diff.py` — unified diff → `changes.json` with per-hunk enclosing function, per-function segments (line range, +/-, snippet), red-path flags, links; ignored files skipped
4. Claude reads every change against [`references/review-rubric.md`](skills/pr-ism/references/review-rubric.md) and writes `review.json` ([schema](skills/pr-ism/references/review-schema.md))
5. `render_report.py` — validates, fills links/lines/snippets/stats, writes the HTML (and/or markdown), opens it

Working files live in `<repo>/.pr-ism/` — add `.pr-ism/work/` and `.pr-ism/reviews/` to `.gitignore`.

## Where it works — and where it doesn't

| | |
|---|---|
| **Any git diff** | Parsing, grouping, links, the report and the rubric are language-agnostic. If `git diff` can produce it, pr-ism can review it. |
| **PR metadata + web links** | GitHub (`gh`, REST, or `git fetch refs/pull/N/head` inside the clone) and GitLab (`glab` or `refs/merge-requests/N/head`). Bitbucket, Azure DevOps, Gitea and others: review the branch or range locally and set `links.style: custom` with a URL template to get clickable file links. |
| **Function detection** | Regex heuristics plus git's own hunk headers for Go, Python, JS/TS, Java, Kotlin, Rust, Ruby, PHP, C#, C, C++, Swift, Scala, Dart, Elixir, SQL. Other languages fall back to `top-level` and Claude names the function by reading the file. Methods are reported by name, not `Class.method`. |
| **Big PRs** | `changes.md` is a compact index; hunks are opened on demand with `parse_diff.py show`. Above `review.max_files_inline` (60) green files are summarised per directory. The GitHub REST diff endpoint caps at ~300 files / 20k lines — use `gh` or a local branch beyond that. |
| **Not covered** | Non-git VCS (Perforce, SVN) unless you hand it a unified diff; binary files (flagged, not reviewed); generated/minified/vendored code (skipped by default — edit `review.ignore`); Python < 3.9. |

## Rating in one paragraph

**Logical** (green/amber/red) rates the *nature and blast radius* of a change — not whether it is
correct. Red is reserved for breaking changes, removed validation/authz, error handling that got
broader, destructive migrations, concurrency/money/quota logic, secrets/PII, and anything under a
configured red path. **Severity** rates the worst *problem* in a row. **Verdict** says what should
happen: lgtm / nit / question / needs-changes / blocking. A red row can be lgtm; a green row can be
blocking.

## Repository layout

```
.claude-plugin/          plugin.json + marketplace.json (Claude Code)
skills/pr-ism/          the skill — SKILL.md, scripts/, references/, assets/
tests/smoke_test.py      end-to-end check run by CI
.github/workflows/       validate on push; attach pr-ism.skill.zip to tagged releases
```

## Contributing

Run `python3 tests/smoke_test.py` before opening a PR. Keep `SKILL.md` under 500 lines — put detail
in `references/`. Bump the version in `SKILL.md` frontmatter, `plugin.json`, `marketplace.json` and
`CHANGELOG.md` together and tag `vX.Y.Z` to cut a release.

## License

Proprietary. Copyright © 2026 Mahadi Hassan. All rights reserved. See [LICENSE](LICENSE).
