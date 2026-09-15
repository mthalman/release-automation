# Run local previews and checks

Use a trusted checkout of this toolkit to inspect a separate consumer
repository. Local `render` and `check` commands are read-only with respect to
the consumer repository: they do not open PRs, update releases, publish, or
write generated guides into the consumer worktree.

Git and Python 3.13 are required. Rendering also uses the toolkit's pinned
Towncrier dependency. Policy validation uses only the Python standard library.

## Set up Python

From the toolkit repository on a system exposing `python3.13`:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r toolkit/requirements.txt
```

On Windows with the Python launcher:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r toolkit\requirements.txt
```

Use Python 3.13, not an unreviewed newer runtime. `toolkit/requirements.txt`
pins the complete dependency set:

| Package | Version | Installation scope |
| --- | --- | --- |
| Towncrier | 26.9.0 | All platforms |
| Click | 8.5.0 | All platforms |
| Jinja2 | 3.1.6 | All platforms |
| MarkupSafe | 3.0.3 | All platforms |
| Colorama | 0.4.6 | Windows only, through the `sys_platform == "win32"` marker |

Install from the requirements file instead of selecting dependencies
individually. You do not need to install this project from PyPI.

## Preview migration notes

Run from the trusted toolkit checkout. Both `--repo` and `--default-branch` are
required. The `--repo` argument identifies the consumer repository, not the
toolkit:

```powershell
python -I toolkit\run.py render --repo C:\path\to\consumer --head HEAD --base v1.0.0 --default-branch main
```

On a POSIX shell, the equivalent is:

```sh
python -I toolkit/run.py render --repo /path/to/consumer --head HEAD --base v1.0.0 --default-branch main
```

Use the actual repository default branch and a real previous stable release
tag. Fetch the relevant history and tags before previewing; the previous
release must be an ancestor of the selected head. The command reads committed
Git objects, so commit fragment or configuration edits before previewing.

Add `--config-path .github/release-automation.json` to use configuration
committed at the selected head. Omit it for defaults.

For an **initial release** with no previous release, omit `--base`:

```powershell
python -I toolkit\run.py render --repo C:\path\to\consumer --head HEAD --default-branch main
```

Locally, omission of `--base` means initial-release rendering; it does not
discover the latest published release for you. The reusable draft workflow
instead obtains the previous release tag from its Release Drafter dry run.

Expect migration Markdown on standard output, or no migration content when no
breaking fragments apply. This preview does not resolve a release version,
prove remote readiness, or substitute for the workflow's full-history/API
checks.

## Check a pull request event

Use a saved GitHub pull request event JSON file containing the base and head
commit data and labels for the PR you want to evaluate. Ensure those commits
are available in the local consumer repository. Use synthetic or non-sensitive
event data when sharing a reproduction.

```powershell
python -I toolkit\run.py check --repo C:\path\to\consumer --event event.json --default-branch main
```

Add `--config-path .github/release-automation.json` when appropriate. Check
loads configuration and deletion-authorizing state from the event's PR base,
not from proposed head configuration. A successful check exits with
status zero; invalid policy input fails with a diagnostic.

`-I` enables Python isolated mode. Invoke `toolkit/run.py` from the trusted
toolkit checkout, not a script supplied by the consumer PR. The local command
does not grant a script from an untrusted checkout the workflow's trust model.

## Run toolkit tests

From the toolkit repository:

```powershell
python -m unittest discover -s tests -q
```

Tests add their own toolkit import paths; no global `PYTHONPATH` change is
needed. The suite includes
[a PR #108 baseline comparison](../../tests/test_baseline.py) against
[output captured from the actual upstream implementation](../../tests/fixtures/pr108-output.json).
It checks exact rendered notes, generated documents and state, indexes, and the
unified release body, including a fenced literal `$OWNER` example.

The [review regression tests](../../tests/test_review_regressions.py) cover
canonical guide metadata, supported previous-release boundaries, and
case-insensitive breaking-change/exclusion label checks.

For workflow edits, run the existing linter when installed:

```powershell
actionlint
```

The repository's [CI workflow](../../.github/workflows/ci.yml) runs the unit
suite on Linux and Windows with Python 3.13. It also runs workflow validation
with actionlint built from a literal immutable source commit corresponding to
v1.7.12, not a mutable tag. CI listens to ordinary `pull_request` events, including
`ready_for_review`, pushes to `main`, and manual dispatch. It tests the proposed
toolkit code; the separate trusted policy workflow validates PR data.

Do not claim a live Actions run based on local unit tests or lint. Repository
permissions, token-trigger behavior, actual nested check names, and the human
review/merge loop need validation in a test consumer repository.

## Report a reproducible problem

Record the toolkit wrapper pin, Python version, command, consumer commit
identifiers, relevant labels, and non-sensitive output. Use a small synthetic
Git repository to reproduce history and configuration problems. Never include
publication tokens or private source in public reports.
