# Install the workflows

This guide installs migration policy checks and draft generation in one
GitHub repository.

Before you begin, confirm that you can configure GitHub Actions, create labels,
edit workflows, and merge changes through the repository's review process.

The repository must use one stable release stream with `vMAJOR.MINOR.PATCH`
tags on its actual default branch. Existing stable release history must be
available in Git. The toolkit does not convert existing product release
pipelines. These two workflows produce drafts, including for an initial release;
publication is a separate, optional installation.

## 1. Select a reviewed commit

Choose a reviewed, published stable release of `mthalman/release-automation`.
Use its exact full commit SHA in **both** callers below and its matching
`vMAJOR.MINOR.PATCH` tag in each trailing comment. Follow
[release verification](upgrading.md#select-and-verify-a-release) first.
`REPLACE_WITH_REVIEWED_COMMIT_SHA` and `vMAJOR.MINOR.PATCH` are placeholders,
not a real ref or tag. Replace both before committing the examples.

The selected wrapper commit already pins its toolkit payload. You do not supply
a second tooling ref. Keep both caller refs and any optional publication Action
refs and tag comments synchronized on future upgrades. The comment does not
replace immutable pinning; it identifies the reviewed release. Dependabot can
update SHA-pinned references even without that comment.
If required changes are not yet released, follow the
[unreleased-commit exception](upgrading.md#use-an-unreleased-commit-only-as-an-explicit-exception)
instead of attaching an older or future tag to a different SHA.

## 2. Enable repository permissions

In **Settings → Actions → General**, allow the reusable workflows and their
pinned actions under your repository or organization policy. Enable **Allow
GitHub Actions to create and approve pull requests**.

That setting permits PR creation; this toolkit does **not** approve PRs.
The draft caller grants `contents: write` and `pull-requests: write`. The policy
caller needs only `contents: read`. Both use the repository's automatic
`GITHUB_TOKEN`; no external secret, personal access token, or `secrets: inherit`
is required.

## 3. Create configured labels

Create the resolved label names in the consuming repository through GitHub's
Labels page or your normal label-management process. Without overrides, use
these defaults:

| Configured role | Default label | Purpose |
| --- | --- | --- |
| `labels.major` | `semver:major` | Breaking change; requires a new breaking fragment |
| `labels.minor` | `semver:minor` | Backward-compatible feature bump |
| `labels.patch` | `semver:patch` | Patch bump |
| `labels.skip` | `skip-changelog` | Exclude a non-breaking PR from release notes |
| `labels.feature` | `enhancement` | Feature category (default title: Features) |
| `labels.fix` | `bug` | Fix category (default title: Bug Fixes) |
| `labels.documentation` | `documentation` | Documentation category (default title: Documentation) |
| `labels.dependencies` | `dependencies` | Dependencies category (default title: Dependencies) |

Colors and descriptions are your choice. If you override label names, create
the configured names instead and share them with contributors. Overrides merge
with defaults; all eight resolved label names must remain distinct
case-insensitively. Former names have no special meaning unless assigned to a
role. Category titles can also be overridden through `categories`. See the
[author guide](author-guide.md#choose-labels).

## 4. Add the policy caller

Save this as `.github/workflows/migration-policy.yml` in the consuming
repository, replacing the ref and tag comment:

```yaml
name: Migration policy

on:
  pull_request_target:
    types: [opened, reopened, synchronize, labeled, unlabeled, ready_for_review]

permissions:
  contents: read

jobs:
  migration-policy:
    uses: mthalman/release-automation/.github/workflows/migration-policy.yml@REPLACE_WITH_REVIEWED_COMMIT_SHA # vMAJOR.MINOR.PATCH
```

Keep `pull_request_target` and its event types. Do not add PR checkout, PR code
execution, or dependency installation to this privileged event. The reusable
workflow reads proposed files as data with trusted base-commit configuration.

The example intentionally has no branch filter. If you add one, use the
repository's actual default branch, not an assumed `main`, and account for
which pull requests should receive a required check.

## 5. Add the draft caller

Save this as `.github/workflows/release-draft.yml`. Replace the ref and tag
comment with your verified SHA/tag pair. If your default branch is not named
`main`, also replace `main` with its actual name:

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
    uses: mthalman/release-automation/.github/workflows/release-draft.yml@REPLACE_WITH_REVIEWED_COMMIT_SHA # vMAJOR.MINOR.PATCH
```

Do not add the reusable workflow's concurrency group to this caller. The callee
serializes the entire draft pipeline with `group: release-drafter`,
`cancel-in-progress: false`, and `queue: max`; duplicating the group can cause
caller/callee contention.

Even on manual dispatch, the workflow selects the latest repository
default-branch snapshot, not an arbitrary dispatch branch.

## 6. Optionally commit configuration

Omit `with` to use all defaults. To customize supported settings, first merge a
JSON configuration file outside the fragment, guide, and state paths. Then add
this input to each caller job:

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
HEAD. Adding the file only in the PR being checked cannot supply base
configuration. Likewise, a proposed configuration change takes effect for
policy checks only after it is merged into their base. See
the [configuration reference](configuration.md) for the full schema.

## 7. Verify the deployment

Merge the caller workflows through your normal review process, then open a
test PR and exercise label and fragment validation. In particular, verify that
the configured `labels.major` value (default: `semver:major`) without a new
valid breaking fragment fails, and that combining it with the configured
`labels.skip` value fails.

The caller job ID is `migration-policy`; the reusable job is named
**Validate migration notes**. GitHub exposes a nested check name. **Discover its
actual name after the first deployed run** before selecting it as a required
check in your ruleset. Do not guess the nested name from these examples.
The toolkit never changes rulesets automatically.

Run the draft workflow and inspect its result. When new guides are needed, it
should create a draft documentation PR, then fail at **Wait for merged migration
guides** without changing an existing release draft. This expected failure ends
the run; it does not pause a runner until review finishes.

A PR created with `GITHUB_TOKEN` does not automatically trigger your normal PR
CI. A **human must mark it ready for review** to generate a
`ready_for_review` event. Ensure your product CI listens to that event.
Automation updates return the PR to draft, so repeat the human readiness step
after updates. Once the exact generated files and state are merged, start a new
draft run if the merge does not trigger one. See
[reviewing generated changes](maintainer-guide.md#review-the-generated-pull-request).

Installation is verified only after you observe policy validation, the human
review/CI path, and a successful post-merge draft run in your own repository.
The examples alone are not evidence of live workflow validation.

## 8. Optionally install tag publishing

Follow [tag publishing](tag-publishing.md) to add a separate tag-push workflow.
It calls `actions/prepare-release`, runs your arbitrary `uses` and `run` steps,
then calls `actions/finalize-release` only after those steps succeed. Pin both
Actions to the same reviewed full SHA as the reusable workflows, with the same
matching stable-tag comments.

Set `group: release-drafter`, `cancel-in-progress: false`, and `queue: max`
on your tag workflow. The reusable draft workflow at this revision already
uses those settings. When upgrading, update your toolkit pins and your tag
workflow together. Do not add a concurrency group to the drafting caller
from step 5.

Both workflows must use `queue: max`; otherwise a new draft run can replace
a pending publication run. GitHub allows up to 100 pending runs in the group
and cancels additional runs when the queue is full. See the
[concurrency contract](workflows.md#release-draft-sequence).

Grant `contents: write` at the publication job, not workflow-wide, and keep
product credentials and approvals in your repository. Verify that prepare's
token can see draft releases. GitHub can also require workflow-modification
authorization to publish an older target after workflow files change on the
default branch; `GITHUB_TOKEN` cannot receive that authorization. See
[publication credential requirements](tag-publishing.md#choose-credentials-and-verify-draft-visibility)
before relying on the default token.

After installing or upgrading, run drafting successfully to refresh preparation
metadata before a human pushes a release tag. Old drafts without that metadata
cannot be published through the Actions, including on first adoption. A tag push
made with `GITHUB_TOKEN` normally does not trigger another push workflow; use a
human push or your own reviewed event-producing credentials outside the toolkit.
Installing files does not establish
that settings, permissions, or live end-to-end publication have been verified;
exercise the tag workflow separately in a test repository.
