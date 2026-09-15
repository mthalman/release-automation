# Release automation

Reusable GitHub Actions workflows for release drafting and reviewed migration
guides. Pull request labels drive release notes and version selection. Breaking
change fragments become versioned migration topics in a draft pull request.
The release draft is updated only after the exact generated documentation and
state are committed on the selected default-branch snapshot.

**This toolkit does not publish releases, create tags, merge pull requests, or
run your product's release pipeline.** Its readiness checks protect draft
generation, not publication. Your repository owns testing, approvals, release
credentials, and the final publication gate.

## Start here

1. Follow [installation](docs/v1/installation.md) to add two small caller
   workflows, create labels, and configure repository permissions.
2. Share the [author guide](docs/v1/author-guide.md) with contributors.
3. Use the [consumer maintainer guide](docs/v1/maintainer-guide.md) to review
   generated guides and prepare a release.

Installation examples contain
`@REPLACE_WITH_REVIEWED_COMMIT_SHA`. This is an installation placeholder,
**not a usable workflow reference**.
Replace it in both callers with the same reviewed, reachable, full commit SHA
from this repository. No floating branch or tag is required.

## How it works

1. `migration-policy.yml` validates a pull request using trusted base-commit
   configuration and state. A pinned, standard-library-only validator reads
   the proposed files without executing pull request code or installing its
   dependencies.
2. `release-draft.yml` selects the latest repository default-branch commit and
   full history. Release Drafter performs a dry run that resolves one version
   and previous release tag.
3. The workflow renders breaking change fragments with Towncrier and opens or
   updates an always-draft migration-guide pull request.
4. A human marks that pull request ready, runs the repository's checks, reviews
   it, and merges it. Automation updates return the pull request to draft.
5. A subsequent run verifies the generated files and state on the selected
   branch, rechecks release state and the remote commit, then creates or updates
   only a draft release.

Until step 4 is complete, an existing release draft stays unchanged. See the
[workflow contract](docs/v1/workflows.md) for ordering, trust boundaries, and
race limitations.

## Supported scope

- Repositories on **github.com**, with one release stream on the
  repository's actual default branch.
- Stable tags in the exact form `vMAJOR.MINOR.PATCH`, such as `v2.4.0`.
  Release names contain only the version, such as `2.4.0`.
- Pinned Python and Towncrier tooling, with SHA-pinned Release Drafter and
  create-pull-request workflows. See the [runtime setup](docs/v1/local-development.md#set-up-python),
  [dependency lock](toolkit/requirements.txt), and
  [workflow definitions](.github/workflows) for versions at your selected commit.
- Optional, versioned JSON configuration for paths, labels, and category titles.
  The defaults work without a configuration file.

Monorepo version streams, prereleases, arbitrary tag prefixes, GitHub Enterprise
hosts, executable consumer configuration, and consumer migration automation are
outside v1's scope. There is no PyPI package or installer to deploy.

## Documentation

| Document | Purpose |
| --- | --- |
| [v1 documentation index](docs/v1/README.md) | Find the guide for your role |
| [Installation](docs/v1/installation.md) | Install pinned caller workflows |
| [Author guide](docs/v1/author-guide.md) | Label changes and write migration fragments |
| [Fragment template](docs/v1/fragment-template.md) | Copy a complete example and adapt it |
| [Consumer maintainer guide](docs/v1/maintainer-guide.md) | Review guides, rerun safely, and prepare publication |
| [Configuration reference](docs/v1/configuration.md) | Supported JSON settings and validation rules |
| [Workflow contract](docs/v1/workflows.md) | Inputs, permissions, sequencing, and trust |
| [Local development](docs/v1/local-development.md) | Preview committed fragments and run tests |
| [Provenance](docs/v1/provenance.md) | Source baseline and extraction boundaries |

The `v1` documentation directory describes the compatibility contract; it is not
a mutable workflow pin. Read documentation at the same commit as your workflow
pins when diagnosing behavior.

## Contribute and maintain

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and pull request
expectations. [MAINTAINERS.md](MAINTAINERS.md) covers toolkit maintenance and the
two-commit payload/workflow pinning procedure. [AGENTS.md](AGENTS.md) records
repository-specific constraints for coding agents.

## This repository uses its own workflows

The [policy caller](.github/workflows/policy.yml) and
[release caller](.github/workflows/release.yml) invoke the two reusable
entrypoints, alongside [toolkit CI](.github/workflows/ci.yml). GitHub resolves
these local calls from the caller's commit; the
reusable wrappers still pin the toolkit payload to literal commit P. External
consumers should continue using the reviewed full-SHA installation examples.

Self-dogfooding requires deployed workflows, the required repository settings,
and canonical labels. It follows the same human review and readiness gates:
no automatic merge, tag creation, or release publication. Passing toolkit CI
does not establish that the end-to-end release and human review lifecycle works
in a particular repository. Follow
[self-dogfooding setup](MAINTAINERS.md#enable-self-dogfooding) to verify it.

## License

This project uses the [MIT license](LICENSE), retaining
`Copyright (c) 2020 Matt Thalman` from the extracted source.
