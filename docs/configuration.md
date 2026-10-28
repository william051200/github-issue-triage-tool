# Configuration

## Defaults

`defaults.yml` contains local repositories, labels, label matching, state, date bounds, and output directory. It is ignored by Git. Copy `defaults.example.yml` to create it; the script uses the example directly when the local file is absent.

```yaml
schema_version: 1

repositories:
  - Azure/azure-cli
  - Azure/azure-cli-extensions
labels:
  - Compute
label_match: all
state: open
date_range:
  field: created
  from: null
  to: null
output_dir: output
```

| Setting | Accepted values |
|---|---|
| `schema_version` | `1` |
| `repositories` | Nonempty list of `owner/repository` names |
| `labels` | Exact label names; `[]` disables label filtering |
| `label_match` | `all`: every label required; `any`: at least one required |
| `state` | `open` |
| `date_range.field` | `created` or `updated` |
| `date_range.from` | Inclusive date/time, or `null` for no lower bound |
| `date_range.to` | Inclusive UTC calendar date or exclusive timestamp, or `null` for no upper bound |
| `output_dir` | Nonempty directory path, relative to the working directory or absolute |

With labels `Compute` and `bug`, `all` requires both; `any` accepts either. With one label, both behave the same.

Quote date/time values in YAML, for example `"2026-01-01"` or `"2026-10-28T15:00:00+08:00"`. Timestamps require a timezone. See [date boundaries](python.md#dates).

## Precedence

CLI flags override config values. Repository and label lists replace configured lists.

`--config path` selects an explicit file. Otherwise, load `defaults.yml` from the skill folder, falling back to `defaults.example.yml` only when the local file is absent. Invalid local or explicitly selected files fail validation.

## Policy files

- `priority-rules.yml`: priority labels, trusted security labels, community identities, age thresholds, file/test limits, and priority rules.
- `verdict-rules.yml`: action verdicts, decision order, and missing-information labels.

These files remain shareable. Edit thresholds, label mappings, or verdict precedence without changing Python. Conditions use supported facts and `all`/`any`; duplicate keys, unknown facts, and unsupported structural changes fail validation.

See [policy](policy.md) for rule meaning and [Python usage](python.md) for alternative file flags.

## Reviewed overrides

Keep local evidence private. `overrides.local.yml` accepts:

```yaml
issues:
  "https://github.com/owner/repository/issues/123":
    evidence: "Maintainer review reference"
    priority: P1
    needs_information: true
    prs:
      - "https://github.com/owner/repository/pull/456"
    related_issues:
      - "https://github.com/owner/repository/issues/789"
authors:
  example-login:
    membership: non_member
    evidence: "Authorized membership review reference"
```

Issue overrides also accept `security_fix: true`. PR URLs may be keys in `issues` for priority/security evidence. Author states are `member`, `non_member`, and `unknown`. Each decision needs an evidence reference.

## Membership inventory

Public membership absence or an ambiguous 404 does not establish non-membership. GitHub can confirm positive membership; negative evidence requires a reviewed override or complete, authorized inventory.

An optional `membership.local.yml` uses:

```yaml
organizations:
  microsoft:
    complete: true
    evidence: "Authorized full active-membership export reference"
    members:
      - example-member
  Azure:
    complete: true
    evidence: "Authorized full active-membership export reference"
    members:
      - another-member
```

Use `complete: true` only for an authorized full active-member list, never a public-members-only export. Absence establishes `non_member` only when every configured organization has complete negative evidence. Do not infer membership from names, email, profiles, or comment badges.

Unknown membership does not match community rules. Other priority rules still apply. Inventories are not copied into exports; audits retain the decision and minimum source evidence.
