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
| `ui\server\cli.cjs` | Node viewer CLI, configuration, and browser launch |
| `ui\server\exports.cjs` | Async export discovery, snapshot selection, and integrity validation |
| `ui\server\http.cjs` | Loopback API handling and allowlisted viewer assets |
| `ui\shared\issues.js` | Pure CSV parsing and issue schema shared by Node and the browser |
| `tests\test_triage.py` | Offline regression tests |
| `ui\tests\test_server.cjs` | Export discovery, integrity, HTTP routes, local-only access, and CLI tests |
| `ui\public\index.html`, `ui\public\styles.css`, `ui\public\app.js` | Local-only CSV viewer |
| `ui\tests\test_viewer.cjs` | Viewer parsing, filtering, and link validation tests |
| `ui\package.json`, `ui\package-lock.json` | Viewer commands and locked Node dependencies |

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

For viewer or API changes, install Node.js 22+, run `npm --prefix ui ci`, then
`npm --prefix ui test` from the repository root.
Open `ui\public\index.html` in a browser to check file selection and layout; no server is required.
Run `npm --prefix ui start` to check automatic loading from saved
exports. The server never invokes collection. Its API uses the newest published
UTC snapshot, rejects mixed or incomplete publication, and reads only the matching
CSV beside its summary, including after a repository move. Audit files and arbitrary
repository files are not HTTP-accessible.

The CLI owns process lifecycle and configuration; HTTP handling owns request policy
and serialization; the export reader owns filesystem discovery and validation.
The reader has no HTTP or DOM dependencies. CSV/schema functions are shared without
browser globals in Node, while classic scripts preserve direct `file:` viewing.
No framework or build step is required. Collection and its export format stay in
Python; changing the viewer does not change saved data.
Node dependencies stay in `ui\node_modules`. With `npm --prefix ui`, relative
export paths use npm's original caller directory rather than the package directory.

Cover priority precedence, same-PR evidence, community uncertainty, CI freshness, the strict age threshold, historical PRs, and selected-PR blockers. Include date boundaries, offsets, one-sided bounds, malformed settings, config fallback, CLI precedence, pagination, metadata changes, partial exports, overwrite protection, and CSV injection.

Invalid configuration must fail before collection or output replacement. The same captured facts and policy must produce the same priorities, verdicts, and row order.
