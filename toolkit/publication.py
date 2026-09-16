import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from configuration import load_config, strict_json, validate_branch
from entrypoint import github_repository, output_values
from migration_guides import guides_ready, linked_notes, plan_guides
from migration_notes import MIGRATION_END, MIGRATION_START, STABLE_TAG, render
from release_metadata import config_digest, digest, preparation, published_digest, release_identity
from repository import git
from update_release_draft import api


SHA = re.compile(r"[0-9a-f]{40}")


def github(endpoint: str, payload: dict | None = None) -> dict:
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if payload is not None:
        args.extend(["--method", "PATCH", "--input", "-"])
    return json.loads(subprocess.check_output(
        args, input=json.dumps(payload) if payload is not None else None,
        text=True, encoding="utf-8",
    ))


def tag_event(environment: dict, event: dict) -> tuple[str, str, str]:
    ref = environment.get("GITHUB_REF", "")
    if (environment.get("GITHUB_EVENT_NAME") != "push"
            or environment.get("GITHUB_REF_TYPE") != "tag"
            or not ref.startswith("refs/tags/")
            or not STABLE_TAG.fullmatch(ref.removeprefix("refs/tags/"))
            or event.get("ref") != ref or event.get("deleted") is not False
            or event.get("forced") is not False or event.get("created") is not True
            or event.get("before") != "0" * 40
            or event.get("repository", {}).get("full_name") != environment.get("GITHUB_REPOSITORY")):
        raise ValueError(
            "Publication requires a non-forced creation push for an exact stable version tag; "
            "tag updates and deletions cannot publish."
        )
    sha, after = environment.get("GITHUB_SHA", ""), event.get("after", "")
    if not isinstance(after, str) or not SHA.fullmatch(after) or not SHA.fullmatch(sha):
        raise ValueError("The tag event must identify immutable Git objects.")
    return ref.removeprefix("refs/tags/"), sha, after


def select_release(releases: list[dict], tag: str) -> dict:
    matches = [release for release in releases if release["tag_name"] == tag]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one prepared release matching the pushed tag; "
            "verify the draft was prepared and the token can view drafts."
        )
    release = matches[0]
    if (type(release["id"]) is not int or release["id"] <= 0
            or type(release["draft"]) is not bool or release["prerelease"] is not False
            or release["name"] != tag[1:] or not isinstance(release["body"], str)
            or not release["body"].strip()
            or (release["draft"] and release["published_at"])
            or (not release["draft"] and not release["published_at"])):
        raise ValueError("Expected a stable prepared release with a version-only title and valid status.")
    if release["draft"] and sum(item["draft"] for item in releases) != 1:
        raise ValueError("Unrelated or multiple release drafts prevent publication.")
    return release


