# GitHub issue triage

## Setup

Install Python 3.10+ and GitHub CLI. From this folder:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
gh auth login
```

Copy `defaults.example.yml` to `defaults.yml` and edit the repositories, labels, dates, or output directory. See [configuration options](docs/configuration.md). Local defaults and results are ignored by Git.

## Run with an agent

Give your agent this request:

```text
Use SKILL.md in this folder and the project .venv.
Collect open Compute issues created from 2026-01-01 through today.
Save results in output\2026.
```

You can specify other repositories, labels, dates, or output folders. For example:

```text
Use SKILL.md to triage Azure/azure-cli issues labeled Network
updated from 2026-10-01 through 2026-10-28. Save to output\network.
```

For direct execution and flags, see [Python usage](docs/python.md).

## View results

Open `ui\index.html` directly in your browser. Choose `issues.csv` or
`issues.partial.csv` from a local output folder. Search results, filter by
priority or verdict, sort by clicking column headers, and open issue or PR links on GitHub.
Use **Triage rules** to view the default priority and verdict policy.
No server or additional dependencies are needed; file contents stay in your browser.
