import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from repository import committed_file, git, safe_path


@dataclass(frozen=True)
class Labels:
    major: str = "semver:major"
    minor: str = "semver:minor"
    patch: str = "semver:patch"
    skip: str = "skip-changelog"
    feature: str = "enhancement"
    fix: str = "bug"
    documentation: str = "documentation"
    dependencies: str = "dependencies"


@dataclass(frozen=True)
class Categories:
    breaking: str = "Breaking Changes"
    feature: str = "Features"
    fix: str = "Bug Fixes"
    documentation: str = "Documentation"
    dependencies: str = "Dependencies"
    maintenance: str = "Maintenance"


@dataclass(frozen=True)
class Config:
    default_branch: str = "main"
    fragment_root: str = ".changes"
    guide_root: str = "docs/migrations"
    state_path: str = ".github/migration-guides.json"
    automation_branch: str = "automation/migration-guides"
    labels: Labels = field(default_factory=Labels)
    categories: Categories = field(default_factory=Categories)


DEFAULT = Config()
ASSETS = Path(__file__).resolve().parent / "assets"


def strict_json(text: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}.")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def validate_branch(repo: Path, branch: str) -> str:
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", branch):
        raise ValueError(f"Unsupported branch name: {branch!r}.")
    git(repo, "check-ref-format", "--branch", branch)
    return branch


def string_overrides(kind, values):
    if not isinstance(values, dict) or set(values) - set(kind.__dataclass_fields__):
        raise ValueError(f"Unsupported {kind.__name__.lower()} configuration.")
    for value in values.values():
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 :_.-]{0,49}", value):
            raise ValueError(f"Unsupported label/category value: {value!r}.")
    result = kind(**values)
    if len({value.casefold() for value in asdict(result).values()}) != len(asdict(result)):
        raise ValueError(f"{kind.__name__} must have distinct values.")
    return result


def load_config(repo: Path, commit: str, config_path: str = "", default_branch: str = "main") -> Config:
    validate_branch(repo, default_branch)
    values = {}
    if config_path:
        text = committed_file(repo, commit, safe_path(config_path))
        if text is None:
            raise ValueError(f"Configuration file does not exist at the selected commit: {config_path}.")
        values = strict_json(text)
        allowed = set(Config.__dataclass_fields__) - {"default_branch"}
        if (not isinstance(values, dict) or set(values) - allowed - {"version"}
                or type(values.get("version")) is not int or values["version"] != 1):
            raise ValueError("Expected configuration version 1 with only supported keys.")
        values.pop("version")
    config = Config(
        default_branch=default_branch,
        **(values | {
            "labels": string_overrides(Labels, values.get("labels", {})),
            "categories": string_overrides(Categories, values.get("categories", {})),
        }),
    )
    paths = [safe_path(config.fragment_root), safe_path(config.guide_root), safe_path(config.state_path)]
    for root in paths[:2]:
        if root.split("/")[0].lower() == ".github":
            raise ValueError("Fragment and guide roots must not be inside .github.")
    if not config.state_path.endswith(".json"):
        raise ValueError("The state path must be a .json file.")
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if path.lower() == other.lower() or path.lower().startswith(other.lower() + "/") or other.lower().startswith(path.lower() + "/"):
                raise ValueError("Fragment, guide and state paths must not overlap.")
    if config_path and any(config_path.lower() == path.lower() or config_path.lower().startswith(path.lower() + "/") for path in paths):
        raise ValueError("Configuration must be outside fragment, guide and state paths.")
    validate_branch(repo, config.automation_branch)
    if config.automation_branch == default_branch:
        raise ValueError("The automation branch must differ from the default branch.")
    return config


def resolve_labels(config: Config, repository_labels: list[dict]) -> Config:
    if not isinstance(repository_labels, list):
        raise ValueError("Expected a repository label snapshot array.")
    names = {}
    for label in repository_labels:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str) or not label["name"]:
            raise ValueError("Invalid repository label snapshot entry.")
        name = label["name"]
        identity = name.casefold()
        if identity in names:
            raise ValueError(f"Ambiguous repository label identity: {name}.")
        names[identity] = name
    return replace(config, labels=Labels(**{
        key: names.get(value.casefold(), value) for key, value in asdict(config.labels).items()
    }))


def drafter_config(config: Config) -> dict:
    preset = json.loads((ASSETS / "release-drafter.json").read_text(encoding="utf-8"))
    labels = config.labels
    categories = config.categories
    preset["categories"][0]["when"]["label"] = labels.skip
    for entry, key, label_key in zip(
        preset["categories"][1:6],
        ("breaking", "feature", "fix", "documentation", "dependencies"),
        ("major", "feature", "fix", "documentation", "dependencies"),
    ):
        entry["title"] = getattr(categories, key)
        entry["when"]["label"] = getattr(labels, label_key)
    preset["categories"][6]["title"] = categories.maintenance
    for entry, key in zip(preset["categories"][7:10], ("major", "minor", "patch")):
        entry["when"]["label"] = getattr(labels, key)
    return preset
