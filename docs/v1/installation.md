# Install the workflows

This guide installs migration policy checks and draft generation in one
github.com repository. You need permission to configure GitHub Actions, create
labels, and edit workflows.

The repository must use one stable release stream with `vMAJOR.MINOR.PATCH`
tags on its actual default branch. Existing stable release history must be
available in Git. The toolkit does not convert existing product release
pipelines or create a first published release for you.

## 1. Select a reviewed commit

Choose a reviewed, reachable, full commit SHA from
`mthalman/release-automation` and use it in **both** callers below.
`REPLACE_WITH_REVIEWED_COMMIT_SHA` is an installation placeholder before the
initial implementation merge, not a real ref. Do not paste the examples
unchanged and expect Actions to resolve them.

The selected wrapper commit already pins its toolkit payload. You do not supply
a second tooling ref. Keep both caller refs synchronized on future upgrades.

## 2. Enable repository permissions

In **Settings → Actions → General**, allow the reusable workflows and their
pinned actions under your repository or organization policy. Enable **Allow
GitHub Actions to create and approve pull requests**.

That setting permits PR creation; this toolkit does **not** approve PRs.
The draft caller grants `contents: write` and `pull-requests: write`. The policy
caller needs only `contents: read`. Both use the repository's automatic
`GITHUB_TOKEN`; no external secret, personal access token, or `secrets: inherit`
is required.

## 3. Create the canonical labels

Create these labels in the consuming repository through GitHub's Labels page
or your normal label-management process:

| Label | Purpose |
| --- | --- |
| `semver:major` | Breaking change; requires a new breaking fragment |
| `semver:minor` | Backward-compatible feature bump |
| `semver:patch` | Patch bump |
| `skip-changelog` | Exclude a non-breaking PR from release notes |
| `enhancement` | Features category |
| `bug` | Bug Fixes category |
| `documentation` | Documentation category |
| `dependencies` | Dependencies category |

Colors and descriptions are your choice. There are no `type:*` aliases. If
you override label names, create the configured names instead and share them
with contributors. See the [author guide](author-guide.md#choose-labels).

## 4. Add the policy caller

Save this as `.github/workflows/migration-policy.yml` in the consuming
repository, replacing the ref:

```yaml
name: Migration policy

on:
  pull_request_target:
    types: [opened, reopened, synchronize, labeled, unlabeled, ready_for_review]

permissions:
  contents: read

jobs:
  migration-policy:
    uses: mthalman/release-automation/.github/workflows/migration-policy.yml@REPLACE_WITH_REVIEWED_COMMIT_SHA
```

Keep `pull_request_target` and its event types. Do not add PR checkout, PR code
execution, or dependency installation to this privileged event. The reusable
workflow reads proposed files as data with trusted base-commit configuration.

The example intentionally has no branch filter. If you add one, use the
repository's actual default branch, not an assumed `main`, and account for
which pull requests should receive a required check.

## 5. Add the draft caller

Save this as `.github/workflows/release-draft.yml`. Replace both the ref and
`main` if your repository's default branch has another name:

```yaml
name: Release draft

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  release-draft:
    uses: mthalman/release-automation/.github/workflows/release-draft.yml@REPLACE_WITH_REVIEWED_COMMIT_SHA
```

Do not add the reusable workflow's concurrency group to this caller. The callee
serializes the entire draft pipeline with cancellation disabled; duplicating
the group can cause caller/callee contention.

Even on manual dispatch, the workflow selects the latest repository
default-branch snapshot, not an arbitrary dispatch branch.

## 6. Optionally commit configuration

Omit `with` to use all defaults. To customize supported settings, commit a JSON
file outside the fragment, guide, and state paths, then add this to each job:

```yaml
    with:
      config-path: .github/release-automation.json
```

A minimal configuration file is:

```json
{
  "version": 1
}
```

When `config-path` is supplied, the file must exist at the trusted commit.
Policy reads it at the PR base; drafting reads it at the selected default-branch
HEAD. Land the configuration before expecting it to govern a PR check. See
the [configuration reference](configuration.md) for the full schema.

## 7. Verify the deployment

Merge the caller workflows through your normal review process, then open a
test PR and exercise label and fragment validation. In particular, verify that
`semver:major` without a new valid breaking fragment fails.

The caller job ID is `migration-policy`; the reusable job is named
**Validate migration notes**. GitHub exposes a nested check name. **Discover its
actual name after the first deployed run** before selecting it as a required
check in your ruleset. Do not guess the nested name from these examples.
The toolkit never changes rulesets automatically.

Run the draft workflow and inspect its result. When new guides are needed, it
should create a draft documentation PR and leave release drafting waiting until
the exact generated files and state are merged.

A PR created with `GITHUB_TOKEN` does not automatically trigger your normal PR
CI. A **human must mark it ready for review** to generate a
`ready_for_review` event. Ensure your product CI listens to that event.
Automation updates return the PR to draft, so repeat the human readiness step
after updates. See [reviewing generated changes](maintainer-guide.md#review-the-generated-pull-request).

Installation is verified only after you observe policy validation, the human
review/CI path, and a successful post-merge draft run in your own repository.
The examples alone are not evidence of live workflow validation.
