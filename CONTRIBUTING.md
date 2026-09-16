# Contributing

Contributions should keep release drafting predictable, reviewable, and separate
from opt-in tag publication. Start with the [workflow contract](docs/workflows.md)
and [local development guide](docs/local-development.md).

## Before changing behavior

Open an issue describing the problem, the expected behavior, and a small
reproduction for a substantial interface or behavior change. For a focused bug
fix or documentation correction, a pull request can provide that context.
Do not include tokens, private repository content, or publication credentials
in issues, fixtures, or logs.

The supported interface includes two draft/policy reusable workflows, each with
only an optional `config-path` string, and the separate
[`prepare-release` and `finalize-release` Actions](docs/tag-publishing.md).
Prepare accepts `token` and optional `config-path`; finalize accepts `token` and
the required opaque `context` output from prepare. Consumers put their own
arbitrary `uses` and `run` steps between the Actions; do not implement registry
plugins, script hooks, or package pipelines in the toolkit. Additional policy
settings belong in the strictly validated versioned JSON contract, not extra
workflow inputs or executable hooks. Changes
outside the [supported scope](README.md#supported-scope) need an explicit design
decision rather than an incidental implementation.

## Develop a change

1. Create a branch from the repository's default branch.
2. Set up Python 3.13 and the pinned toolkit dependencies using the
   [local setup instructions](docs/local-development.md#set-up-python).
3. Add or update focused tests alongside behavior changes. Include negative
   cases for validation, trusted Git-object reads, and fail-closed readiness
   behavior where relevant. For tag publishing, cover tag movement, stale
   preparation, conflicting drafts, cross-step changes, asset uploads, and
   exact-tag published reruns.
4. Run `python -m unittest discover -s tests -q`. For workflow changes, also run
   `actionlint` if installed.
5. Update the related `docs` guide or reference when behavior, examples, or
   supported inputs change.

Use synthetic repositories and event data in tests. Do not add real consumer
fragments, migration-guide state, published guides, or product CI configuration
to this toolkit repository.

## Submit a pull request

Explain the problem and solution, list validation commands and results, and
identify any compatibility or pin-refresh implications. Distinguish local tests
from real GitHub Actions runs; do not report live workflow validation unless
you actually performed it.

Keep changes scoped. Preserve Markdown code fences and literal template-like
text such as `$OWNER`. Keep existing published-guide retention and pending-state
authorization behavior intact.

Toolkit source, asset, requirement, or public Action metadata changes need a new
immutable payload commit and refreshed reusable wrapper and self-dogfooding
Action pins. The payload includes both `toolkit` and `actions`. Follow the
[maintainer pinning procedure](MAINTAINERS.md#update-the-immutable-payload-pins);
do not guess a SHA or create a self-referential commit hash.

PRs introducing a payload pin must use a **merge commit**, not squash or rebase,
so payload P remains in default-branch history as an ancestor of wrapper W.
State this requirement in the PR description. CI compares the pinned payload
with the proposed toolkit and Action definitions and runs an archive of P; it
needs that history.

## Licensing

By submitting a contribution, you agree that it is provided under this
repository's [MIT license](LICENSE). Preserve the original
`Copyright (c) 2020 Matt Thalman` notice and any applicable upstream attribution.
