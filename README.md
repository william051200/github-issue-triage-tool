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

Replace the placeholders, then give your agent this prompt:

```text
Use SKILL.md in this folder and the project .venv.
Collect all open issues labeled <label> in <owner/repo>,
created from <YYYY-MM-DD> through <YYYY-MM-DD>.
Review every issue's body, comments, and linked issues/PRs.
Provide evidence-backed suggested handling and a concrete next action for each.
Save the collection and viewer-compatible review files in a new folder under output.
Open this collection in the UI and verify suggested handling and next actions load.
```

For example, use `Compute` and `Azure/azure-cli`. Replace the date line with
`with no date bounds` to include all matching open issues.

## View latest result

```text
Use SKILL.md in this folder.
Open the UI and load the latest collected results, including saved suggested
handling and next actions. Do not collect or review again.
```
