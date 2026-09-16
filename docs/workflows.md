# Reusable workflow contract

This reference describes the two reusable entrypoints and their trust boundaries.
For copyable callers, see [installation](installation.md).

## Entrypoints and inputs

| Entrypoint | Caller trigger | Required caller permissions |
| --- | --- | --- |
| `.github/workflows/migration-policy.yml` | `pull_request_target` | `contents: read` |
| `.github/workflows/release-draft.yml` | Push to actual default branch; `workflow_dispatch` | `contents: write`, `pull-requests: write` |

Both expose **only** `config-path`: an optional string whose default is empty.
Empty means built-in defaults; nonempty means a JSON file that must exist at
the trusted commit. See [configuration](configuration.md).

Both use `secrets.GITHUB_TOKEN` supplied by GitHub. No external secret is
required. Neither entrypoint accepts a second tooling ref, a publication token,
a default-branch override, arbitrary execution hooks, or custom templates.

## Immutable toolkit identity

A consumer pins one reviewed wrapper commit **W** in each caller's `uses`.
Both wrappers contain a literal full commit SHA **P** identifying their
trusted payload. P is committed and made reachable before W is created.
The workflow does not dynamically infer a second source ref from the caller.

Toolkit PRs introducing payload pins preserve P as an ancestor of W by using a
merge commit rather than squash or rebase. CI compares the pinned toolkit tree
with the proposed files and runs an archive of P from full history. See
[payload retention](../MAINTAINERS.md#update-the-immutable-payload-pins);
separate retention branches or tags require an explicit maintenance decision.

External action dependencies are also SHA-pinned. The
[workflow definitions](../.github/workflows) and
[dependency lock](../toolkit/requirements.txt) identify the runtime and
dependency versions for each toolkit commit. See the
[pinning procedure](../MAINTAINERS.md#update-the-immutable-payload-pins).

For self-dogfooding, this toolkit repository calls its reusable workflows using
`./.github/workflows/migration-policy.yml` and
`./.github/workflows/release-draft.yml`. GitHub resolves each local workflow at
the caller's commit, while its wrapper still uses literal payload P. This
same-repository arrangement does not change the external consumer pinning
contract. Activation and live verification require deployment and repository setup;
see [self-dogfooding setup](../MAINTAINERS.md#enable-self-dogfooding).

## Migration policy

The caller listens for `opened`, `reopened`, `synchronize`, `labeled`,
`unlabeled`, and `ready_for_review` under `pull_request_target`.

Policy evaluates proposed file contents as data. Its trusted executable is an
immutable, standard-library-only validator from P. It does not execute PR
Python, PR workflows, consumer templates, or PR dependency installation.
The workflow fetches `refs/pull/<number>/head` as Git data and requires
`FETCH_HEAD` to match the event's head SHA exactly. It never checks out that
head. If the PR head has changed since the event, the stale run fails rather
than validating a different revision.

Configuration and pending-state deletion authority come from the exact PR
base Git objects. A PR cannot weaken its own checks by changing its proposed
configuration or mark a published guide pending to authorize its deletion.

The validator checks fragment naming and section content, new-fragment
requirements for major PRs, the major/skip conflict, guide structure, and
retention rules. These checks do not enforce every label convention or replace
consumer product tests.

Fragment and topic validation supports a constrained Markdown format: raw HTML
outside code examples is rejected, and ordinary comments cannot supply required
headings or content. Inline code is restricted to a single source line;
multiline examples require fenced code blocks. This keeps the trusted validator
standard-library-only; it is not a general-purpose CommonMark or HTML renderer.

Major and exclusion label comparisons are case-insensitive and use only
resolved `labels.major` and `labels.skip` (defaults: `semver:major` and
`skip-changelog`). A PR with the configured major label must add a new valid
breaking fragment and cannot use the configured skip label. Policy does not
infer breaking impact from code.

The installation caller job ID is `migration-policy`; the callee job name is
**Validate migration notes**. Discover GitHub's actual nested check name after
deployment before adding it to a ruleset. The toolkit does not manage rulesets.

## Release draft sequence

One concurrency group, `release-drafter`, serializes the **entire** pipeline
with `cancel-in-progress: false`. Keep this group in the reusable workflow,
not duplicated in the caller.

The run follows this order:

1. **Select the source snapshot.** Read the repository's default branch from
   GitHub metadata, select its latest commit, and fetch full history. Use that
   exact commit for configuration and generation, even on manual dispatch.
2. **Resolve the draft once.** Run the pinned Release Drafter in dry-run mode using
   the materialized locked preset. Snapshot repository labels first and map
   configured names to their actual spellings for the case-sensitive matcher.
   The preset lives at the workspace root, outside the consumer checkout, and
   is loaded as `file:/release-drafter.json`. Resolve a single version and previous
   release tag, then carry that result through generation and draft mutation.
   Do not independently calculate a second version later.
   The preview's previous-tag marker must be empty for an initial release or
   contain exactly a stable `vMAJOR.MINOR.PATCH` tag. Prerelease suffixes, build
   metadata, and other refs are rejected.
3. **Generate migration content.** Render retained breaking fragments using
   toolkit-owned Towncrier assets after rechecking label spellings against the
   snapshot. Produce standalone topics, indexes, and
   pending-version state. Preserve published guides and reviewed corrections;
   keep pending versions linked from all release bodies.
   On an initial run with no fragments, generation still creates the root guide
   `README.md` but does not create a state file. The PR file allowlist omits an
   absent state path.
4. **Create or update the review PR.** Use the pinned create-pull-request on the
   configured automation branch, with draft always true. Updates reset it to
   draft. Use the configured patch and documentation labels, without the
   configured skip label. If that action fails, for example because the
   repository forbids GitHub Actions from creating pull requests, the step named
   **Report a blocked documentation pull request** ends the run with the
   required setting and permission named. No draft release is written.
5. **Verify review metadata.** Whenever the action returns a documentation PR
   number, require exactly the configured patch and documentation labels among
   configured version and category labels, and no configured skip label.
   Unrelated labels are allowed. Require draft status after PR creation or an
   actual update. A no-op rerun can preserve a human-selected ready-for-review
   state, but it does not skip label validation. Do not trust action success
   alone or silently accept conflicting generated PR labels.
6. **Require committed files.** If the selected default-branch commit does not
   contain the exact generated files and state, fail the run before any
   draft-release write. Leave an existing draft unchanged. The step named
   **Wait for merged migration guides** ends the run; it does not suspend it.
   Human review, merge, and a new run are required. Matching files only on the
   automation branch are not sufficient.
7. **Recheck mutable state.** Re-read releases, the remote selected-branch
   commit, relevant label spellings, and readiness. Stop if assumptions changed.
8. **Write only a draft.** Only after those checks, POST a new draft release or
   PATCH the existing draft. Do not publish, create tags, merge a PR, or run
   consumer publication.

A subsequent run after guide merge can pass readiness without needing another
documentation change. If bot-token event suppression prevents that run, a human
can dispatch it manually.

## Versioning and categorization

Stable tags use exactly `vMAJOR.MINOR.PATCH`. Release names use the version
alone. One repository default branch and one stable release stream are
supported; prerelease streams, arbitrary prefixes, monorepo version sets, and
hosts other than github.com are not.

Resolved configuration determines every label role and category title. The
preset pre-excludes `labels.skip` (default: `skip-changelog`) and places
`labels.major` changes in `categories.breaking` (default: **Breaking Changes**).
It then uses the exclusive `feature`, `fix`, `documentation`, and `dependencies`
categories before the `maintenance` fallback. Their default titles are
**Features**, **Bug Fixes**, **Documentation**, **Dependencies**, and
**Maintenance**. The dependencies category collapses after five entries.

No label names or namespaces are reserved. Former default names have no special
meaning after an override unless explicitly assigned to a role. Unrelated
labels do not count as configured version, category, or exclusion labels.
All eight resolved label identities must remain distinct case-insensitively
and satisfy the [configuration constraints](configuration.md#branch-label-and-title-constraints).

Release Drafter retains highest-bump resolution for conflicting configured
version labels and patch fallback when no stronger bump applies. Exactly one
configured version label and at most one configured category label are
contributor conventions, not universal policy validation. See
[author labels](author-guide.md#choose-labels).

## Human and publication boundaries

`GITHUB_TOKEN`-created PRs do not automatically trigger ordinary PR CI. A human
must mark the generated PR ready for review, and consumer CI must subscribe to
`ready_for_review`. Automation updates return the PR to draft. The toolkit
never auto-approves, auto-merges, or publishes.

The final API rechecks are not transactional with human publication. A human
can change a release between requests. The consumer must recheck the final
draft before publishing and retain independent product CI, credentials, and
release gates. Pre-draft readiness is not a publication gate.
