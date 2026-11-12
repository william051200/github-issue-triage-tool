# GitHub issue triage

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

## View latest result

```text
Use SKILL.md in this folder.
Open the UI and load the latest collected results, including saved suggested
handling and next actions. Do not collect or review again.
```
