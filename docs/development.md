# Development

## Files

| File | Responsibility |
|---|---|
| `SKILL.md` | Agent invocation and compact reporting |
| `defaults.example.yml` | Shareable settings template |
| `defaults.yml` | Ignored local settings |
| `VERSION`, `CHANGELOG.md` | Release version and history |
| `priority-rules.yml`, `verdict-rules.yml` | Priority and action policy |
| `scripts\triage.py` | CLI, config precedence, and orchestration |
| `scripts\github_data.py` | Read-only APIs, pagination, and evidence |
| `scripts\triage_rules.py` | YAML validation, UTC dates, and rule evaluation |
| `scripts\triage_export.py` | CSV, audit, summary, and publication |
| `tests\test_triage.py` | Offline regression tests |
| `ui\index.html`, `ui\styles.css`, `ui\app.js` | Local-only CSV viewer |
| `tests\test_viewer.cjs` | Viewer parsing, filtering, and link validation tests |

## Versioning

Use semantic versions in `VERSION`. Update `CHANGELOG.md` for each release and tag the release commit `v<version>`. CLI output and new exports record the same version.

## Collection

Validate settings, authentication, repositories, and exact labels before enumeration. A missing label is a scope error, not an empty success.

Enumerate matching issues with REST pagination, excluding PR objects. Server-side date filters are prefilters; Python enforces the final interval. Updated-time `since` alone cannot implement a created-time range. Do not stop scanning an unsorted page after one out-of-range issue.

Collect direct dependencies, confirmed PR relationships, explicit linked priorities, current PR metadata, diff/test paths, CI, reviews, and membership evidence. Use each PR's facts independently.

Bound retries and respect rate-limit headers. Unknown mergeability remains unknown after bounded retries. Before export, verify the selected PR head; refresh changed evidence or flag it incomplete.

Refresh issue state, labels, and timestamps; exclude closed or newly out-of-scope issues. Record the collection window because GitHub's multi-request view is not an atomic snapshot.

Do not silently truncate REST/GraphQL connections or use capped Search results as inventory.

## Verification

Run the [test command](python.md#help-and-tests) before and after refactoring.

For viewer changes, run `node --test tests\test_viewer.cjs` with Node.js 18+.
Open `ui\index.html` in a browser to check file selection and layout; no server is required.

Cover priority precedence, same-PR evidence, community uncertainty, CI freshness, the strict age threshold, historical PRs, and selected-PR blockers. Include date boundaries, offsets, one-sided bounds, malformed settings, config fallback, CLI precedence, pagination, metadata changes, partial exports, overwrite protection, and CSV injection.

Invalid configuration must fail before collection or output replacement. The same captured facts and policy must produce the same priorities, verdicts, and row order.
