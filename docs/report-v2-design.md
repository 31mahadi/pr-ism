# pr-ism report v2: the Review Path

Design for the next report and chat output. Grounded in research on how expert reviewers work
and on what the best review tools do; checked against a real 354-file review (PB Play #8).

## 1. What the evidence says

| Finding | Source | Consequence for pr-ism |
|---|---|---|
| Understanding, not defect-hunting, is the reviewer's main challenge; 14% of comments are defects | Bacchelli & Bird, ICSE 2013 | The "what changed, per function" map is the core product. Make it faster to absorb, then decide. |
| Read the description, then the load-bearing file, then tests, then the rest | Google eng-practices, "Navigating a CL" | The report must name the load-bearing change and put it first. |
| A defect in the last-shown file has 64% lower odds of being found; only 10% of reviewers think alphabetical order is right | Fregnan et al. ESEC/FSE 2022; ICSE 2026 survey (arXiv 2609.04207) | Stop grouping by file path by default. Order by intent and risk. |
| Review is skimming (~27 words/s), slowing only on suspicion | Begel & Vrzakova, eye tracking | Rows need scent: front-loaded keywords, severity, counts. Prose belongs behind a click. |
| 200–400 LOC per session, ~60 min before quality drops | SmartBear/Cisco | Show a time budget. Big PRs get sessions, not one endless table. |
| Useful comments: functional defects, corner cases, API misuse. Style and questions rank lowest | Bosu, Greiler & Bird, MSR 2015 | Blockers first; nits and lgtm rows collapsed. |
| Verdict first; one screen; 57% of attention above the fold | Minto; Few; Nielsen | Decision + reason + top finding on the first screen at 1440×900. |
| Tables beat cards for compare/find/act tasks | NN/g | Keep the table. Improve its cells, ordering and grouping. |
| Per-file "viewed" state that resets when the file changes; header progress counters | GitHub, Gerrit, Reviewable, Critique | Reviewed checkboxes per row, keyed by hunk content; counters in the header. |
| Reviewer triage of bot findings (Please fix / Not useful) turns noise into curated comments | Critique (SWE at Google, ch. 19) | Agree / Not an issue / Fixed per finding; decisions drive posting. |
| Volume is not value; poems, effort badges and labels train people to ignore the bot | CodeRabbit criticism; Cursor Bugbot guidance | No decoration. Every element must change a decision. |

Gaps no current tool fills, which pr-ism can own: review by intent with a time budget; progress per
finding; reviewer decisions that feed the posted review; "what changed since I last looked" merged
with "which of my comments were addressed".

## 2. The pattern: Review Path

The table stays, but its default grouping becomes an **ordered walk**. Each station is a group
header with a purpose, a row count, an estimated time, and progress dots.

| # | Station | Rows that belong | Why first |
|---|---|---|---|
| 1 | Load-bearing | `summary.load_bearing` row ids (Claude names them), else red rows with `impact: system` | Google: if the design is wrong, the rest is wasted |
| 2 | Blockers | verdict `needs-changes` / `blocking`, plus rows with attached findings at or above the middle severity | Decide fast |
| 3 | Red paths, judged ok | `logical: red` rows with verdict `lgtm`/`nit` | The reviewer must confirm Claude's judgement, not skip it |
| 4 | Tests | test-kind rows and `test_gaps` | Google: tests tell you what the change is meant to do |
| 5 | Everything else | remaining amber/green rows and directory summaries | Collapsed by default |

Rules: a row appears once, in the first station that claims it. Order inside a station: severity
desc, then RAG, then file. Time per station = lines / 400 per hour, shown in minutes; the header
sums them into "~N sessions". `report.group_by` gains the value `path`; it becomes the default.
`file`, `severity`, `logical`, `change_type`, `none` keep working.

## 3. First screen (1440×900)

```
┌ rail ───────┬────────────────────────────────────────────────────────────────────────┐
│ Path        │ Depth: LTS, the rollout gate, DRM …                    31mahadi/pb-play #8 │
│ ① Load-b. 2 │ ■ REQUEST CHANGES  native SDKs accept an expired token from activation   │
│ ② Blockers 6│ [Open worst finding]  [Copy decisions]  [Post to PR]                    │
│ ③ Red ok 14 ├────────────────────────────────────────────────────────────────────────┤
│ ④ Tests   4 │ SHAPE  ▉▉▉▉▉ sdk/ 🔴●3  ▉▉▉ backend/ 🔴●3  ▉▉ packages/ 🟡  ▉ services/ 🟡●2 │
│ ⑤ Rest   24 │        354 files · +28.8k −0.5k · 65 tests · 🔴22 🟡12 🟢3 · ~4 sessions   │
│             ├────────────────────────────────────────────────────────────────────────┤
│ Files ▸     │ [search] [sev ▾] [source ▾] [group: path ▾] [findings only] [expand] [⋯] │
│ Findings 10 │ 6 of 37 reviewed · 2 of 6 blockers decided                              │
│ Test gaps 4 │ ① LOAD-BEARING  2 rows · ~12 min                                   ○○   │
│ Questions 2 │ ☐ ▸ PBActivation.activate ●2  ▮▮▮▮▮▮ +210   red  New activation lifecycle… needs-changes high │
│             │ ☐ ▸ PBActivation.activate ●1  ▮▮▮▮▮▮ +264   red  Android mirror…       needs-changes high │
│ j/k · f · o │ ② BLOCKERS  6 rows · ~25 min                                     ○○○○○○ │
│             │ ☐ ▸ AuthSsoService ●2         ▮▮▮ +101      red  SSO settings, provider… needs-changes medium │
└─────────────┴────────────────────────────────────────────────────────────────────────┘
```

- **Decide strip**: verdict colour, one reason (`summary.one_liner`), three actions. Nothing else
  clickable in that band (Hick's law).
- **Shape strip**: one tile per top-level directory (from the directory rows and `changes.json`):
  width = lines changed, colour = worst RAG in it, badge = findings count. Click filters the table.
  One line of totals under it. Replaces today's spectrum bar and stats row.
- **Summary narrative and risk overview** move behind the one-liner: "Read the summary" opens
  them inline. Risk overview becomes grouped chips (`Red paths 6 · Migrations 6 · Breaking 1 ·
  Deps 3 · Other 2`) that expand on click, instead of a 21-bullet list.
- **Rail** leads with the path stations (click scrolls, shows counts), then a collapsible file
  tree (directories with worst RAG and totals, leaf names only), then sections.

## 4. Row anatomy

`☐ ▸ function ●n   shape   logical   what   verdict   severity`

- `☐` reviewed. Stored in `localStorage` under `prism:<head_sha>:<row hunk_hash>`. The renderer
  adds `hunk_hash` (sha1 of the row's hunk previews) so a changed hunk clears the tick.
- `●n` findings attached to the row (from `row_ids`). Tooltip lists titles.
- shape: proportional green/red bar on a shared scale plus `+a −d`; a `✓` when
  `related_test_changed`. Tufte: one word-sized graphic, one number.
- Expanded: attached findings first, each with Agree / Not an issue / Fixed; then the diff
  snippet with `+`/`−` gutter and line numbers; then why / notes / suggestion; then links.
- Keyboard: `j/k` move, `↵` expand, `x` reviewed, `f` next row with a finding, `o` open line
  link, `n` next station, `/` search, `t` theme.

## 5. Findings and decisions

- Findings section becomes a table (severity, title, file:line, source, decision), sorted by
  severity, grouped by station. Cards are gone.
- Decisions (`agree` / `dismiss` / `fixed`, optional note) persist locally. "Copy decisions"
  copies JSON: `{"head_sha": …, "decisions": {"f3": {"state": "agree"}, …}}`. In chat, the user
  pastes it or says "use my decisions"; the skill reads it, and `post_review.py --decisions`
  posts only agreed findings and marks dismissed ones in the body as "reviewed, not an issue".
- Repeat reviews: rows whose hunk changed carry a "changed since your review" mark; findings
  that disappeared since the previous review are listed as "resolved" (Copilot's Open /
  Resolved / Missed grouping).

## 6. Merge fixes found in real data

- Two findings at `PBActivation.swift:90` survived dedupe because the titles differ in wording.
  Add a second rule: same file and lines within 3 and either title similarity ≥ 0.6 or the same
  severity. Keep the higher-confidence one.
- Prism findings written by Claude have no `row_ids`; attach them by line the same way agent
  findings are attached, so they show inside rows and count in `●n`.
- The source select is 300px wide because of long option text; options show the agent name only.

## 7. review.json additions

```jsonc
"summary": {
  "load_bearing": ["r1", "r2"],          // the design core; 1–3 row ids
  "verify": ["Activate with an expired token; expect lapse, not licensed"],  // how to check (Phabricator test plan)
  "sessions": 4                          // filled by the renderer from lines / 400 per hour
}
"rows": [{ "hunk_hash": "9f1c2a", … }]   // filled by the renderer
```

The rubric asks Claude to name `load_bearing` (the change the rest depends on) and up to three
`verify` steps. Both optional; the renderer falls back as in section 2.

## 8. Chat: the review card and `walk`

Printed after every review, at most 12 lines. In Claude Code / VS Code every location is a
markdown link so it opens the file at the line.

```
REQUEST CHANGES — native SDKs accept an expired licensed token straight from activation
354 files · +28.8k −0.5k · 🔴22 🟡12 🟢3 · 10 findings · ~4 sessions · engine: toolkit
Start here: [PBActivation.swift:41-120](sdk/ios/…/PBActivation.swift#L41) · [PBActivation.kt:98-160](…)
 1 high    [PBActivation.swift:90](…#L90)   activate() applies a verified token without checking exp/grace
 2 high    [PBActivation.kt:122](…#L122)    same gap on Android
 3 medium  [auth-sso.service.ts:86](…#L86)  provider registered upstream before the DB write; failure orphans it
 4 medium  [auth-sso.service.ts:183](…)     DNS resolver errors reported as "TXT record not found yet"
 5 medium  [rollout-gate.service.ts:31](…)  gate errors logged at warn and the rollout carries on
 +5 more in the report · 6 nits · 24 lgtm · 4 test gaps · 2 questions
Report: .pr-ism/reviews/31mahadi-pb-play-pr-8-2026-09-29.html
Next: `walk` guided review · `fix 2` apply a fix · `show 3` open the diff · `post` comment on the PR
```

Rules: verdict and reason on line 1; shape on line 2; load-bearing on line 3; findings capped at
5–7, severity-sorted, front-loaded titles; tail counts on one line; two to four next actions as
literal commands. Same shape every run so the reviewer builds a scan habit.

New modes in SKILL.md, resolved from `$ARGUMENTS` after a review exists in `.pr-ism/work/`:

- `walk` — present station 1 (rows with links, attached findings, the diff snippet on request),
  then wait. `next`, `back`, `skip`, `fix N`, `show N`, `dismiss N`, `done`. Ends with the review
  card and the decisions collected.
- `show N` — print row or finding N's diff snippet with line links.
- `fix N` — propose the smallest change that resolves finding N, show it as a diff, apply only
  after the user says yes, then re-run the merge and render so the report reflects it.
- `post` — as today, but honours decisions when present.

## 9. Build plan

| Phase | Scope | Touches |
|---|---|---|
| 1. Decide + Shape + Path grouping | decide strip, shape strip, `group_by: path`, station headers with time, row shape cell, findings badge, source select fix, merge fixes (§6) | template, render_report.py, merge_findings.py, config.py, smoke test |
| 2. Progress + decisions | reviewed checkbox, `hunk_hash`, header counters, finding decisions, Copy decisions, `post_review.py --decisions` | template, render_report.py, post_review.py, schema doc |
| 3. Chat card + walk/fix/show | SKILL.md modes, rubric additions (`load_bearing`, `verify`), review card format | SKILL.md, review-rubric.md, review-schema.md |
| 4. Rail tree + repeat-review deltas | file tree, "changed since your review", resolved findings | template, render_report.py |

Each phase re-renders PB Play #8 from its existing `review.json` to check the result on real data,
and is screenshotted at 1440×900 before it is called done. SKILL.md stays under 500 lines.

## 10. Open questions

1. Default `group_by` becomes `path`. Anyone who set `file` explicitly keeps it.
2. Time estimates use 400 LOC/hour. Configurable as `review.loc_per_hour`?
3. Decisions live in the browser only, until pasted into chat. A `decisions.json` written by the
   page is not possible from a `file://` report; the clipboard is the bridge.
