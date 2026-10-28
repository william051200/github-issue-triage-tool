"""Configuration, UTC date filters, and deterministic triage policy."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

UTC = timezone.utc
PRIORITY_FACTS = {
    "issue_has_explicit_p0",
    "issue_has_explicit_p1",
    "issue_has_trusted_security_fix_evidence",
    "eligible_pr_has_trusted_security_fix_evidence",
    "accepted_link_has_explicit_p0",
    "accepted_link_has_explicit_p1",
    "same_eligible_pr_is_verified_community",
    "same_eligible_pr_meets_low_effort_policy",
    "same_eligible_pr_is_older_than_age_threshold",
    "issue_and_same_pr_have_no_explicit_priority",
    "issue_and_same_pr_have_no_unmapped_priority_like_label",
    "eligible_pr_is_verified_community",
}
VERDICT_FACTS = PRIORITY_FACTS | {
    "required_issue_or_pr_collection_failed",
    "selected_pr_has_failed_current_head_ci",
    "selected_pr_has_pending_or_running_current_head_ci",
    "selected_pr_is_draft",
    "selected_pr_has_merge_conflict",
    "selected_pr_has_effective_changes_requested_review",
    "relevant_fix_pr_is_merged",
    "no_active_replacement_pr_exists",
    "selected_pr_is_verified_community",
    "selected_pr_meets_low_effort_policy",
    "selected_pr_matches_overdue_unprioritized_rule",
    "issue_has_reviewed_or_configured_missing_information_state",
}


class ConfigurationError(ValueError):
    """An input or rule file cannot be interpreted safely."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of silently replacing earlier rules."""


