# Release automation documentation

These documents describe the consumer contract at this repository revision.
Read them at the same commit as your workflow pins so the guidance matches
the implementation you use.

## Install and operate

1. [Install the workflows](installation.md).
2. [Label pull requests and write fragments](author-guide.md).
3. [Review generated guides and prepare releases](maintainer-guide.md).
4. Optionally [publish from a tag with consumer-owned steps](tag-publishing.md).
5. [Upgrade toolkit pins and documentation links together](upgrading.md).

## Look up details

- [Configuration reference](configuration.md): defaults, overrides, and rejected
  values.
- [Workflow contract](workflows.md): permissions, trusted inputs, ordered
  operations, and limitations.
- [Tag publishing](tag-publishing.md): prepare/finalize inputs and outputs,
  publication checks, custom steps, reruns, and cross-job context.
- [Fragment template](fragment-template.md): a copyable, completed example.
- [Local development](local-development.md): read-only preview, policy checks,
  and tests.

## Develop the toolkit

See [contribution instructions](../CONTRIBUTING.md) and
[toolkit maintenance](../MAINTAINERS.md) for repository development and
immutable payload pin updates.