def remote_tag(repository: str, tag: str) -> str:
    result = github(f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")
    value = result["object"]
    if value["type"] not in ("tag", "commit") or not SHA.fullmatch(value["sha"]):
        raise ValueError("The remote tag must refer to a commit or annotated tag.")
    return value["sha"]


def fetch_source(
    repo: Path, repository: str, branch: str, tag: str, base: str | None,
) -> None:
    git(repo, "init", "-q")
    validate_branch(repo, branch)
    git(repo, "remote", "add", "origin", f"https://github.com/{repository}.git")
    token = os.environ["GH_TOKEN"]
    if not token or "\n" in token or "\r" in token:
        raise ValueError("A GitHub token is required.")
    auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    environment = os.environ.copy()
    config_index = int(environment.get("GIT_CONFIG_COUNT", "0"))
    environment.update({
        "GIT_CONFIG_COUNT": str(config_index + 1),
        f"GIT_CONFIG_KEY_{config_index}": "http.https://github.com/.extraheader",
        f"GIT_CONFIG_VALUE_{config_index}": f"AUTHORIZATION: basic {auth}",
        "GIT_TERMINAL_PROMPT": "0",
    })
    refs = [f"+refs/heads/{branch}:refs/remotes/origin/{branch}", f"+refs/tags/{tag}:refs/tags/{tag}"]
    if base and base != tag:
        refs.append(f"+refs/tags/{base}:refs/tags/{base}")
    subprocess.run(
        ["git", "fetch", "--quiet", "--no-tags", "origin", *refs], cwd=repo,
        env=environment, check=True,
    )


def validate_source(
    repo: Path, branch: str, tag: str, sha: str, after: str, release: dict,
    releases: list[dict], config_path: str,
) -> dict:
    metadata = preparation(release["body"])
    commit = git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").strip()
    tag_object = git(repo, "rev-parse", "--verify", f"refs/tags/{tag}").strip()
    if after != tag_object:
        raise ValueError("Pushed tag object changed since the creation event.")
    if (metadata["tag"] != tag or sha not in (commit, tag_object)
            or release["target_commitish"] != commit or metadata["commit"] != commit):
        raise ValueError("Pushed tag, event, and prepared draft must identify exactly the same commit.")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, f"refs/remotes/origin/{branch}"], cwd=repo,
    )
    if ancestor.returncode == 1:
        raise ValueError("The tagged commit must belong to the current default-branch history.")
    ancestor.check_returncode()
    config = load_config(repo, commit, config_path, branch)
    if config_digest(config) != metadata["config"]:
        raise ValueError("Tagged configuration does not match the prepared draft.")
    if release["draft"]:
        base = metadata["base"]
        if base is not None and (not isinstance(base, str) or not STABLE_TAG.fullmatch(base)):
            raise ValueError("Invalid prepared previous release tag.")
        base_commit = git(repo, "rev-parse", "--verify", f"refs/tags/{base}^{{commit}}").strip() if base else None
        if base_commit != metadata["base_commit"]:
            raise ValueError("The previous release tag changed after drafting.")
        if published_digest(releases) != metadata["published"]:
            raise ValueError("Published release state changed after drafting; prepare a fresh draft.")
        version = tuple(map(int, tag[1:].split(".")))
        if any(not item["draft"] and STABLE_TAG.fullmatch(item["tag_name"])
               and tuple(map(int, item["tag_name"][1:].split("."))) >= version for item in releases):
            raise ValueError("A stable publication must advance the existing release stream.")
        notes = render(repo, f"refs/tags/{base}" if base else None, commit, config)
        references = metadata["guide_references"]
        if (not isinstance(references, list)
                or any(not isinstance(version, str) or not STABLE_TAG.fullmatch(f"v{version}")
                       for version in references)):
            raise ValueError("Invalid prepared guide retention references.")
        # Draft replacement can remove old links. Replay their retention effect, not a moving draft body.
        planning_releases = [item for item in releases if not item["draft"]] + [{
            "draft": True, "body": "\n".join(f"/{config.guide_root}/{version}/" for version in references),
        }]
        documents = plan_guides(repo, commit, notes, tag, planning_releases, config)
        if not guides_ready(repo, commit, documents, config):
            raise ValueError("The tagged commit does not contain the exact prepared migration guides and state.")
        links = linked_notes(notes, tag, os.environ["GITHUB_REPOSITORY"], config)
        expected = f"{MIGRATION_START}\n**Migration guides**\n\n{links.rstrip()}\n{MIGRATION_END}" if links else ""
        body = release["body"].replace("\r\n", "\n")
        if expected:
            if body.count(MIGRATION_START) != 1 or body.count(MIGRATION_END) != 1 or expected not in body:
                raise ValueError("Prepared release migration links do not match the tagged source.")
        elif MIGRATION_START in body or MIGRATION_END in body:
            raise ValueError("Unexpected migration links in the prepared release.")
    return {"sha": commit, "tag-object": tag_object, "release": digest(release_identity(release))}


