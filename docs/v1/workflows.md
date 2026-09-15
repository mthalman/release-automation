# Reusable workflow contract

This reference describes v1's two entrypoints and their trust boundaries.
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
[payload retention](../../MAINTAINERS.md#update-the-immutable-payload-pins);
the initial setup does not create separate retention branches or tags.

External action dependencies are also SHA-pinned. The supported baseline uses
Release Drafter v7.7, create-pull-request v8.1.1, Python 3.13, and Towncrier
26.9.0. See the [pinning procedure](../../MAINTAINERS.md#update-the-immutable-payload-pins).

For self-dogfooding, this toolkit repository calls its reusable workflows using
`./.github/workflows/migration-policy.yml` and
`./.github/workflows/release-draft.yml`. GitHub resolves each local workflow at
the caller's commit, while its wrapper still uses literal payload P. This
same-repository arrangement does not change the external consumer pinning
contract. Activation and live verification require merge and repository setup;
see [self-dogfooding setup](../../MAINTAINERS.md#enable-self-dogfooding).

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
Major and exclusion label comparisons are case-insensitive. A breaking PR
cannot use either the configured exclusion label or canonical
`skip-changelog`, even when the configured exclusion label has another name.

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
2. **Resolve the draft once.** Run Release Drafter v7.7 in dry-run mode using
   the materialized locked preset. Resolve a single version and previous
   release tag, then carry that result through generation and draft mutation.
   Do not independently calculate a second version later.
   The preview's previous-tag marker must be empty for an initial release or
   contain exactly a stable `vMAJOR.MINOR.PATCH` tag. Prerelease suffixes, build
   metadata, and other refs are rejected.
3. **Generate migration content.** Render retained breaking fragments using
   toolkit-owned Towncrier assets. Produce standalone topics, indexes, and
   pending-version state. Preserve published guides and reviewed corrections;
   keep pending versions linked from all release bodies.
   On an initial run with no fragments, generation still creates the root guide
   `README.md` but does not create a state file. The PR file allowlist omits an
   absent state path.
4. **Create or update the review PR.** Use create-pull-request v8.1.1 on the
   configured automation branch, with draft always true. Updates reset it to
   draft. Use the configured patch and documentation labels, without
   `skip-changelog`.
5. **Verify review metadata.** Whenever the action returns a documentation PR
   number, recheck its exact intended generated label categories. Require
   draft status after PR creation or an actual update. A no-op rerun can
   preserve a human-selected ready-for-review state, but it does not skip label
   validation. Do not trust action success alone or silently accept conflicting
   generated PR labels.
6. **Wait for committed readiness.** If the selected branch does not contain
   the exact generated docs and state, report waiting/failure and stop before
   any draft-release write. Leave an existing draft unchanged. Human review and
   merge are required; a matching file only on the automation branch is not
   ready.
7. **Recheck mutable state.** Re-read releases, the remote selected-branch
   commit, and readiness. Stop if assumptions changed.
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

The preset pre-excludes `skip-changelog`, places major-labeled changes in the
unified Breaking Changes category, then uses the exclusive Features, Bug
Fixes, Documentation, and Dependencies categories before Maintenance.
Dependencies collapse after five entries. Labels and titles can use supported
declarative overrides.

Release Drafter retains highest-bump resolution for conflicting semantic labels
and patch fallback when no stronger bump applies. Exactly one semantic label
and at most one category are contributor conventions, not universal policy
validation. See [author labels](author-guide.md#choose-labels).

## Human and publication boundaries

`GITHUB_TOKEN`-created PRs do not automatically trigger ordinary PR CI. A human
must mark the generated PR ready for review, and consumer CI must subscribe to
`ready_for_review`. Automation updates return the PR to draft. The toolkit
never auto-approves, auto-merges, or publishes.

The final API rechecks are not transactional with human publication. A human
can change a release between requests. The consumer must recheck the final
draft before publishing and retain independent product CI, credentials, and
release gates. Pre-draft readiness is not a publication gate.
