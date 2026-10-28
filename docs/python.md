# Python usage

Run from the skill folder after [setup](../README.md#setup).

## Collect

Use the configured defaults:

```text
.venv\Scripts\python.exe scripts\triage.py
```

Select repositories, labels, and dates:

```text
.venv\Scripts\python.exe scripts\triage.py --repo Azure/azure-cli --label Compute --date-field updated --from 2026-01-01 --to 2026-10-28 --output-dir output\2026
```

CLI values override [local defaults](configuration.md). Relative output paths use the working directory. Default config and rule paths use the skill directory.

## Flags

| Flag | Behavior |
|---|---|
| `--version` | Print the tool version without collecting issues. |
| `--config path` | Use another defaults YAML; a missing explicit file is an error. |
| `--repo owner/name` | Repeat to replace the repository list. |
| `--label name` | Repeat to replace the label list; names must match exactly. |
| `--no-labels` | Include all labels; cannot combine with `--label`. |
| `--label-match all\|any` | Require all labels or at least one. |
| `--date-field created\|updated` | Select the issue timestamp to filter. |
| `--from value`, `--to value` | Optional date/time bounds. |
| `--output-dir path` | Set the export directory. |
| `--force` | Permit replacement of existing exports. |
| `--priority-rules path`, `--verdict-rules path` | Use alternative policy files. |
| `--overrides path` | Load reviewed issue/author decisions. |
| `--membership-inventory path` | Load an authorized organization inventory. |

State is always open. Standard output is a compact JSON summary. Exit codes: `0` complete, `1` partial, `2` invalid input or fatal failure. See [outputs](output.md).

## Dates

Accept `YYYY-MM-DD` or timezone-aware ISO 8601 timestamps. Normalize to UTC. Reject invalid dates, timezone-free timestamps, and reversed or empty normalized intervals.

The lower bound is inclusive. A date-only upper bound includes that entire UTC day; a timestamp upper bound is exclusive. Either bound may be omitted. Without bounds, include all matching open issues.

For example, October 1 through October 28 is `[2026-10-01T00:00:00Z, 2026-10-29T00:00:00Z)`. Identical date-only bounds select one day.

Filter exported issues only. Related issues and PRs can fall outside the interval. PR age uses collection time, not the interval's end.

## Local evidence

See [configuration](configuration.md) before creating evidence files.

```text
.venv\Scripts\python.exe scripts\triage.py --overrides overrides.local.yml --output-dir output\reviewed
.venv\Scripts\python.exe scripts\triage.py --membership-inventory membership.local.yml --output-dir output\membership-reviewed
```

## Help and tests

```text
.venv\Scripts\python.exe scripts\triage.py --help
.venv\Scripts\python.exe scripts\triage.py --version
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
