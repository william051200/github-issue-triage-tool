# Triage policy

Priority controls queue order. Verdict identifies the next action. P0 can represent a security fix or a convenient community merge; it does not always mean critical severity.

## Priority

| Priority | Any matching condition |
|---|---|
| P0 | Security fix; accepted link to P0 issue; low-effort eligible community PR. |
| P1 | Accepted link to P1 issue; eligible unprioritized PR older than 14 days; eligible community PR. |
| P2 | No higher rule matched. |

Evaluate every rule and keep all matched IDs. Highest priority wins. Preserve an issue's explicit P0/P1 as a floor. A lower label does not prevent escalation. Conflicting labels use the highest priority and produce a warning.

Explicit priority comes from configured labels or reviewed overrides, not titles, comments, or milestones. Unmapped priority-like labels block the unprioritized-age shortcut and request mapping review.

Security requires configured trusted labels or a reviewed security override on the issue or an eligible PR. Keywords alone do not assign P0. Use the repository's private reporting process for sensitive findings.

## Relationships

Accept direct issue dependencies, other issues closed by the same confirmed PR, and reviewed related-issue links. Read linked priority from explicit labels or reviewed overrides. Do not recursively propagate derived priorities.

Related issues may be closed or outside collection scope. Fetch their direct metadata only. Plain URL mentions and cross-references do not establish priority links.

Eligible PRs are open, unmerged, and confirmed to close the issue or explicitly associated by review. Historical PRs remain in the export but do not trigger active age/community rules. Drafts can match age/community rules, but not the shipped low-effort rule.

## Community

A community PR author must not match an excluded Copilot identity and must be verified outside all configured Microsoft organizations. Evaluate the PR author, not the issue reporter.

Configured organizations are an operational membership proxy, not an employment claim. Membership states and evidence requirements are in [configuration](configuration.md).

## Low-effort merge

Shipped limits: at most 5 files and 100 added plus deleted lines. Count all files. Require:

- Complete file inventory, no binary or omitted patches, and an added/modified test file.
- Successful current-head test evidence and all required checks successful.
- No failed, pending, cancelled, indeterminate, or stale-head checks.
- Non-draft status and confirmed mergeability without conflicts.

Unknown required-check configuration, skipped required tests, or unknown mergeability prevents this rule. Test-file and test-job patterns are configurable.

These checks identify a `merge-candidate`; maintainer review still decides whether to merge.

## Age

PR age must be strictly greater than 14 days at the run's UTC snapshot. Exactly 14 days does not match; updates do not reset age.

Neither the issue nor the eligible PR may have an explicit priority or priority override. Unknown priority-like labels require review. Issue age alone never triggers this rule.

## Verdict

Use the first matching rule in `verdict-rules.yml`. Preserve secondary actions in the audit.

| Verdict | Action |
|---|---|
| `security-review` | Route the fix through the security process. |
| `data-incomplete` | Restore required access or retry collection. |
| `ci-fix-needed` | Repair failed current-head CI. |
| `awaiting-ci` | Wait for running/pending CI, then refresh. |
| `pr-update-needed` | Address draft status, conflicts, or requested changes. |
| `verify-release` | Confirm a merged fix is released and resolves the issue. |
| `merge-candidate` | Review the low-effort community fix for merging. |
| `review-overdue` | Prioritize and review the old unprioritized PR. |
| `review-community-pr` | Review the contribution and give feedback. |
| `linked-priority-review` | Review the dependency or shared fix with its owner. |
| `needs-information` | Request the specific missing evidence. |
| `triage-needed` | Diagnose the issue and confirm ownership. |

Select one active PR by highest matched priority, then merge readiness, creation time, repository, and PR number. Evaluate blockers for that PR, not unrelated failed PRs.

A known security fix retains `security-review` during partial collection. Membership/mergeability unknowns alone are evidence gaps, not collection failures. Explicit priority alone does not establish an action. A merged fix gets `verify-release` only when no active replacement PR exists.
