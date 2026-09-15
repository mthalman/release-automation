import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from configuration import Config, drafter_config, load_config, resolve_labels, strict_json
from migration_notes import check_pr, render
from repository import git
from update_release_draft import api, process_preview


def github_repository() -> str:
    if os.environ.get("GITHUB_SERVER_URL", "https://github.com") != "https://github.com":
        raise ValueError("This version supports github.com repositories only.")
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GITHUB_REPOSITORY.")
    return repository


def output_values(values: dict[str, str]) -> None:
    if "GITHUB_OUTPUT" in os.environ:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for key, value in values.items():
                if "\n" in value or "\r" in value:
                    raise ValueError(f"Multiline workflow output: {key}.")
                output.write(f"{key}={value}\n")


def verify_documentation_pr(pr: dict, config: Config, *, require_draft: bool = True) -> None:
    labels = [label["name"].casefold() for label in pr["labels"]]
    semver = {name.casefold() for name in (config.labels.major, config.labels.minor, config.labels.patch)}
    categories = {
        config.labels.feature, config.labels.fix,
        config.labels.documentation, config.labels.dependencies,
    }
    categories = {name.casefold() for name in categories}
    if ((require_draft and pr["draft"] is not True)
            or [label for label in labels if label in semver] != [config.labels.patch.casefold()]
            or [label for label in labels if label in categories] != [config.labels.documentation.casefold()]
            or config.labels.skip.casefold() in labels):
        draft_rule = "must be draft and " if require_draft else "must "
        raise ValueError(
            f"Documentation PR {draft_rule}have {config.labels.patch} and "
            f"{config.labels.documentation}, no other configured version/category labels, "
            f"and no {config.labels.skip}."
        )


def execute() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "render", "configuration", "snapshot", "prepare", "update", "verify-pr"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--config-path", default="")
    parser.add_argument("--base")
    parser.add_argument("--event", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--require-draft", choices=("true", "false"), default="true")
    args = parser.parse_args()
    repo = Path(git(args.repo, "rev-parse", "--show-toplevel").strip())
    if args.command == "check":
        if not args.event:
            parser.error("check requires --event")
        pr = json.loads(args.event.read_text(encoding="utf-8"))["pull_request"]
        for ref in (pr["base"]["sha"], pr["head"]["sha"]):
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                raise ValueError("PR base/head must be full commit SHAs.")
        config = load_config(repo, pr["base"]["sha"], args.config_path, args.default_branch)
        check_pr(repo, pr["base"]["sha"], pr["head"]["sha"],
                 [label["name"] for label in pr["labels"]], config)
        print("Migration note policy passed.")
        return
    commit = git(repo, "rev-parse", "--verify", f"{args.head}^{{commit}}").strip()
    config = load_config(repo, commit, args.config_path, args.default_branch)
    if args.command == "render":
        if args.base and not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", args.base):
            raise ValueError("--base must be a stable vMAJOR.MINOR.PATCH tag.")
        print(render(repo, f"refs/tags/{args.base}" if args.base else None, commit, config), end="")
        return
    if args.command == "configuration":
        if not args.output:
            parser.error("configuration requires --output")
        if not args.labels:
            parser.error("configuration requires --labels")
        config = resolve_labels(config, strict_json(args.labels.read_text(encoding="utf-8")))
        destination = args.output.resolve()
        if destination.is_relative_to(repo.resolve()):
            raise ValueError("Materialized Release Drafter config must be outside the consumer repository.")
        destination.write_text(json.dumps(drafter_config(config), indent=2) + "\n", encoding="utf-8")
        output_values({
            "sha": commit, "config-file": str(destination),
            "guide-root": config.guide_root, "state-path": config.state_path,
            "automation-branch": config.automation_branch,
            "patch-label": config.labels.patch, "documentation-label": config.labels.documentation,
        })
        return
    repository = github_repository()
    if args.command == "verify-pr":
        if not args.pr or args.pr < 1:
            parser.error("verify-pr requires a positive --pr number")
        pr = json.loads(subprocess.check_output(
            ["gh", "api", f"repos/{repository}/pulls/{args.pr}"], text=True, encoding="utf-8",
        ))
        verify_documentation_pr(pr, config, require_draft=args.require_draft == "true")
        print("Documentation PR draft status and labels verified.")
        return
    if not args.snapshot:
        parser.error(f"{args.command} requires --snapshot")
    if args.command == "snapshot":
        args.snapshot.write_text(json.dumps(api(f"repos/{repository}/releases")), encoding="utf-8")
        return
    if not args.labels:
        parser.error(f"{args.command} requires --labels")
    frozen_labels = resolve_labels(config, strict_json(args.labels.read_text(encoding="utf-8"))).labels
    if resolve_labels(config, api(f"repos/{repository}/labels")).labels != frozen_labels:
        raise ValueError("Repository release labels changed during generation; rerun the release workflow.")
    ready = process_preview(
        repo, commit, os.environ["RELEASE_PREVIEW"], os.environ["RELEASE_NAME"],
        os.environ["RELEASE_TAG"], repository,
        json.loads(args.snapshot.read_text(encoding="utf-8")),
        prepare=args.command == "prepare", config=config,
    )
    if args.command == "prepare":
        output_values({
            "guides-ready": str(ready).lower(),
            "add-state-path": config.state_path if (repo / config.state_path).is_file() else "",
        })
        print("Migration guides match the selected commit." if ready else
              "Waiting for merged migration guides; existing release draft unchanged.")


def main() -> None:
    try:
        execute()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release automation failed: {error}", file=sys.stderr)
        sys.exit(1)
