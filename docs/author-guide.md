# Write release notes and migration fragments

Use pull request labels to describe the release impact of your change. For a
breaking change, add a migration fragment before requesting review. Paths and
label names below are defaults; use your repository's resolved configuration.
The `labels` settings assign label roles, and `categories` sets release-note
category titles. Omitted settings retain their defaults.

## Choose labels

Use **exactly one** configured version label and **at most one** configured
category label as a contributor convention:

| Change | Version role (default label) | Optional category role (default label) |
| --- | --- | --- |
| Breaking behavior or API change | `major` (`semver:major`) | The relevant category, if needed |
| Backward-compatible feature | `minor` (`semver:minor`) | `feature` (`enhancement`) |
| Bug fix | `patch` (`semver:patch`) | `fix` (`bug`) |
| Documentation | `patch` (`semver:patch`) | `documentation` (`documentation`) |
| Dependency update | The appropriate version role | `dependencies` (`dependencies`) |
| Other maintenance | `patch` (`semver:patch`) | None |

The migration policy does not globally enforce exactly-one version label or
at-most-one category label. If configured version labels conflict, Release
Drafter selects the largest requested bump: major before minor before patch.
If no configured label requests a larger bump, it selects patch. Missing or
conflicting labels can therefore produce a draft rather than fail; maintainers
must review them.

The configured `major` label takes precedence in the unified `breaking`
category (default title: **Breaking Changes**). Other exclusive category roles
are `feature`, `fix`, `documentation`, and `dependencies`, followed by
`maintenance` as the fallback. Their default titles are **Features**, **Bug
Fixes**, **Documentation**, **Dependencies**, and **Maintenance**, respectively.
The dependencies category collapses after five entries.

For a non-breaking change that should not appear in release notes, use
the configured `skip` label (default: `skip-changelog`). Release Drafter
pre-excludes that PR before category and version resolution. **Never combine
the configured `major` and `skip` labels: policy rejects it.** Do not hide a
breaking change by removing its configured major label.

Label identities are case-insensitive. Policy uses only the configured `major`
and `skip` identities for the fragment requirement and exclusion conflict.
After an override, the former name has no special meaning unless explicitly
assigned to a role. There are no reserved label names or namespaces:
`skip-changelog` or a `semver:*` name can serve any role, provided all eight
resolved labels remain distinct case-insensitively and satisfy the
[syntax constraints](configuration.md#branch-label-and-title-constraints).
Unrelated labels do not count as configured version, category, or exclusion
labels.

## Include labeling rules in AGENTS.md

Include the labeling rules in your consuming repository's `AGENTS.md` so coding
agents apply them when opening or updating pull requests, rather than relying
on a human to correct labels afterward. This is particularly useful because
the workflow does not enforce the general label-count convention.

Link to this author guide at the same reviewed commit as your workflow pins,
and summarize the expected behavior locally. For example:

```markdown
## Pull request release labels

- Follow the shared release-automation author guide linked in this repository.
- Resolve configuration before choosing labels or fragment paths. Inspect the
  reusable workflow callers' optional config-path at the trusted PR base (or
  the selected default-branch commit when preparing a PR). Discover the actual
  default branch from GitHub repository metadata, not an assumed branch name.
  Read the configured JSON file from that commit and merge its partial
  overrides with the toolkit defaults. With no config-path, use the defaults.
  Do not use proposed PR configuration as the authority for its own checks.
- Before opening or updating a PR, assess its release impact and apply exactly
  one of the resolved labels.major, labels.minor, or labels.patch values.
- Apply at most one of the resolved labels.feature, labels.fix,
  labels.documentation, or labels.dependencies values. Use no category label
  for other maintenance.
- For breaking changes, apply the resolved labels.major value and add a new
  completed migration fragment under the resolved fragment_root. Never combine
  a breaking change with the resolved labels.skip value.
- Use the resolved labels.skip value only for intentionally excluded
  non-breaking changes. Label roles come only from resolved configuration:
  former default names have no special meaning unless assigned to a role.
- Defaults, used only where not overridden: major=semver:major,
  minor=semver:minor, patch=semver:patch, skip=skip-changelog,
  feature=enhancement, fix=bug, documentation=documentation,
  dependencies=dependencies; fragment_root=.changes.
- Recheck labels when the scope of a PR changes, removing conflicting
  configured labels. Unrelated labels do not count toward these conventions.
- If label permissions are unavailable or the release impact is unclear,
  report that explicitly for maintainer review rather than silently skipping it.
```

Add the pinned guide link before adopting the example. Keep that link and the
local summary in sync when upgrading the workflows. Resolve configured values
rather than copying default names as permanent rules. Agent instructions guide
behavior; they do not replace human review or add a new executable policy check.

## Add a breaking fragment

1. Add a new file directly under `.changes`, using the name
   `+short-kebab-slug.breaking.md`, for example
   `.changes/+explicit-owner-option.breaking.md`.
2. Copy the example in the [fragment template](fragment-template.md), then
   replace its prose and code with the actual change.
3. Start with one H3 (`###`) title, followed by a brief introductory paragraph
   describing the breaking change and who or what it affects. Then include
   these meaningful H4 (`####`) sections in exactly this order:

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

A PR with the configured `major` label must **add** a new valid fragment.
Editing an existing fragment does not satisfy the requirement to document a
new breaking change. Fragments are retained in Git forever: do not delete or
rename them after a release.
Non-breaking PRs do not need migration fragments; normal release-note entries
come from their titles and labels.

## Make the fragment actionable

Explain the observable old and new behavior. Identify whether the change
affects source compatibility, binary compatibility, behavior, or configuration,
as appropriate for the product. Explain why it changed and give a concrete
migration step. Name the affected APIs, commands, or configuration settings.
If there is no API change, explain which user-facing behavior is affected
instead of writing only `N/A`.

The introduction and every required section need real content. Empty,
comment-only, and placeholder-only values such as `TODO`, `TBD`, or `N/A` are
invalid. The introduction must be prose before any body heading, not a list,
blockquote, code block, or version metadata. Keep it brief; validation checks
structure and placeholders, not writing quality or a word limit.
Titles, required headings, and their instructions must be visible:
HTML comments cannot supply them, even when a comment spans multiple sections.
Literal HTML-comment examples inside single-line inline code spans or fenced
code blocks remain unchanged.

Keep the title as the only H3; body headings are H4 or deeper. Do not
insert reserved migration-note or topic markers.

## Use the supported Markdown format

Raw HTML is not supported outside code examples. Use Markdown rather than
elements such as `<div>`, `<details>`, or `<script>`; HTML declarations,
processing instructions, and CDATA are also unsupported. Ordinary HTML
comments are allowed but cannot supply required instructions. Put literal HTML
in a single-line inline code span or fenced code block when documenting an API
or syntax. Inline code must start and end on the same source line. Use fenced
code blocks for multiline examples, including examples within lists.
Normal Markdown links and autolinks remain supported.

This explicit subset keeps the trusted validator standard-library-only without
depending on a full HTML/Markdown renderer to decide which guidance is visible.
Before adopting or upgrading the toolkit, convert raw HTML in retained
fragments and migration topics to Markdown or code examples, and convert
multiline inline code spans to fenced blocks.

The renderer preserves heading-like code and literal strings such as `$OWNER`
inside fenced examples. Do not pre-expand or escape them merely because
Release Drafter also uses dollar-prefixed variables.

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
