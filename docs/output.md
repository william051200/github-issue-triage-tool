# Outputs

## CSV

`issues.csv` has one row per issue and these columns:

```csv
Issue link,Title,Created time,Last updated time,Priority,verdict,PR
```

Use canonical GitHub URLs and UTC ISO 8601 timestamps from the issue, not collection time. `PR` contains all confirmed associated PR URLs, semicolon-separated, or an empty cell. Historical PR states appear in the audit.

Deduplicate by repository/issue number. Sort by P0/P1/P2, creation time, then issue URL. Write UTF-8 with standard quoting for commas, quotes, Unicode, and newlines. Escape spreadsheet-formula prefixes; preserve original titles in the audit.

## Audit

`issues.audit.jsonl` records each issue's matched rules, priority, verdict, action, selected PR, secondary actions, evidence URLs, PR state/head SHA, membership decision, CI/test/diff evidence, unknowns, and collection errors.

Each record includes the tool version, run ID, snapshot time, and policy/default hashes. Keep credentials and full membership inventories out of exports.

## Summary

`run-summary.json` contains the tool version, parameters, original and normalized date bounds, repository/priority/verdict counts, failures, full warnings, request count, output paths, and artifact hashes.

Standard output contains only the tool version, status, date scope, counts, paths, request count, and up to 10 warning messages of at most 400 characters. Full diagnostics stay in the local artifacts.

Exit codes: `0` complete, `1` partial, `2` invalid input or fatal failure.

## Partial runs and replacement

Incomplete enumeration produces a partial run. Required per-issue failures retain known evidence and use `data-incomplete` where applicable. Inaccessible linked priorities remain unknown; unknown membership or CI cannot establish community or merge readiness.

Partial files use `.partial` before the extension, including `run-summary.partial.json`; they never replace successful exports. A P2 fallback with missing evidence is provisional.

Existing exports require explicit replacement permission. Stage files locally and publish the summary last. Its hashes detect interrupted or mixed artifact sets; publication across multiple files is not atomic.

Results and staging files are ignored by Git. This does not make them safe to publish: review local evidence and sensitive security details before sharing.

## Review files

The agent's evidence review is separate from deterministic collection. Save these
files in the same new output folder as the selected collection:

| File | Contract |
|---|---|
| `issue-review.csv` | UTF-8 CSV with the columns below, one row per collected issue, keyed by its exact canonical `Issue link`. |
| `issue-review.json` | JSON array of the same rows, using CSV column names as keys and string values. |
| `review-summary.json` | Review status, UTC snapshot, coverage, category counts, limitations, and artifact hashes. Publish last. |

Use these columns:

```csv
Issue link,Title,Created time,Last updated time,Category,Suggested next action,Assessment,Evidence URLs,Confidence,Caveat
```

The first four fields match the collection. Use standard CSV quoting and the
collection's spreadsheet-formula escaping for free-text cells. `Suggested next
action` must be a nonempty, issue-specific action; `Assessment` explains the
supporting evidence. `Evidence URLs` contains semicolon-separated GitHub source
URLs. Use `high`, `medium`, or `low` for `Confidence`; record uncertainty and
inaccessible evidence in `Caveat`, not as established facts.

Choose the best-supported category from the viewer's existing vocabulary:

| Category | Suggested handling shown by the viewer |
|---|---|
| `addressed` | Verify fix or resolution |
| `partially-addressed` | Isolate remaining problem |
| `active-pr` | Review or unblock existing PR |
| `approach-known` | Validate known approach |
| `no-approach-visible` | Investigate and propose solution |
| `needs-information` | Supply missing evidence |
| `external-dependency` | Coordinate with component owner |
| `abandoned-attempt` | Confirm whether to revive |

`review-summary.json` must contain `status: "complete"`, a timezone-aware
`snapshot_time` no earlier than the collection snapshot, `issue_count` equal to the
collection's row count, and `artifact_sha256.csv` containing the SHA-256 hex digest
of the exact saved CSV bytes before the viewer will join it. Also record
`artifact_sha256.json`, `category_counts`, and `limitations` for auditability.
The review must cover exactly the collected issue URL set with no duplicates.
An empty collection has a header-only review CSV, an empty JSON array, and zero
counts.

Only publish a complete summary after reviewing every row's required evidence.
If required evidence cannot be read, save draft CSV/JSON files, report incomplete
review coverage and limitations, and do not publish a complete review summary.
The viewer rejects incomplete or invalid review summaries rather than displaying
unverified suggestions. Keep a partial collection partial even when its review is
complete.

Verify the selected viewer API response includes `summary.review`, the expected
review count, and the saved `Category` and `Suggested next action` for every issue
URL. Merely loading the collector CSV does not verify review suggestions.
