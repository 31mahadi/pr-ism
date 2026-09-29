# Toolkit engine

pr-ism can hand issue detection to the agents of Anthropic's official **pr-review-toolkit** plugin
(`/plugin install pr-review-toolkit@claude-plugins-official`). pr-ism still owns fetch, parse, the
per-function rows, the green/amber/red rating, the verdicts, the report and posting. The agents
only add findings. The toolkit is optional; without it pr-ism reviews with its own rubric.

## Resolving the engine

| `review.engine` | toolkit agents available | result |
|---|---|---|
| `auto` | yes | toolkit |
| `auto` | no | prism (say so in one line of the chat summary) |
| `prism` | either | prism |
| `toolkit` | no | stop: "review.engine is toolkit but pr-review-toolkit's agents are not available in this session. Install it with `/plugin install pr-review-toolkit@claude-plugins-official`, or run `/pr-ism config set review.engine auto`." |

"Available" means you can spawn subagents and the session's agent list includes
`pr-review-toolkit:code-reviewer` (names may appear without the prefix). claude.ai and other
surfaces without subagents always resolve to prism.

## Which agents to spawn

Decide from `changes.md`. Spawn all selected agents in parallel, in one message.

| agent | spawn when |
|---|---|
| `code-reviewer` | always |
| `silent-failure-hunter` | the diff adds or changes error handling: try/catch/except, `if err != nil`, fallbacks, default values on failure, retries, logging in failure paths |
| `pr-test-analyzer` | the PR changes source files under `review.require_tests_for`, or changes tests |
| `type-design-analyzer` | the diff adds or changes a type, class, struct, interface, enum or schema definition |
| `comment-analyzer` | the diff adds or changes docstrings or comments beyond a line or two |

Skip every agent except code-reviewer at `review.depth: quick`.

## What each agent gets

Give each agent, in its task prompt:

- the absolute path of the diff (`pr.since.diff` on a repeat review, else `pr.diff`)
- the absolute path of `changes.md`
- repo root, base ref, head ref and head SHA (from `pr.json`)
- an instruction to review only lines the diff changes, and to read head-revision files for
  context (`git show <head_sha>:<path>` when the head is not checked out)
- the output contract below, and an instruction to return **only** the JSON lines, no prose

## Output contract

One JSON object per line:

```json
{"agent": "silent-failure-hunter", "file": "internal/billing/webhook.go", "line": 79, "severity": "high", "title": "Exhausted retries are discarded", "detail": "After the 3rd attempt the event is logged at WARN and dropped.", "suggestion": "Publish to billing.dlq with the payload and attempt count.", "confidence": 88}
```

- `file` exactly as in `changes.md`; `line` on the head side, inside the diff where possible
- `severity`: critical | high | medium | low | info (other common words are mapped)
- `confidence`: 0–100; findings below `review.min_agent_confidence` are dropped at merge
- `agent` is the agent's short name, without the plugin prefix

Concatenate every agent's lines into `.pr-ism/work/<id>/agent-findings.jsonl`. If an agent returns
prose around its JSON, keep only lines that parse; the merge skips malformed lines and reports them.
If an agent fails, carry on with the others and note it in `summary.narrative`.

## Rows stay yours

While the agents run, write the rows yourself from the rubric as usual: what changed,
`change_type`, `logical` RAG, verdict, severity. Agents never set `logical`; a red-path file stays
red. Read `agent-findings.jsonl` before you finalise rows: if a finding is wrong, leave it in the
file and say why in a `questions` entry or a row's `notes`, rather than deleting it silently.

## Merge

```
python3 $SKILL/scripts/merge_findings.py .pr-ism/work/<id>/review.json --changes .pr-ism/work/<id>/changes.json --agents .pr-ism/work/<id>/agent-findings.jsonl --config .pr-ism/effective.json
```

It attaches each finding to the row whose function segment contains its line (`row_ids`), dedupes
near-identical findings (including against yours, recording the extra agent in `also_found_by`),
maps severities onto `severity_scale`, raises a row's severity when a finding is worse, raises its
verdict to the second-strongest configured verdict when the severity reaches the middle of the
scale (it never sets `blocking`), turns `pr-test-analyzer` findings into `test_gaps`, and tags
every finding with `source`. Findings that match no row stay top-level. It is safe to rerun.

If it prints `rows raised`, re-read `summary.overall_verdict`, `one_liner` and `narrative` and make
them match the raised rows before rendering. The merge also folds duplicates already in the file
(a prism finding restating an agent's at the same line), so it is safe to rerun.
