# Changelog

## 1.3.0 — 2026-09-29
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
