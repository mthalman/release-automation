# Publish a prepared release from a tag

Use two opt-in composite Actions to put your own release steps between toolkit
validation and GitHub Release publication:

1. `actions/prepare-release` validates the pushed tag and prepared draft.
2. Your workflow runs any number of consumer-owned `uses` and `run` steps.
3. `actions/finalize-release` independently revalidates and publishes the
   existing GitHub Release.

A reusable workflow runs as a job and cannot accept an arbitrary array of
caller-defined steps. Composite Actions run within your job, so you can place
your own `uses` and `run` steps between preparation and finalization.

The reusable policy and drafting workflows remain unchanged in scope: each
accepts only optional `config-path`, and neither publishes. These Actions do not
implement registry plugins, package publishing, or executable configuration
hooks. They have no tag-creation, retagging, PR-merge, or generated-guide write
operation. Publication still has [non-atomic API race limitations](#what-the-publication-checks-establish).

## Before you enable publication

- Install and verify [drafting and policy](installation.md). Use github.com,
  one stable release stream, and exact `vMAJOR.MINOR.PATCH` tags.
- Pin both Actions and the reusable workflows to the same reviewed, reachable,
  full commit SHA **W**. The placeholder below is not a usable reference.
  Consumers do not select a second toolkit ref. The Actions load packaged
  scripts relative to `github.action_path`; they do not use scripts from your
  checkout.
- Use a runner with Bash, Git, and GitHub CLI (`gh`). The Actions set up Python
  3.13 and install the toolkit's pinned requirements in an isolated temporary
  environment. GitHub-hosted Linux and Windows runners are the intended
  environments; your build steps must also support the runner you choose.
- Decide your environments, required approvals, runners, credentials, release
  assets, and step ordering. Grant `contents: write` only at the publication
  job in the tag workflow. Both Actions default to `github.token`, but its
  availability does not guarantee sufficient draft visibility or publication
  permissions; see [credential requirements](#choose-credentials-and-verify-draft-visibility).
  Do not grant `id-token: write` unless your own steps require it.
- Serialize the **whole tag workflow** with concurrency group
  `release-drafter` and `cancel-in-progress: false`, shared with the reusable
  draft pipeline. Do not add that group to the drafting caller: the drafting
  callee already owns it.

**Existing drafts need a refreshed, successful drafting run before tagging.**
Drafts created before preparation metadata was introduced lack the required
record. Missing or unsupported metadata fails validation; do not hand-author
it. Follow [the tagging procedure](#refresh-the-draft-and-push-its-tag) after
installing the workflow.

## Choose credentials and verify draft visibility

Prepare performs read operations, but its token must be able to see unpublished
drafts. GitHub's [List releases documentation](https://docs.github.com/en/rest/releases/releases#list-releases)
says only users with push access receive draft listings. Do not assume a
read-only installation token can see drafts merely because the endpoint accepts
`contents: read`. Verify the chosen token's identity and effective access in
your deployment. The single-job example grants `contents: write` for the
publication job; it is not a guarantee for every token or repository policy.

GitHub's [Update a release documentation](https://docs.github.com/en/rest/releases/releases#update-a-release)
also requires workflow-modification authorization when the resolved target
commit adds or modifies `.github/workflows/` files relative to the repository's
default branch. This applies to the existing target even when the PATCH does
not change `target_commitish`. An older prepared commit can therefore pass
toolkit ancestry checks yet encounter a platform permission failure after the
default branch advances.

GitHub documents `404 Not Found`, or in some authentication paths
`403 Resource not accessible by integration`, for this condition. `GITHUB_TOKEN`
cannot receive the required workflow-modification authorization. If needed,
use a narrowly scoped GitHub App installation token or personal access token
under your own approval process and pass it through the Actions' `token` input.
Fine-grained tokens and App tokens need Contents (write) and, when that condition
applies, Workflows (write) repository permissions; classic tokens need the appropriate repository access
and `workflow` scope. Consumers own credential issuance, storage, scope, and
rotation. The toolkit does not create credentials or alter settings.

API failures fail the Action; they are not bypassed by valid provenance.
Investigate draft visibility and permissions rather than assuming a missing
release, retagging, or weakening checks. Verify publication with the chosen
credentials in a test deployment before relying on the workflow.

## Add a tag workflow with your own steps

This example is a consumer-owned `.github/workflows/publish.yml`. Replace every
`REPLACE_WITH_REVIEWED_COMMIT_SHA` with the same full W SHA. The checkout and
setup-node pins are reviewed dependency examples; review them for your own
repository.

The `eng/build-release.sh` and `eng/publish-release.sh` scripts are illustrative
**consumer files**, not files supplied by this toolkit. Replace them with your
own steps. The second script can upload assets or publish your product; the
toolkit supplies no registry-specific implementation.

```yaml
name: Publish release

on:
  push:
    tags: ['v*']

permissions:
  contents: read

concurrency:
  group: release-drafter
  cancel-in-progress: false

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Prepare release
        id: prepare
        uses: mthalman/release-automation/actions/prepare-release@REPLACE_WITH_REVIEWED_COMMIT_SHA

      - name: Check out the validated source for consumer steps
        if: steps.prepare.outputs.already-published != 'true'
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ steps.prepare.outputs.sha }}
          persist-credentials: false

      - name: Set up the consumer build runtime
        if: steps.prepare.outputs.already-published != 'true'
        uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
        with:
          node-version: '24'

      - name: Build consumer artifacts
        if: steps.prepare.outputs.already-published != 'true'
        shell: bash
        env:
          RELEASE_VERSION: ${{ steps.prepare.outputs.version }}
          RELEASE_SHA: ${{ steps.prepare.outputs.sha }}
        run: bash ./eng/build-release.sh "$RELEASE_VERSION" "$RELEASE_SHA"

      - name: Publish consumer artifacts
        if: steps.prepare.outputs.already-published != 'true'
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          RELEASE_TAG: ${{ steps.prepare.outputs.tag }}
          RELEASE_ID: ${{ steps.prepare.outputs.release-id }}
        run: bash ./eng/publish-release.sh "$RELEASE_TAG" "$RELEASE_ID"

      - name: Finalize GitHub Release
        if: steps.prepare.outputs.already-published != 'true'
        uses: mthalman/release-automation/actions/finalize-release@REPLACE_WITH_REVIEWED_COMMIT_SHA
        with:
          context: ${{ steps.prepare.outputs.context }}
```

The `v*` event filter is deliberately broader than the supported tag grammar.
The Actions require an actual **new-tag creation push**: `created` must be
Boolean `true`, `forced` and `deleted` must be Boolean `false`, and `before`
must be the all-zero 40-character SHA. Missing or malformed flags or `before`
fail closed. Unsupported tags, branch pushes, existing-tag updates (including
forced moves), tag deletions, manual dispatches, and other events are rejected.

A creation event does not prove that a tag name has never previously been
deleted and recreated. These checks validate the event and current Git objects,
not persistent immutable ref history. Retain your own tag-protection and audit
controls; do not delete and recreate tags to bypass a failed gate.

Every build or publication step uses the `already-published` guard. Its ordinary
GitHub Actions success condition also remains in effect. Do not add `always()`
to finalization, and do not use `continue-on-error` to bypass a failed consumer
step. The finalize guard is optional if you want it to verify the already
published no-op path, but consumer side-effect guards are still required.

The example passes output values through `env` rather than interpolating
expressions into shell scripts. Add your own secrets only to steps that need
them. Asset upload steps can use `gh release upload "$RELEASE_TAG" ...` with
`GH_REPO` and `GH_TOKEN`; that command takes the tag, not the numeric release ID.
Uploads are allowed between prepare and finalize. You own asset naming,
replacement policy, and verification.

If you use custom configuration, add `config-path` to prepare with the same
repository-relative path used by drafting. The file must exist in the tagged
commit. Do not pass a local checkout or snapshot path to finalize.

## Refresh the draft and push its tag

First exercise this procedure in a test repository. Installing workflow files
alone does not verify credentials, approvals, or publication behavior.

1. Merge the workflow and any exact generated documentation and state through
   your normal review process.
2. Run drafting successfully with the reviewed toolkit revision. This refreshes
   the preparation metadata, including on first adoption.
3. Inspect the draft's prepared tag and commit. From a checkout of the consuming
   repository, use an authenticated GitHub CLI session with draft visibility:

   ```sh
   gh api --hostname github.com 'repos/{owner}/{repo}/releases' --paginate --jq '.[] | select(.draft) | {id, tag_name, target_commitish, html_url}'
   ```

   Expect exactly one draft. After successful drafting, `tag_name` is the
   intended stable tag and `target_commitish` is the full prepared commit SHA.
   If no draft appears or multiple drafts appear, resolve visibility or draft
   conflicts before continuing.
4. Review that draft's version, source commit, release notes, migration links,
   CI, and required approvals. You can edit non-migration note prose before
   prepare runs; keep the version-only title, preparation metadata, and
   migration-links block intact. The metadata is a consistency record, not a
   signed attestation.
5. Have a human create the new tag named by `tag_name` at the exact
   `target_commitish` SHA and push it. Do not substitute the current
   default-branch tip. Both annotated and lightweight tags are supported.
   Existing-tag updates, including forced moves, are rejected; do not move or
   recreate a tag to repair a failed gate.
6. Observe prepare, the consumer steps, and finalize in the tag workflow.
   After a successful first publication, the existing release is published
   with its reviewed notes and title preserved.

Tag pushes made with a workflow's `GITHUB_TOKEN` normally do not trigger another
push workflow. A human push avoids that event suppression. If you automate tag
creation outside this toolkit, choosing event-producing credentials and
protecting them remains your responsibility; these Actions provide no
tag-creation operation.

## Verify the installation

In the test repository, confirm the successful path above, then test rejection
of existing-tag updates, forced moves, missing or malformed event flags, stale
preparation, and changed draft metadata. Also test successful asset uploads
between the Actions, failure propagation from consumer steps, and an exact-tag
published rerun that skips those steps.

Inspect environment approvals, token permissions, and the shared concurrency
behavior in deployed runs. Local tests and committed workflow files are not
evidence of repository activation or live end-to-end validation.

## Rerun and recover safely

Retrying the workflow for the original valid tag-creation event remains
supported; a retry does not require another tag push. The creation-event checks
still apply on already-published reruns.

For an already-published release at the exact event tag, the Actions validate
its preparation marker, source provenance, tagged configuration, and current
default-branch ancestry and return
`already-published: 'true'` without changing the release. They do not regenerate
historical guides or compare an old preparation record against today's
published-release state. Later releases and reviewed historical guide
corrections must not make an exact-tag no-op rerun act like a new publication.
An unprepared published release is not a shortcut around provenance validation.

Guard all consumer build and publication steps on `already-published != 'true'`
so an exact-tag published rerun skips external side effects. This guard does
**not** make partial failures idempotent. If your package or artifact upload
succeeds but a later step fails before GitHub Release publication, prepare can
still return `'false'` on a rerun. Your scripts must detect their own completed
external operations and verify or resume them safely. Rerunning failed jobs may
repeat publishing unless you check the external destination's state.

There is no rollback of consumer side effects. If validation fails before the
publication PATCH, the toolkit makes no release mutation, but cannot undo an
upload or external publication. A failure during or after the PATCH does not
prove the release is still draft; inspect its actual state before retrying.
Investigate changes to the tag, draft, configuration, boundary, or published
state. Do not bypass checks or move a tag to force success.

## Action reference

### Prepare inputs

| Input | Required | Default | Meaning |
| --- | --- | --- | --- |
| `token` | No | `github.token` | Available, nonempty token for Git/API reads whose identity and effective access can see draft releases; `contents: read` alone is not a draft-visibility guarantee. |
| `config-path` | No | Empty | Configuration path in the tagged Git commit; empty uses defaults. |

### Prepare outputs

| Output | Meaning |
| --- | --- |
| `tag` | Validated stable tag, such as `v2.4.0`. |
| `version` | Version without `v`, such as `2.4.0`. |
| `sha` | Tagged commit SHA, including for an annotated tag. |
| `release-id` | Existing GitHub Release ID. |
| `release-url` | Actual `html_url` returned by GitHub; an unpublished draft can use an `untagged-...` URL. |
| `already-published` | String `'true'` for an exact-tag published rerun; otherwise `'false'`. |
| `context` | Opaque JSON that finalize requires unchanged. It includes the repository-relative configuration selection, not local filesystem paths or an execution hook. |

### Finalize inputs and outputs

| Input | Required | Default | Meaning |
| --- | --- | --- | --- |
| `token` | No | `github.token` | Available, nonempty token with `contents: write`, draft visibility, and any workflow-modification authorization GitHub requires for the target. |
| `context` | Yes | None | Exact opaque JSON output from prepare in the same tag-event workflow run. |

Finalize outputs `release-id`, `release-url`, and `already-published`. The last
output is a string `'true'` or `'false'`, not a YAML Boolean: `'true'` means
publication was already complete and finalize made no mutation; a successful
new publication returns `'false'`. Neither Action
exposes a second tooling ref, shell command, custom template, or local snapshot
path as an input.

Finalize returns the release URL reported by GitHub after publication or for
the already-published release. Treat `release-url` as opaque: prepare's draft
URL can differ from finalize's published URL. Neither Action synthesizes this
output from the tag.

## What the publication checks establish

### Preparation metadata

Drafting records a hidden, versioned metadata block in the release body with:

- the tag resolved by the drafting dry run and the selected source commit;
- the previous release tag and its commit, or an initial-release boundary;
- a digest of the resolved configuration;
- a digest of the published release state;
- pending guide-version references from the draft body before its update,
  needed to replay retention during validation.

The versioned record stays minimal: configuration and published release state
are represented by hashes, not full snapshots. The guide-reference list exists
only to reproduce draft-time retention. The recorded tag carries forward the
single dry-run version resolution; it does not calculate another version.

The configuration digest case-folds label values to match their
case-insensitive identities. The published-state digest covers each published
release's ID, tag, title, prerelease flag, target commit, and body. It excludes
assets and `updated_at`, so uploading assets to a published release alone does
not invalidate a prepared draft.

This metadata is a consistency record, **not a signed attestation**. Keep
repository write access and workflow credentials restricted.

### Source and release validation

Prepare and finalize each fetch immutable Git data into an isolated temporary
Git repository. Neither checks out or executes consumer code. A consumer checkout
in the example is solely for the consumer-owned steps.

For an unpublished release, prepare requires all of the following:

1. The event is a supported new-tag creation push, and its tag has the exact
   stable format and still resolves to the expected raw tag object and tagged
   commit. The event's `after` value must equal the raw tag object, not just its
   peeled commit. Replacing a lightweight tag with an annotated tag, or replacing
   an annotated tag object, is rejected even if the commit stays the same and
   the replacement occurs before prepare starts.
2. The repository has one prepared stable draft for this tag, with the exact
   source commit in `target_commitish`, a version-only title, and valid
   preparation metadata whose recorded tag equals the event tag. Renaming or
   retagging a draft cannot reuse preparation for another version at the same
   source commit, even when no migration content exists.
   Unrelated or multiple drafts fail the publication
   path rather than being silently ignored or selected.
3. The tagged commit matches the recorded source and is an ancestor of the
   **current** default branch discovered through GitHub metadata. Default-branch
   advancement alone is allowed; the tag need not equal the latest branch tip.
4. Configuration read from the tagged commit matches the recorded resolved
   configuration digest. It is not compared with configuration at a newer
   default-branch commit.
5. Generated topics, version and root indexes, and state match the committed
   tagged files exactly when evaluated with the tagged configuration and the
   recorded previous-tag/commit boundary. The release's migration-links block
   is correct. Validation replays the recorded retention effect of links in
   the pre-update draft body, rather than treating links removed by draft
   replacement as permission to discard legitimately retained guides.
6. The current published release state matches the preparation record, and the
   release version is greater than every existing published stable version.

Within each inspection, the Actions re-read releases, the default-branch name
and head, and tag identity. A detected change during that inspection fails the
run. Default-branch head advancement **between** prepare and finalize is allowed
if the tag is still an ancestor; the branch name and the other frozen context
must still match.

The checks do not silently retag, regenerate files in your repository, or write
guides to fix a mismatch. Resolve failures through normal source review and a
fresh successful drafting run before selecting a new release tag.

Prepare's context freezes the release ID, tag, title, prerelease flag, target
commit, and body, together with the raw tag object, tagged commit, and preparation
provenance. It deliberately excludes draft status, timestamps, and assets.
Asset uploads do not invalidate the context, and finalize accepts an otherwise
identical release that was already published between the Actions. Other
relevant changes, including note edits after prepare, require a fresh prepare
run; do not modify the opaque context to accept them.

Context is not signed authority or a permission grant. Finalize independently
derives the release, tag, and commit from GitHub and immutable Git data, then
compares that result with the supplied context. The consumer workflow and any
steps holding its write token remain trusted; this handoff does not restrict
what those steps can do with their credentials.

Finalize fetches and verifies everything independently, checks that the context
still matches, and makes only this release mutation: PATCH the existing release
with `draft: false` and `make_latest: "true"`. It sends no release-creation,
tag-creation, retagging, note-edit, or title-edit request and makes no mutation
when inspection finds the release already published.

**The API rechecks are non-atomic.** Prepare/finalize are not a transactional
publication lock. Humans or other clients can change repository or release
state between the final reads and PATCH. If someone deletes the tag in that
window, GitHub can recreate it as a side effect of publishing the release.
Concurrent release-editor changes can also race the PATCH; a post-response
check can report a mismatch after publication has already occurred, but cannot
undo it. Thus, the absence of an explicit tag-creation request is not a guarantee
that remote tags cannot change during a race. Concurrency coordinates
participating workflows, not every GitHub writer. Keep independent product
checks, approval controls, and restricted write access; pre-draft readiness is
not a publication gate by itself.

## Split consumer work across jobs

You can run prepare, consumer work, and finalize in separate jobs of the same
tag-event workflow. Keep workflow-level concurrency, and pin both Actions to
the same W. Map the prepare step outputs to job outputs:

```yaml
outputs:
  context: ${{ steps.prepare.outputs.context }}
  tag: ${{ steps.prepare.outputs.tag }}
  version: ${{ steps.prepare.outputs.version }}
  sha: ${{ steps.prepare.outputs.sha }}
  release-id: ${{ steps.prepare.outputs.release-id }}
  release-url: ${{ steps.prepare.outputs.release-url }}
  already-published: ${{ steps.prepare.outputs.already-published }}
```

These snippets are job fragments, not a complete additional workflow:

```yaml
build:
  needs: prepare
  if: needs.prepare.outputs.already-published != 'true'
  # Supply your own runner, permissions, and steps.

finalize:
  needs: [prepare, build, publish-artifacts]
  if: needs.prepare.outputs.already-published != 'true'
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - uses: mthalman/release-automation/actions/finalize-release@REPLACE_WITH_REVIEWED_COMMIT_SHA
      with:
        context: ${{ needs.prepare.outputs.context }}
```

Define `publish-artifacts` as your own job and guard it too. Include **every**
required build, check, approval, and publication job in finalize's dependency
chain; finalization must require their success. Do not use `always()` to run
past failed or skipped prerequisites. Use read-only permissions for consumer
build jobs that need no draft access. Scope write access to the release jobs
that require it for draft visibility, asset uploads, or finalization.
For a separate prepare job, verify that its
token can actually see draft releases; do not infer draft access from the
read-only API operation alone.

Pass `context` unchanged through `needs`, not through a toolkit filesystem
snapshot. Each Action reconstructs its own Git data and runtime. Artifacts can
transport your build outputs between runners, but are not a transport for
toolkit local paths or trusted release state. All jobs must retain the same
tag-push event; this is not a handoff to a manually dispatched workflow.
