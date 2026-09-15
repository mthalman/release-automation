# Toolkit maintenance

This document is for maintainers of `mthalman/release-automation`. Maintainers
of repositories that consume it should use the
[consumer maintainer guide](docs/v1/maintainer-guide.md).

## Review responsibilities

Keep the workflow interface small and the payload immutable. Review changes to
trusted Git-object access, path validation, dependency installation, release
API calls, and workflow permissions as changes to the trust boundary.

Before accepting a change:

- Confirm both entrypoints still expose only optional `config-path`.
- Run unit tests with Python 3.13 and pinned dependencies; run `actionlint` for
  workflow edits.
- Check default-branch discovery, stable-tag restrictions, label mapping, and
  configuration rejection cases. Every label role must come from resolved
  configuration, with no reserved names or namespaces. Check that partial
  overrides preserve case-insensitive distinctness across all eight labels.
- Verify policy uses base configuration and state without executing PR code.
- Verify draft mutation follows exact committed-document/state readiness and
  fresh remote/release checks. No waiting path may rewrite an existing draft.
- Preserve fragment and published-guide retention, including reviewed
  corrections and references from all release bodies.
- Update versioned docs and identify any compatibility changes.

Write maintained guides as procedures and contracts that apply to future
installations and upgrades. Keep PR-specific test results, setup status, and
temporary blockers in the PR or issue, not in these guides. Link to authoritative
workflow and dependency files instead of repeating version inventories.
Historical facts belong in the explicitly scoped provenance document.

Use a disposable public test repository for end-to-end exercises. Test the
human ready-for-review step and a rerun after guide merge, not just initial PR
creation. Local tests do not prove GitHub permissions, nested check names,
token event behavior, or live API integration.

## Update the immutable payload pins

**Merge PRs that introduce payload pins with a merge commit, not squash or
rebase.** Payload P must remain an ancestor of wrapper W and reachable in
default-branch history. Squashing or rebasing rewrites that history without
rewriting the literal SHA inside W. A successful pre-merge checkout does not
prove the original payload will remain reachable after merge.

Two commits avoid a circular hash dependency:

1. Finish and test the payload: toolkit Python sources, locked assets, and
   `toolkit/requirements.txt`. Commit those changes as **P**.
2. Push P to this repository so GitHub can fetch that exact, reachable commit.
3. Update both reusable workflow wrappers to use the full literal SHA P for
   their internal payload. Do not derive it dynamically from the caller or
   accept a separate `tooling-ref` input.
4. Verify the pinned payload file objects match the tested toolkit files.
   Include shared imported modules, assets, and requirements, not just the
   entry script. A pin resolving successfully is not sufficient evidence.
   CI compares `git ls-tree` output for P's `toolkit` tree with the checked-out
   toolkit and archives and runs P itself. Full-history checkout therefore
   needs P in the branch history, not merely referenced in workflow text.
5. Verify every external action and shared workflow dependency remains pinned to a
   reviewed immutable SHA. Preserve the tested runtime and dependency versions
   in the workflow definitions and `toolkit/requirements.txt` unless the change
   deliberately updates them.
6. Run wrapper/payload consistency tests and workflow lint. Commit the wrapper
   changes as **W**, then push W.
7. Test consumers against W. Publish the reviewed full W SHA in installation
   guidance or upgrade instructions once it is reachable.
8. State **merge commit required; do not squash or rebase** in the PR
   description, and use that merge strategy. Verify that P and W remain
   reachable in default-branch history after merge.

Consumers pin W in both caller workflows; W binds them to P. Never insert W
into its own contents, substitute an invented SHA, or publish a wrapper before
its payload is reachable. Installation examples use
`REPLACE_WITH_REVIEWED_COMMIT_SHA` to require an explicit version selection.

An alternative retention design can keep P reachable through a permanent
immutable ref, but that requires an explicit maintenance decision and suitable
CI access. The default retention strategy relies on merge-commit history;
do not create retention branches or tags without that maintenance decision.