def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)) or key in mapping:
            raise ConfigurationError("YAML keys must be unique strings or integers")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def load_yaml(path: Path) -> dict:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read valid YAML from {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{path.name} must contain a mapping")
    return value


def _string_list(value, name, allow_empty=True):
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ConfigurationError(f"{name} must be a list of nonempty strings")
    if not allow_empty and not value:
        raise ConfigurationError(f"{name} must not be empty")


def _validate_rules(config, facts, priorities=None):
    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ConfigurationError("rules must be a nonempty list")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise ConfigurationError("Each rule needs a string id")
        if rule["id"] in ids:
            raise ConfigurationError(f"Duplicate rule id: {rule['id']}")
        ids.add(rule["id"])
        when = rule.get("when")
        if not isinstance(when, dict) or len(when) != 1:
            raise ConfigurationError(f"{rule['id']}: use exactly one all/any condition")
        operator = next(iter(when))
        if operator not in ("all", "any"):
            raise ConfigurationError(f"{rule['id']}: unsupported condition operator")
        names = when[operator]
        _string_list(names, f"{rule['id']} conditions", allow_empty=False)
        if set(names) - facts:
            raise ConfigurationError(f"{rule['id']}: unknown fact name")
        if priorities and rule.get("priority") not in priorities:
            raise ConfigurationError(f"{rule['id']}: unknown priority")
        if not priorities and not isinstance(rule.get("action"), str):
            raise ConfigurationError(f"{rule['id']}: missing action")


def load_defaults(path: Path):
    defaults = load_yaml(path)
    allowed = {
        "schema_version", "repositories", "labels", "label_match",
        "state", "date_range", "output_dir",
    }
    if set(defaults) != allowed:
        raise ConfigurationError("Defaults contain missing or unsupported settings")
    try:
        if defaults["schema_version"] != 1:
            raise ConfigurationError("Only default schema_version 1 is supported")
        _string_list(defaults["repositories"], "repositories", allow_empty=False)
        _string_list(defaults["labels"], "labels")
        if defaults["state"] != "open" or defaults["label_match"] not in ("all", "any"):
            raise ConfigurationError("Only open issues and all/any labels are supported")
        dates = defaults["date_range"]
        if not isinstance(dates, dict) or set(dates) != {"field", "from", "to"}:
            raise ConfigurationError("date_range needs field, from, and to")
        DateRange(dates["field"], dates["from"], dates["to"])
        if not isinstance(defaults["output_dir"], str) or not defaults["output_dir"].strip():
            raise ConfigurationError("output_dir must be a nonempty path string")
    except (KeyError, TypeError) as exc:
        raise ConfigurationError("Missing or invalid default configuration") from exc
    return defaults, hashlib.sha256(path.read_bytes()).hexdigest()


def load_policy(priority_path: Path, verdict_path: Path):
    policy, verdicts = load_yaml(priority_path), load_yaml(verdict_path)
    try:
        if policy["schema_version"] != 1 or verdicts["schema_version"] != 1:
            raise ConfigurationError("Only rule schema_version 1 is supported")
        if "defaults" in policy:
            raise ConfigurationError("Move defaults from priority rules to defaults.yml")
        if policy["priority"]["order"] != ["P0", "P1", "P2"]:
            raise ConfigurationError("Priority order must be P0, P1, P2")
        if policy["priority"]["fallback"] != "P2":
            raise ConfigurationError("Fallback priority must be P2")
        for priority in policy["priority"]["order"]:
            _string_list(
                policy["priority"]["explicit_labels"][priority],
                f"{priority} explicit labels",
            )
        re.compile(policy["priority"]["priority_like_label_pattern"])
        _string_list(policy["security"]["labels"], "security labels")
        _string_list(policy["community"]["excluded_authors"], "excluded authors")
        _string_list(
            policy["community"]["microsoft_organizations"],
            "membership organizations",
            allow_empty=False,
        )
        low = policy["low_effort"]
        for key in ("max_changed_files", "max_added_plus_deleted_lines"):
            if type(low[key]) is not int or low[key] < 0:
                raise ConfigurationError(f"{key} must be a nonnegative integer")
        for key in ("test_file_patterns", "test_job_patterns"):
            _string_list(low[key], key, allow_empty=False)
        if type(policy["overdue"]["age_days"]) is not int or policy["overdue"]["age_days"] < 0:
            raise ConfigurationError("age_days must be a nonnegative integer")
        _string_list(verdicts["missing_information_labels"], "missing information labels")
        _validate_rules(policy, PRIORITY_FACTS, ["P0", "P1", "P2"])
        _validate_rules(verdicts, VERDICT_FACTS)
        if verdicts["selection"]["fallback"] != verdicts["fallback"]["id"]:
            raise ConfigurationError("Verdict fallback definitions disagree")
        fixed = [
            (policy["priority"], "evaluate_all_rules", True),
            (policy["priority"], "linked_priority_source", "explicit_labels_or_reviewed_overrides"),
            (policy["priority"], "recursive_derived_priority_propagation", False),
            (policy["security"], "keyword_only_match", False),
            (policy["relationships"], "plain_cross_reference_is_confirmed", False),
            (policy["relationships"], "active_pr_states", ["open"]),
            (policy["relationships"], "allow_merged_pr_for_priority", False),
            (policy["community"], "required_membership_state", "non_member"),
            (policy["community"], "public_membership_absence_is_non_membership", False),
            (policy["community"], "ambiguous_404_is_non_membership", False),
            (low, "count_all_changed_files", True),
            (low, "allow_failed_pending_cancelled_or_unknown_checks", False),
            (low, "allow_stale_head_checks", False),
            (low, "allow_unknown_required_checks", False),
            (policy["overdue"], "comparison", "strictly_greater_than"),
            (policy["overdue"], "time_basis", "pr_created_at"),
            (policy["overdue"], "timezone", "UTC"),
            (policy["overdue"], "no_priority_scope", "issue_and_pr"),
            (policy["overdue"], "unknown_priority_like_label_counts_as_unset", False),
            (verdicts["selection"], "first_matching_rule_wins", True),
            (verdicts["selection"], "preserve_secondary_actions_in_audit", True),
        ]
        for section, key, expected in fixed:
            if section[key] != expected:
                raise ConfigurationError(f"Unsupported setting: {key}")
        expected_order = [
            "highest_matched_priority", "low_effort_merge_candidate_first",
            "created_at_ascending", "repository_ascending", "number_ascending",
        ]
        if verdicts["selection"]["selected_pr"]["order"] != expected_order:
            raise ConfigurationError("Unsupported selected PR ordering")
        allowed_issue_links = {
            "github_issue_dependency", "shared_confirmed_closing_pr", "reviewed_related_issue"
        }
        allowed_pr_links = {"github_closing_relationship", "reviewed_association"}
        for key, allowed in (
            ("accepted_issue_links", allowed_issue_links),
            ("accepted_pr_links", allowed_pr_links),
        ):
            _string_list(policy["relationships"][key], key)
            if set(policy["relationships"][key]) - allowed:
                raise ConfigurationError(f"Unsupported relationship: {key}")
        for section, keys in (
            (policy["priority"], ["preserve_explicit_priority_floor"]),
            (policy["priority"]["explicit_labels"], ["case_sensitive"]),
            (policy["security"], ["case_sensitive", "allow_reviewed_override"]),
            (policy["community"], ["case_sensitive", "allow_reviewed_membership_override"]),
            (low, [
                "allow_binary_changes", "allow_draft", "require_confirmed_mergeable",
                "require_changed_test_file", "require_successful_current_head_test_job",
                "require_all_required_checks_successful",
            ]),
        ):
            for key in keys:
                if type(section[key]) is not bool:
                    raise ConfigurationError(f"{key} must be boolean")
    except (KeyError, TypeError, re.error) as exc:
        raise ConfigurationError("Missing or invalid rule configuration") from exc
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (priority_path, verdict_path)
    }
    return policy, verdicts, hashes


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        return result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ConfigurationError(f"Expected timezone-aware ISO timestamp: {value}") from exc


