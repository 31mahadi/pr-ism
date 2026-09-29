# Chat output and follow-up modes

The report is the table. Chat is for the decision and for acting on it. Every location in chat is
a link the user can click: in Claude Code / VS Code, `[file.ts:42](path/from/repo/root/file.ts#L42)`;
elsewhere use the `line_link` the renderer wrote into the row or finding.

## The review card

Print this after every review, at most 12 lines, same shape every time so the reviewer builds a
scan habit. Numbers come from the renderer's `verdict:` line, `review.json` and `changes.json`.

```
REQUEST CHANGES — native SDKs accept an expired licensed token straight from activation
354 files · +28829 −481 · 🔴22 🟡12 🟢3 · 9 findings · ~4.6 h in 5 sessions · engine: toolkit
Start here: [PBActivation.swift:41](sdk/ios/Sources/PBPlay/Licence/PBActivation.swift#L41) · [PBActivation.kt:98](sdk/android/pbplay/src/main/kotlin/dev/pbplay/sdk/PBActivation.kt#L98)
 1 high    [PBActivation.swift:90](…#L90)   activate() applies a verified token without checking exp or grace
 2 medium  [PBActivation.swift:94](…#L94)   rejected activation leaves previous licensed claims in `stored`
 3 medium  [auth-sso.service.ts:86](…#L86)  provider registered upstream before the DB write; a failure orphans it
 4 medium  [auth-sso.service.ts:183](…)     DNS resolver errors reported as "TXT record not found yet"
 5 medium  [rollout-gate.service.ts:31](…)  gate errors logged at warn and the rollout carries on
 +4 more in the report · 6 nits · 24 lgtm · 4 test gaps · 2 questions
Report: .pr-ism/reviews/31mahadi-pb-play-pr-8-2026-09-29.html
Next: `walk` guided review · `fix 1` apply a fix · `show 3` see the diff · `post` comment on the PR
```

Line by line:

1. Verdict in caps, then the `one_liner`.
2. Shape: files, +/−, RAG counts, findings, time (`summary.stats.minutes` and `sessions` from the
   rendered review; omit when absent), engine (`prism` or `toolkit`).
3. `Start here`: the `summary.load_bearing` rows as links to their `line_start`. Omit when empty.
4. Findings, severity-sorted, numbered by their `id` (`f1` → 1) so `fix 2` is unambiguous. Cap at
   five (seven when there are no nits to mention). Front-load each title: the defect, not the file.
5. Tail counts on one line: findings not shown, nit rows, lgtm rows, test gaps, questions.
6. Report path.
7. Next actions: two to four literal commands. Always offer `walk` and, when the engine found
   something, `fix N`. Offer `post` only for a GitHub PR or GitLab MR.

Do not repeat the narrative, the table or the risk overview in chat.

## Modes after a review

When `$ARGUMENTS` (or the message) is one of these and `.pr-ism/work/<id>/review.json` exists
for the most recent review, run the mode instead of a new review. `N` is a finding number from
the card (`f<N>` in `review.json`) or a row id (`r<N>`); a bare word or path matches a row by
function or file name.

### `walk`

A guided pass through the review path, one station at a time. Stations are the ones the renderer
assigned (`station` on each row; names in `review.json` → `render_stations`):
① load-bearing ② blockers ③ red paths judged ok ④ tests ⑤ everything else.

For each station: print its name, hint and time estimate, then its rows in severity order, one
line each: row id, `[file:line](link)`, function, verdict/severity, `what`. Under a row, its
attached findings (`row_ids`) as `fN severity title`. Then wait. Understand:

- `next` / `back`: move between stations. `skip`: skip the rest of this station.
- `show rN` or `show fN`: the diff (`parse_diff.py show changes.json <hunk-id>`), with links.
- `fix fN`, `dismiss fN` (note why), `agree fN`: record a decision in
  `.pr-ism/work/<id>/decisions.json` `{"head_sha": …, "decisions": {"fN": {"state": …, "note": …}}}`.
- `done`: stop. Print the review card again with a line of decisions collected
  (`3 agreed · 1 dismissed · 1 fixed`) and offer `post`.

Never read files beyond the station being walked; keep each turn to one station.

### `show N`

Print the row's or finding's diff snippet (`parse_diff.py show` for the full hunk) with the line
link, `what`, `why`, and attached findings. One screen; no re-review.

### `fix N`

1. Read the finding, its row and the file at the head revision around the line.
2. Propose the smallest change that resolves it, as a unified diff, with one sentence on why.
   If the fix needs a decision the author should make (behaviour choice, missing context), say
   so and stop.
3. Apply only after the user says yes, and only when the PR's head is checked out locally
   (`git rev-parse HEAD` equals `head_sha`, or the user confirms the branch). Never commit.
4. Record `{"state": "fixed"}` in `decisions.json`, then re-run `render_report.py` so the report
   shows the decision on the next open, and print the file:line link of the change.

### `post`

As step 8 of the review. When `.pr-ism/work/<id>/decisions.json` exists, or the user pastes the
JSON from the report's **Copy decisions** button, save it there and pass
`--decisions .pr-ism/work/<id>/decisions.json`: dismissed findings are left out, fixed ones are
listed as already addressed. Show the dry-run counts, then post only after a yes.
