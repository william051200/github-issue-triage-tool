# GitHub issue triage

## Setup

For collection, install Python 3.10+ and GitHub CLI. From this folder:

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
Open the UI and load this run's CSV.
```

You can specify other repositories, labels, dates, or output folders. For example:

```text
Use SKILL.md to triage Azure/azure-cli issues labeled Network
updated from 2026-10-01 through 2026-10-28. Save to output\network.
```

For direct execution and flags, see [Python usage](docs/python.md).

## View results

Install Node.js 22+, then run from this folder:

```text
npm --prefix ui install
npm --prefix ui start
```

The viewer opens at `http://127.0.0.1:8000` and loads the latest saved results
without running collection. Search, filter, and sort issues in your browser.

See the [viewer guide](docs/viewer.md) for agent prompts, specific collections,
manual CSV loading, and API details.
