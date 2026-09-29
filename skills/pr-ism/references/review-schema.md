# review.json schema

Write this file, then run `render_report.py`. The renderer validates it and fills in links, line
ranges, diff snippets and stats from `changes.json`, so you only supply what needs judgement.
Fields marked ● are required.

```jsonc
{
  "meta": {
    "title": "Cap retry attempts in payment webhook handler",   // ● from pr.json title unless you improve it
    // url, repo, number, author, base, head, head_sha are copied from changes.json if omitted
  },
  "summary": {
    "overall_verdict": "request-changes",       // ● approve | approve-with-nits | comment | request-changes
    "one_liner": "Bounds webhook retries and adds idempotency, but the new cap can drop legitimate retries during provider outages.",  // ●
    "narrative": [                              // 1–4 short paragraphs, plain prose
      "The PR replaces the unbounded retry loop in `handleWebhook` with a 3-attempt exponential backoff and stores an idempotency key per event.",
      "Two things need attention before merge: the cap is not configurable and there is no dead-letter path, and the new `webhook_events` migration is not reversible."
    ],
    "themes": ["retries", "idempotency", "migration"]   // 2–6 tags
  },
  "risk_overview": {                             // each list may be empty; strings or {text, file, line}
    "red_paths_touched": ["internal/billing/webhook.go"],
    "breaking_changes": [],
    "migrations": ["20260929_add_webhook_events.sql adds table + unique index (forward only)"],
    "deps": [],
    "other": []
  },
  "rows": [
    {
      "file": "internal/billing/webhook.go",     // ● path exactly as in changes.json
      "function": "handleWebhook",               // enclosing function; "top-level" / class name if none
      "hunk_id": "3f2a1c-h1",                    // from changes.json — gives lines, links, snippet for free
      // "hunk_ids": ["3f2a1c-h1", "3f2a1c-h3"],  // instead of hunk_id when one row merges several hunks of a function
      // directory summary row (large PRs): "file": "pkg/cmd/", "function": "(12 files)", no hunk_id,
      //   notes listing the files; the renderer totals +/- and links to the PR's file list
      "line_start": 41,                          // optional if hunk_id given
      "line_end": 88,
      "change_type": "behavior-change",          // ● see rubric
      "logical": "red",                          // ● green | amber | red
      "what": "Retries are now capped at 3 with 200ms→1.6s backoff (was: loop until success).",   // ●
      "why": "Payment confirmations arriving during a >2s provider blip will be dropped after the 3rd attempt with no dead-letter record.",
      "verdict": "needs-changes",                // ● from configured verdicts
      "severity": "high",                        // ● from configured severity_scale
      "impact": "system",                        // local | module | service | system
      "notes": "maxAttempts is a const; ctx deadline is not consulted between attempts.",
      "suggestion": "Read maxAttempts from config and push exhausted events to the existing `billing.dlq` topic."
    }
  ],
  "findings": [                                  // cross-cutting issues that span rows, or anything worth its own bullet
    {
      "severity": "high",                        // ● from configured scale
      "title": "No dead-letter path for exhausted retries",   // ●
      "detail": "Events that fail all 3 attempts are logged at WARN and discarded.",
      "suggestion": "Publish to billing.dlq with the original payload and attempt count.",
      "file": "internal/billing/webhook.go",
      "line": 79,
      "row_ids": ["r1"],                         // rows this finding belongs to; shown inside the expanded row
      "source": "prism"                          // "prism" (you) or "toolkit:<agent>" (added by merge_findings.py)
      // "also_found_by": ["toolkit:code-reviewer"], "confidence": 91   — set by merge_findings.py
    }
  ],
  "test_gaps": [
    {"file": "internal/billing/webhook.go", "function": "handleWebhook", "reason": "no test covers the exhausted-retry branch"}
  ],
  "questions": [
    "Is 3 attempts a product decision or a placeholder? The previous behaviour retried indefinitely."
  ]
}
```

`line_start`, `line_end`, `additions` and `deletions` are integers. Omit `source` on findings you
write; it defaults to `prism`. `test_gaps` entries may carry `source` too.

## agent-findings.jsonl (toolkit engine only)

Written by the pr-review-toolkit agents, read by `merge_findings.py`. One JSON object per line:

```json
{"agent": "code-reviewer", "file": "internal/billing/webhook.go", "line": 79, "severity": "high", "title": "Exhausted retries are discarded", "detail": "…", "suggestion": "…", "confidence": 88}
```

`agent`, `file`, `line` (head side), `severity` (critical | high | medium | low | info; other
common words are mapped onto `severity_scale`), `title`, `detail`, `suggestion`, `confidence`
(0–100). See `toolkit-engine.md` for how they are merged.

Rules the validator enforces: non-empty `rows`; every row has `file`, `change_type`, `logical`, `what`,
`verdict`, `severity`; enum values match the rubric and the effective config. Everything else is optional
and filled from `changes.json` when possible.
