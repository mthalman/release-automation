import json
import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from test_configuration import CUSTOM, GitFixture

import configuration
from configuration import Categories, Config, Labels, drafter_config, load_config
from entrypoint import execute, verify_documentation_pr
from migration_notes import check_pr
from test_integration import NOTE


class LabelResolutionTests(unittest.TestCase):
    def test_configured_labels_use_actual_repository_spelling(self):
        config = Config()
        names = {key: value.upper() for key, value in asdict(config.labels).items()}
        resolved = configuration.resolve_labels(
            config, [{"name": name} for name in names.values()]
        )
        self.assertEqual(asdict(resolved.labels), names)
        self.assertEqual(config, Config())
        preset = drafter_config(resolved)
        self.assertEqual(preset["categories"][0]["when"]["label"], "SKIP-CHANGELOG")
        self.assertEqual(preset["categories"][1]["when"]["label"], "SEMVER:MAJOR")
        self.assertEqual(preset["categories"][7]["when"]["label"], "SEMVER:MAJOR")
        self.assertEqual(preset["categories"][8]["when"]["label"], "SEMVER:MINOR")
        self.assertEqual(preset["categories"][9]["when"]["label"], "SEMVER:PATCH")

    def test_missing_and_unrelated_labels_do_not_change_configuration(self):
        config = Config()
        self.assertEqual(configuration.resolve_labels(config, []), config)
        self.assertEqual(configuration.resolve_labels(config, [{"name": "unrelated"}]), config)

    def test_custom_labels_resolve_without_adopting_unconfigured_roles(self):
        config = Config(labels=Labels(major="release:breaking", skip="omit"))
        resolved = configuration.resolve_labels(
            config, [{"name": "RELEASE:BREAKING"}, {"name": "OMIT"}, {"name": "SEMVER:MAJOR"}]
        )
        self.assertEqual(resolved.labels.major, "RELEASE:BREAKING")
        self.assertEqual(resolved.labels.skip, "OMIT")
        self.assertEqual(resolved.labels.patch, "semver:patch")

    def test_malformed_or_ambiguous_repository_labels_fail_explicitly(self):
        for labels in (None, {}, ["bug"], [{}], [{"name": None}],
                       [{"name": "bug"}, {"name": "BUG"}]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                configuration.resolve_labels(Config(), labels)

    def test_documentation_pr_verification_uses_case_insensitive_label_identity(self):
        config = Config(labels=Labels(major="release:breaking", patch="release:fix", skip="omit"))
        expected = [{"name": "RELEASE:FIX"}, {"name": "DOCUMENTATION"}]
        verify_documentation_pr({"draft": True, "labels": expected}, config)
        for extra in ("RELEASE:BREAKING", "BUG", "OMIT"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                verify_documentation_pr(
                    {"draft": True, "labels": expected + [{"name": extra}]}, config
                )

    def test_every_drafter_label_and_title_uses_its_configured_role(self):
        config = Config(
            labels=Labels(**{role: f"custom:{role}" for role in Labels.__dataclass_fields__}),
            categories=Categories(**{role: f"Custom {role}" for role in Categories.__dataclass_fields__}),
        )
        entries = drafter_config(config)["categories"]
        self.assertEqual(entries[0]["when"]["label"], config.labels.skip)
        for index, role, category in (
            (1, "major", "breaking"), (2, "feature", "feature"), (3, "fix", "fix"),
            (4, "documentation", "documentation"), (5, "dependencies", "dependencies"),
        ):
            self.assertEqual(entries[index]["when"]["label"], getattr(config.labels, role))
            self.assertEqual(entries[index]["title"], getattr(config.categories, category))
        self.assertEqual(entries[6]["title"], config.categories.maintenance)
        for index, role in enumerate(("major", "minor", "patch"), 7):
            self.assertEqual(entries[index]["when"]["label"], getattr(config.labels, role))
            self.assertEqual(entries[index]["semver-increment"], role)
        self.assertEqual(entries[10], {"type": "version-resolver", "semver-increment": "patch"})

    def test_retired_default_labels_do_not_affect_generated_pr_validation(self):
        config = Config(labels=Labels(**{
            role: f"custom:{role}" for role in Labels.__dataclass_fields__
        }))
        labels = [config.labels.patch, config.labels.documentation]
        for unrelated in (*asdict(Labels()).values(), "semver:unexpected"):
            with self.subTest(unrelated=unrelated):
                verify_documentation_pr({
                    "draft": True,
                    "labels": [{"name": name.upper()} for name in [*labels, unrelated]],
                }, config)

    def test_generated_pr_errors_name_configured_labels(self):
        config = Config(labels=Labels(patch="release:fix", documentation="kind:docs", skip="omit"))
        for require_draft in (True, False):
            with self.subTest(require_draft=require_draft):
                with self.assertRaises(ValueError) as error:
                    verify_documentation_pr({"draft": False, "labels": []}, config,
                                            require_draft=require_draft)
                for name in ("release:fix", "kind:docs", "omit"):
                    self.assertIn(name, str(error.exception))
                self.assertNotIn("skip-changelog", str(error.exception))
                self.assertEqual("must be draft" in str(error.exception), require_draft)


class ConfiguredLabelPolicyTests(GitFixture):
    def test_only_configured_major_and_skip_labels_control_policy(self):
        config = Config(labels=Labels(**{
            role: f"custom:{role}" for role in Labels.__dataclass_fields__
        }))
        retired = list(asdict(Labels()).values())
        check_pr(self.repo, self.base, self.base, retired, config)
        with self.assertRaisesRegex(ValueError, "custom:major.*new migration fragment"):
            check_pr(self.repo, self.base, self.base, [config.labels.major.upper()], config)
        self.write(".changes/+configured-labels.breaking.md", NOTE)
        head = self.commit()
        check_pr(self.repo, self.base, head, [config.labels.major, *retired], config)
        with self.assertRaisesRegex(ValueError, "must not use custom:skip"):
            check_pr(self.repo, self.base, head,
                     [config.labels.major.upper(), config.labels.skip.upper()], config)

    def test_default_names_reassigned_to_other_roles_have_only_the_new_meaning(self):
        config = Config(labels=Labels(
            major="skip-changelog", skip="semver:major", patch="release:patch",
            documentation="semver:docs",
        ))
        with self.assertRaisesRegex(ValueError, "skip-changelog.*new migration fragment"):
            check_pr(self.repo, self.base, self.base, ["skip-changelog"], config)
        check_pr(self.repo, self.base, self.base, ["semver:major"], config)
        self.write(".changes/+reassigned-labels.breaking.md", NOTE)
        head = self.commit()
        check_pr(self.repo, self.base, head, ["skip-changelog"], config)
        with self.assertRaisesRegex(ValueError, "must not use semver:major"):
            check_pr(self.repo, self.base, head, ["skip-changelog", "semver:major"], config)
        verify_documentation_pr({
            "draft": True,
            "labels": [{"name": "release:patch"}, {"name": "semver:docs"}],
        }, config)


class LabelSnapshotCliTests(GitFixture):
    def test_label_changes_stop_prepare_and_update_before_release_mutation(self):
        labels = self.workspace / "labels.json"
        releases = self.workspace / "releases.json"
        releases.write_text("[]", encoding="utf-8")
        overrides = {role: f"custom:{role}" for role in Labels.__dataclass_fields__}
        head = self.config_commit({"version": 1, "labels": overrides})
        for name in overrides.values():
            labels.write_text(json.dumps([{"name": name.upper()}]), encoding="utf-8")
            for command in ("prepare", "update"):
                with self.subTest(command=command, label=name):
                    with patch("entrypoint.os.environ", {**os.environ, "GITHUB_REPOSITORY": "example/library",
                                                         "GITHUB_SERVER_URL": "https://github.com"}):
                        with patch("sys.argv", [
                            "run.py", command, "--repo", str(self.repo), "--default-branch", "main",
                            "--head", head, "--config-path", ".automation/release.json",
                            "--labels", str(labels), "--snapshot", str(releases),
                        ]), patch("entrypoint.api", return_value=[{"name": name}]) as api:
                            with patch("entrypoint.process_preview") as process:
                                with self.assertRaisesRegex(ValueError, "labels changed"):
                                    execute()
                                process.assert_not_called()
                            api.assert_called_once_with("repos/example/library/labels")

    def test_cli_freezes_repository_spelling_into_preset_and_pr_outputs(self):
        commit = self.config_commit(CUSTOM)
        config = load_config(self.repo, commit, ".automation/release.json")
        snapshot = self.workspace / "labels.json"
        snapshot.write_text(
            json.dumps([{"name": name.upper()} for name in asdict(config.labels).values()]),
            encoding="utf-8",
        )
        preset = self.workspace / "release-drafter.json"
        output = self.workspace / "outputs.txt"
        with patch("entrypoint.os.environ", {**os.environ, "GITHUB_OUTPUT": str(output)}):
            with patch("sys.argv", [
                "run.py", "configuration", "--repo", str(self.repo),
                "--default-branch", "main", "--head", commit,
                "--config-path", ".automation/release.json",
                "--labels", str(snapshot), "--output", str(preset),
            ]):
                execute()
        data = json.loads(preset.read_text(encoding="utf-8"))
        self.assertEqual(data["categories"][1]["when"]["label"], "RELEASE:BREAKING")
        outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        self.assertEqual(outputs["patch-label"], "RELEASE:FIX")
        self.assertEqual(outputs["documentation-label"], "KIND:DOCS")
        self.assertFalse(preset.is_relative_to(self.repo))


if __name__ == "__main__":
    unittest.main()
