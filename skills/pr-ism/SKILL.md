---
name: pr-ism
description: Reviews a pull request or merge request end to end and delivers an interactive HTML report — a summary plus a navigable, function-level table (file link, function, change type, green/amber/red logical-change rating, what changed, verdict, severity/impact), findings, test gaps and questions. Use this whenever the user asks to review, audit, summarise, explain, risk-assess or "check" a PR, MR, diff, patch, branch or commit range — including when they only paste a GitHub/GitLab PR URL, a `#123`, a branch name, or say "look at this PR before I merge". Can post the review back to the PR as comments and re-review only new commits. Also handles `config` to customise the output (columns, sections, grouping, link style, severity labels, review depth, ignore and red-path globs). Invoke with `/pr-ism PR-REF` or `/pr-ism config`.
license: Proprietary. See LICENSE
compatibility: Needs python3 (3.9+) and git. GitHub PRs use the gh CLI, else the REST API (GITHUB_TOKEN for private), else a git fetch of refs/pull/N/head from inside the clone; GitLab MRs use glab or refs/merge-requests/N/head. Other providers work via a local branch, commit range or patch file. The HTML report is self-contained and works offline.
metadata:
  author: Mahadi Hassan <01.mahadi@gmail.com>
  version: "1.4.0"
---

# pr-ism

Turn a PR into a report a reviewer can navigate: what changed, per function, how risky it is, and
what should happen next. All heavy lifting is scripted; your job is judgement.

Scripts live next to this file. `$SKILL` below means this skill's directory (resolve it from the
path of this SKILL.md). Run every script with `python3`.

