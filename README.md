# Release automation

Reusable GitHub Actions workflows for release drafting and reviewed migration
guides, with optional tag-driven GitHub Release publication. Pull request labels
drive release notes and version selection. Breaking
change fragments become versioned migration topics in a draft pull request.
The release draft is updated only after the exact generated documentation and
state are committed on the selected default-branch snapshot.

**The reusable workflows remain draft-only.** You can opt in to separate
`prepare-release` and `finalize-release` composite Actions to publish an existing,
prepared GitHub Release after a human pushes its tag. Put arbitrary
consumer-owned `uses` and `run` steps between those Actions. The toolkit has no
tag-creation, retagging, or PR-merge operation and implements no package
publishing. Your repository owns testing, approvals, runners, credentials, and product release
steps. Pre-draft readiness alone is not a publication gate; publication has
[non-atomic API race limitations](docs/tag-publishing.md#what-the-publication-checks-establish).

## Start here

1. Follow [installation](docs/installation.md) to add two small caller
   workflows, create labels, and configure repository permissions.
2. Share the [author guide](docs/author-guide.md) with contributors.
3. Use the [consumer maintainer guide](docs/maintainer-guide.md) to review
   generated guides and prepare a release.
4. Optionally install [tag publishing](docs/tag-publishing.md) to validate a
   pushed tag, run your own release steps, and publish the prepared GitHub Release.

Installation examples contain
`@REPLACE_WITH_REVIEWED_COMMIT_SHA`. This is an installation placeholder,
**not a usable workflow reference**.
Replace it in both callers and any publication Action references with the same
reviewed, reachable, full commit SHA from this repository. No floating branch,
tag, or second tooling ref is required.

## How it works

1. `migration-policy.yml` validates a pull request using trusted base-commit
   configuration and state. A pinned, standard-library-only validator reads
   the proposed files without executing pull request code or installing its
   dependencies.
2. `release-draft.yml` selects the latest repository default-branch commit and
   full history. Release Drafter performs a dry run that resolves one version
   and previous release tag.
3. The workflow renders breaking change fragments with Towncrier. If generated
   guides, indexes, or state need changes, it opens or updates a documentation
   pull request in draft status.
4. A human marks that pull request ready, runs the repository's checks, reviews
   it, and merges it. Automation updates return the pull request to draft.
5. A subsequent run verifies the generated files and state on the selected
   branch, rechecks release state and the remote commit, then creates or updates
   only a draft release, recording preparation metadata for optional tag publishing.
6. If you install a tag workflow, a human pushes the exact prepared stable tag.
   `prepare-release` checks its immutable source and prepared draft. After your
   own steps succeed, `finalize-release` independently rechecks the context and
   publishes that existing GitHub Release without changing its notes.

If documentation changes are needed, the run fails at the readiness step and
leaves an existing release draft unchanged. It does not stay running while
review is pending. If the selected commit already contains the exact required
files, no documentation PR or additional review cycle is needed. See the
[workflow contract](docs/workflows.md) for ordering, trust boundaries, and
race limitations.

## Supported scope

- Repositories on **github.com**, with one release stream on the
  repository's actual default branch.
- Stable tags in the exact form `vMAJOR.MINOR.PATCH`, such as `v2.4.0`.
  Release names contain only the version, such as `2.4.0`.
- Pinned Python and Towncrier tooling, with SHA-pinned Release Drafter and
  create-pull-request workflows. See the [runtime setup](docs/local-development.md#set-up-python),
  [dependency lock](toolkit/requirements.txt), and
  [workflow definitions](.github/workflows) for versions at your selected commit.
- Optional, versioned JSON configuration for paths, labels, and category titles.
  The defaults work without a configuration file. Resolved configuration
  determines every label role and category title; overridden default label
  names have no special meaning unless assigned to a role.

Monorepo version streams, prereleases, arbitrary tag prefixes, GitHub Enterprise
hosts, executable consumer configuration, and automatic migration of consumers'
existing release pipelines are outside the supported scope. There is no PyPI package or
installer to deploy.

## Documentation

| Document | Purpose |
| --- | --- |
| [Documentation index](docs/README.md) | Find the guide for your role |
| [Installation](docs/installation.md) | Install pinned caller workflows |
| [Author guide](docs/author-guide.md) | Label changes and write migration fragments |
| [Fragment template](docs/fragment-template.md) | Copy a complete example and adapt it |
| [Consumer maintainer guide](docs/maintainer-guide.md) | Review guides, rerun safely, and prepare publication |
| [Tag publishing](docs/tag-publishing.md) | Opt in to prepare/finalize Actions around your own release steps |
| [Configuration reference](docs/configuration.md) | Supported JSON settings and validation rules |
| [Workflow contract](docs/workflows.md) | Inputs, permissions, sequencing, and trust |
| [Local development](docs/local-development.md) | Preview committed fragments and run tests |

Git versions the documentation alongside the implementation. Read documentation
at the same commit as your workflow pins when installing, upgrading, or
diagnosing behavior.

## Contribute and maintain

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and pull request
expectations. [MAINTAINERS.md](MAINTAINERS.md) covers toolkit maintenance and the
two-commit payload/workflow pinning procedure. [AGENTS.md](AGENTS.md) records
repository-specific constraints for coding agents.

## This repository uses its own workflows

The [policy caller](.github/workflows/policy.yml) and
[release caller](.github/workflows/release.yml) invoke the two reusable
entrypoints, alongside [toolkit CI](.github/workflows/ci.yml). The separate
[tag workflow](.github/workflows/publish.yml) pins both publication Actions to
the same literal payload P, which includes the Action definitions. It checks
out the prepared source and runs toolkit tests between the Actions, skipping
those consumer-owned steps when the release is already published.
GitHub resolves
these local calls from the caller's commit; the reusable wrappers still pin
the toolkit's code and assets to an immutable commit. External consumers should
continue using the reviewed full-SHA installation examples.

Self-dogfooding requires deployed workflows, the required repository settings,
and the configured labels (the default names for this repository's default
setup). Drafting still never publishes automatically: humans review the draft
and push a tag only after the draft gates pass. The tag workflow can then
publish the prepared GitHub Release; it includes no PR-merge or tag-creation step.
Passing toolkit CI
does not establish that the end-to-end release and human review lifecycle works
in a particular repository. Follow
[self-dogfooding setup](MAINTAINERS.md#enable-self-dogfooding) to verify it.

## License

This project uses the [MIT license](LICENSE).
