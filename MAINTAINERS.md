# Toolkit maintenance

This document is for maintainers of `mthalman/release-automation`. Maintainers
of repositories that consume it should use the
[consumer maintainer guide](docs/maintainer-guide.md).

## Review responsibilities

Keep the workflow interface small and the payload immutable. Review changes to
trusted Git-object access, path validation, dependency installation, release
API calls, and workflow permissions as changes to the trust boundary.

Before accepting a change:

- Confirm both entrypoints still expose only optional `config-path`.
- Confirm the separate prepare/finalize Actions retain their documented
  inputs and opaque context contract. Keep consumer-owned `uses` and `run`
  steps in consumer workflows, not registry plugins or execution hooks.
- Run unit tests with Python 3.13 and pinned dependencies; run `actionlint` for
  workflow edits.
- Check default-branch discovery, stable-tag restrictions, label mapping, and
  configuration rejection cases. Every label role must come from resolved
  configuration, with no reserved names or namespaces. Check that partial
  overrides preserve case-insensitive distinctness across all eight labels.
- Verify policy uses base configuration and state without executing PR code.
- Verify draft mutation follows exact committed-document/state readiness and
  fresh remote/release checks. No waiting path may rewrite an existing draft.
- Verify successful drafting records versioned preparation metadata. Check
  publication against tagged configuration, source and previous-tag/commit
  provenance, exact committed files/state, migration links, published state,
  and current default-branch ancestry. Newer default-branch commits alone must
  not invalidate an otherwise valid prepared tag.
- Verify prepare and finalize independently fetch Git objects without consumer
  code execution, freeze relevant metadata but allow asset uploads, reject
  unrelated or multiple drafts, and handle exact-tag published reruns without
  regenerating historical guides or editing published releases.
- Keep finalization limited to PATCHing the prepared release with
  `draft: false` and `make_latest: "true"`. Rechecks are not a transactional lock:
  a concurrent tag deletion can let GitHub recreate the tag during publication,
  and concurrent release edits can race the PATCH.
- Preserve fragment and published-guide retention, including reviewed
  corrections and references from all release bodies.
- Update documentation and identify any compatibility changes.

Write maintained guides as procedures and contracts that apply to future
installations and upgrades. Keep PR-specific test results, setup status, and
temporary blockers in the PR or issue, not in these guides. Link to authoritative
workflow and dependency files instead of repeating version inventories.
Record change-specific historical context in the relevant PR or commit.

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

1. Finish and test the payload: toolkit Python sources, locked assets,
   `toolkit/requirements.txt`, and the public composite Action definitions under
   `actions`. Commit those changes as **P**.
2. Push P to this repository so GitHub can fetch that exact, reachable commit.
3. Update both reusable workflow wrappers to use the full literal SHA P for
   their internal payload. Update the self-dogfooding `publish.yml` to pin both
   external prepare/finalize Action references to that same literal P.
   Do not derive P dynamically from the caller or accept a separate `tooling-ref`
   input.
4. Verify the pinned payload file objects match the tested files under both
   `toolkit` and `actions`. Include shared imported modules, assets, requirements,
   and Action metadata, not just the entry script. A pin resolving successfully
   is not sufficient evidence. CI compares the pinned trees with the checked-out
   files and archives and runs P itself. Full-history checkout therefore
   needs P in the branch history, not merely referenced in workflow text.
5. Verify every external action and shared workflow dependency remains pinned to a
   reviewed immutable SHA. Preserve the tested runtime and dependency versions
   in the workflow definitions and `toolkit/requirements.txt` unless the change
   deliberately updates them. Verify the prepare/finalize composite Actions
   load packaged scripts through `github.action_path`, not a consumer checkout
   or a second ref, and install pinned requirements in isolated environments.
6. Run wrapper/payload consistency tests and workflow lint. Commit the wrapper
   changes as **W**, then push W.
7. Test consumers against W. Publish the reviewed full W SHA in installation
   guidance or upgrade instructions once it is reachable.
