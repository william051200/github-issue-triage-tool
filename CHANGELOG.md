# Changelog

## 0.0.4 - 2026-11-12

Add bounded concurrent GitHub issue collection with a CPU-based default capped at
four workers and a `--workers` override for resource-aware or serial execution.
Protect shared API state, stop new requests after exhausted rate limits, and
retain pending results when pagination fails. Allow resource-sized sub-agent
review batches with coordinator-owned coverage validation and final publication.

## 0.0.3 - 2026-11-12

Make repository and label prompts trigger collection, evidence review, saved
handling and next actions, and local viewer verification. Support optional
inclusive creation-date ranges; omitted dates mean no bounds. Document the
viewer-compatible review files and preserve explicit view-only requests.

## 0.0.2 - 2026-10-30

Add a local Node.js viewer that opens the latest saved export without collection, validates export integrity, and preserves partial-run warnings. Keep manual CSV loading, search, filters, sorting, and triage rule references.

## 0.0.1 - 2026-10-28

Initial release: Python-backed issue triage, configurable priorities and verdicts, repo/label/date filters, CSV/audit exports, and agent instructions.
