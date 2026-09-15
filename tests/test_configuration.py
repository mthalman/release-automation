import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from configuration import Categories, Config, Labels, drafter_config, load_config
from entrypoint import verify_documentation_pr
from migration_guides import plan_guides
from migration_notes import check_pr


CUSTOM = {
    "version": 1,
    "fragment_root": "notes/changelog",
    "guide_root": "manuals/upgrades/migrations",
    "state_path": ".automation/state.json",
    "automation_branch": "bots/upgrade-guides",
    "labels": {
        "major": "release:breaking",
        "minor": "release:feature",
        "patch": "release:fix",
        "skip": "release:skip",
        "documentation": "kind:docs",
    },
    "categories": {"breaking": "Compatibility Changes", "documentation": "Guides"},
}


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT, prefix="release-tests-")
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        self.repo = self.workspace / "consumer"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Release automation tests")
        self.git("config", "user.email", "release-tests@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", ".git/no-hooks")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.write("source.txt", "Initial source\n")
        self.base = self.commit()

    def git(self, *args, input=None):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, input=input, text=True, encoding="utf-8"
        ).strip()

    def write(self, name, text):
        path = self.repo.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "Consumer fixture", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def config_commit(self, values, name=".automation/release.json"):
        self.write(name, json.dumps(values))
        return self.commit()

    def mode_commit(self, name, mode, contents):
        oid = self.git("hash-object", "-w", "--stdin", input=contents)
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{oid},{name}")
        self.git("commit", "-qm", "Non-regular committed object")
        return self.git("rev-parse", "HEAD")