8. State **merge commit required; do not squash or rebase** in the PR
   description, and use that merge strategy. Verify that P and W remain
   reachable in default-branch history after merge.

Consumers pin W in both caller workflows and in both optional publication
Action references. The reusable wrappers at W bind them to P; the composite
Actions use the toolkit packaged at W. Verify that packaged toolkit matches
the tested payload. Never insert W
into its own contents, substitute an invented SHA, or publish a wrapper before
its payload is reachable. Installation examples use
`REPLACE_WITH_REVIEWED_COMMIT_SHA` to require an explicit version selection.

An alternative retention design can keep P reachable through a permanent
immutable ref, but that requires an explicit maintenance decision and suitable
CI access. The default retention strategy relies on merge-commit history;
do not create retention branches or tags without that maintenance decision.

A documentation-only or wrapper-only commit can retain an existing P if the
payload file objects are unchanged. **Any payload source, asset, requirement,
or public Action metadata change requires a new P and a pin refresh**, even if
an older pin still runs successfully. Refresh the self-dogfooding Action pins
as well as both reusable wrapper payload pins.

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

Consumers upgrade both workflow references and any prepare/finalize Action
references together in a reviewed pull request. Keep the documentation at the
upgrade commit consistent with the wrappers, Actions, and payload. Refresh
existing drafts with a successful updated drafting run before tag publication;
preparation metadata is required. No PyPI release or installer publication is
needed.

## Enable self-dogfooding

This repository includes [toolkit CI](.github/workflows/ci.yml) and
same-repository callers for its own migration policy
([policy.yml](.github/workflows/policy.yml)) and release drafting
([release.yml](.github/workflows/release.yml)). A separate
[publish.yml](.github/workflows/publish.yml) handles tag-driven publication.
The policy and draft caller jobs use local reusable workflow paths:

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

The tag workflow in W uses external
`mthalman/release-automation/actions/prepare-release@P` and
`mthalman/release-automation/actions/finalize-release@P` references, replacing
`P` with the same full literal payload SHA. P includes both Action directories
and the toolkit scripts they load through `github.action_path`. This internal
self-dogfooding pin avoids a self-reference to W; external consumers still pin
both Actions to W and choose no second tooling ref.

Between prepare and finalize, the tag workflow checks out the validated source
SHA and runs toolkit tests as this repository's consumer-owned steps. Both
steps are guarded by `already-published != 'true'`; the Actions themselves do
not check out consumer code. The workflow shares `release-drafter` concurrency
with drafting, with cancellation disabled.
It does not turn a successful draft run into a tag push: humans push tags
only after the review and draft gates pass. This self-dogfooding workflow
publishes the toolkit's GitHub Release, not a consumer package pipeline.

When enabling self-dogfooding, or verifying it after an upgrade:

1. Enable the required Actions policies and **Allow GitHub Actions to create
   and approve pull requests**, as described in
   [installation](docs/installation.md#2-enable-repository-permissions).
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
   draft update with preparation metadata. Inspect the final draft before
   any tag push or manual publication.
6. In a test repository, push the prepared stable tag as a human and verify
   prepare/finalize publication, rejection paths, and an already-published
   rerun. Check that consumer steps fail closed and uploads do not invalidate
   context. Follow the [tag-publishing verification guide](docs/tag-publishing.md#verify-the-installation).

Verify current settings and labels rather than assuming a previous deployment
configured them. Record run links, observed results, and outstanding setup work
in the relevant PR or issue.

Passing CI and merged workflow files alone do not prove permissions, token event
behavior, review/merge integration, or live end-to-end publication. Do not treat
activation settings or those live exercises as completed without observed run
evidence. Self-dogfooding includes no automatic merge or tag-creation step. Drafting
remains draft-only; only the separate tag workflow can publish the prepared
GitHub Release after a human tag push and successful gates.

## Compatibility

Treat existing fragments and published migration URLs as durable source
history. Keep legacy guide wrappers readable while generating standalone
topics for new output. Explain migrations for any future incompatible
configuration schema; reject unsupported versions rather than guessing.
