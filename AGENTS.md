# Agent instructions

Read [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the relevant
[v1 documentation](docs/v1/README.md) before changing behavior.

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
- Read policy configuration and deletion-authorizing state from the PR base
  Git object. Never let proposed configuration weaken its own validation.
- Do not check out or execute PR code or install PR dependencies under
  `pull_request_target`. Use the immutable, standard-library-only validator.
- Read draft configuration from the selected default-branch commit, not an
  arbitrary worktree. Discover the default branch through GitHub metadata.
- Keep the entire draft pipeline serialized with `cancel-in-progress: false`.
  Do not add the same concurrency group to the caller.
- Resolve release version and previous tag once through the dry run. Require
  exact committed guides and state before any draft-release mutation.
- Generated guide PRs must be draft, with exactly the intended generated label
  categories. Do not automatically mark ready, approve, merge, tag, or publish.
- Treat final API rechecks as non-atomic. Never describe pre-draft readiness as
  a publication gate.

## Editing and verification

Use Python 3.13 and `toolkit/requirements.txt`. Run
`python -m unittest discover -s tests -q` for code changes and `actionlint` for
workflow changes when available. Test both intended behavior and rejection
paths. State missing tooling and unperformed live validation explicitly.

Update related documentation and preserve literal text in Markdown code
fences. Do not replace the locked assets with consumer-provided YAML,
templates, `_extends`, or execution hooks.

When toolkit source, assets, or requirements change, follow
[MAINTAINERS.md](MAINTAINERS.md#update-the-immutable-payload-pins): commit and
push tested payload P before committing wrappers W with literal P pins.
Consumers pin W; they do not choose a second tooling ref.
Require a merge commit for PRs introducing payload pins, not squash or rebase,
so P remains reachable in default-branch history. Record that merge requirement
in the PR body; do not create retention tags or branches without an explicit
maintenance decision.