A documentation-only or wrapper-only commit can retain an existing P if the
payload file objects are unchanged. **Any payload source, asset, or requirement
change requires a new P and a wrapper refresh**, even if an older pin still
runs successfully.

## Upgrade dependencies and consumers

Use Dependabot or Renovate to propose dependency and action-pin updates, and
review the corresponding upstream changes. Do not let an automated dependency
bump silently alter the compatibility contract. Update comments or
documentation that name versions when their pins change.

The development-only [Go tools module](tools/go.mod) owns actionlint and its
dependency graph. Dependabot checks `/tools` weekly, including indirect
dependencies because Go records tool requirements that way. Review changes to both
`go.mod` and `go.sum`; CI builds with `-mod=readonly` and runs the linter on this
repository's workflows. For a manual update, run
`go -C tools get -tool github.com/rhysd/actionlint/cmd/actionlint@<version>`,
then `go -C tools mod tidy`, and review the resulting module changes.
Changes confined to this development module do not require a toolkit payload
refresh.

Dependabot proposes dependency updates; it does not eliminate tool maintenance.
Keep the module's Go version supported, review new lint findings, and resolve
build incompatibilities before merging an update.

Consumers upgrade both workflow references together in a reviewed pull
request. Keep the v1 documentation at the upgrade commit consistent with the
wrappers and payload. No PyPI release or installer publication is needed.

## Enable self-dogfooding

This repository includes [toolkit CI](.github/workflows/ci.yml) and
same-repository callers for its own migration policy
([policy.yml](.github/workflows/policy.yml)) and release drafting
([release.yml](.github/workflows/release.yml)). The caller jobs use local
reusable workflow paths:

```yaml
uses: ./.github/workflows/migration-policy.yml
```

```yaml
uses: ./.github/workflows/release-draft.yml
```

GitHub resolves a local reusable workflow from the same commit as its caller.
Do not append an `@ref` to these local paths. Each wrapper still fetches its
literal immutable payload P, so self-dogfooding does not bypass the two-commit
pinning procedure or automatically execute unpinned toolkit changes. External
consumers continue to pin the reviewed wrapper commit W.

When enabling self-dogfooding, or verifying it after an upgrade:

1. Enable the required Actions policies and **Allow GitHub Actions to create
   and approve pull requests**, as described in
   [installation](docs/v1/installation.md#2-enable-repository-permissions).
2. Confirm the configured labels exist (the default names for this repository's
   default setup) and that the draft caller targets the repository's actual
   default branch. This repository's Dependabot label settings are static;
   keep them aligned if changing its release-automation label configuration.
3. Exercise the policy caller on a test PR. Discover its actual nested check
   name before configuring a required-check ruleset.
4. Run toolkit CI and manually dispatch drafting. If guides are generated,
   verify that the PR stays draft until a human marks it ready, then confirm CI
   runs, review, and merge it.
5. Rerun drafting and verify that exact committed guides and state permit a
   draft update. Inspect the final draft before any manual publication.

Verify current settings and labels rather than assuming a previous deployment
configured them. Record run links, observed results, and outstanding setup work
in the relevant PR or issue.

Passing CI and merged workflow files alone do not prove permissions, token event
behavior, or review/merge integration. Self-dogfooding creates no automatic
merge, tag, or published release, and does not replace independent publication
gates.

## Compatibility and provenance

Treat existing fragments and published migration URLs as durable source
history. Keep legacy guide wrappers readable while generating standalone
topics for new output. Explain migrations for any future incompatible
configuration schema; reject unsupported versions rather than guessing.

The original extraction baseline and intentionally excluded product concerns
are recorded in [provenance](docs/v1/provenance.md). Keep the original MIT
copyright notice. Do not transplant source-product contributor instructions
or publication credentials into this repository.
