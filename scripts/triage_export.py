"""Spreadsheet-safe CSV, traceable audit records, and bounded run summaries."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import uuid
from collections import Counter
from pathlib import Path

from triage_rules import ConfigurationError

COLUMNS = [
    "Issue link", "Title", "Created time", "Last updated time",
    "Priority", "verdict", "PR",
]


def safe_cell(value):
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def output_paths(directory, partial=False):
    marker = ".partial" if partial else ""
    return {
        "csv": directory / f"issues{marker}.csv",
        "audit": directory / f"issues{marker}.audit.jsonl",
        "summary": directory / f"run-summary{marker}.json",
    }


def check_output_paths(directory, force):
    if directory.exists() and not directory.is_dir():
        raise ConfigurationError("Output directory points to a file")
    if not force:
        for partial in (False, True):
            if any(path.exists() for path in output_paths(directory, partial).values()):
                raise ConfigurationError("Export already exists; choose a new directory or use --force")


def write_exports(directory, records, summary, force=False):
    """Stage each artifact, then publish the summary last as the commit marker."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".triage.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ConfigurationError("Another export owns this output directory") from exc
    try:
        os.close(descriptor)
        paths = output_paths(directory, partial=summary["status"] == "partial")
        if not force and any(path.exists() for path in paths.values()):
            raise ConfigurationError("Export already exists; choose a new directory or use --force")
        records = sorted(
            records,
            key=lambda row: (
                ("P0", "P1", "P2").index(row["assessment"]["priority"]),
                row["created_at"], row["url"],
            ),
        )
        summary = dict(summary)
        summary.update({
            "run_id": str(uuid.uuid4()),
            "issue_count": len(records),
            "priority_counts": {
                priority: sum(row["assessment"]["priority"] == priority for row in records)
                for priority in ("P0", "P1", "P2")
            },
            "verdict_counts": dict(sorted(Counter(
                row["assessment"]["verdict"] for row in records
            ).items())),
            "output_paths": {key: str(path) for key, path in paths.items()},
        })
        with tempfile.TemporaryDirectory(prefix=".triage-stage-", dir=directory) as staging:
            staged = {key: Path(staging) / path.name for key, path in paths.items()}
            with staged["csv"].open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(COLUMNS)
                for row in records:
                    writer.writerow([
                        row["url"], safe_cell(row["title"]),
                        row["created_at"], row["updated_at"],
                        row["assessment"]["priority"], row["assessment"]["verdict"],
                        ";".join(sorted({pr["url"] for pr in row["prs"]})),
                    ])
            with staged["audit"].open("w", encoding="utf-8", newline="\n") as stream:
                for row in records:
                    stream.write(json.dumps(
                        dict(row, run_id=summary["run_id"], tool_version=summary.get("tool_version"),
                             snapshot_time=summary["snapshot_time"],
                             rule_hashes=summary["rule_hashes"]),
                        ensure_ascii=False, sort_keys=True,
                    ) + "\n")
            summary["artifact_sha256"] = {
                key: hashlib.sha256(staged[key].read_bytes()).hexdigest()
                for key in ("csv", "audit")
            }
            staged["summary"].write_text(
                json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for key in ("csv", "audit", "summary"):
                os.replace(staged[key], paths[key])
        return summary
    finally:
        lock.unlink(missing_ok=True)


def compact_summary(summary):
    keys = (
        "tool_version", "status", "snapshot_time", "date_range", "issue_count", "priority_counts",
        "verdict_counts", "repository_counts", "output_paths", "request_count",
    )
    compact = {key: summary[key] for key in keys if key in summary}
    warnings = summary.get("warnings", [])
    compact["warning_count"] = len(warnings)
    compact["warnings"] = [warning[:400] for warning in warnings[:10]]
    return compact
