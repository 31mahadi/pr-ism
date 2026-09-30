# pr-ism review rubric

Every row in the report is one **function-level change** (or one file-level change when there is no
function, e.g. config/docs). Each row gets five labels. Keep them independent: a red row can be
`lgtm`, a green row can be `blocking` (e.g. a typo in a user-facing string is green but blocking).

## 1. change_type — what kind of edit is this?

| value | use when |
|---|---|
| `added` | new function / file that did not exist |
| `removed` | function / file deleted |
| `renamed`, `moved` | same code, new name or location (check call sites were updated) |
| `signature-change` | parameters, return type, visibility, or error contract changed |
| `refactor` | structure changed, observable behaviour intended to be identical |
| `behavior-change` | conditionals, defaults, return values, side effects changed on purpose |
| `bugfix` | corrects wrong behaviour (say what was wrong in `what`) |
| `feature` | new capability wired through an existing function |
| `perf` | change made for speed/memory (caching, batching, indexes, algorithmic) |
| `test` | test code |
| `docs`, `formatting` | comments, docs, whitespace, lint fixes |
| `config`, `deps`, `generated`, `migration`, `api` | non-function files by kind |

Pick the most specific. If a hunk both refactors and changes behaviour, split into two rows when the
functions differ; otherwise use `behavior-change` and mention the refactor in `notes`.

## 2. logical — green / amber / red

This rates the **nature and blast radius of the logical change**, not whether it is correct.

**🟢 green — no observable behaviour change, or trivially safe**
- formatting, comments, docs, type annotations, log message wording
- tests added or strengthened
- rename/move with every reference updated in the same PR
- dead code removal, unused import removal
- pure refactor where you can verify inputs → outputs are unchanged from the diff alone
- one-line pass-through of a new optional value to an existing call (the decision lives elsewhere; rate that row instead)

**🟡 amber — intended, bounded behaviour change**
- new feature path, new endpoint, new field that is optional / has a default
- changed conditional, default value, return value, error message, sort order
- a bug fix that changes a conditional or return path, even when clearly correct
- new dependency or bumped major version
- performance change that alters timing or memory but not results
- backward-compatible API addition
- additive schema change (nullable column, new table, new index)
- error handling narrowed *or* made more specific

**🔴 red — high blast radius, or on a path where mistakes are expensive**
- any change inside a configured `review.red_paths` glob (auth, authz, billing, payments, migrations, crypto, secrets) — even a one-liner
- breaking API / contract / wire-format change, removed or renamed public symbol
- validation, permission or authentication check removed or weakened
- error handling removed or broadened (catch-all, swallowed error, ignored return)
- destructive schema change (drop/alter column, type narrowing, backfill)
- concurrency: locks, transactions, retries, timeouts, idempotency keys, queues
- money, quotas, limits, rate limits, tier logic
- secrets, tokens, PII handling, logging of sensitive data
- data deletion or bulk writes
- production change in a `require_tests_for` path with **no** test change anywhere in the PR (also record a test gap)

When unsure between two colours, choose the more cautious one and explain in `why`.

## 3. severity — how bad is the worst issue in this row?

Applies to the *problem you found*, not the change size. A red-path change with no issue is `info`.

| value | meaning |
|---|---|
| `info` | nothing wrong; row exists for navigation and context |
| `low` | style, naming, minor clarity, optional improvement |
| `medium` | likely bug in an edge case, unclear contract, minor perf regression |
| `high` | probable bug on the main path, data inconsistency, security weakness, notable perf regression |
| `critical` | data loss, security hole, outage risk, money handled incorrectly, breaks callers |

A missing test goes in `test_gaps`, not into a row's severity.
Severity `medium` or higher needs a verdict other than `lgtm` (the renderer warns when they contradict).
The configured `severity_scale` may differ; always use the labels from the effective config.

## 4. impact — how far does this row reach?

`local` (inside the function) · `module` (package/service-internal callers) · `service` (other services, clients, DB) · `system` (users, money, data, compliance).

## 5. verdict — what should happen to this row?

| value | meaning |
|---|---|
| `lgtm` | fine as is |
| `nit` | optional polish, do not block |
| `question` | you need the author's intent before judging (write the question in `questions` too) |
| `needs-changes` | should be fixed before merge |
| `blocking` | must not merge as is (usually paired with `high`/`critical`) |

## Load-bearing change and how to verify (summary.load_bearing, summary.verify)

`load_bearing`: the ids of the one to three rows the rest of the PR depends on — the design core
(a new lifecycle, a changed data model, the function every other change calls). A reviewer reads
these first; if the design is wrong the rest is wasted. Pick by dependency, not by severity: a
green row can be load-bearing. Omit when nothing stands out (a flat set of independent edits).

`verify`: up to three concrete steps a reviewer can run to check the change does what it says
(an input and the expected outcome), like a test plan. Omit rather than invent.

## Overall verdict (summary.overall_verdict)

- any `blocking` → `request-changes`
- any `needs-changes` → `request-changes`
- only `question` / `nit` with at least one `question` → `comment`
- only `nit` → `approve-with-nits`
- otherwise → `approve`

## Writing the cells

- `what`: one concrete sentence, before → after. "Retries now cap at 3 (was unbounded) and back off 200ms" beats "improved retry logic".
- `summary.narrative`: at most two short paragraphs — what the PR is for, and what needs
  attention. Do not restate rows; the table already lists every change.
- `what`: the behaviour change in at most ~80 characters, as a reviewer would say it out loud.
  Lead with the effect, not the mechanics: "SSO sessions checked against the account's provider",
  not "issue() now branches on SSO sessions (must match…) vs password sessions (aal2…)". Put the
  mechanics in `notes`. The renderer warns above 100 characters.
- `delta` (optional, for behaviour changes): `{"before": "password sessions only", "after":
  "SSO sessions must match the account's provider"}`. Each side under ~60 characters. The report
  shows it as before → after in place of `what`. Omit for new code (`added`) and pure refactors;
  write `what` as `new: …` for added code.
- `why`: the consequence for a reader who has not seen the diff: who is affected, what could break, what to double-check. Leave it out on `lgtm`/`info` rows rather than writing filler.
- `notes`: evidence — the line, the caller, the assumption. Quote identifiers, not whole hunks.
- `suggestion`: an actionable fix or a specific test to add. Skip it if there is nothing to suggest.
- Never invent a function name. If the parser gives no `enclosing_function` and reading the file does not settle it, use the nearest named scope (class, module, "top-level") and say so in `notes`.
- Prefer fewer, sharper rows over one row per hunk: merge hunks that touch the same function, and list them all in `hunk_ids`.
- Amber is the default for real changes, so make `what` carry the difference: a reader should tell a one-argument pass-through from a new code path without opening the diff.
