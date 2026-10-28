"""Offline policy, collection, and export regression tests."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from github_data import APIError, Collector, GitHubAPI, validate_local_inputs
from triage import parser, run
from triage_export import COLUMNS, compact_summary, safe_cell, write_exports
from triage_rules import (
    ConfigurationError, DateRange, assess, load_defaults, load_policy, load_yaml, parse_time,
)

SNAPSHOT = parse_time("2026-10-28T00:00:00Z")
REPO = "example/project"
ISSUE = f"https://github.com/{REPO}/issues/1"
PR = f"https://github.com/{REPO}/pull/2"


def issue(**changes):
    value = {
        "url": ISSUE, "repository": REPO, "number": 1, "title": "Example issue",
        "state": "open", "labels": [], "override": {},
        "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-28T00:00:00Z",
        "prs": [], "linked_issues": [], "collection_errors": [], "gaps": [],
    }
    value.update(changes)
    return value


def pr(**changes):
    value = {
        "url": PR, "repository": REPO, "number": 2, "state": "open", "merged": False,
        "created_at": "2026-10-20T00:00:00Z", "labels": [], "override": {},
        "community": True, "draft": False, "mergeable": True,
        "changed_files": 2, "changed_lines": 40, "files_complete": True,
        "text_files_confirmed": True, "tests_changed": True, "head_sha": "abc",
        "ci": {"state": "success", "required_known": True, "test_success": True},
    }
    value.update(changes)
    return value


def raw_issue(number=1, **changes):
    value = {
        "html_url": f"https://github.com/{REPO}/issues/{number}", "number": number,
        "title": "Example issue", "state": "open", "labels": [{"name": "Compute"}],
        "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-28T00:00:00Z",
    }
    value.update(changes)
    return value


class MemoryAPI(GitHubAPI):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.calls = []

    def request(self, method, endpoint, body=None, fresh=False):
        self.request_count += 1
        self.calls.append((method, endpoint, fresh))
        value = self.routes.get(endpoint, self.routes.get(endpoint.split("?")[0]))
        if value is None:
            raise APIError(f"Unconfigured fixture: {endpoint}", 404)
        if callable(value):
            value = value(method, endpoint, body, fresh)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return copy.deepcopy(value)
        return copy.deepcopy(value), {}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.verdicts, _ = load_policy(
            ROOT / "priority-rules.yml", ROOT / "verdict-rules.yml"
        )

    def result(self, value):
        return assess(value, self.policy, self.verdicts, SNAPSHOT)

    def test_security_and_linked_priorities_without_pr(self):
        for value, priority, verdict in (
            (issue(labels=["security"]), "P0", "security-review"),
            (issue(linked_issues=[{"labels": ["P0"]}]), "P0", "linked-priority-review"),
            (issue(linked_issues=[{"labels": ["P1"]}]), "P1", "linked-priority-review"),
            (issue(title="CRITICAL SECURITY P0"), "P2", "triage-needed"),
        ):
            with self.subTest(value=value):
                result = self.result(value)
                self.assertEqual((result["priority"], result["verdict"]), (priority, verdict))

    def test_low_effort_community_contribution(self):
        result = self.result(issue(prs=[pr()]))
        self.assertEqual((result["priority"], result["verdict"]), ("P0", "merge-candidate"))
        self.assertIn("community-pr", result["matched_rules"])

    def test_low_effort_requires_all_current_evidence(self):
        cases = [
            {"changed_files": 6}, {"changed_lines": 101}, {"files_complete": False},
            {"text_files_confirmed": False}, {"tests_changed": False},
            {"draft": True}, {"mergeable": None},
            {"ci": {"state": "unknown", "required_known": True, "test_success": True}},
            {"ci": {"state": "success", "required_known": False, "test_success": True}},
            {"ci": {"state": "success", "required_known": True, "test_success": False}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.result(issue(prs=[pr(**changes)]))["priority"], "P1")

    def test_ci_and_review_blockers_determine_next_action(self):
        cases = [
            ({"ci": {"state": "failed"}}, "ci-fix-needed"),
            ({"ci": {"state": "pending"}}, "awaiting-ci"),
            ({"draft": True}, "pr-update-needed"),
            ({"mergeable": False}, "pr-update-needed"),
            ({"changes_requested": True}, "pr-update-needed"),
        ]
        for changes, verdict in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.result(issue(prs=[pr(**changes)]))["verdict"], verdict)

    def test_large_community_pr_and_noncommunity_defaults(self):
        self.assertEqual(
            self.result(issue(prs=[pr(changed_lines=200)]))["verdict"], "review-community-pr"
        )
        for community in (False, None):
            with self.subTest(community=community):
                self.assertEqual(
                    self.result(issue(prs=[pr(community=community)]))["priority"], "P2"
                )

    def test_age_is_strict_and_uses_pr_creation(self):
        exact = pr(community=False, created_at="2026-10-14T00:00:00Z")
        self.assertEqual(self.result(issue(prs=[exact]))["priority"], "P2")
        older = pr(community=False, created_at="2026-10-13T23:59:59Z")
        result = self.result(issue(created_at="2026-10-27T00:00:00Z", prs=[older]))
        self.assertEqual((result["priority"], result["verdict"]), ("P1", "review-overdue"))
        self.assertEqual(self.result(issue(created_at="2010-01-01T00:00:00Z"))["priority"], "P2")

    def test_explicit_and_unmapped_priorities_block_unprioritized_age(self):
        older = pr(community=False, created_at="2026-10-01T00:00:00Z")
        for labels in (["P2"], ["P3"]):
            with self.subTest(labels=labels):
                self.assertEqual(self.result(issue(labels=labels, prs=[older]))["priority"], "P2")
        result = self.result(issue(labels=["P0", "p1"], prs=[older]))
        self.assertEqual(result["priority"], "P0")
        self.assertIn("conflicting-priority-labels", result["gaps"])

    def test_pr_evidence_is_not_mixed_across_candidates(self):
        large_community = pr(changed_lines=500)
        small_member = pr(
            url=f"https://github.com/{REPO}/pull/3", number=3, community=False
        )
        result = self.result(issue(prs=[large_community, small_member]))
        self.assertEqual(result["priority"], "P1")
        self.assertNotIn("low-effort-community-pr", result["matched_rules"])
        self.assertEqual(result["selected_pr"], large_community["url"])

    def test_unrelated_failed_pr_does_not_override_selected_merge_candidate(self):
        failed = pr(
            url=f"https://github.com/{REPO}/pull/3", number=3,
            ci={"state": "failed"}, community=False,
        )
        result = self.result(issue(prs=[failed, pr()]))
        self.assertEqual(result["verdict"], "merge-candidate")
        self.assertEqual(result["selected_pr"], PR)

    def test_historical_prs_do_not_raise_priority(self):
        for merged in (False, True):
            result = self.result(issue(prs=[pr(state="closed", merged=merged)]))
            self.assertEqual(result["priority"], "P2")
            self.assertEqual(result["verdict"], "verify-release" if merged else "triage-needed")

    def test_collection_failure_and_security_precedence(self):
        partial = issue(collection_errors=["HTTP failure"])
        self.assertEqual(self.result(partial)["verdict"], "data-incomplete")
        partial["labels"] = ["security"]
        self.assertEqual(self.result(partial)["verdict"], "security-review")

    def test_rules_and_thresholds_can_be_maintained(self):
        self.policy["low_effort"]["max_added_plus_deleted_lines"] = 20
        self.assertEqual(self.result(issue(prs=[pr()]))["priority"], "P1")
        self.verdicts["rules"].reverse()
        self.assertEqual(self.result(issue(labels=["needs-info"]))["verdict"], "needs-information")


class DateTests(unittest.TestCase):
    def test_inclusive_calendar_end_and_unbounded_default(self):
        dates = DateRange("created", "2026-10-01", "2026-10-28")
        self.assertTrue(dates.includes(issue(created_at="2026-10-01T00:00:00Z")))
        self.assertTrue(dates.includes(issue(created_at="2026-10-28T23:59:59Z")))
        self.assertFalse(dates.includes(issue(created_at="2026-10-29T00:00:00Z")))
        self.assertTrue(DateRange().includes(issue(created_at="2010-01-01T00:00:00Z")))
        self.assertTrue(DateRange("created", "2026-10-28", "2026-10-28").includes(
            issue(created_at="2026-10-28T12:00:00Z")
        ))

    def test_timestamp_offsets_and_exclusive_upper(self):
        dates = DateRange("created", "2026-10-28T08:00:00+08:00", "2026-10-28T01:00:00Z")
        self.assertTrue(dates.includes(issue(created_at="2026-10-28T00:00:00Z")))
        self.assertFalse(dates.includes(issue(created_at="2026-10-28T01:00:00Z")))

    def test_updated_field_and_one_sided_ranges(self):
        value = issue(created_at="2010-01-01T00:00:00Z")
        self.assertTrue(DateRange("updated", "2026-10-28").includes(value))
        self.assertFalse(DateRange("created", "2026-10-28").includes(value))
        self.assertTrue(DateRange("created", end="2026-10-28").includes(value))

    def test_invalid_ranges(self):
        for field, start, end in (
            ("other", None, None), ("created", "2026-02-30", None),
            ("created", "2026-10-29", "2026-10-27"),
            ("created", "2026-10-28T00:00:00", None),
            ("created", None, "2026-02-30"),
            ("created", None, "2026-10-28T00:00:00"),
            ("created", "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z"),
        ):
            with self.subTest(field=field, start=start, end=end):
                with self.assertRaises(ConfigurationError):
                    DateRange(field, start, end)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.policy, _, _ = load_policy(ROOT / "priority-rules.yml", ROOT / "verdict-rules.yml")

    def test_rest_pagination_follows_next_link(self):
        api = MemoryAPI({
            "repos/example/project/issues?per_page=100&page=1": ([{"number": 1}], {"link": '<next>; rel="next"'}),
            "repos/example/project/issues?per_page=100&page=2": ([{"number": 2}], {}),
        })
        self.assertEqual(
            [item["number"] for item in api.pages("repos/example/project/issues")], [1, 2]
        )

    def test_graphql_pagination_and_repeated_cursor(self):
        def response(method, endpoint, body, fresh):
            cursor = body["variables"].get("cursor")
            connection = {
                "nodes": [{"url": PR if cursor is None else PR + "3"}],
                "pageInfo": {"hasNextPage": cursor is None, "endCursor": "next"},
            }
            return {"data": {"repository": {"issue": {"links": connection}}}}
        api = MemoryAPI({"graphql": response})
        nodes, _ = api.connection(REPO, 1, "query {}", "issue", "links")
        self.assertEqual(len(nodes), 2)

        def repeated(method, endpoint, body, fresh):
            return {"data": {"repository": {"issue": {"links": {
                "nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "same"},
            }}}}}
        api.routes["graphql"] = repeated
        with self.assertRaises(APIError):
            api.connection(REPO, 1, "query {}", "issue", "links")

    def test_issue_filters_exclude_prs_and_apply_any_labels_and_dates(self):
        raw = [
            raw_issue(), raw_issue(2, labels=[{"name": "Network"}]),
            raw_issue(3, pull_request={}), raw_issue(4, labels=[]),
        ]
        api = MemoryAPI({f"repos/{REPO}/issues": raw})
        collector = Collector(api, self.policy)
        results = list(collector.issues(
            REPO, ["Compute", "Network"], "any", DateRange("updated", "2026-10-28")
        ))
        self.assertEqual([item["number"] for item in results], [1, 2])
        self.assertIn("since=", api.calls[0][1])

    def test_membership_404_is_unknown_but_reviewed_inventory_can_prove_absence(self):
        api = MemoryAPI({})
        collector = Collector(api, self.policy)
        self.assertEqual(collector._membership("outsider")["state"], "unknown")
        collector = Collector(api, self.policy, inventory={"organizations": {
            org: {"complete": True, "members": [], "evidence": "authorized fixture"}
            for org in ("microsoft", "Azure")
        }})
        self.assertEqual(collector._membership("outsider")["state"], "non_member")
        collector.inventory["organizations"]["Azure"]["members"] = ["inside"]
        self.assertEqual(collector._membership("inside")["state"], "member")

    def test_positive_membership_and_partial_inventory(self):
        api = MemoryAPI({"orgs/microsoft/memberships/inside": {"state": "active"}})
        self.assertEqual(Collector(api, self.policy)._membership("inside")["state"], "member")
        inventory = {"organizations": {
            "microsoft": {"complete": True, "members": [], "evidence": "fixture"}
        }}
        self.assertEqual(
            Collector(MemoryAPI({}), self.policy, inventory=inventory)._membership("outside")["state"],
            "unknown",
        )

    def test_ci_uses_latest_results_current_sha_and_all_required_contexts(self):
        prefix = f"repos/{REPO}/commits/abc"
        routes = {
            prefix + "/check-runs": {"check_runs": [
                {"id": 2, "name": "unit tests", "app": {"id": 10}, "head_sha": "abc",
                 "status": "completed", "conclusion": "success"},
                {"id": 1, "name": "unit tests", "app": {"id": 10}, "head_sha": "abc",
                 "status": "completed", "conclusion": "failure"},
            ]},
            prefix + "/statuses": [],
            f"repos/{REPO}/branches/main": {"protected": False},
            f"repos/{REPO}/rules/branches/main": [],
        }
        api = MemoryAPI(routes)
        collector = Collector(api, self.policy)
        self.assertEqual(collector._ci(REPO, "abc", "main")["state"], "success")
        routes[prefix + "/check-runs"]["check_runs"][0]["head_sha"] = "old"
        self.assertEqual(collector._ci(REPO, "abc", "main")["state"], "unknown")
        routes[prefix + "/check-runs"]["check_runs"][0]["head_sha"] = "abc"
        routes[f"repos/{REPO}/rules/branches/main"] = [{
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "missing", "integration_id": None}]},
        }]
        self.assertEqual(collector._ci(REPO, "abc", "main")["state"], "unknown")

    def test_required_configuration_failure_is_a_gap_not_green(self):
        api = MemoryAPI({
            f"repos/{REPO}/branches/main": {"protected": True},
            f"repos/{REPO}/rules/branches/main": [],
        })
        self.assertEqual(Collector(api, self.policy)._required_checks(REPO, "main"), (False, []))

    def test_protected_branch_can_explicitly_have_no_required_status_checks(self):
        api = MemoryAPI({
            f"repos/{REPO}/branches/main": {"protected": True},
            f"repos/{REPO}/rules/branches/main": [],
            f"repos/{REPO}/branches/main/protection": {"required_status_checks": None},
        })
        self.assertEqual(Collector(api, self.policy)._required_checks(REPO, "main"), (True, []))

    def test_changed_pr_head_invalidates_unverifiable_ci(self):
        current = pr()
        record = issue(prs=[current])
        api = MemoryAPI({
            f"repos/{REPO}/pulls/2": APIError("cannot refresh", 403),
        })
        Collector(api, self.policy).verify_selected_head(record, PR)
        self.assertTrue(record["collection_errors"])
        self.assertEqual(current["ci"]["state"], "unknown")


class TransportTests(unittest.TestCase):
    @patch("github_data.subprocess.run")
    def test_read_only_request_headers_and_json(self, process):
        process.return_value = subprocess.CompletedProcess(
            [], 0, 'HTTP/2.0 200 OK\nLink: <next>; rel="next"\n\n[{"number":1}]', ""
        )
        api = GitHubAPI()
        data, headers = api.request("GET", "repos/example/project/issues")
        self.assertEqual(data, [{"number": 1}])
        self.assertIn("next", headers["link"])
        api.request("GET", "repos/example/project/issues")
        self.assertEqual(process.call_count, 1)
        with self.assertRaises(APIError):
            api.request("POST", "repos/example/project/issues", {"title": "no writes"})
        with self.assertRaises(APIError):
            api.request("POST", "graphql", {"query": "mutation { anything }"})

    @patch("github_data.time.sleep")
    @patch("github_data.subprocess.run")
    def test_retry_respects_headers_without_exposing_stderr(self, process, sleep):
        process.side_effect = [
            subprocess.CompletedProcess([], 1, "HTTP/2.0 429 Too Many Requests\nRetry-After: 2\n\n{}", "private"),
            subprocess.CompletedProcess([], 0, "HTTP/2.0 200 OK\n\n[]", ""),
        ]
        self.assertEqual(GitHubAPI().get("repos/example/project"), [])
        sleep.assert_called_once_with(2)


class ExportAndConfigTests(unittest.TestCase):
    def test_csv_quotes_formula_safety_audit_and_no_overwrite(self):
        value = issue(title='=SUM(1,2), "quoted"\nsecond line')
        value["assessment"] = {
            "priority": "P0", "verdict": "security-review", "matched_rules": ["security-fix"]
        }
        with tempfile.TemporaryDirectory() as directory:
            summary = write_exports(Path(directory), [value], {
                "status": "complete", "snapshot_time": "2026-10-28T00:00:00Z", "rule_hashes": {},
            })
            with Path(summary["output_paths"]["csv"]).open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], COLUMNS)
            self.assertEqual(rows[1][1], "'" + value["title"])
            audit = json.loads(Path(summary["output_paths"]["audit"]).read_text(encoding="utf-8"))
            self.assertEqual(audit["title"], value["title"])
            for key, expected in summary["artifact_sha256"].items():
                self.assertEqual(
                    hashlib.sha256(Path(summary["output_paths"][key]).read_bytes()).hexdigest(),
                    expected,
                )
            with self.assertRaises(ConfigurationError):
                write_exports(Path(directory), [], summary)
            partial = write_exports(Path(directory), [], dict(summary, status="partial"))
            self.assertTrue(Path(partial["output_paths"]["csv"]).name.endswith(".partial.csv"))
            self.assertTrue(Path(summary["output_paths"]["csv"]).exists())
        self.assertEqual(safe_cell(" \t+formula"), "' \t+formula")

    def test_compact_summary_has_bounded_warning_count(self):
        result = compact_summary({"warnings": ["x" * 1000] * 100})
        self.assertEqual(result["warning_count"], 100)
        self.assertEqual(len(result["warnings"]), 10)
        self.assertLessEqual(len(result["warnings"][0]), 400)

    def test_duplicate_yaml_keys_and_unknown_facts_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.yml"
            path.write_text("key: first\nkey: second\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_yaml(path)
            original = (ROOT / "priority-rules.yml").read_text(encoding="utf-8")
            path.write_text(original.replace("issue_has_explicit_p0", "invented_fact"), encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_policy(path, ROOT / "verdict-rules.yml")

    def test_invalid_overrides_fail_validation(self):
        with self.assertRaises(ConfigurationError):
            validate_local_inputs({"issues": {ISSUE: {"priority": "P0"}}}, {})
        with self.assertRaises(ConfigurationError):
            validate_local_inputs({}, {"organizations": {
                "microsoft": {"complete": True, "evidence": "reference", "members": "not-a-list"}
            }})
        with self.assertRaises(ConfigurationError):
            validate_local_inputs({"issues": []}, {})

    def test_invalid_defaults_fail_before_collection(self):
        baseline = load_yaml(ROOT / "defaults.example.yml")
        cases = [
            {"repositories": []},
            {"labels": "Compute"},
            {"date_range": {"field": "created", "from": None, "to": "2026-02-30"}},
            {"output_dir": ""},
            {"unknown_setting": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "defaults.yml"
            for changes in cases:
                with self.subTest(changes=changes):
                    config.write_text(json.dumps(dict(baseline, **changes)), encoding="utf-8")
                    with self.assertRaises(ConfigurationError):
                        load_defaults(config)


class EndToEndTests(unittest.TestCase):
    def api(self, refreshed=None, enumeration_failure=False):
        raw = raw_issue()

        def graphql(method, endpoint, body, fresh):
            return {"data": {"repository": {"issue": {"closedByPullRequestsReferences": {
                "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}}}}

        return MemoryAPI({
            f"repos/{REPO}": {"full_name": REPO},
            f"repos/{REPO}/labels/Compute": {"name": "Compute"},
            f"repos/{REPO}/issues": APIError("fixture failure", 503) if enumeration_failure else [raw],
            f"repos/{REPO}/issues/1": refreshed or raw,
            f"repos/{REPO}/issues/1/dependencies/blocked_by": [],
            f"repos/{REPO}/issues/1/dependencies/blocking": [],
            "graphql": graphql,
        })

    def test_complete_run_writes_seven_column_csv_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            args = parser().parse_args(["--repo", REPO, "--output-dir", directory])
            summary = run(args, self.api(), SNAPSHOT)
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["issue_count"], 1)
            self.assertEqual(summary["priority_counts"]["P2"], 1)
            with Path(summary["output_paths"]["csv"]).open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], COLUMNS)
            self.assertEqual(len(rows[1]), 7)
            audit = json.loads(Path(summary["output_paths"]["audit"]).read_text(encoding="utf-8"))
            self.assertEqual(audit["tool_version"], summary["tool_version"])
            self.assertEqual(compact_summary(summary)["tool_version"], summary["tool_version"])

    def test_version_exits_without_api_collection(self):
        from triage import VERSION, main
        stream = io.StringIO()
        with patch("sys.stdout", stream), patch("triage.GitHubAPI") as api:
            with self.assertRaises(SystemExit) as exited:
                main(["--version"])
        self.assertEqual(exited.exception.code, 0)
        self.assertIn(VERSION, stream.getvalue())
        api.assert_not_called()

    def test_config_selects_repository_dates_and_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            defaults = load_yaml(ROOT / "defaults.example.yml")
            defaults.update({
                "repositories": [REPO],
                "date_range": {"field": "updated", "from": "2026-10-28", "to": "2026-10-28"},
                "output_dir": str(Path(directory) / "result"),
            })
            config = Path(directory) / "defaults.yml"
            config.write_text(json.dumps(defaults), encoding="utf-8")
            summary = run(parser().parse_args(["--config", str(config)]), self.api(), SNAPSHOT)
            self.assertEqual(summary["parameters"]["repositories"], [REPO])
            self.assertEqual(summary["date_range"]["field"], "updated")
            self.assertEqual(summary["issue_count"], 1)
            self.assertEqual(
                Path(summary["output_paths"]["csv"]).parent,
                (Path(directory) / "result").resolve(),
            )
            self.assertEqual(summary["rule_hashes"]["defaults"], hashlib.sha256(config.read_bytes()).hexdigest())

    def test_cli_flags_override_config_scope_dates_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            defaults = load_yaml(ROOT / "defaults.example.yml")
            defaults.update({
                "repositories": ["other/repository"], "labels": ["Other"], "label_match": "any",
                "date_range": {"field": "created", "from": "2020-01-01", "to": "2020-01-01"},
                "output_dir": str(Path(directory) / "unused"),
            })
            config = Path(directory) / "defaults.yml"
            config.write_text(json.dumps(defaults), encoding="utf-8")
            args = parser().parse_args([
                "--config", str(config), "--repo", REPO, "--label", "Compute",
                "--label-match", "all", "--date-field", "updated",
                "--from", "2026-10-28", "--to", "2026-10-28",
                "--output-dir", str(Path(directory) / "selected"),
            ])
            summary = run(args, self.api(), SNAPSHOT)
            self.assertEqual(summary["issue_count"], 1)
            self.assertEqual(summary["parameters"]["labels"], ["Compute"])
            self.assertEqual(summary["parameters"]["label_match"], "all")
            self.assertEqual(
                Path(summary["output_paths"]["csv"]).parent,
                (Path(directory) / "selected").resolve(),
            )
            self.assertFalse((Path(directory) / "unused").exists())

    def test_local_defaults_precede_example_and_missing_local_uses_example(self):
        import triage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = load_yaml(ROOT / "defaults.example.yml")
            defaults["repositories"] = [REPO]
            (root / "defaults.example.yml").write_text(json.dumps(defaults), encoding="utf-8")
            with patch.object(triage, "SKILL_DIRECTORY", root):
                def arguments(output):
                    return parser().parse_args([
                        "--priority-rules", str(ROOT / "priority-rules.yml"),
                        "--verdict-rules", str(ROOT / "verdict-rules.yml"),
                        "--output-dir", str(root / output),
                    ])
                fallback = run(arguments("fallback"), self.api(), SNAPSHOT)
                self.assertEqual(fallback["issue_count"], 1)
                defaults["date_range"]["from"] = "2027-01-01"
                (root / "defaults.yml").write_text(json.dumps(defaults), encoding="utf-8")
                local = run(arguments("local"), self.api(), SNAPSHOT)
                self.assertEqual(local["issue_count"], 0)
                missing = arguments("missing")
                missing.config = root / "missing.yml"
                with self.assertRaises(ConfigurationError):
                    run(missing, self.api(), SNAPSHOT)

    def test_linked_community_pr_end_to_end(self):
        api = self.api()

        def graphql(method, endpoint, body, fresh):
            if "closedByPullRequestsReferences" in body["query"]:
                node = {"closedByPullRequestsReferences": {
                    "nodes": [{"url": PR}], "pageInfo": {"hasNextPage": False, "endCursor": None},
                }}
                return {"data": {"repository": {"issue": node}}}
            node = {
                "reviewDecision": "APPROVED",
                "closingIssuesReferences": {
                    "nodes": [{"url": ISSUE}], "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
            return {"data": {"repository": {"pullRequest": node}}}

        api.routes.update({
            "graphql": graphql,
            f"repos/{REPO}/pulls/2": {
                "state": "open", "merged_at": None, "created_at": "2026-10-20T00:00:00Z",
                "mergeable": True, "labels": [], "draft": False,
                "head": {"sha": "abc"}, "base": {"ref": "main"},
                "changed_files": 2, "additions": 20, "deletions": 2,
                "user": {"login": "contributor"},
            },
            f"repos/{REPO}/pulls/2/files": [
                {"filename": "tests/test_vm.py", "status": "modified",
                 "patch": "@@ test @@", "additions": 10, "deletions": 1},
                {"filename": "vm.py", "status": "modified",
                 "patch": "@@ code @@", "additions": 10, "deletions": 1},
            ],
            f"repos/{REPO}/commits/abc/check-runs": {"check_runs": [
                {"id": 1, "name": "unit tests", "app": {"id": 10}, "head_sha": "abc",
                 "status": "completed", "conclusion": "success"},
            ]},
            f"repos/{REPO}/commits/abc/statuses": [],
            f"repos/{REPO}/branches/main": {"protected": False},
            f"repos/{REPO}/rules/branches/main": [],
        })
        with tempfile.TemporaryDirectory() as directory:
            overrides = Path(directory) / "overrides.yml"
            overrides.write_text(json.dumps({"authors": {
                "contributor": {"membership": "non_member", "evidence": "reviewed fixture"}
            }}), encoding="utf-8")
            args = parser().parse_args([
                "--repo", REPO, "--overrides", str(overrides),
                "--output-dir", str(Path(directory) / "result"),
                "--from", "2026-10-01", "--to", "2026-10-01",
            ])
            summary = run(args, api, SNAPSHOT)
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["priority_counts"]["P0"], 1)
            audit = json.loads(Path(summary["output_paths"]["audit"]).read_text(encoding="utf-8"))
            self.assertEqual(audit["assessment"]["verdict"], "merge-candidate")
            self.assertEqual(audit["assessment"]["selected_pr"], PR)
            self.assertTrue(audit["prs"][0]["tests_changed"])
            self.assertFalse(any("orgs/" in call[1] for call in api.calls))

    def test_refreshed_closed_or_updated_outside_range_is_excluded(self):
        for refreshed in (
            raw_issue(state="closed"), raw_issue(updated_at="2026-10-29T00:00:00Z"),
            raw_issue(labels=[]),
        ):
            with self.subTest(refreshed=refreshed), tempfile.TemporaryDirectory() as directory:
                args = parser().parse_args([
                    "--repo", REPO, "--date-field", "updated",
                    "--from", "2026-10-28", "--to", "2026-10-28",
                    "--output-dir", directory,
                ])
                summary = run(args, self.api(refreshed), SNAPSHOT)
                self.assertEqual(summary["issue_count"], 0)

    def test_missing_label_errors_and_enumeration_partial_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            args = parser().parse_args(["--repo", REPO, "--output-dir", directory])
            api = self.api()
            api.routes[f"repos/{REPO}/labels/Compute"] = APIError("missing", 404)
            with self.assertRaises(ConfigurationError):
                run(args, api, SNAPSHOT)
            summary = run(args, self.api(enumeration_failure=True), SNAPSHOT)
            self.assertEqual(summary["status"], "partial")
            self.assertIn(".partial.csv", summary["output_paths"]["csv"])

    def test_invalid_cli_returns_compact_error(self):
        from triage import main
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = main(["--from", "2026-02-30"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stream.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
