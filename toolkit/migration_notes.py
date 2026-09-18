import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from configuration import ASSETS, DEFAULT, Config, load_config, strict_json
from repository import committed_file, git

FRAGMENTS = ".changes"
GUIDE_STATE = ".github/migration-guides.json"
FILENAME = re.compile(r"\+[a-z0-9]+(?:-[a-z0-9]+)*\.breaking\.md")
STABLE_TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", re.ASCII)
MIGRATION_START = "<!-- migration-notes:start -->"
MIGRATION_END = "<!-- migration-notes:end -->"
TOPIC_MARKER_PREFIX = "<!-- migration-topic:"
REQUIRED_SECTIONS = (
    "Previous behavior",
    "New behavior",
    "Type of breaking change",
    "Reason for change",
    "Recommended action",
    "Affected APIs",
)
AUTOLINK = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\x00-\x20<>]*|"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>"
)


def changed_files(repo: Path, base: str, head: str, directory: str = FRAGMENTS) -> list[tuple[str, str]]:
    entries = git(
        repo, "diff", "--name-status", "--no-renames", "-z", base, head, "--", directory
    ).split("\0")
    return list(zip(entries[0:-1:2], entries[1:-1:2]))


def markdown_lines(
    text: str, *, include_fenced: bool = True, hide_comments: bool = False,
    validate_format: bool = False,
) -> Iterator[tuple[str, re.Match[str] | None]]:
    """Ignore comments for validation, preserving raw offsets and code literals."""
    fence = ""
    in_comment = False
    literal_end = 0
    line_end = 0
    for raw_line in text.splitlines(keepends=True):
        line_end += len(raw_line)
        line = raw_line.rstrip("\r\n")
        if fence:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line):
                fence = ""
            if include_fenced:
                yield raw_line, None
            continue
        opening = None if in_comment else re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening and (opening[1][0] == "~" or "`" not in opening[2]):
            fence = opening[1]
            if include_fenced:
                yield raw_line, None
            continue
        visible = ""
        heading_line = ""
        remaining = raw_line
        while remaining:
            if in_comment:
                end = remaining.find("-->")
                length = end + 3 if end != -1 else len(remaining)
                heading_line += re.sub(r"[^\r\n]", " ", remaining[:length])
                visible += re.sub(r"[^\r\n]", "", remaining[:length])
                remaining = remaining[length:]
                in_comment = end == -1
            elif literal_end > line_end - len(remaining):
                length = min(len(remaining), literal_end - (line_end - len(remaining)))
                visible += remaining[:length]
                heading_line += remaining[:length]
                remaining = remaining[length:]
            else:
                token = re.search(r"<|`+", remaining)
                if token is None:
                    visible += remaining
                    heading_line += remaining
                    break
                start = token.start()
                visible += remaining[:start]
                heading_line += remaining[:start]
                remaining = remaining[start:]
                offset = line_end - len(remaining)
                prefix = raw_line[:len(raw_line) - len(remaining)]
                escaped = len(re.search(r"\\*$", prefix)[0]) % 2
                if token[0] == "<":
                    if not escaped and remaining.startswith("<!--"):
                        in_comment = True
                    elif not escaped and (autolink := AUTOLINK.match(remaining)):
                        literal_end = offset + autolink.end()
                    elif not escaped and validate_format and re.match(r"</?[A-Za-z]|<[!?]", remaining):
                        # Attribute backticks must never turn an HTML opener into a code span.
                        raise ValueError(
                            "Raw HTML is not supported in migration documents; "
                            "use Markdown or a code example instead."
                        )
                    else:
                        visible += "<"
                        heading_line += "<"
                        remaining = remaining[1:]
                else:
                    delimiter = rf"(?<!`){re.escape(token[0])}(?!`)"
                    following = remaining[len(token[0]):].rstrip("\r\n")
                    closing = None if escaped else re.search(delimiter, following)
                    if closing:
                        literal_end = offset + len(token[0]) + closing.end()
                    else:
                        if not escaped and validate_format:
                            # Look ahead only to reject, never to shield text on later lines.
                            continuation = re.split(
                                r"\r?\n[ \t]*\r?\n", text[offset + len(token[0]):], maxsplit=1
                            )[0]
                            if re.search(delimiter, continuation):
                                raise ValueError(
                                    "Inline code must stay on a single line; "
                                    "use fenced code blocks for multiline examples."
                                )
                        length = 1 if escaped else len(token[0])
                        visible += remaining[:length]
                        heading_line += remaining[:length]
                        remaining = remaining[length:]
        yield (
            visible if hide_comments else raw_line,
            re.match(r" {0,3}(#{1,6})(?:[ \t]+(.*)|$)", heading_line.rstrip("\r\n")),
        )


def shift_heading_levels(text: str, offset: int) -> str:
    lines = []
    for line, heading in markdown_lines(text):
        if heading:
            level = len(heading[1]) + offset
            if not 1 <= level <= 6:
                raise ValueError(f"Cannot shift Markdown heading {heading[0]!r} to level {level}.")
            line = line[:heading.start(1)] + "#" * level + line[heading.end(1):]
        lines.append(line)
    return "".join(lines)


