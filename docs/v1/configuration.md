# Configuration reference

Both reusable workflows accept the same single optional input, `config-path`.
An empty string or omitted input selects the defaults. A nonempty value names
a committed JSON file; if that file is absent at the selected trusted commit,
validation fails.

Policy loads configuration from the PR base Git object. Drafting loads it from
the selected default-branch HEAD Git object. Neither loads configuration from
an arbitrary checked-out or uncommitted worktree.

## Complete defaults

The following JSON is a valid explicit configuration:

```json
{
  "version": 1,
  "fragment_root": ".changes",
  "guide_root": "docs/migrations",
  "state_path": ".github/migration-guides.json",
  "automation_branch": "automation/migration-guides",
  "labels": {
    "major": "semver:major",
    "minor": "semver:minor",
    "patch": "semver:patch",
    "skip": "skip-changelog",
    "feature": "enhancement",
    "fix": "bug",
    "documentation": "documentation",
    "dependencies": "dependencies"
  },
  "categories": {
    "breaking": "Breaking Changes",
    "feature": "Features",
    "fix": "Bug Fixes",
    "documentation": "Documentation",
    "dependencies": "Dependencies",
    "maintenance": "Maintenance"
  }
}
```

## Top-level fields

| Field | Type | Contract |
| --- | --- | --- |
| `version` | Integer | Required when a file is supplied; must be exactly `1`. |
| `fragment_root` | String | Directory containing retained breaking fragments. |
| `guide_root` | String | Root for generated versioned guides and indexes. |
| `state_path` | String | Automation-owned pending-guide state; must end in `.json`. |
| `automation_branch` | String | Generated PR branch; must differ from the repository default branch. |
| `labels` | Object | Partial override of the eight label names shown above. |
| `categories` | Object | Partial override of the six release-note category titles shown above. |

Except for `version`, fields are optional. Omitted fields and omitted nested
entries retain their defaults. Unknown keys at any level, unsupported schema
versions, duplicate JSON keys, and wrong value types fail validation.

`default_branch` is **not** a configuration setting. Workflows discover it from
GitHub repository metadata. Tag prefixes, release-name templates, execution
hooks, and publication settings are also not configurable.

## Path constraints

All configured paths and `config-path` are safe ASCII repository-relative paths:

- Use `/` as the separator in configuration, regardless of the local OS.
- Do not use absolute paths, drive letters, backslashes, `..` traversal, empty
  path components, or symlinks.
- Fragment and guide roots cannot be `.github` or be inside `.github`.
- Fragment, guide, state, and configuration locations cannot overlap. Keep the
  configuration file outside both roots and separate from the state file.
- The state path must name a `.json` file.

These restrictions keep configuration declarative and prevent generated output
from overwriting workflows, inputs, or unrelated repository files. A safe
example configuration location is `.github/release-automation.json`.

## Branch, label, and title constraints

Branch names use conservative ASCII letters, digits, underscores, periods,
hyphens, and slash-separated components, and must pass Git branch-name
validation. Git-invalid forms are rejected even if they use those characters.
The automation branch cannot equal the default branch.

Each label and category title contains 1–50 ASCII characters. It starts with an
alphanumeric character; the remaining characters can be alphanumeric, spaces,
colons, underscores, periods, or hyphens. Values must be distinct
case-insensitively within the resolved label set and within the resolved
category set, including defaults retained by partial overrides.

The `semver:` label namespace is reserved for the `major`, `minor`, and `patch`
settings. The literal `skip-changelog` label is reserved for the `skip` setting.
These reservations are also case-insensitive; category label overrides cannot
use them to bypass generated-PR checks.

For example, this partial override is valid:

```json
{
  "version": 1,
  "labels": {
    "major": "release:major",
    "documentation": "docs"
  },
  "categories": {
    "breaking": "Breaking changes"
  }
}
```

Create `release:major` and `docs` in the consumer repository, keep the other
default labels, and update contributor guidance. The toolkit maps these
supported overrides coherently across validation, version resolution,
generated PR labels, and release categories.

Before previewing a release, the workflow snapshots repository labels and
resolves configured names to their actual GitHub spellings, matching label
identity case-insensitively. Release Drafter receives those exact spellings
because its matcher is case-sensitive. For example, an existing
`SEMVER:MAJOR` label still selects a major bump with the default configuration.
The same resolution applies to category and exclusion labels.

The workflow rechecks relevant label spellings before preparing guides and
updating the draft. If they changed since the snapshot, it fails and asks for a
rerun. These checks do not enforce general label counts or make GitHub API
operations atomic.

## Locked rendering configuration

The toolkit owns the Release Drafter and Towncrier assets. Supported overrides
are applied to a locked Release Drafter preset and materialized as JSON, which
is valid YAML for Release Drafter. The workflow writes
`$GITHUB_WORKSPACE/release-drafter.json`, outside the separate consumer checkout,
and passes `file:/release-drafter.json`. In the pinned loader, the leading slash
means relative to `GITHUB_WORKSPACE`, **not an absolute filesystem path**.
The file is generated from the toolkit asset, not loaded as arbitrary consumer
Release Drafter configuration.

There is no consumer YAML execution, `_extends`, custom template configuration,
or hook mechanism. Do not add a consumer `.github/release-drafter.yml` expecting
the workflow to execute or merge it.

## Generated state is not configuration

The default state path is `.github/migration-guides.json`. Its bookkeeping
tracks pending versions:

```json
{
  "pending_versions": ["2.0.0"]
}
```

This is a schema example, not a file to create during installation. Let
automation generate and review state together with the guides. Pending-version
cleanup authority comes from state at the PR base; proposed state cannot
authorize its own deletions. See
[history retention](maintainer-guide.md#retain-source-and-published-history).
