# GitHub issue triage

## Choose a workflow

The general workflow below collects and reviews issues by repository and label,
then opens the viewer. For a deeper investigation of one issue, use the separate
[targeted issue-triage skill](.github/skills/issue-triage/README.md):

```text
Use issue-triage to investigate https://github.com/<owner>/<repo>/issues/<number>.
```

Targeted triage saves a detailed Markdown report with evidence, proposed fixes
and tests, and a suggested issue comment. It does not run collection or open the
viewer. Use one workflow at a time; combine them only when explicitly requested.

## Setup

Install Python 3.10+, GitHub CLI, and Node.js 22+. Run from this folder:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
gh auth login
npm --prefix ui install
```

## Run with an agent

Give your agent the repository and label. Dates are optional:

```text
repo: <owner/repo>
label: <label>
date range: <YYYY-MM-DD> - <YYYY-MM-DD>
```

For example:

```text
repo: Azure/azure-cli
label: Compute
```

Omit `date range` to include all matching open issues, regardless of local date
defaults. When supplied, dates filter creation time and include both UTC days.

The repository instructions automatically use `SKILL.md` and the project `.venv`,
collect the issues, and review every issue's body, comments, and linked issues/PRs.
The agent saves evidence-backed suggested handling and concrete next actions
alongside the collection in a new folder under `output`, then opens that collection
in the UI and verifies the suggestions load. Browser checks depend on available
tools; otherwise the agent verifies the server/API and reports that limitation.

For large collections, the agent can split evidence review across sub-agents,
sized to available resources and API quota. GitHub collection overlaps issue
evidence reads with a bounded worker pool, defaulting to CPU count capped at four.
Use `--workers 1` for serial collection; the agent can select a different limit
when resources allow. One coordinator validates coverage and saves final files.

## View latest result

```text
Use SKILL.md in this folder.
Open the UI and load the latest collected results, including saved suggested
handling and next actions. Do not collect or review again.
```
