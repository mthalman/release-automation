# Maintain release drafts in a consuming repository

This guide covers the human steps between a merged product change and a
reviewed draft release. For maintenance of the toolkit itself, see
[MAINTAINERS.md](../MAINTAINERS.md).

## Review incoming product changes

Check the release impact, labels, and fragment content during normal PR
review. A breaking PR must use the configured `labels.major` value (default:
`semver:major`), add a new valid breaking fragment, and cannot use the configured
`labels.skip` value (default: `skip-changelog`). Policy requires a new fragment
for PRs with the configured major label; it does not infer breaking impact from
code, replace product tests, or globally enforce the one-version-label
convention.

Resolve label roles and category titles from the trusted configuration, merging
partial overrides with defaults. Former label names have no special meaning
unless explicitly assigned to a role; unrelated labels do not count as
configured version, category, or exclusion labels. See the
[configuration reference](configuration.md#branch-label-and-title-constraints).

Keep the two workflow pins synchronized. Your repository owns its labels,
rulesets, CI triggers, approval requirements, release credentials, and
publication pipeline.

## Review the generated pull request

After a default-branch push or manual dispatch, the draft workflow resolves the
release version and generates guides and state. If those exact files are not
already committed on the selected default-branch snapshot, it opens or updates
a draft PR on `automation/migration-guides` by default.

An initial run with no breaking fragments can still open a PR for the root
guide `README.md`. That case does not create a state file; absence is expected,
and the automation omits the absent state path from its PR file allowlist.
Do not create an empty state file merely to satisfy readiness.

1. Inspect the generated topics, indexes, version directories, and state diff.
   Check that the release version and the migration instructions are correct.
2. For a newly created or updated PR, check it is draft and has the intended labels:
   the configured `labels.patch` and `labels.documentation` values
   (`semver:patch` plus `documentation` by default), with no other configured
   version or category labels and no configured `labels.skip` value.
   Unrelated labels are allowed. The workflow verifies these configured roles,
   rather than assuming a successful PR-create action established them.
3. Have a **human mark the PR ready for review**. A PR created or updated with
   `GITHUB_TOKEN` does not automatically launch normal PR workflows. Configure
   your CI to listen to `ready_for_review`, and verify that required checks ran.
4. Review and merge through your normal branch protection process.
5. Rerun the draft workflow after merge if necessary. A merge performed by
   automation using `GITHUB_TOKEN` can suppress the follow-up workflow event;
   use manual dispatch rather than bypassing readiness checks.

Every automation update resets the PR to draft, even if a human previously
marked it ready. Re-review changed output, mark it ready again, and rerun
required CI. The workflow never auto-approves, auto-merges, or automatically
marks the PR ready.

A no-change rerun can leave a PR in the ready-for-review state a human selected;
draft status is required after creation or an actual update, not after a no-op.
The workflow still checks its generated label categories.

While documentation is pending, the run fails at **Wait for merged migration
guides** without changing an existing release draft. The run ends; it does not
resume automatically when review finishes. Merge the documentation changes,
then let the merge trigger a new run or start one manually.

The new run must find the **exact** generated files and state on its selected
default-branch commit. An open or approved PR is not sufficient. Even a merged
PR may be insufficient if subsequent changes alter the expected output.

## Retain source and published history

- Keep breaking fragments forever, including after release. Do not rename
  them to tidy the directory.
- Fix unpublished migration content by changing fragments in normal PRs.
  Do not edit generated files on the automation branch.
- Retain published guides and their URLs. Submit corrections to published
  guides through normal review; preserve those reviewed corrections.
- Treat the state file as automation-owned bookkeeping, not a switch to bypass
  review or authorize arbitrary deletion.

By default, standalone topics live at
`docs/migrations/MAJOR.MINOR.PATCH/slug.md`. New topics have an H1 title, an exact
`**Version introduced:** MAJOR.MINOR.PATCH` line matching their directory, and
the same six sections as fragments, promoted to H2. The version metadata must
appear exactly once as that canonical line, outside code fences and HTML
comments. Fenced or commented examples cannot substitute for the real metadata;
duplicate or conflicting metadata lines outside examples and comments are
rejected.

Topics use the same [supported Markdown format](author-guide.md#use-the-supported-markdown-format)
as fragments. Convert unsupported formatting in retained topics before
adopting this validator; do not remove published history to bypass validation.

Root and per-version `README.md` indexes are exempt from the topic section
schema. Existing legacy guides with a **Breaking changes and migration**
wrapper remain accepted; new output uses standalone topics.

The state file tracks pending version directories. Deletion or rename of a
guide is authorized only when its version was pending in state at the **PR
base**, not merely added to state in the proposed PR.

When an unpublished version changes, automation can clean up obsolete pending
output. It must keep pending versions linked from **any release body**, not
just the currently selected release, and retain published history. Do not
manually delete a version directory to resolve a draft conflict.

## Inspect the final draft before publishing

Once generated documentation and state match the selected branch exactly, the
workflow rechecks releases, the remote default-branch commit, and readiness
before creating or patching a draft release. It does not create a tag or
publish the release.

These API checks are **not atomic with human actions**. Another maintainer can
publish or change a release between requests. Before publication, independently
recheck the final draft, intended tag and target commit, release notes, migration
links, CI, artifacts, and required approvals.

The toolkit's pre-draft readiness is not your publication gate. Keep publication
credentials and product-specific gates in your own release process.

## Troubleshoot a run

| Symptom | What to check |
| --- | --- |
| Workflow ref cannot be resolved | Replace the installation placeholder with a reachable reviewed full wrapper SHA in both callers. |
| Configuration not found | Commit it at the policy base or selected draft HEAD. An uncommitted worktree file does not count. |
| Major PR fails after editing a note | Add a new fragment; editing an older one cannot document a new major change. |
| Run fails at **Report a blocked documentation pull request** | Check token job permissions, repository Actions policy, and the create-and-approve-PR setting. |
| Generated PR has no product CI | Have a human mark it ready and ensure CI listens to `ready_for_review`. |
| Run fails at **Wait for merged migration guides** | Merge the exact generated files and state, then start a new run. The previous run does not resume. |
| Run reports a changed remote commit or release | Let current work settle and rerun from the latest default-branch snapshot; do not bypass checks. |
| No draft run after guide merge | Manually dispatch; bot-token event suppression can prevent a follow-up run. |
| Version or category is unexpected | Review resolved label roles and category titles, merged PR labels, configured skip pre-exclusion, highest conflicting bump, and patch fallback. |
| Guide deletion is rejected | Check pending state at PR base and all release-body references; do not forge state in the PR. |

For local reproduction, use the [read-only commands](local-development.md).
Include the workflow pin, selected commit, non-sensitive configuration, and
the failing step when reporting an issue.
