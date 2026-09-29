# Changelog

## 1.5.1 — 2026-09-29
- Code formatted and linted with ruff (no behaviour change); fuller `.gitignore`; lint step in CI.

## 1.5.0 — 2026-09-29
- Licensed under MIT and prepared for public release; README drops the private-access notes and adds the `npx skills add` install.

## 1.4.0 — 2026-09-29
- Post a review back to the PR: `post_review.py` builds one GitHub review (summary + inline comments on diff lines) or a GitLab MR note. Dry run by default; `--post` sends it.
- Repeat reviews: re-fetching a reviewed PR writes `pr.since.diff` with only the new commits and keeps the previous review as `review.prev.json`. `--since SHA` and `--full` override.
- Parser: nested definitions stay in their enclosing function; Go `type … struct`, TS `interface`/`type`/`enum` and JS test titles (`describe`/`it`) are named; `testdata/`, `fixtures/` and `.txtar` count as tests; a source file counts as tested when a test in the PR mentions its module or package; `changes.md` shows the hunk id per function; `show` exits 1 on an unknown id; stdout is a short summary.
- Renderer: `hunk_ids` for rows merged from several hunks; directory summary rows (`file` ending in `/`); integer line counts; warns on `medium`+ rows marked `lgtm`; inline code in prose; no web fonts (works offline) and no local paths in the HTML.
- Rubric: missing tests go in `test_gaps`, not severity; bug fixes that change a conditional are amber; pass-throughs are green; `why` optional on `lgtm` rows.
- Evals: 11 planted-issue diff fixtures plus posting and repeat-review cases.

## 1.3.0 — 2026-09-29
- License changed from MIT to proprietary (all rights reserved, Mahadi Hassan).
- Renamed from prism to **pr-ism**: command is now `/pr-ism`, skill folder `skills/pr-ism`, plugin `pr-ism@pr-ism`.
- Working and config directories moved from `.prism/` to `.pr-ism/` (project) and `~/.pr-ism/` (global); env var `PRISM_CONFIG` is now `PR_ISM_CONFIG`; `$XDG_CONFIG_HOME/pr-ism/`.

## 1.2.0 — 2026-09-29
- Renamed from pr-sama to **prism**: command is now `/prism`, skill folder `skills/prism`, plugin `prism@prism`.
- Working and config directories moved from `.pr-sama/` to `.prism/` (project) and `~/.prism/` (global); env var `PR_SAMA_CONFIG` is now `PRISM_CONFIG`; `$XDG_CONFIG_HOME/prism/`.

## 1.1.0 — 2026-09-29
- `changes.md` compact index + `parse_diff.py show` so large PRs are reviewed progressively instead of loading one huge JSON.
- Function detection: keyword false-positives fixed (`if (`, `for (`, `else if (` are no longer "functions"), renames reported as `old → new`, previews capped at 300 lines.
- Related-test detection per source file (`related_test_changed`) feeds test gaps.
- `links.style: custom` + `links.template` for Bitbucket, Azure DevOps, Gitea and any other host.
- Private PRs without `gh`/`glab`: falls back to `git fetch refs/pull/N/head` / `refs/merge-requests/N/head` inside the clone.
- Report: "Copy as markdown" button (visible rows + findings, ready to paste as a PR comment); `?group=`, `?expand=all`, `?theme=` URL params; file column hidden when grouped by file.
- `evals/evals.json` with four trigger/behaviour cases; regression tests for the parser.

## 1.0.0 — 2026-09-29
- First release: `/pr-sama <ref>` reviews GitHub PRs, GitLab MRs, local branches/ranges and patch files.
- Interactive HTML report: spectrum bar filter, grouped function-level table, expandable rows with diff snippet, findings, test gaps, questions, dark mode, keyboard navigation.
- `/pr-sama config` with layered project/global config and validated keys.