def find_section(text: str, title: str | None, level: int = 4) -> tuple[int, str]:
    content = []
    position = -1
    active = False
    for line_number, (raw_line, heading) in enumerate(markdown_lines(text, hide_comments=True, validate_format=True)):
        if heading:
            if len(heading[1]) > level:
                continue
            if active:
                break
            heading_title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2] or "").strip()
            if len(heading[1]) == level and (title is None or heading_title == title):
                position = line_number
                active = True
                continue
        if active:
            content.append(raw_line)
    return position, "".join(content)


def validate_fragment(name: str, text: str, config: Config = DEFAULT) -> None:
    if not FILENAME.fullmatch(PurePosixPath(name).name) or PurePosixPath(name).parent.as_posix() != config.fragment_root:
        raise ValueError(
            f"Invalid migration fragment filename: {name}. "
            f"Use {config.fragment_root}/+short-description.breaking.md."
        )
    if PurePosixPath(name).name == "+readme.breaking.md":
        raise ValueError(f"{name}: migration fragment filename 'readme' is reserved for the version index.")
    if MIGRATION_START in text or MIGRATION_END in text or TOPIC_MARKER_PREFIX in text:
        raise ValueError(f"{name}: migration fragment contains a reserved release-note marker.")
    first_line, _ = next(markdown_lines(text, hide_comments=True, validate_format=True), ("", None))
    title = re.match(r"### ([^\n]+)\n", first_line)
    if (
        not re.match(r"### [^\n]+\n", text)
        or not title
        or not re.sub(r"[ \t]+#+[ \t]*$", "", title[1]).strip()
    ):
        raise ValueError(f"{name}: migration fragment must start with a level-three title.")
    positions = []
    for heading in REQUIRED_SECTIONS:
        position, section = find_section(text, heading)
        content = section.strip()
        if not content or content.upper().rstrip(".") in ("TODO", "TBD", "N/A"):
            raise ValueError(f"{name}: migration fragment needs a completed '#### {heading}' section.")
        positions.append(position)
    if positions != sorted(positions):
        raise ValueError(
            f"{name}: required sections must appear in this order: "
            + ", ".join(REQUIRED_SECTIONS) + "."
        )
    for line_number, (_, heading) in enumerate(markdown_lines(text, validate_format=True)):
        if line_number > 0 and heading and len(heading[1]) <= 3:
            raise ValueError(
                f"{name}: migration fragment body headings must be level four or deeper; "
                "only the opening title may be level three."
            )


def validate_guide(name: str, text: str, config: Config = DEFAULT) -> None:
    text = text.replace("\r\n", "\n")
    if name == f"{config.guide_root}/README.md":
        return
    path = re.fullmatch(rf"{re.escape(config.guide_root)}/([^/]+)/([^/]+)\.md", name)
    if not path or not STABLE_TAG.fullmatch(f"v{path[1]}"):
        raise ValueError(f"Invalid migration guide path: {name}.")
    if path[2] == "README":
        return
    visible = "".join(
        line for line, _ in markdown_lines(text, include_fenced=False, hide_comments=True, validate_format=True)
    )
    metadata = [
        line for line in visible.splitlines()
        if line.lstrip().startswith("**Version introduced:**")
    ]
    if metadata != [f"**Version introduced:** {path[1]}"]:
        raise ValueError(
            f"{name}: Version introduced must match its version directory and appear "
            "exactly once outside examples/comments."
        )
    position, _ = find_section(text, "Breaking changes and migration", level=2)
    # Remove comments before slicing so their state survives the guide preamble.
    visible_lines = [line for line, _ in markdown_lines(text, hide_comments=True)]
    if position != -1:
        start = position + 1
        topic = "".join(visible_lines[start:]).lstrip("\r\n")
    else:
        position, _ = find_section(text, None, level=1)
        if position == -1:
            raise ValueError(f"{name}: migration topic is missing its title heading.")
        start = position
        topic = "".join(visible_lines[start:])
        topic = shift_heading_levels(topic, 2).lstrip(" ")
    original_topic = "".join(text.splitlines(keepends=True)[start:])
    if MIGRATION_START in original_topic or MIGRATION_END in original_topic or TOPIC_MARKER_PREFIX in original_topic:
        raise ValueError(f"{name}: migration fragment contains a reserved release-note marker.")
    validate_fragment(f"{config.fragment_root}/+{path[2]}.breaking.md", topic, config)


def pending_guide_versions(text: str | None) -> list[str]:
    state = strict_json(text) if text is not None else {"pending_versions": []}
    if not isinstance(state, dict) or set(state) != {"pending_versions"}:
        raise ValueError("Invalid migration guide state.")
    pending = state["pending_versions"]
    if not isinstance(pending, list) or any(
        not isinstance(version, str) or not STABLE_TAG.fullmatch(f"v{version}") for version in pending
    ) or len(pending) != len(set(pending)):
        raise ValueError("Invalid pending migration guide versions.")
    return pending


