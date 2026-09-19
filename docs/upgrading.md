# Upgrade toolkit pins

Upgrade the two reusable workflows and both optional publication Actions as
one reviewed dependency. Keep every installed entrypoint on the same full
wrapper commit SHA **W** and matching stable release tag. GitHub executes the
SHA; the trailing tag comment identifies the reviewed release for readers.

## Select and verify a release

Choose a published stable `vMAJOR.MINOR.PATCH` release that contains the
behavior you need. A draft release, an unreleased default-branch commit, and a
published tag are not interchangeable. Read the release notes and documentation
at the selected SHA, not just the default-branch documentation.

From an authenticated GitHub CLI session, replace `TAG` in both commands:

```sh
gh api --hostname github.com repos/mthalman/release-automation/releases/tags/TAG --jq '{tag_name, draft, prerelease, html_url}'
gh api --hostname github.com repos/mthalman/release-automation/commits/TAG --jq .sha
```

Require `draft: false`, `prerelease: false`, and the intended stable tag.
The second command resolves the tag to its full 40-character commit SHA,
including for annotated tags. Do not use a tag object's SHA or infer the commit
from a release's `target_commitish`, which can be a branch name.
Confirm that all four entrypoint files exist at the resolved commit and review
their changes before adopting it. A matching tag is a version identifier, not
evidence that the code is safe or compatible.

For example, these are the four reference forms for the published `v1.0.0`
commit. **This is a pin-format example, not the recommended installation for
the current guide:** that release predates the shared `queue: max` fix. Do not
downgrade a queue-fix installation to obtain a version comment.

```yaml
uses: mthalman/release-automation/.github/workflows/migration-policy.yml@a2018dd1e9ab1371dd6c2f180c35bd94dc7becf3 # v1.0.0
```

```yaml
uses: mthalman/release-automation/.github/workflows/release-draft.yml@a2018dd1e9ab1371dd6c2f180c35bd94dc7becf3 # v1.0.0
```

```yaml
uses: mthalman/release-automation/actions/prepare-release@a2018dd1e9ab1371dd6c2f180c35bd94dc7becf3 # v1.0.0
```

```yaml
uses: mthalman/release-automation/actions/finalize-release@a2018dd1e9ab1371dd6c2f180c35bd94dc7becf3 # v1.0.0
```

These lines belong in separate jobs or steps, not together in one YAML mapping:
the workflows are job-level `uses`; the Actions are step-level `uses`.
Use the complete [installation](installation.md) and
[publication](tag-publishing.md) examples with your verified SHA/tag pair.
Never label a later commit with an earlier release tag, even if that release
is an ancestor. Do not change `@<full SHA>` to `@v1`, `@main`, or `@v1.2.3`.

## Review and synchronize the upgrade

Before adopting a revision that requires introductory paragraphs, add a brief
description of each breaking change after the title in retained fragments.
Update retained migration topics through reviewed corrections, placing the
introduction after the version metadata and before the detailed sections.
Preserve published guide paths and existing guidance; do not regenerate or
delete published history. Existing documents without introductions fail
validation, including retained topics checked during draft planning.
See the [fragment template](fragment-template.md) for the required format.

1. Verify the proposed tag-to-SHA mapping using the commands above. Review the
   release notes and the diff from your old SHA to the new SHA. A digest-only
   change under an unchanged tag needs investigation, not automatic acceptance.
2. Update both workflow refs and any installed prepare/finalize Action refs to
   the same W, with the same truthful tag comments. Check all installed
   entrypoints even if the bot's PR includes only some of them. Preserve caller
   permissions, publication guards, and the documented concurrency settings.
3. Search your repository's Markdown for `mthalman/release-automation`.
   Update documentation links containing `/blob/<old SHA>/` or
   `/tree/<old SHA>/` to W. Update embedded workflow and Action examples to W,
   with matching tag comments, and update nearby version text. Confirm each
   linked path and heading exists at W. Preserve deliberately historical
   references and explain those exceptions in the PR.
