# Agent instructions

Read [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the relevant
[documentation](docs/README.md) before changing behavior.

## Repository boundaries

- This is a reusable release-automation toolkit, not a consuming product.
- Keep consumer fragments, state, guides, build pipelines, package publishing,
  and credentials out of the repository except synthetic test fixtures.
- Support one default-branch release stream on github.com with stable
  `vMAJOR.MINOR.PATCH` tags. Do not silently generalize to prereleases,
  monorepos, arbitrary tag prefixes, or other hosts.
- Preserve the MIT license and original 2020 Matt Thalman copyright.

## Trust and workflow invariants

- Both reusable entrypoints expose only optional `config-path`.
- Keep opt-in publication in `actions/prepare-release` and
  `actions/finalize-release`, not in the draft workflows. Consumers pin both
  Actions to the same reviewed full SHA W; packaged scripts load through
  `github.action_path`, with no second tooling ref.
- Allow arbitrary consumer-owned `uses` and `run` steps between the Actions.
  Do not add registry plugins, consumer execution hooks, or package pipelines.
- Read policy configuration and deletion-authorizing state from the PR base
  Git object. Never let proposed configuration weaken its own validation.
- Do not check out or execute PR code or install PR dependencies under
  `pull_request_target`. Use the immutable, standard-library-only validator.
- Read draft configuration from the selected default-branch commit, not an
  arbitrary worktree. Discover the default branch through GitHub metadata.
- Keep the entire draft pipeline serialized with `cancel-in-progress: false`
  and `queue: max`.
  Do not add the same concurrency group to the drafting caller. The separate
  consumer tag workflow must share `release-drafter` with cancellation disabled
  and `queue: max` so new draft runs do not replace pending publication runs.
- Resolve release version and previous tag once through the dry run. Require
  exact committed guides and state before any draft-release mutation.
- Generated guide PRs must be draft, with exactly the intended generated label
  categories. Do not automatically mark ready, approve, merge, or tag.
  Draft workflows must never publish.
- Tag publication requires a new stable-tag creation push (`created: true`,
  `forced: false`, `deleted: false`, and an all-zero 40-character `before` SHA).
  Reject missing/malformed event fields and existing-tag updates, including
  forced moves. Preserve retries of the original valid creation event without
  claiming to prove that the tag name was never deleted and recreated.
  Require tagged configuration,
  prepared provenance, exact committed guides/state, and default-branch
  ancestry. Prepare and finalize independently fetch Git data without checking
  out or executing consumer code. Transfer only opaque JSON context, not local
  paths. Freeze release identity excluding draft status, timestamps, and assets,
  so an otherwise identical already-published release is accepted.
- Finalize may only PATCH the existing draft with `draft: false` and
  `make_latest: "true"`. Never send release/tag creation, retagging, or note-edit
  requests, or mutate a release found already published. Exact-tag published
  reruns skip consumer side effects.
- Treat final API rechecks as non-atomic. Never describe pre-draft readiness as
  a publication gate or prepare/finalize as a transactional publication lock.
  A concurrent tag deletion can let GitHub recreate the tag during publication;
  concurrent release edits can race the PATCH. Do not promise race-free results.

## Editing and verification

Use Python 3.13 and `toolkit/requirements.txt`. Run
`python -m unittest discover -s tests -q` for code changes and `actionlint` for
workflow changes when available. Test both intended behavior and rejection
paths. State missing tooling and unperformed live validation explicitly.

Update related documentation and preserve literal text in Markdown code
fences. Do not replace the locked assets with consumer-provided YAML,
templates, `_extends`, or execution hooks.

When toolkit source, assets, requirements, or public Action metadata change, follow
[MAINTAINERS.md](MAINTAINERS.md#update-the-immutable-payload-pins): commit and
push tested payload P, including `toolkit` and `actions`, before committing
wrappers W with literal P pins. Refresh both reusable payload pins and the
self-dogfooding tag workflow's external Action pins to P. External consumers
pin W; they do not choose a second tooling ref.
Require a merge commit for PRs introducing payload pins, not squash or rebase,
so P remains reachable in default-branch history. Record that merge requirement
in the PR body; do not create retention tags or branches without an explicit
maintenance decision.
