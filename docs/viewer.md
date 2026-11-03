# View results

## Start the viewer

Install Node.js 22+, then run from the repository root:

```text
npm --prefix ui install
npm --prefix ui start
```

This opens `http://127.0.0.1:8000` and loads the latest saved export. Viewing
does not need Python or browser automation and never runs collection.
Refresh to read newer saved results. Stop the server with Ctrl+C.

Search results, filter by priority, verdict, or suggested handling, sort by clicking column headers,
and open issue or PR links on GitHub. Use **Triage rules** to view the default
priority and verdict policy.

When a collection has a sibling `review-summary.json` and `issue-review.csv`,
the API joins reviewed handling and per-issue next actions by issue URL. It checks
the review hash, snapshot and exact issue coverage before showing the suggestions.
Older collections still load; their handling column says **Not reviewed**.

## Choose a collection

The server scans `output` and the configured output directory. "Latest" means the
newest published summary's UTC snapshot time, including partial runs. Partial
results remain labeled incomplete.

To scan only a specific collection directory:

```text
npm --prefix ui start -- --output-dir output\2026
```

Relative output paths use the caller's working directory, as they do for
collection. Use `--port 8001` if port 8000 is occupied.

## Ask an agent

To show an existing collection without collecting again:

```text
Use SKILL.md in this folder.
Open the UI and load the latest collected issues. Do not run collection.
```

To select a specific collection:

```text
Use SKILL.md to open the UI and load the export from output\2026.
Do not run collection.
```

## Load a CSV manually

Open `ui\public\index.html` directly in your browser and choose `issues.csv` or
`issues.partial.csv` from a local output folder. You can also choose
`issue-review.csv` to view handling and next actions without collector priorities
or verdicts. Manual file loading needs no
server or additional dependencies; file contents stay in your browser.

## Collection and review files

A reviewed collection contains two sets of three files:

| File | Purpose |
|---|---|
| `issues.csv` / `issues.partial.csv` | Collected issues, deterministic priorities, verdicts and PR links |
| `issues.audit.jsonl` / `issues.partial.audit.jsonl` | Per-issue collection evidence and rule decisions |
| `run-summary.json` / `run-summary.partial.json` | Collection scope, counts, diagnostics and integrity hashes |
| `issue-review.csv` | Per-issue review categories, assessments, suggested next actions and evidence links |
| `issue-review.json` | The same reviewed results in structured JSON |
| `review-summary.json` | Review coverage, category counts, limitations and integrity hashes |

The viewer reads the collection CSV and summary, plus the review CSV and summary
when present. The audit and review JSON are for inspection or other tooling.
Review coverage does not change a partial collection's status.

## Local API

The UI calls `GET /api/issues/latest` on startup. The read-only response contains:

| Field | Contents |
|---|---|
| `filename` | Selected CSV filename |
| `issues` | Issue records with CSV column names as keys |
| `summary` | Snapshot, status, counts, scope, warnings, and failures |

The server checks CSV hashes and issue counts before serving results. Missing
exports return 404. Invalid or publishing exports return 409 without falling back
to older data.

The server binds only to loopback, serves only the viewer and its rule references,
and never collects or changes exports. Results stay on your machine.

All JavaScript tooling lives in `ui`: browser assets in `public`, API and startup
code in `server`, reusable parsing in `shared`, and Node tests in `tests`.
See [development](development.md) for file responsibilities and test commands.