def check_pr(repo: Path, base: str, head: str, labels: list[str], config: Config = DEFAULT) -> None:
    label_names = {label.casefold() for label in labels}
    breaking = config.labels.major.casefold() in label_names
    if breaking and config.labels.skip.casefold() in label_names:
        raise ValueError(f"Breaking-change PRs must not use {config.labels.skip}.")
    branch_base = git(repo, "merge-base", base, head).strip()
    changes = changed_files(repo, branch_base, head, config.fragment_root)
    for status, name in changes:
        if status == "D":
            raise ValueError(f"Keep migration fragments in Git; do not delete or rename {name}.")
        validate_fragment(name, git(repo, "show", f"{head}:{name}"), config)
    if breaking and not any(status == "A" for status, _ in changes):
        raise ValueError(
            f"{config.labels.major} PRs must add a new migration fragment in {config.fragment_root}; "
            "editing an existing note does not document a new breaking change."
        )
    guide_changes = changed_files(repo, branch_base, head, config.guide_root)
    pending_guide_versions(committed_file(repo, base, config.state_path))
    state_changes = changed_files(repo, branch_base, head, config.state_path)
    if state_changes:
        if any(status == "D" for status, _ in state_changes):
            raise ValueError("Keep migration guide state in Git; do not delete it.")
        pending_guide_versions(committed_file(repo, head, config.state_path))
    pending = []
    if any(status == "D" and name.endswith(".md") for status, name in guide_changes):
        state_files = git(
            repo, "ls-tree", "-rz", "--name-only", base, "--", config.state_path
        ).split("\0")
        pending = pending_guide_versions(
            git(repo, "show", f"{base}:{config.state_path}") if config.state_path in state_files else None
        )
    for status, name in guide_changes:
        if not name.endswith(".md"):
            continue
        if status == "D":
            parts = name.removeprefix(config.guide_root + "/").split("/")
            if len(parts) != 2 or parts[0] not in pending:
                raise ValueError(
                    f"Cannot delete or rename {name}: "
                    "its version must be pending at the PR base."
                )
        else:
            validate_guide(name, git(repo, "show", f"{head}:{name}"), config)


def render(repo: Path, base: str | None, head: str, config: Config = DEFAULT) -> str:
    if base:
        base_commit = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", base_commit, head], cwd=repo
        )
        if ancestor.returncode == 1:
            raise ValueError("The previous release must be an ancestor of the draft commit.")
        ancestor.check_returncode()
        names = [name for status, name in changed_files(repo, base, head, config.fragment_root) if status == "A"]
    else:
        names = git(repo, "ls-tree", "-rz", "--name-only", head, "--", config.fragment_root).split("\0")
        names = [name for name in names if name]
    if not names:
        return ""

    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        for asset in ("towncrier.toml", "migration-notes.md.jinja"):
            (staging / asset).write_bytes((ASSETS / asset).read_bytes())
        for name in sorted(names):
            text = git(repo, "show", f"{head}:{name}")
            validate_fragment(name, text, config)
            slug = PurePosixPath(name).name.removeprefix("+").removesuffix(".breaking.md")
            text = f"{TOPIC_MARKER_PREFIX} {slug} -->\n{text}"
            target = staging / ".changes" / PurePosixPath(name).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        output = subprocess.check_output(
            [sys.executable, "-I", "-X", "utf8", "-m", "towncrier", "build", "--draft",
             "--version", "Unreleased", "--dir", str(staging)],
            text=True, encoding="utf-8", cwd=staging,
        )
    if "## Breaking changes and migration" not in output or not output.strip():
        raise ValueError("Towncrier did not render the migration notes.")
    return output.strip() + "\n\n"


def previous_tag(preview: str) -> str | None:
    marker = re.match(r"\A<!-- migration-base: ([^\r\n]*?) -->", preview)
    if not marker:
        raise ValueError("Release Drafter preview is missing its migration-base marker.")
    if marker[1] and not STABLE_TAG.fullmatch(marker[1]):
        raise ValueError("Release Drafter previous tag must be a stable vMAJOR.MINOR.PATCH tag.")
    return marker[1] or None


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--event", type=Path, required=True)
    build = commands.add_parser("render")
    build.add_argument("--base", help="Previous published release tag; omit for Drafter preview.")
    build.add_argument("--head", default="HEAD")
    for command in (check, build):
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--default-branch", default="main")
        command.add_argument("--config-path", default="")
    args = parser.parse_args()
    repo = Path(git(args.repo, "rev-parse", "--show-toplevel").strip())
    if args.command == "check":
        event = json.loads(args.event.read_text(encoding="utf-8"))
        pr = event["pull_request"]
        config = load_config(repo, pr["base"]["sha"], args.config_path, args.default_branch)
        check_pr(repo, pr["base"]["sha"], pr["head"]["sha"],
                 [label["name"] for label in pr["labels"]], config)
        print("Migration note policy passed.")
    else:
        tag = args.base if args.base is not None else previous_tag(os.environ["RELEASE_PREVIEW"])
        base = f"refs/tags/{tag}" if tag else None
        config = load_config(repo, args.head, args.config_path, args.default_branch)
        notes = render(repo, base, args.head, config)
        print(notes, end="")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Migration notes failed: {error}", file=sys.stderr)
        sys.exit(1)
