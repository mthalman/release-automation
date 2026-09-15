# Write release notes and migration fragments

Use pull request labels to describe the release impact of your change. For a
breaking change, add a migration fragment before requesting review. Paths and
labels below are defaults; use your repository's configured equivalents.

## Choose labels

Use **exactly one** semantic-version label and **at most one** category label
as a contributor convention:

| Change | Version label | Optional category label |
| --- | --- | --- |
| Breaking behavior or API change | `semver:major` | The relevant category, if needed |
| Backward-compatible feature | `semver:minor` | `enhancement` |
| Bug fix | `semver:patch` | `bug` |
| Documentation | `semver:patch` | `documentation` |
| Dependency update | The appropriate semantic-version label | `dependencies` |
| Other maintenance | `semver:patch` | None |

The migration policy does not globally enforce exactly-one version label or
at-most-one category label. Release Drafter retains its highest-conflicting-bump
behavior and patch fallback. Missing or conflicting labels can therefore
produce a draft rather than fail; maintainers must review them.

`semver:major` takes precedence in the unified **Breaking Changes** category.
Other exclusive categories are **Features**, **Bug Fixes**, **Documentation**,
and **Dependencies**, followed by **Maintenance** as the fallback. Dependencies
collapse after five entries. Category labels are canonical names, not `type:*`
aliases.

For a non-breaking change that should not appear in release notes, use
`skip-changelog`. Release Drafter pre-excludes that PR before category and
version resolution. **Never combine `semver:major` and `skip-changelog`: policy
rejects it.** Do not hide a breaking change by removing its major label.

## Add a breaking fragment

1. Add a new file directly under `.changes`, using the name
   `+short-kebab-slug.breaking.md`, for example
   `.changes/+explicit-owner-option.breaking.md`.
2. Copy the example in the [fragment template](fragment-template.md), then
   replace its prose and code with the actual change.
3. Start with one H3 (`###`) title and include these meaningful H4 (`####`)
   sections in exactly this order:

   1. Previous behavior
   2. New behavior
   3. Type of breaking change
   4. Reason for change
   5. Recommended action
   6. Affected APIs

4. Add the configured major label and request review.

The filename uses lowercase ASCII letters, digits, and single hyphen-separated
words. The leading `+` and `.breaking.md` suffix are required. Do not use the
reserved slug `readme` or nested directories.

A major PR must **add** a new valid fragment. Editing an existing fragment does
not satisfy the requirement to document a new breaking change. Fragments are
retained in Git forever: do not delete or rename them after a release.
Non-breaking PRs do not need migration fragments; normal release-note entries
come from their titles and labels.

## Make the fragment actionable

Explain the observable old and new behavior. Identify whether the change
affects source compatibility, binary compatibility, behavior, or configuration,
as appropriate for the product. Explain why it changed and give a concrete
migration step. Name the affected APIs, commands, or configuration settings.
If there is no API change, explain which user-facing behavior is affected
instead of writing only `N/A`.

Every required section needs real content. Empty sections, comment-only
sections, and placeholder-only values such as `TODO`, `TBD`, or `N/A` are
invalid. Keep the title as the only H3; body headings are H4 or deeper. Do not
insert reserved migration-note or topic markers.

Use fenced code blocks for examples. The renderer preserves heading-like code
and literal strings such as `$OWNER`; do not pre-expand or escape them merely
because Release Drafter also uses dollar-prefixed variables.

## Preview committed content

Commit the fragment in your development repository, then use a trusted toolkit
checkout to [render a read-only preview](local-development.md#preview-migration-notes).
The renderer reads Git objects, so uncommitted fragment edits do not appear.

## Correct a change after it merges

Before publication, edit the retained source fragment in a normal PR and let
automation regenerate the pending guide. Do not manually edit the automation
branch: its generated files can be overwritten on the next run.

After publication, retain the published guide and its URL. Submit a reviewed
correction to the guide when necessary; regeneration must not replace
reviewed published corrections. See the
[maintainer guide](maintainer-guide.md#retain-source-and-published-history)
for pending-version cleanup and release-link retention.
