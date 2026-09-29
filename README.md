# pr-ism

A Claude skill that reviews a pull request function by function and produces an interactive HTML report.

Private and proprietary. See [License](#license).

## Usage

```
/pr-ism https://github.com/o/r/pull/123   # GitHub PR
/pr-ism #123                              # PR in the current repo
/pr-ism https://gitlab.com/g/p/-/merge_requests/7
/pr-ism feature/foo                       # branch vs default branch
/pr-ism main..HEAD                        # commit range
/pr-ism change.patch                      # patch file
/pr-ism config                            # customise output
```

The report contains:

- **Summary**: verdict, one-liner, themes
- **Spectrum bar**: share of 🟢 no behaviour change, 🟡 intended change, 🔴 high blast radius
- **Changes by function**: file, function, change type, rating, what changed, verdict, severity, diff hunk
- **Findings**, **test gaps**, **questions for the author**

Markdown output is also available (`output.format`).

## Install

The repo is private, so you need access to `31mahadi/pr-ism` (`gh auth login`).

**Claude Code plugin**
```
/plugin marketplace add 31mahadi/pr-ism
/plugin install pr-ism@pr-ism
```
Invoke as `/pr-ism:pr-ism <ref>`.

**Manual**: copy `skills/pr-ism` into `~/.claude/skills/` or `<project>/.claude/skills/`.

**claude.ai / Claude Desktop**: upload `pr-ism.skill.zip` from the [latest release](https://github.com/31mahadi/pr-ism/releases/latest) under *Settings → Skills*.

**Requirements**: `python3` 3.9+ and `git`. GitHub PRs need `gh`, or `GITHUB_TOKEN` for the REST API. GitLab MRs need `glab`.

## Configure

```
/pr-ism config set report.group_by severity
/pr-ism config set review.red_paths "**/billing/**" --global
/pr-ism config reset
```

Settings are layered, and later layers win: built-in defaults, then `~/.pr-ism/config.json`, then `<repo>/.pr-ism/config.json`.
All keys are listed in [config-reference.md](skills/pr-ism/references/config-reference.md).

Review files are written to `<repo>/.pr-ism/`. Add `.pr-ism/work/` and `.pr-ism/reviews/` to your `.gitignore`.

## Ratings

- **Logical** (green / amber / red): how far-reaching the change is, not whether it is correct.
- **Severity**: the worst problem found in a row.
- **Verdict**: `lgtm`, `nit`, `question`, `needs-changes` or `blocking`.

## Limits

- Function names are detected for most major languages. For other languages the row says `top-level`.
- Binary files are flagged but not reviewed. Lockfiles, build output and vendored code are skipped (`review.ignore`).
- The GitHub REST API caps a diff at about 300 files. For larger PRs, use `gh` or review the local branch.

## Development

```
python3 tests/smoke_test.py   # must print "all good"
```

To release:

1. Bump the version in `skills/pr-ism/SKILL.md`, `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. Add an entry to `CHANGELOG.md`.
3. Tag the commit: `git tag vX.Y.Z && git push origin vX.Y.Z`.

CI then builds `pr-ism.skill.zip` and attaches it to the release.

## License

Proprietary. © 2026 Mahadi Hassan. All rights reserved. See [LICENSE](LICENSE).