4. Review the workflow pins, comments, documentation links, and embedded
   examples together in the same PR. Dependabot's `github-actions` ecosystem
   does **not** update SHA-pinned
   Markdown links or YAML examples inside Markdown. Grouping its dependencies
   does not change that scope. Manual synchronization during review is the
   default procedure; no new automation is required.
5. Run your workflow checks and exercise policy and drafting after deployment.
   Refresh existing drafts with a successful updated drafting run before tag
   publication. Verify publication separately in a test repository as described
   in [tag publishing](tag-publishing.md#verify-the-installation).

## Optionally group future Dependabot updates

Dependabot's `github-actions` ecosystem supports SHA-pinned reusable workflow
calls and subdirectory Actions. Dependabot can update bare-SHA reusable workflow
and Action references without version comments. Its
[GitHub Actions update logic](https://github.com/dependabot/dependabot-core/blob/main/github_actions/lib/dependabot/github_actions/update_checker.rb)
can use a matching release tag or look for a containing branch for an untagged
commit. An untagged pin therefore does not necessarily track stable releases.
Use a verified release SHA and matching tag comment for a clear, portable
convention; do not rely on missing comments to prevent Dependabot updates.

In the consuming repository, add this configuration to `.github/dependabot.yml`.
If you already have a `github-actions` entry, merge the `release-automation`
group into it instead of adding a duplicate entry. Preserve your existing
schedule, labels, and other ecosystems:

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    groups:
      release-automation:
        patterns:
          - "mthalman/release-automation"
          - "mthalman/release-automation/*"
```

The wildcard includes the reusable workflow and subdirectory Action dependency
names; the repository-only pattern also covers references identified by the
repository name. This group includes major, minor, and patch version updates
without changing full-SHA pinning. See the
[Dependabot `groups` reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#groups--).
The group applies to version updates by default, not security updates.

Grouping does not enforce four-way equality or review compatibility. Check for
earlier groups that also match these dependencies, restrictive `allow` or
`ignore` rules, and update-type filters. Do not automatically merge the group
or accept a partial upgrade. This toolkit repository also uses Dependabot,
but its internal payload pins require exclusions rather than this consumer group.

## Use an unreleased commit only as an explicit exception

If required fixes have no published stable release yet, review and pin the same
reachable full SHA in all installed entrypoints and documentation links. Leave
those `uses` lines without version comments; record the reason and the release
needed to remove the exception in your upgrade PR or tracking issue.
Dependabot may still propose updates for those untagged SHAs. To hold the
reviewed exception until a suitable release exists, add these temporary
exclusions under your existing `github-actions` entry:

```yaml
    ignore:
      - dependency-name: "mthalman/release-automation"
      - dependency-name: "mthalman/release-automation/*"
```

Do not add a guessed future tag, a draft release's name, or an older tag that
does not resolve to that exact SHA. A prerelease toolkit revision is likewise
an explicit opt-in, not the stable-release default; pin its reviewed SHA and
manage the exception manually. This does not add support for prerelease tags
in a consumer's own release stream.

Once a suitable stable release is published, verify its actual tag target and
changes, then update all entrypoint SHAs, matching stable-tag comments, and
documentation links in one reviewed PR. The released commit can differ from
the temporary SHA; do not merely append a tag comment to the old pin.
Remove only these temporary toolkit exclusions so Dependabot can propose
subsequent release updates.

## Keep internal payload pins separate

This section is for maintainers of `mthalman/release-automation` itself, not
consuming repositories.

The toolkit's internal trusted payload **P** is not the public wrapper release
**W**. Its reusable workflows fetch P via `with.ref`; its own publication
workflow pins both Actions to P to avoid a self-reference to W. Those pins are
intentional managed exceptions to public release-tag comments. Local reusable
workflow calls have no `@ref` or version comment at all.

Do not attach W's release tag to P or let a dependency bot update these pins
independently. Follow the
[two-commit payload protocol](../MAINTAINERS.md#update-the-immutable-payload-pins)
and verify payload equivalence. This repository's Dependabot configuration
explicitly ignores its own dependency name and subpaths. Unlike a consumer's
temporary unreleased-pin exception, these internal exclusions remain in place
when a stable release is published. The consumer group above is not a
replacement for the maintainer procedure.