def inspect_release(repository: str, tag: str, sha: str, after: str, config_path: str) -> tuple[dict, dict]:
    endpoint = f"repos/{repository}/releases"
    releases = api(endpoint)
    release = select_release(releases, tag)
    metadata = preparation(release["body"])
    base = metadata["base"]
    if base is not None and (not isinstance(base, str) or not STABLE_TAG.fullmatch(base)):
        raise ValueError("Invalid prepared previous release tag.")
    branch = github(f"repos/{repository}")["default_branch"]
    with tempfile.TemporaryDirectory(prefix="release-automation-source-") as directory:
        repo = Path(directory)
        fetch_source(repo, repository, branch, tag, base if release["draft"] else None)
        identity = validate_source(repo, branch, tag, sha, after, release, releases, config_path)
        branch_head = git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}").strip()
    current = api(endpoint)
    selected = select_release(current, tag)
    if (digest(release_identity(selected)) != identity["release"]
            or selected["draft"] != release["draft"]
            or published_digest(current) != published_digest(releases)
            or github(f"repos/{repository}")["default_branch"] != branch
            or github(f"repos/{repository}/git/ref/heads/{quote(branch, safe='')}")["object"]["sha"] != branch_head
            or remote_tag(repository, tag) != identity["tag-object"]):
        raise ValueError("Release or source state changed during preparation; retry after review.")
    if release["draft"] and base and remote_tag_commit(repository, base) != metadata["base_commit"]:
        raise ValueError("The previous release tag changed during preparation.")
    identity.update({
        "version": 1, "repository": repository, "tag": tag, "release-id": release["id"],
        "config-path": config_path, "default-branch": branch,
    })
    return release, identity


def remote_tag_commit(repository: str, tag: str) -> str:
    value = github(f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")["object"]
    for _ in range(16):
        if value["type"] == "commit" and SHA.fullmatch(value["sha"]):
            return value["sha"]
        if value["type"] != "tag" or not SHA.fullmatch(value["sha"]):
            break
        value = github(f"repos/{repository}/git/tags/{value['sha']}")["object"]
    raise ValueError("Cannot resolve the previous tag to a commit.")


def finalize(repository: str, release: dict, identity: dict, context: dict) -> dict:
    if context != identity:
        raise ValueError("Preparation context changed; refusing to publish a stale or edited release.")
    if not release["draft"]:
        return release
    result = github(f"repos/{repository}/releases/{release['id']}", {"draft": False, "make_latest": "true"})
    if (release_identity(result) != release_identity(release)
            or result["draft"] is not False or not result["published_at"]):
        raise ValueError("GitHub did not return the expected published release; inspect it before retrying.")
    return result


def execute() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "finalize"))
    args = parser.parse_args()
    repository = github_repository()
    if os.environ.get("GITHUB_API_URL", "https://api.github.com") != "https://api.github.com":
        raise ValueError("Publication supports the github.com API only.")
    event = strict_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    tag, sha, after = tag_event(os.environ, event)
    context = strict_json(os.environ["RELEASE_CONTEXT"]) if args.command == "finalize" else None
    if context is not None and not isinstance(context, dict):
        raise ValueError("Expected the preparation context object.")
    config_path = context["config-path"] if context is not None else os.environ.get("CONFIG_PATH", "")
    if not isinstance(config_path, str):
        raise ValueError("Expected a configuration path string.")
    release, identity = inspect_release(repository, tag, sha, after, config_path)
    already_published = not release["draft"]
    if args.command == "finalize":
        release = finalize(repository, release, identity, context)
    values = {
        "release-id": str(release["id"]),
        "release-url": release["html_url"],
        "already-published": str(already_published).lower(),
    }
    if args.command == "prepare":
        values.update({
            "tag": tag, "version": tag[1:], "sha": identity["sha"],
            "context": json.dumps(identity, sort_keys=True, separators=(",", ":")),
        })
    output_values(values)
    print(f"Release {tag}: " + ("already published." if already_published else
                               "prepared." if args.command == "prepare" else "published."))


def main() -> None:
    try:
        execute()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release publication failed: {error}", file=sys.stderr)
        sys.exit(1)