class ConfigurationTests(GitFixture):
    def test_no_config_preserves_upstream_defaults(self):
        config = load_config(self.repo, self.base)
        self.assertEqual(config, Config())
        self.assertEqual(
            (config.default_branch, config.fragment_root, config.guide_root,
             config.state_path, config.automation_branch),
            ("main", ".changes", "docs/migrations", ".github/migration-guides.json",
             "automation/migration-guides"),
        )
        self.assertEqual(config.labels, Labels())
        self.assertEqual(config.categories, Categories())

    def test_partial_overrides_and_nested_paths_with_slash_branch(self):
        self.git("branch", "-m", "trunk/dev")
        head = self.config_commit(CUSTOM)
        config = load_config(self.repo, head, ".automation/release.json", "trunk/dev")
        self.assertEqual(config.default_branch, "trunk/dev")
        for key in ("fragment_root", "guide_root", "state_path", "automation_branch"):
            self.assertEqual(getattr(config, key), CUSTOM[key])
        self.assertEqual(config.labels.major, "release:breaking")
        self.assertEqual(config.labels.feature, Labels().feature)
        self.assertEqual(config.categories.breaking, "Compatibility Changes")
        self.assertEqual(config.categories.fix, Categories().fix)

    def test_configuration_is_read_from_frozen_commit_not_head_or_worktree(self):
        frozen = self.config_commit(CUSTOM)
        self.config_commit({"version": 1, "fragment_root": "head-notes"})
        self.write(".automation/release.json", '{"version": 999}')
        config = load_config(self.repo, frozen, ".automation/release.json", "trunk/dev")
        self.assertEqual(config.fragment_root, CUSTOM["fragment_root"])
        self.assertEqual(config.labels.major, CUSTOM["labels"]["major"])
        self.assertEqual(config.categories.breaking, CUSTOM["categories"]["breaking"])

    def test_missing_committed_config_does_not_fall_back_to_worktree(self):
        self.write(".automation/release.json", json.dumps(CUSTOM))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            load_config(self.repo, self.base, ".automation/release.json")

    def test_schema_rejects_unknown_version_keys_and_nonobjects(self):
        invalid = [
            {}, {"version": 0}, {"version": 2}, {"version": True}, {"version": "1"},
            {"version": 1.0}, {"version": 1, "unknown": "setting"},
            {"version": 1, "default_branch": "other"},
            [], None, "config", 1,
        ]
        for values in invalid:
            with self.subTest(values=values):
                head = self.config_commit(values)
                with self.assertRaises(ValueError):
                    load_config(self.repo, head, ".automation/release.json")

    def test_duplicate_json_keys_are_rejected_at_every_level(self):
        for text in (
            '{"version":1,"version":1}',
            '{"version":1,"fragment_root":"notes","fragment_root":"other"}',
            '{"version":1,"labels":{"major":"breaking","major":"other"}}',
            '{"version":1,"categories":{"breaking":"First","breaking":"Second"}}',
            '{"version":',
        ):
            with self.subTest(text=text):
                self.write(".automation/release.json", text)
                head = self.commit()
                with self.assertRaises(ValueError):
                    load_config(self.repo, head, ".automation/release.json")

    def test_paths_reject_unsafe_values_and_wrong_types(self):
        invalid = [
            None, True, 42, [], {}, "", ".", "..", "../notes", "notes/../outside",
            "/absolute", "C:/outside", r"notes\changelog", "notes//changelog",
            "notes/./changelog", ".git", ".GIT/objects", "notes/.git/objects",
            "notes/", "notes with spaces",
        ]
        for field in ("fragment_root", "guide_root", "state_path"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    head = self.config_commit({"version": 1, field: value})
                    with self.assertRaises(ValueError):
                        load_config(self.repo, head, ".automation/release.json")

    def test_github_is_reserved_for_fragment_and_guide_roots(self):
        for field in ("fragment_root", "guide_root"):
            for value in (".github", ".github/notes", ".GitHub/notes"):
                with self.subTest(field=field, value=value):
                    head = self.config_commit({"version": 1, field: value})
                    with self.assertRaises(ValueError):
                        load_config(self.repo, head, ".automation/release.json")

    def test_roots_state_and_config_cannot_overlap(self):
        invalid = [
            {"fragment_root": "notes", "guide_root": "notes"},
            {"fragment_root": "notes", "guide_root": "notes/guides"},
            {"fragment_root": "NOTES/changes", "guide_root": "notes"},
            {"fragment_root": "notes", "state_path": "notes/state.json"},
            {"guide_root": "guides", "state_path": "guides/state.json"},
            {"guide_root": "state.json/docs", "state_path": "state.json"},
            {"fragment_root": ".automation"},
            {"guide_root": ".automation"},
            {"state_path": ".automation/release.json"},
            {"state_path": "state.txt"},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                head = self.config_commit({"version": 1, **overrides})
                with self.assertRaises(ValueError):
                    load_config(self.repo, head, ".automation/release.json")

    def test_config_path_cannot_escape_repository(self):
        for name in ("../release.json", "/release.json", r".automation\release.json",
                     ".git/config", ".automation/../release.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_config(self.repo, self.base, name)

    def test_branch_names_and_automation_branch_are_validated(self):
        for branch in ("", "HEAD", "../main", "/main", "-main", "main..old", "main.lock",
                       "main@{1}", "main\ninjection", True, None):
            with self.subTest(branch=branch):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    load_config(self.repo, self.base, default_branch=branch)
        for branch in ("main", "../bot", "bot..notes", r"bot\notes", [], None):
            with self.subTest(automation_branch=branch):
                head = self.config_commit({"version": 1, "automation_branch": branch})
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    load_config(self.repo, head, ".automation/release.json")

    def test_labels_and_categories_reject_unsupported_or_ambiguous_values(self):
        for kind in ("labels", "categories"):
            key = "major" if kind == "labels" else "breaking"
            for values in (None, [], "value", {"unknown": "value"}, {key: 1},
                           {key: ""}, {key: "a\nb"}, {key: "*"}, {key: "x" * 51}):
                with self.subTest(kind=kind, values=values):
                    head = self.config_commit({"version": 1, kind: values})
                    with self.assertRaises(ValueError):
                        load_config(self.repo, head, ".automation/release.json")
        for kind, values in (
            ("labels", {"major": "semver:patch"}),
            ("labels", {"major": "SEMVER:PATCH"}),
            ("categories", {"breaking": "Features"}),
            ("categories", {"breaking": "features"}),
        ):
            with self.subTest(kind=kind):
                head = self.config_commit({"version": 1, kind: values})
                with self.assertRaises(ValueError):
                    load_config(self.repo, head, ".automation/release.json")

    def test_config_must_be_regular_nonexecutable_git_blob(self):
        for mode in ("120000", "100755"):
            with self.subTest(mode=mode):
                head = self.mode_commit("release.json", mode, '{"version":1}')
                with self.assertRaisesRegex(ValueError, "regular"):
                    load_config(self.repo, head, "release.json")
        self.write("directory/child.json", '{"version":1}')
        head = self.commit()
        with self.assertRaisesRegex(ValueError, "regular"):
            load_config(self.repo, head, "directory")

    def test_label_names_can_be_assigned_to_any_distinct_configured_role(self):
        configurations = [
            {"patch": "skip-changelog", "skip": "omit"},
            {"documentation": "semver:docs"},
        ]
        configurations.extend(
            {role: "SKIP-CHANGELOG", "skip": "omit"}
            for role in Labels.__dataclass_fields__ if role != "skip"
        )
        configurations.extend(
            {role: "SeMvEr:custom"}
            for role in ("skip", "feature", "fix", "documentation", "dependencies")
        )
        for labels in configurations:
            with self.subTest(labels=labels):
                head = self.config_commit({"version": 1, "labels": labels})
                config = load_config(self.repo, head, ".automation/release.json")
                for role, name in labels.items():
                    self.assertEqual(getattr(config.labels, role), name)
                verify_documentation_pr({
                    "draft": True,
                    "labels": [{"name": config.labels.patch},
                               {"name": config.labels.documentation}],
                }, config)

    def test_accepted_label_configurations_accept_generated_documentation_pair(self):
        configurations = [
            {},
            CUSTOM["labels"],
            {role: f"custom:{role}" for role in Labels.__dataclass_fields__},
            {
                "major": "SemVer:breaking", "minor": "SemVer:feature",
                "patch": "SemVer:fix", "skip": "SKIP-CHANGELOG",
                "documentation": "Kind:Docs",
            },
        ]
        for labels in configurations:
            with self.subTest(labels=labels):
                head = self.config_commit({"version": 1, "labels": labels})
                config = load_config(self.repo, head, ".automation/release.json")
                expected = [
                    {"name": config.labels.patch}, {"name": config.labels.documentation}
                ]
                verify_documentation_pr({"draft": True, "labels": expected}, config)
                verify_documentation_pr(
                    {"draft": False, "labels": expected}, config, require_draft=False
                )
                for missing in range(len(expected)):
                    with self.subTest(missing=missing), self.assertRaises(ValueError):
                        verify_documentation_pr(
                            {"draft": True, "labels": expected[:missing] + expected[missing + 1:]},
                            config,
                        )

    def test_custom_drafter_categories_and_labels_keep_default_fallbacks(self):
        config = load_config(self.repo, self.config_commit(CUSTOM),
                             ".automation/release.json", "trunk/dev")
        preset = drafter_config(config)
        entries = preset["categories"]
        titled = {entry["title"]: entry for entry in entries if "title" in entry}
        self.assertEqual(titled["Compatibility Changes"]["when"]["label"], "release:breaking")
        self.assertEqual(titled["Guides"]["when"]["label"], "kind:docs")
        self.assertEqual(titled["Bug Fixes"]["when"]["label"], Labels().fix)
        serialized = json.dumps(preset)
        for label in ("release:breaking", "release:feature", "release:fix", "release:skip"):
            self.assertIn(label, serialized)
        self.assertNotIn("semver:major", serialized)
        self.assertEqual(asdict(load_config(self.repo, self.base)), asdict(Config()))

    def test_malformed_committed_state_is_rejected_by_policy_and_planner(self):
        states = [
            "null", "[]", "{}", '{"pending_versions":"1.0.0"}',
            '{"pending_versions":[1]}', '{"pending_versions":["v1.0.0"]}',
            '{"pending_versions":["1.0.0","1.0.0"]}',
            '{"pending_versions":["../1.0.0"]}',
            '{"pending_versions":[],"extra":true}',
            '{"pending_versions":[],"pending_versions":[]}', "{",
        ]
        for text in states:
            with self.subTest(state=text):
                self.write(".github/migration-guides.json", text)
                head = self.commit()
                with self.assertRaises(ValueError):
                    check_pr(self.repo, head, head, [])
                with self.assertRaises(ValueError):
                    plan_guides(self.repo, head, "", "v1.0.0", [])

    def test_state_symlink_and_executable_modes_are_rejected(self):
        for mode in ("120000", "100755"):
            with self.subTest(mode=mode):
                head = self.mode_commit(
                    ".github/migration-guides.json", mode, '{"pending_versions":[]}'
                )
                with self.assertRaisesRegex(ValueError, "regular"):
                    check_pr(self.repo, head, head, [])
                with self.assertRaisesRegex(ValueError, "regular"):
                    plan_guides(self.repo, head, "", "v1.0.0", [])


if __name__ == "__main__":
    unittest.main()
