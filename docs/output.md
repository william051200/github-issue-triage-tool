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
