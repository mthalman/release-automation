# Breaking fragment template

Copy only the Markdown inside the outer fence into
`.changes/+explicit-owner-option.breaking.md`, or another descriptive unused
slug. Replace the example with the real change. Keep the opening H3, a brief
introductory paragraph describing the breaking change, and all six H4 section
names in this order. The introduction and each section need meaningful content.

````markdown
### Require an explicit owner for repository lookups

The `lookup` command no longer defaults to the current user's account. Scripts
and interactive invocations must now specify the repository owner explicitly.

#### Previous behavior

The `lookup` command used the current user's account when `--owner` was omitted.

#### New behavior

The `lookup` command requires `--owner` and reports an error when it is missing.

#### Type of breaking change

This is a command-line behavior change. Scripts that omit `--owner` stop with a
nonzero exit code.

#### Reason for change

An explicit owner prevents lookups from changing targets when the authenticated
account changes.

#### Recommended action

Add the repository owner to each invocation:

```sh
lookup --owner "$OWNER" --repository sample
```

#### Affected APIs

The `lookup` command's `--owner` option is now required. The HTTP API is unchanged.
````

The code block deliberately contains literal `$OWNER`. It is example text, not
a release-template variable to substitute. This document is a template guide,
not a consumer fragment to install in the toolkit repository.