def iso_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bound(value, upper=False):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError("Quote dates in YAML or pass ISO date strings")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            result = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
            return result + timedelta(days=1) if upper else result
        except (ValueError, OverflowError) as exc:
            raise ConfigurationError(f"Invalid calendar date: {value}") from exc
    return parse_time(value)


@dataclass(frozen=True)
class DateRange:
    field: str = "created"
    start: str | None = None
    end: str | None = None

    def __post_init__(self):
        if self.field not in ("created", "updated"):
            raise ConfigurationError("Date field must be created or updated")
        lower, upper = self.lower, self.upper
        if lower and upper and lower >= upper:
            raise ConfigurationError("Date range must have from earlier than to")

    @property
    def lower(self):
        return _bound(self.start)

    @property
    def upper(self):
        return _bound(self.end, upper=True)

    def includes(self, issue):
        value = parse_time(issue[f"{self.field}_at"])
        return (self.lower is None or value >= self.lower) and (
            self.upper is None or value < self.upper
        )

    def summary(self):
        return {
            "field": self.field, "from": self.start, "to": self.end,
            "from_utc": iso_time(self.lower) if self.lower else None,
            "to_exclusive_utc": iso_time(self.upper) if self.upper else None,
        }


def matches_patterns(value, patterns):
    return any(
        fnmatch.fnmatchcase(value.casefold(), pattern.casefold())
        or (
            pattern.startswith("**/")
            and fnmatch.fnmatchcase(value.casefold(), pattern[3:].casefold())
        )
        for pattern in patterns
    )


def _label_match(labels, configured, case_sensitive=False):
    normalize = (lambda text: text) if case_sensitive else str.casefold
    return bool({normalize(x) for x in labels} & {normalize(x) for x in configured})


def explicit_priority(item, policy):
    settings = policy["priority"]
    labels = item.get("labels", [])
    matches = [
        priority for priority in settings["order"]
        if _label_match(
            labels, settings["explicit_labels"][priority],
            settings["explicit_labels"]["case_sensitive"],
        )
    ]
    override = item.get("override", {}).get("priority")
    if override is not None:
        matches.append(override)
    known_labels = [
        label for priority in settings["order"]
        for label in settings["explicit_labels"][priority]
    ]
    unknown = any(
        re.fullmatch(settings["priority_like_label_pattern"], label, re.IGNORECASE)
        and not _label_match(
            [label], known_labels, settings["explicit_labels"]["case_sensitive"]
        )
        for label in labels
    )
    return (
        min(matches, key=settings["order"].index) if matches else None,
        unknown,
        len(set(matches)) > 1,
    )


def _security(item, policy):
    settings = policy["security"]
    return _label_match(item.get("labels", []), settings["labels"], settings["case_sensitive"]) or (
        settings["allow_reviewed_override"]
        and item.get("override", {}).get("security_fix") is True
    )


def _rule_matches(rule, facts):
    operator, names = next(iter(rule["when"].items()))
    return all(name in facts for name in names) if operator == "all" else any(
        name in facts for name in names
    )


def _priority_rules(facts, policy):
    return [rule for rule in policy["rules"] if _rule_matches(rule, facts)]


def _low_effort(pr, policy):
    settings, ci = policy["low_effort"], pr.get("ci", {})
    if pr.get("changed_files", float("inf")) > settings["max_changed_files"]:
        return False
    if pr.get("changed_lines", float("inf")) > settings["max_added_plus_deleted_lines"]:
        return False
    if not pr.get("files_complete") or (
        not settings["allow_binary_changes"] and not pr.get("text_files_confirmed")
    ):
        return False
    if not settings["allow_draft"] and pr.get("draft", True):
        return False
    if settings["require_confirmed_mergeable"] and pr.get("mergeable") is not True:
        return False
    if settings["require_changed_test_file"] and not pr.get("tests_changed"):
        return False
    if ci.get("state") != "success":
        return False
    if settings["require_all_required_checks_successful"] and not ci.get("required_known"):
        return False
    return not settings["require_successful_current_head_test_job"] or ci.get("test_success") is True


