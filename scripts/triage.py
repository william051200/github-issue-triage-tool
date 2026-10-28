"""Collect open GitHub issues and export a deterministic priority queue."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from github_data import APIError, Collector, GitHubAPI, validate_local_inputs, validate_repository
    from triage_export import check_output_paths, compact_summary, write_exports
    from triage_rules import (
        UTC, ConfigurationError, DateRange, assess, iso_time, load_defaults, load_policy, load_yaml,
    )
except ModuleNotFoundError as exc:
    if exc.name != "yaml":
        raise
    print(json.dumps({
        "status": "error",
        "error": "PyYAML is missing; install this skill's requirements.txt with python -m pip install -r",
    }))
    sys.exit(2)

SKILL_DIRECTORY = Path(__file__).resolve().parent.parent
VERSION = (SKILL_DIRECTORY / "VERSION").read_text(encoding="ascii").strip()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ConfigurationError(message)


def parser():
    result = Parser(description=__doc__)
    result.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    result.add_argument("--config", type=Path, help="default settings YAML; CLI flags take precedence")
    result.add_argument("--repo", action="append", help="owner/repository; repeat to replace defaults")
    labels = result.add_mutually_exclusive_group()
    labels.add_argument("--label", action="append", help="exact label; repeat to replace defaults")
    labels.add_argument("--no-labels", action="store_true", help="include all labels")
    result.add_argument("--label-match", choices=("all", "any"))
    result.add_argument("--date-field", choices=("created", "updated"))
    result.add_argument("--from", dest="from_date", help="inclusive date or timezone-aware timestamp")
    result.add_argument("--to", dest="to_date", help="inclusive calendar date or exclusive timestamp")
    result.add_argument("--output-dir", type=Path, help="output directory; overrides config")
    result.add_argument("--force", action="store_true", help="allow replacing existing exports")
    result.add_argument("--priority-rules", type=Path, default=SKILL_DIRECTORY / "priority-rules.yml")
    result.add_argument("--verdict-rules", type=Path, default=SKILL_DIRECTORY / "verdict-rules.yml")
    result.add_argument("--overrides", type=Path, help="reviewed local YAML decisions")
    result.add_argument("--membership-inventory", type=Path, help="reviewed organization membership YAML")
    return result


def run(args, api=None, snapshot=None):
    policy, verdicts, hashes = load_policy(args.priority_rules, args.verdict_rules)
    config_path = args.config
    if config_path is None:
        config_path = SKILL_DIRECTORY / "defaults.yml"
        if not config_path.exists():
            config_path = SKILL_DIRECTORY / "defaults.example.yml"
    defaults, config_hash = load_defaults(config_path)
    hashes["defaults"] = config_hash
    repositories = list(dict.fromkeys(args.repo or defaults["repositories"]))
    for repository in repositories:
        validate_repository(repository)
    labels = [] if args.no_labels else list(dict.fromkeys(
        defaults["labels"] if args.label is None else args.label
    ))
    if any(not label for label in labels):
        raise ConfigurationError("Labels must not be empty; use --no-labels instead")
    label_match = args.label_match or defaults["label_match"]
    date_defaults = defaults["date_range"]
    dates = DateRange(
        args.date_field or date_defaults["field"],
        args.from_date if args.from_date is not None else date_defaults["from"],
        args.to_date if args.to_date is not None else date_defaults["to"],
    )
    overrides = load_yaml(args.overrides) if args.overrides else {}
    inventory = load_yaml(args.membership_inventory) if args.membership_inventory else {}
    validate_local_inputs(overrides, inventory)
    output_dir = args.output_dir if args.output_dir is not None else Path(defaults["output_dir"])
    check_output_paths(output_dir, args.force)
    snapshot = snapshot or datetime.now(UTC)
    api = api or GitHubAPI()
    collector = Collector(api, policy, overrides, inventory)
    collector.validate_scope(repositories, labels)
    records, warnings, failures, repository_counts = {}, [], [], {}
    for repository in repositories:
        repository_counts[repository] = 0
        try:
            for issue in collector.issues(repository, labels, label_match, dates):
                record = collector.collect(issue)
                if record["state"] != "open" or not dates.includes(record):
                    continue
                current_labels = set(record["labels"])
                if labels and not (
                    set(labels) <= current_labels if label_match == "all"
                    else bool(set(labels) & current_labels)
                ):
                    continue
                record["assessment"] = assess(record, policy, verdicts, snapshot)
                collector.verify_selected_head(record, record["assessment"]["selected_pr"])
                record["assessment"] = assess(record, policy, verdicts, snapshot)
                records[record["url"]] = record
                warnings.extend(f"{record['url']}: {gap}" for gap in record["assessment"]["gaps"])
                warnings.extend(record["collection_errors"])
                if record["collection_errors"]:
                    failures.append(record["url"])
        except APIError as exc:
            failures.append(repository)
            warnings.append(f"{repository}: enumeration incomplete: {exc}")
        repository_counts[repository] = sum(
            record["repository"].casefold() == repository.casefold() for record in records.values()
        )
    summary = {
        "tool_version": VERSION,
        "status": "partial" if failures else "complete",
        "snapshot_time": iso_time(snapshot),
        "completed_at": iso_time(datetime.now(UTC)),
        "date_range": dates.summary(),
        "parameters": {
            "repositories": repositories, "labels": labels,
            "label_match": label_match, "state": "open",
        },
        "repository_counts": repository_counts,
        "failures": sorted(set(failures)),
        "warnings": sorted(set(warnings)),
        "rule_hashes": hashes,
        "request_count": api.request_count,
    }
    return write_exports(output_dir, list(records.values()), summary, args.force)


def main(argv=None):
    try:
        summary = run(parser().parse_args(argv))
        print(json.dumps(compact_summary(summary), ensure_ascii=True, sort_keys=True))
        return 0 if summary["status"] == "complete" else 1
    except (ConfigurationError, APIError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "error", "error": "Collection interrupted; export not completed"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