Decide the mode from `$ARGUMENTS` (or the user's message when there are no arguments):

- starts with `config` → **Configure** (below)
- anything else (URL, `#123`, branch, range, patch path, or nothing) → **Review**

---

## Review

### 1. Load the effective config
```
python3 $SKILL/scripts/config.py show --json > .pr-ism/effective.json
```
Read it once. It decides depth, focus lenses, columns, sections, link style, ignore globs, red
paths, severity labels and verdict labels. Never hard-code those; always use the configured values.

### 2. Fetch the change
```
python3 $SKILL/scripts/fetch_pr.py "<ref>" --out .pr-ism/work/<id>
```
Accepts GitHub PR URLs, `owner/repo#123`, `#123`, GitLab MR URLs, `!7`, a local branch (diffed
against the default branch — pass `--base` to override), `a..b`, a `.diff`/`.patch` file, or `-`
for stdin. If the user gave no ref and the message contains a diff, save it to a file and pass that.
If the user gave nothing at all, ask for the PR link, number or branch — one question, then proceed.

**Repeat reviews.** If the output has an `incremental:` line, this PR was reviewed before and
new commits arrived. Parse `pr.since.diff` too (`--out .pr-ism/work/<id>/since.json`) and re-review
only the functions it touches. Carry every other row over from `review.prev.json` unchanged, but
drop their `hunk_id` (hunk ids are positional and shift) so the renderer re-resolves them by
function. Start `summary.narrative` with one sentence on what changed since the last review. If it
says the old head is unreachable, do a normal full review. Pass `--full` to force one.

If the script exits with an error (no `gh`, not logged in, not a git repo, unknown ref), show its
message verbatim and offer the next step (`gh auth login`, paste the diff, run inside the repo).
Do not try to reconstruct the diff yourself.

### 3. Parse it
```
python3 $SKILL/scripts/parse_diff.py .pr-ism/work/<id>/pr.diff --meta .pr-ism/work/<id>/pr.json --config .pr-ism/effective.json --out .pr-ism/work/<id>/changes.json
```
This writes two files. Read **`changes.md` first** — a compact index: one line per file with kind
(source/test/config/docs/deps/migration/api), red-path flag, +/- counts, the functions touched with
their line ranges, and hunk ids. Then open only what you need:

```
python3 $SKILL/scripts/parse_diff.py show .pr-ism/work/<id>/changes.json <hunk-id>          # one hunk, full text
python3 $SKILL/scripts/parse_diff.py show .pr-ism/work/<id>/changes.json <path>:<function>  # one function's segment
```

`changes.json` holds everything (per hunk: `id`, `new_range`, `enclosing_function`,
`definitions_touched`, `definition_changed`, per-function `segments` with line range and snippet,
links; per source file: `related_test_changed`). Read it whole only when the PR is small (under
~15 files); it is about 3× the size of the diff, so on large PRs never `cat` it and work from the
index and `show`. Ignored files are listed
under `skipped` — mention them in one line, do not review them. A segment named
`old → new` means the parser saw a rename; verify call sites were updated.

### 4. Understand every change
Work file by file, hunk by hunk. Load `references/review-rubric.md` now and apply it.

- Merge hunks that touch the same function into **one row**; split a hunk into several rows only
  when it spans several functions.
- When the hunk alone cannot tell you what a change does (trimmed context, a renamed helper,
  changed constant used elsewhere) and `review.read_source_context` is true, read the file at the
  head revision (`git show <head_sha>:<path>` when local, else the checked-out file) around
  `new_range`. With `review.depth: deep`, also grep for callers of changed functions and look for
  the tests that cover them.
- `red_path: true` files are always `logical: red`. Everything else follows the rubric.
- Judge through the configured `review.focus` lenses in that order. Each finding needs evidence
  (a line, a caller, a missing branch), not a vibe.
- Track test coverage: the index lists source files under `review.require_tests_for` with no
  related test change (`related_test_changed` is false; it is true when a test in the PR matches
  the file name or mentions the module or package). Each becomes a `test_gaps` entry unless the
  change is green and trivially safe, or a test elsewhere in the PR demonstrably exercises it; then
  leave it out rather than adding a waived entry.
- When the parser could not name a function (`top-level` on a language it does not know, e.g.
  Haskell, Lua, OCaml), read the file and name the enclosing definition yourself; note
  "named by reading the file" in `notes`.
- More than `review.max_files_inline` files: fully review red and amber files plus anything with a
  finding; summarise the remaining green files as one row per directory: `file` is the directory
  path ending in `/`, `function` is `"(N files)"`, no `hunk_id`, `change_type` is the dominant kind,
  and `notes` lists the file names.

### 5. Write `review.json`
Follow `references/review-schema.md` exactly. Write it to `.pr-ism/work/<id>/review.json`.
Use `hunk_id` from `changes.json` on every row so the renderer can attach lines, links and the
diff snippet. Use only the severity and verdict labels from the effective config. Narrative
language and tone come from `report.language` and `report.tone`.

### 6. Render
```
python3 $SKILL/scripts/render_report.py .pr-ism/work/<id>/review.json --changes .pr-ism/work/<id>/changes.json --config .pr-ism/effective.json
```
If validation fails it prints every problem; fix `review.json` and rerun rather than editing the
HTML. `warning:` lines flag contradictions (e.g. a `medium` row marked `lgtm`); fix them unless you
meant it. The script prints the report path and a one-line verdict summary.

### 7. Deliver
- **Claude Code / a terminal**: print the report path (already opened if `output.open` is true).
- **claude.ai, Cowork or any UI with file delivery**: present or publish the HTML file so the user
  can open it in place. Never paste the HTML into the chat.

Then give a chat summary of at most six lines: overall verdict, 🟢/🟡/🔴 counts, the two or three
findings that matter most with file:line, and any question you need answered. Do not repeat the
whole table in chat — the report is the table.

### 8. Post to the PR (only when asked)
For a GitHub PR or GitLab MR, offer once to post the review as PR comments. Run a dry run first
and show the counts:
```
python3 $SKILL/scripts/post_review.py .pr-ism/work/<id>/review.json --changes .pr-ism/work/<id>/changes.json --config .pr-ism/effective.json
```
It builds one review: a summary body plus inline comments for findings and for
`needs-changes`/`blocking`/`question` rows on lines inside the diff (the rest go in the body).
Add `--post` only after the user says yes. It posts as a plain comment; pass
`--event request-changes` or `--event approve` only when the user asks for that. GitLab gets one MR note.

---

## Configure (`/pr-ism config …`)

Everything goes through `$SKILL/scripts/config.py`; `references/config-reference.md` documents
every key. Project scope (`<repo>/.pr-ism/config.json`) is the default; `--global` writes the
user-level file.

- `config` or `config show` → run `config.py show`, present the effective settings compactly
  (group by section), then ask what they want to change. In Claude Code, prefer the ask-user
  tool with the most common choices: output format, columns, group-by, link style, review depth,
  severity labels, red paths. Otherwise ask one focused question.
- `config set <key> <value>` → run it, show the confirmation line. Comma lists work for list keys.
- `config get <key>` / `config unset <key>` / `config reset [--global]` / `config schema` → run
  the matching command and relay the output.
- A described change in prose ("make it group by severity and add a why column") → translate to
  one or more `set` calls, run them, and show the resulting effective values.
- If `config.py` rejects a value, show its message (it lists the allowed options) and offer the
  closest valid choice.

Finish by saying the settings apply to the next review and offering to rerun the last one.

---

## Guardrails

- Read the code. Never describe a change from the PR title or description alone; the diff is the
  source of truth and the description is a claim to verify.
- Never invent function names, line numbers or links — they come from `changes.json`, or from
  reading the file when the parser could not name a function.
- Do not review ignored or binary files; say they were skipped.
- Keep verdicts proportionate: `blocking` and `critical` need concrete evidence of breakage,
  data loss, security exposure or wrong money handling.
- Do not run the PR's code, install its dependencies, or execute anything from `scripts/` in the
  reviewed repo. Only this skill's own scripts run.
- Work directory is `.pr-ism/` at the repo root; suggest adding it to `.gitignore` the first
  time it is created (the project config file `.pr-ism/config.json` is the one thing worth committing).
