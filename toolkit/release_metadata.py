import base64
import hashlib
import json
import re
from dataclasses import asdict

from configuration import Config, strict_json


MARKER = "<!-- release-automation: "
RELEASE_FIELDS = ("id", "tag_name", "name", "prerelease", "target_commitish", "body")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def release_identity(release: dict) -> dict:
    # Asset uploads change updated_at; they must not invalidate a prepared handoff.
    return {key: release[key] for key in RELEASE_FIELDS}


def published_digest(releases: list[dict]) -> str:
    return digest(sorted(
        [release_identity(release) for release in releases if not release["draft"]],
        key=lambda release: release["id"],
    ))


def config_digest(config: Config) -> str:
    values = asdict(config)
    values["labels"] = {key: value.casefold() for key, value in values["labels"].items()}
    return digest(values)


def prepared_body(
    body: str, commit: str, base: str | None, base_commit: str | None,
    releases: list[dict], config: Config, guide_references: list[str] | None = None, *, tag: str,
) -> str:
    if MARKER in body:
        raise ValueError("Release notes contain a reserved preparation marker.")
    metadata = {
        "version": 1, "tag": tag, "commit": commit, "base": base, "base_commit": base_commit,
        "config": config_digest(config), "published": published_digest(releases),
        "guide_references": sorted(guide_references or []),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).decode("ascii")
    return body.rstrip() + f"\n\n{MARKER}{encoded} -->\n"


def preparation(body: str) -> dict:
    body = body.replace("\r\n", "\n")
    matches = re.findall(r"^<!-- release-automation: ([A-Za-z0-9_=-]+) -->$", body, re.MULTILINE)
    if len(matches) != 1 or body.count(MARKER) != 1:
        raise ValueError("Missing or ambiguous preparation metadata; successfully redraft before tagging.")
    try:
        value = strict_json(base64.b64decode(matches[0], altchars=b"-_", validate=True).decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid release preparation metadata.") from error
    keys = {"version", "tag", "commit", "base", "base_commit", "config", "published", "guide_references"}
    if not isinstance(value, dict) or set(value) != keys or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported release preparation metadata.")
    return value