def assess(issue, policy, verdicts, snapshot):
    """Evaluate each PR independently so evidence cannot mix across PRs."""
    facts, gaps = set(), list(issue.get("gaps", []))
    own_priority, own_unknown, conflict = explicit_priority(issue, policy)
    if conflict:
        gaps.append("conflicting-priority-labels")
    if own_unknown:
        gaps.append("unmapped-priority-like-label")
    if policy["priority"]["preserve_explicit_priority_floor"] and own_priority in ("P0", "P1"):
        facts.add(f"issue_has_explicit_{own_priority.lower()}")
    if _security(issue, policy):
        facts.add("issue_has_trusted_security_fix_evidence")
    for linked in issue.get("linked_issues", []):
        linked_priority, _, _ = explicit_priority(linked, policy)
        if linked_priority in ("P0", "P1"):
            facts.add(f"accepted_link_has_explicit_{linked_priority.lower()}")
    if issue.get("collection_errors"):
        facts.add("required_issue_or_pr_collection_failed")
    if issue.get("override", {}).get("needs_information") is True or _label_match(
        issue.get("labels", []), verdicts["missing_information_labels"]
    ):
        facts.add("issue_has_reviewed_or_configured_missing_information_state")

    candidates, matched = [], _priority_rules(facts, policy)
    all_pr_facts = set()
    active = [pr for pr in issue.get("prs", []) if pr["state"] == "open" and not pr.get("merged")]
    for pr in active:
        pr_facts = set()
        priority, unknown, pr_conflict = explicit_priority(pr, policy)
        if pr_conflict:
            gaps.append(f"{pr['url']}: conflicting-priority-labels")
        if unknown:
            gaps.append(f"{pr['url']}: unmapped-priority-like-label")
        if _security(pr, policy):
            pr_facts.add("eligible_pr_has_trusted_security_fix_evidence")
        if pr.get("community") is True:
            pr_facts.update({
                "same_eligible_pr_is_verified_community",
                "eligible_pr_is_verified_community",
            })
        low = _low_effort(pr, policy)
        if low:
            pr_facts.add("same_eligible_pr_meets_low_effort_policy")
        if snapshot - parse_time(pr["created_at"]) > timedelta(days=policy["overdue"]["age_days"]):
            pr_facts.add("same_eligible_pr_is_older_than_age_threshold")
        if own_priority is None and priority is None:
            pr_facts.add("issue_and_same_pr_have_no_explicit_priority")
        if not own_unknown and not unknown:
            pr_facts.add("issue_and_same_pr_have_no_unmapped_priority_like_label")
        rules = _priority_rules(facts | pr_facts, policy)
        matched.extend(rules)
        all_pr_facts |= pr_facts
        rank = min(
            (policy["priority"]["order"].index(rule["priority"]) for rule in rules),
            default=2,
        )
        candidates.append((
            (rank, not (low and pr.get("community") is True), parse_time(pr["created_at"]),
             pr["repository"].casefold(), pr["number"]),
            pr, {rule["id"] for rule in rules},
        ))

    facts |= all_pr_facts & {
        "eligible_pr_has_trusted_security_fix_evidence", "eligible_pr_is_verified_community"
    }
    selected = min(candidates, key=lambda value: value[0]) if candidates else None
    if selected:
        _, pr, selected_rules = selected
        state = pr.get("ci", {}).get("state")
        selected_facts = {
            "selected_pr_has_failed_current_head_ci": state == "failed",
            "selected_pr_has_pending_or_running_current_head_ci": state == "pending",
            "selected_pr_is_draft": pr.get("draft") is True,
            "selected_pr_has_merge_conflict": pr.get("mergeable") is False,
            "selected_pr_has_effective_changes_requested_review": pr.get("changes_requested") is True,
            "selected_pr_is_verified_community": pr.get("community") is True,
            "selected_pr_meets_low_effort_policy": _low_effort(pr, policy),
            "selected_pr_matches_overdue_unprioritized_rule": "overdue-unprioritized-pr" in selected_rules,
        }
        facts.update(name for name, value in selected_facts.items() if value)
    if not active:
        facts.add("no_active_replacement_pr_exists")
    if any(pr.get("merged") for pr in issue.get("prs", [])):
        facts.add("relevant_fix_pr_is_merged")
    actions = [rule for rule in verdicts["rules"] if _rule_matches(rule, facts)]
    primary = actions[0] if actions else verdicts["fallback"]
    priority = min(
        (rule["priority"] for rule in matched),
        key=policy["priority"]["order"].index,
        default=policy["priority"]["fallback"],
    )
    return {
        "priority": priority,
        "verdict": primary["id"],
        "action": primary["action"],
        "matched_rules": sorted({rule["id"] for rule in matched}),
        "secondary_actions": [rule["id"] for rule in actions[1:]],
        "selected_pr": selected[1]["url"] if selected else None,
        "gaps": sorted(set(gaps)),
    }
