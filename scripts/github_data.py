"""Read-only GitHub access and evidence collection; no model calls."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time
from datetime import timedelta
from urllib.parse import quote, urlencode

from triage_rules import ConfigurationError, iso_time, matches_patterns

ISSUE_PRS = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      closedByPullRequestsReferences(first:100,after:$cursor,includeClosedPrs:true) {
        nodes { url }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
PR_ISSUES = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    pullRequest(number:$number) {
      reviewDecision
      closingIssuesReferences(first:100,after:$cursor) {
        nodes { url }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
ITEM_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(issues|pull)/([1-9][0-9]*)/?"
)


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def parse_item_url(url, kind=None):
    match = ITEM_URL.fullmatch(url) if isinstance(url, str) else None
    if not match or (kind and match[2] != kind):
        raise ConfigurationError("Expected a github.com issue or pull request URL")
    return match[1], match[2], int(match[3])


def validate_repository(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ConfigurationError(f"Invalid owner/repository: {value}")
    return value


class GitHubAPI:
    """Use gh authentication without reading or logging its token."""

    def __init__(self, attempts=3, timeout=90):
        self.attempts = attempts
        self.timeout = timeout
        self.cache = {}
        self.request_count = 0

    def request(self, method, endpoint, body=None, fresh=False):
        if not endpoint.startswith(("repos/", "orgs/", "graphql")):
            raise APIError("Unsupported GitHub endpoint")
        if method != "GET" and not (
            method == "POST" and endpoint == "graphql"
            and body and body["query"].lstrip().startswith("query")
        ):
            raise APIError("Only read-only GitHub requests are allowed")
        key = (method, endpoint, json.dumps(body, sort_keys=True))
        if not fresh and key in self.cache:
            return copy.deepcopy(self.cache[key])
        command = [
            "gh", "api", "--hostname", "github.com", "--include",
            "--method", method, endpoint,
        ]
        if body is not None:
            command.extend(["--input", "-"])
        environment = dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat")
        for attempt in range(self.attempts):
            self.request_count += 1
            try:
                result = subprocess.run(
                    command, input=json.dumps(body) if body is not None else None,
                    capture_output=True, text=True, encoding="utf-8",
                    timeout=self.timeout, env=environment,
                )
            except FileNotFoundError as exc:
                raise APIError("GitHub CLI is missing; install gh and authenticate") from exc
            except subprocess.TimeoutExpired as exc:
                if attempt + 1 < self.attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise APIError("GitHub request timed out") from exc
            head, separator, content = result.stdout.replace("\r\n", "\n").partition("\n\n")
            status_match = re.match(r"HTTP/\S+\s+(\d+)", head)
            status = int(status_match[1]) if status_match else None
            headers = {}
            for line in head.splitlines()[1:]:
                name, colon, value = line.partition(":")
                if colon:
                    headers[name.casefold()] = value.strip()
            transient = status in (429, 500, 502, 503, 504) or (
                status == 403 and (
                    headers.get("x-ratelimit-remaining") == "0"
                    or "retry-after" in headers
                )
            )
            delay = 2 ** attempt
            if "retry-after" in headers:
                try:
                    delay = max(delay, int(headers["retry-after"]))
                except ValueError:
                    delay = 31
            if headers.get("x-ratelimit-remaining") == "0":
                try:
                    delay = max(delay, int(headers["x-ratelimit-reset"]) - int(time.time()) + 1)
                except (KeyError, ValueError):
                    delay = 31
            if transient and attempt + 1 < self.attempts and delay <= 30:
                time.sleep(delay)
                continue
            if result.returncode or status is None or status >= 400 or not separator:
                raise APIError(
                    f"{method} {endpoint.split('?')[0]} failed"
                    + (f" (HTTP {status})" if status else "; check gh authentication"),
                    status,
                )
            try:
                data = json.loads(content) if content.strip() else None
            except json.JSONDecodeError as exc:
                raise APIError("GitHub returned invalid JSON") from exc
            if endpoint == "graphql" and (not data or data.get("errors")):
                raise APIError("GitHub GraphQL failed; partial query data was rejected")
            self.cache[key] = (data, headers)
            return copy.deepcopy((data, headers))
        raise APIError("GitHub retries exhausted")

    def get(self, endpoint, fresh=False):
        return self.request("GET", endpoint, fresh=fresh)[0]

    def pages(self, endpoint, params=None, item_key=None):
        page = 1
        while True:
            query = dict(params or {}, per_page=100, page=page)
            data, headers = self.request("GET", endpoint + "?" + urlencode(query))
            items = data[item_key] if item_key else data
            if not isinstance(items, list):
                raise APIError(f"Invalid paginated response: {endpoint}")
            yield from items
            if 'rel="next"' not in headers.get("link", "") and len(items) < 100:
                break
            if not items:
                break
            page += 1

    def connection(self, repository, number, query, node_name, field):
        owner, name = repository.split("/")
        variables = {"owner": owner, "name": name, "number": number}
        nodes, metadata, cursors = [], {}, set()
        while True:
            data, _ = self.request(
                "POST", "graphql", {"query": query, "variables": variables}
            )
            root = data.get("data", {}).get("repository")
            node = root.get(node_name) if root else None
            if node is None:
                raise APIError(f"Inaccessible {node_name} relationship data")
            metadata = {key: value for key, value in node.items() if key != field}
            connection = node[field]
            nodes.extend(connection["nodes"])
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                return nodes, metadata
            cursor = info["endCursor"]
            if not cursor or cursor in cursors:
                raise APIError("GitHub returned a repeated pagination cursor")
            cursors.add(cursor)
            variables["cursor"] = cursor


def validate_local_inputs(overrides, inventory):
    if set(overrides) - {"issues", "authors"}:
        raise ConfigurationError("Overrides support only issues and authors")
    for key in ("issues", "authors"):
        if not isinstance(overrides.get(key, {}), dict):
            raise ConfigurationError(f"Overrides {key} must be a mapping")
    for url, item in overrides.get("issues", {}).items():
        parse_item_url(url)
        if not isinstance(item, dict) or not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise ConfigurationError("Each item override needs an evidence string")
        if set(item) - {
            "evidence", "priority", "security_fix", "needs_information", "prs", "related_issues"
        }:
            raise ConfigurationError("Unknown issue override field")
        if "priority" in item and item["priority"] not in ("P0", "P1", "P2"):
            raise ConfigurationError("Override priority must be P0, P1, or P2")
        for key in ("security_fix", "needs_information"):
            if key in item and type(item[key]) is not bool:
                raise ConfigurationError(f"Override {key} must be boolean")
        for key, kind in (("prs", "pull"), ("related_issues", "issues")):
            values = item.get(key, [])
            if not isinstance(values, list):
                raise ConfigurationError(f"Override {key} must be a URL list")
            for value in values:
                parse_item_url(value, kind)
    for author, item in overrides.get("authors", {}).items():
        if not isinstance(author, str) or not isinstance(item, dict):
            raise ConfigurationError("Invalid author override")
        if (
            item.get("membership") not in ("member", "non_member", "unknown")
            or not isinstance(item.get("evidence"), str) or not item["evidence"].strip()
        ):
            raise ConfigurationError("Author overrides need membership and evidence")
    if set(inventory) - {"organizations"}:
        raise ConfigurationError("Membership inventory supports only organizations")
    if not isinstance(inventory.get("organizations", {}), dict):
        raise ConfigurationError("Inventory organizations must be a mapping")
    for org, item in inventory.get("organizations", {}).items():
        if not isinstance(org, str) or not isinstance(item, dict):
            raise ConfigurationError("Invalid membership inventory")
        if (
            type(item.get("complete")) is not bool
            or not isinstance(item.get("evidence"), str) or not item["evidence"].strip()
        ):
            raise ConfigurationError("Inventory entries need complete and evidence")
        if not isinstance(item.get("members"), list) or any(
            not isinstance(member, str) or not member for member in item["members"]
        ):
            raise ConfigurationError("Inventory members must be login strings")


def issue_metadata(raw, overrides):
    repository, _, number = parse_item_url(raw["html_url"], "issues")
    url = raw["html_url"].rstrip("/")
    return {
        "repository": repository, "number": number, "url": url,
        "title": raw["title"], "state": raw["state"],
        "created_at": raw["created_at"], "updated_at": raw["updated_at"],
        "labels": [label["name"] for label in raw.get("labels", [])],
        "override": overrides.get("issues", {}).get(url, {}),
    }


class Collector:
    def __init__(self, api, policy, overrides=None, inventory=None):
        self.api, self.policy = api, policy
        self.overrides, self.inventory = overrides or {}, inventory or {}
        self.membership_cache, self.pr_cache = {}, {}

    def validate_scope(self, repositories, labels):
        for repository in repositories:
            validate_repository(repository)
            self.api.get(f"repos/{repository}")
            for label in labels:
                try:
                    actual = self.api.get(f"repos/{repository}/labels/{quote(label, safe='')}")
                except APIError as exc:
                    if exc.status == 404:
                        raise ConfigurationError(
                            f"Label {label!r} does not exist in {repository}"
                        ) from exc
                    raise
                if actual["name"] != label:
                    raise ConfigurationError(
                        f"Use the exact label {actual['name']!r} in {repository}"
                    )

    def issues(self, repository, labels, label_match, dates):
        params = {"state": "open", "sort": "created", "direction": "asc"}
        if labels and (label_match == "all" or len(labels) == 1):
            params["labels"] = ",".join(labels)
        if dates.lower:
            # Updated time cannot predate creation; this is only a safe prefilter.
            params["since"] = iso_time(dates.lower - timedelta(seconds=1))
        seen = set()
        for raw in self.api.pages(f"repos/{repository}/issues", params):
            if "pull_request" in raw or raw["state"] != "open":
                continue
            issue = issue_metadata(raw, self.overrides)
            selected = set(labels) & set(issue["labels"])
            labels_match = not labels or (
                len(selected) == len(set(labels)) if label_match == "all" else bool(selected)
            )
            if labels_match and dates.includes(issue) and issue["url"] not in seen:
                seen.add(issue["url"])
                yield issue

    def _membership(self, author):
        key = author.casefold()
        if key in self.membership_cache:
            return self.membership_cache[key]
        settings = self.policy["community"]
        override = {
            name.casefold(): value for name, value in self.overrides.get("authors", {}).items()
        }.get(key)
        if settings["allow_reviewed_membership_override"] and override:
            result = {
                "state": override["membership"], "source": "reviewed_override",
                "evidence": override["evidence"],
            }
        else:
            inventories = {
                name.casefold(): value
                for name, value in self.inventory.get("organizations", {}).items()
            }
            all_complete, member, sources = True, False, []
            for org in settings["microsoft_organizations"]:
                item = inventories.get(org.casefold())
                if item and key in {login.casefold() for login in item["members"]}:
                    member = True
                    sources.append(f"reviewed_inventory:{org}")
                    break
                if item and item["complete"]:
                    sources.append(f"reviewed_inventory:{org}")
                    continue
                all_complete = False
                endpoint = f"orgs/{quote(org, safe='')}/memberships/{quote(author, safe='')}"
                try:
                    membership = self.api.get(endpoint)
                    if membership.get("state") == "active":
                        member = True
                        sources.append(f"https://api.github.com/{endpoint}")
                        break
                except APIError:
                    pass
            result = {
                "state": "member" if member else "non_member" if all_complete else "unknown",
                "source": "membership_evidence", "evidence": sources,
            }
        self.membership_cache[key] = result
        return result

    def _attempt(self, record, name, operation, default=None, required=True):
        try:
            return operation()
        except APIError as exc:
            record["collection_errors" if required else "gaps"].append(f"{name}: {exc}")
            return default

    def collect(self, issue):
        record = dict(issue, prs=[], linked_issues=[], collection_errors=[], gaps=[])
        repo, number = issue["repository"], issue["number"]
        relationships = self.policy["relationships"]
        linked_urls, pr_urls = set(), set()
        if "github_issue_dependency" in relationships["accepted_issue_links"]:
            for direction in ("blocked_by", "blocking"):
                dependencies = self._attempt(
                    record, f"dependencies/{direction}",
                    lambda direction=direction: list(self.api.pages(
                        f"repos/{repo}/issues/{number}/dependencies/{direction}"
                    )), [],
                )
                linked_urls.update(item["html_url"] for item in dependencies)
        if "github_closing_relationship" in relationships["accepted_pr_links"]:
            nodes, _ = self._attempt(
                record, "closing-prs",
                lambda: self.api.connection(
                    repo, number, ISSUE_PRS, "issue", "closedByPullRequestsReferences"
                ), ([], {}),
            )
            pr_urls.update(node["url"] for node in nodes)
        if "reviewed_association" in relationships["accepted_pr_links"]:
            pr_urls.update(issue["override"].get("prs", []))
        if "reviewed_related_issue" in relationships["accepted_issue_links"]:
            linked_urls.update(issue["override"].get("related_issues", []))
        for url in sorted(pr_urls):
            pr = self._attempt(record, f"pr {url}", lambda url=url: self.pr(url))
            if pr:
                record["prs"].append(pr)
                record["collection_errors"].extend(pr["collection_errors"])
                record["gaps"].extend(pr["gaps"])
                if "shared_confirmed_closing_pr" in relationships["accepted_issue_links"]:
                    linked_urls.update(pr["closing_issues"])
            else:
                repository, _, pr_number = parse_item_url(url, "pull")
                record["prs"].append({
                    "url": url, "repository": repository, "number": pr_number,
                    "state": "unknown", "merged": False,
                })
        linked_urls.discard(issue["url"])
        for url in sorted(linked_urls):
            linked = self._attempt(record, f"linked issue {url}", lambda url=url: self.linked_issue(url))
            if linked:
                record["linked_issues"].append(linked)
        refreshed = self._attempt(
            record, "refresh issue",
            lambda: issue_metadata(
                self.api.get(f"repos/{repo}/issues/{number}", fresh=True), self.overrides
            ),
        )
        if refreshed:
            record.update(refreshed)
        return record

    def linked_issue(self, url):
        repo, _, number = parse_item_url(url, "issues")
        item = issue_metadata(self.api.get(f"repos/{repo}/issues/{number}"), self.overrides)
        return {key: item[key] for key in ("url", "labels", "override")}

    def _required_checks(self, repository, branch):
        endpoint = f"repos/{repository}/branches/{quote(branch, safe='')}"
        try:
            metadata = self.api.get(endpoint)
            rules = self.api.get(
                f"repos/{repository}/rules/branches/{quote(branch, safe='')}"
            )
            contexts = []
            for rule in rules:
                if rule["type"] == "required_status_checks":
                    contexts.extend({
                        "context": item["context"], "app_id": item.get("integration_id")
                    } for item in rule["parameters"]["required_status_checks"])
            if metadata["protected"]:
                classic = self.api.get(endpoint + "/protection").get("required_status_checks") or {}
                contexts.extend({
                    "context": item["context"], "app_id": item.get("app_id")
                } for item in classic.get("checks", []))
                contexts.extend(
                    {"context": name, "app_id": None} for name in classic.get("contexts", [])
                    if name not in {item["context"] for item in contexts}
                )
            return True, contexts
        except APIError:
            return False, []

    def _ci(self, repository, sha, branch):
        endpoint = f"repos/{repository}/commits/{sha}"
        raw_checks = list(self.api.pages(endpoint + "/check-runs", {"filter": "latest"}, "check_runs"))
        raw_statuses = list(self.api.pages(endpoint + "/statuses"))
        checks, seen = [], set()
        for check in sorted(raw_checks, key=lambda item: item["id"], reverse=True):
            key = (check.get("app", {}).get("id"), check["name"])
            if key in seen:
                continue
            seen.add(key)
            conclusion = check.get("conclusion")
            state = "unknown"
            if check.get("head_sha") == sha:
                if check["status"] != "completed":
                    state = "pending"
                elif conclusion == "success":
                    state = "success"
                elif conclusion in ("failure", "timed_out", "action_required", "startup_failure"):
                    state = "failed"
            checks.append({
                "name": check["name"], "app_id": key[0], "state": state,
                "url": check.get("html_url"),
            })
        seen_statuses = set()
        for status in sorted(raw_statuses, key=lambda item: item["id"], reverse=True):
            if status["context"] in seen_statuses:
                continue
            seen_statuses.add(status["context"])
            state = {
                "success": "success", "failure": "failed", "error": "failed", "pending": "pending"
            }.get(status["state"], "unknown")
            checks.append({
                "name": status["context"], "app_id": None,
                "state": state, "url": status.get("target_url"),
            })
        required_known, required = self._required_checks(repository, branch)
        requirements_met = required_known and all(
            any(
                check["name"] == item["context"] and check["state"] == "success"
                and (item["app_id"] in (None, -1) or item["app_id"] == check["app_id"])
                for check in checks
            )
            for item in required
        )
        states = {check["state"] for check in checks}
        state = "unknown"
        if "failed" in states:
            state = "failed"
        elif "pending" in states:
            state = "pending"
        elif states == {"success"} and requirements_met:
            state = "success"
        patterns = self.policy["low_effort"]["test_job_patterns"]
        return {
            "state": state, "head_sha": sha,
            "required_known": required_known, "required_checks": required,
            "checks": checks,
            "test_success": any(
                check["state"] == "success" and matches_patterns(check["name"], patterns)
                for check in checks
            ),
        }

    def pr(self, url, fresh=False):
        if not fresh and url in self.pr_cache:
            return copy.deepcopy(self.pr_cache[url])
        repository, _, number = parse_item_url(url, "pull")
        endpoint = f"repos/{repository}/pulls/{number}"
        raw = self.api.get(endpoint, fresh=fresh)
        for _ in range(2):
            if raw["state"] != "open" or raw.get("mergeable") is not None:
                break
            time.sleep(1)
            raw = self.api.get(endpoint, fresh=True)
        active = raw["state"] == "open" and not raw.get("merged_at")
        record = {
            "url": url, "repository": repository, "number": number,
            "state": raw["state"], "merged": bool(raw.get("merged_at")),
            "created_at": raw["created_at"], "labels": [item["name"] for item in raw["labels"]],
            "override": self.overrides.get("issues", {}).get(url, {}),
            "author": (raw.get("user") or {}).get("login"),
            "draft": raw.get("draft", False), "mergeable": raw.get("mergeable"),
            "head_sha": raw["head"]["sha"],
            "changed_files": raw["changed_files"],
            "changed_lines": raw["additions"] + raw["deletions"],
            "collection_errors": [], "gaps": [], "closing_issues": [],
        }
        nodes, metadata = self._attempt(
            record, f"{url} closing-issues",
            lambda: self.api.connection(
                repository, number, PR_ISSUES, "pullRequest", "closingIssuesReferences"
            ), ([], {}),
        )
        record["closing_issues"] = [node["url"] for node in nodes]
        record["changes_requested"] = metadata.get("reviewDecision") == "CHANGES_REQUESTED"
        if active:
            files = self._attempt(
                record, f"{url} files",
                lambda: list(self.api.pages(endpoint + "/files")), [],
            )
            record["files_complete"] = len(files) == record["changed_files"]
            if not record["files_complete"]:
                record["collection_errors"].append(f"{url}: changed-file inventory is incomplete")
            record["text_files_confirmed"] = all(isinstance(item.get("patch"), str) for item in files)
            record["tests_changed"] = any(
                item["status"] != "removed" and item["additions"] + item["deletions"] > 0
                and matches_patterns(item["filename"], self.policy["low_effort"]["test_file_patterns"])
                for item in files
            )
            record["ci"] = self._attempt(
                record, f"{url} CI",
                lambda: self._ci(repository, raw["head"]["sha"], raw["base"]["ref"]), {},
            )
            author = record["author"]
            excluded = self.policy["community"]["excluded_authors"]
            case_sensitive = self.policy["community"]["case_sensitive"]
            normalize = (lambda value: value) if case_sensitive else str.casefold
            is_excluded = author is not None and normalize(author) in {
                normalize(value) for value in excluded
            }
            if author and not is_excluded:
                record["membership"] = self._membership(author)
                state = record["membership"]["state"]
                record["community"] = {"member": False, "non_member": True}.get(state)
                if state == "unknown":
                    record["gaps"].append(f"{url}: author membership is unknown")
            else:
                record["community"] = False if is_excluded else None
                record["membership"] = {"state": "unknown", "source": "excluded_or_missing_author"}
            if record["mergeable"] is None:
                record["gaps"].append(f"{url}: mergeability is unknown")
            if not record.get("ci", {}).get("required_known"):
                record["gaps"].append(f"{url}: required CI configuration is unknown")
            if not record["text_files_confirmed"]:
                record["gaps"].append(f"{url}: binary or omitted file patches prevent text-only proof")
        self.pr_cache[url] = copy.deepcopy(record)
        return record

    def verify_selected_head(self, record, selected_url):
        if not selected_url:
            return
        selected = next(pr for pr in record["prs"] if pr["url"] == selected_url)
        repository, _, number = parse_item_url(selected_url, "pull")
        try:
            latest = self.api.get(f"repos/{repository}/pulls/{number}", fresh=True)
            if (
                latest["head"]["sha"] != selected.get("head_sha")
                or latest["state"] != selected["state"]
                or bool(latest.get("merged_at")) != selected.get("merged")
            ):
                # Do not reuse SHA-specific cached checks when a PR changes mid-run.
                self.api.cache.clear()
                replacement = self.pr(selected_url, fresh=True)
                record["prs"][record["prs"].index(selected)] = replacement
                record["collection_errors"].extend(replacement["collection_errors"])
                record["gaps"].extend(replacement["gaps"])
                check = self.api.get(f"repos/{repository}/pulls/{number}", fresh=True)
                if check["head"]["sha"] != replacement["head_sha"]:
                    record["collection_errors"].append(f"{selected_url}: PR head kept changing")
                    replacement["ci"] = {"state": "unknown"}
        except APIError as exc:
            record["collection_errors"].append(f"{selected_url} head verification: {exc}")
            selected["ci"] = {"state": "unknown"}
