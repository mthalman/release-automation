import json
import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from test_configuration import CUSTOM, GitFixture

import configuration
from configuration import Config, Labels, drafter_config, load_config
from entrypoint import execute, verify_documentation_pr


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
        for extra in ("RELEASE:BREAKING", "BUG", "OMIT", "SKIP-CHANGELOG"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                verify_documentation_pr(
                    {"draft": True, "labels": expected + [{"name": extra}]}, config
                )


class LabelSnapshotCliTests(GitFixture):
    def test_label_changes_stop_prepare_and_update_before_release_mutation(self):
        labels = self.workspace / "labels.json"
        labels.write_text('[{"name":"SEMVER:MAJOR"}]', encoding="utf-8")
        releases = self.workspace / "releases.json"
        releases.write_text("[]", encoding="utf-8")
        for command in ("prepare", "update"):
            with self.subTest(command=command):
                with patch("entrypoint.os.environ", {**os.environ, "GITHUB_REPOSITORY": "example/library",
                                                     "GITHUB_SERVER_URL": "https://github.com"}):
                    with patch("sys.argv", [
                        "run.py", command, "--repo", str(self.repo), "--default-branch", "main",
                        "--head", self.base, "--labels", str(labels), "--snapshot", str(releases),
                    ]), patch("entrypoint.api", return_value=[{"name": "semver:major"}]) as api:
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
