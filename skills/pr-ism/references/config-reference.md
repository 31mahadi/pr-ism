# pr-ism configuration reference

Layers, later wins: bundled `assets/default-config.json` → global → project.

- global: `$PR_ISM_CONFIG`, else `$XDG_CONFIG_HOME/pr-ism/config.json`, else `~/.pr-ism/config.json`
- project: `<repo root>/.pr-ism/config.json` (commit it to share team defaults)

Commands (all via `scripts/config.py`):

```
config.py show                      # effective config, flattened
config.py show --json               # same, as JSON (feed this to parse_diff / render_report)
config.py show --project            # only the project overrides
config.py schema                    # every key with type, default, allowed values, description
config.py get report.columns
config.py set report.group_by severity            # project scope by default
config.py set review.depth deep --global
config.py set report.columns file,function,logical,what,verdict    # comma list or JSON array
config.py unset review.red_paths
config.py reset                     # delete project overrides (use --global for global)
```

Unknown keys, wrong types and values outside the allowed set are rejected with a message naming the
valid options — surface that message to the user verbatim.

## Keys

### output
| key | default | effect |
|---|---|---|
| `output.format` | `html` | `html` interactive report · `markdown` plain table · `both` |
| `output.dir` | `.pr-ism/reviews` | relative to repo root |
| `output.filename` | `{repo}-pr-{id}-{date}.html` | tokens `{repo}` `{id}` `{date}` `{branch}`; extension follows format |
| `output.open` | `true` | open the HTML after rendering (Claude Code / desktop only) |

### report
| key | default | effect |
|---|---|---|
| `report.sections` | summary, risk_overview, table, findings, test_gaps, questions | which sections render, in order |
| `report.columns` | file, function, change_type, logical, what, verdict, severity | table columns, in order; extras: `why`, `impact`, `lines` |
| `report.group_by` | `file` | `file` · `severity` · `logical` · `change_type` · `none` (user can regroup live in the HTML) |
| `report.sort` | `severity_desc` | order inside each group: `severity_desc` `severity_asc` `file` `logical` `none` |
| `report.language` | `en` | language of `what` / `why` / narrative (identifiers stay as-is) |
| `report.tone` | `concise` | `concise` one-line cells · `detailed` fuller `why`/`notes`, 2–4 narrative paragraphs |
| `report.show_diff_snippets` | `true` | include the hunk in each expandable row |

### links
| key | default | effect |
|---|---|---|
| `links.style` | `auto` | `auto` → provider web links when the PR has a URL, else editor scheme, else `relative` · `github` · `gitlab` · `custom` · `vscode` · `file` · `relative` |
| `links.editor` | `vscode` | `vscode` `cursor` `idea` `none` — scheme used for local links |
| `links.template` | `""` | with `links.style: custom`, a URL pattern for the file at head. Tokens `{web_base}` `{sha}` `{path}` `{line}` `{end}` `{number}` `{url}`. Bitbucket: `{web_base}/src/{sha}/{path}#lines-{line}` · Azure DevOps: `{web_base}?path=/{path}&version=GC{sha}&line={line}` · Gitea/Forgejo: `{web_base}/src/commit/{sha}/{path}#L{line}` |
| `links.review_template` | `""` | optional pattern for the "Open in review" link; defaults to `links.template` |

Web links point at the file **at the PR head commit** with a line anchor (`blob/<sha>/path#L10-L20`);
the row's "Open in review" link jumps to that file's diff on the PR page.

### review
| key | default | effect |
|---|---|---|
| `review.engine` | `auto` | `auto` use pr-review-toolkit agents when they are available in the session, else pr-ism's rubric · `prism` rubric only · `toolkit` agents, stop with an error if unavailable |
| `review.min_agent_confidence` | `80` | toolkit findings below this confidence (0–100) are dropped at merge |
| `review.depth` | `standard` | `quick` diff only · `standard` read surrounding source when a hunk is ambiguous · `deep` also trace callers/callees and existing tests |
| `review.focus` | correctness, security, performance, tests, readability | lenses, in priority order; extras: `api` `data` `concurrency` `observability` |
| `review.ignore` | lockfiles, dist/, vendor/, generated, snapshots… | globs dropped from the table (counted under skipped) |
| `review.red_paths` | auth, authz, billing, payment*, migrations, crypto, secrets | globs that force `logical: red` |
| `review.require_tests_for` | src/**, internal/**, pkg/**, app/**, lib/** | production globs where a change without any test change becomes a test gap |
| `review.max_files_inline` | `60` | above this, review the riskiest files fully and summarise the rest by directory |
| `review.read_source_context` | `true` | allow reading whole files from the checkout when needed |

### scales
| key | default | effect |
|---|---|---|
| `severity_scale` | info, low, medium, high, critical | ordered labels; the report's severity filter and sort use this order |
| `verdicts` | lgtm, nit, question, needs-changes, blocking | allowed row verdicts |

If a team renames severities (e.g. `P3,P2,P1,P0`), keep the order lowest → highest and map the rubric
accordingly when writing rows.
