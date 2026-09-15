import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from configuration import Config, Labels
from migration_notes import REQUIRED_SECTIONS, check_pr, previous_tag, validate_guide


GUIDE = "# Timeout\n\n**Version introduced:** 2.0.0\n\n" + "".join(
    f"## {section}\n\nMeaningful {section.lower()} guidance.\n\n"
    for section in REQUIRED_SECTIONS
)
PATH = "docs/migrations/2.0.0/timeout.md"


class GuideMetadataTests(unittest.TestCase):
    def test_one_unfenced_canonical_version_is_valid(self):
        validate_guide(PATH, GUIDE)
        validate_guide(PATH, GUIDE + "\n```markdown\n**Version introduced:** 9.0.0\n```\n")

    def test_fenced_metadata_cannot_replace_actual_metadata(self):
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                text = GUIDE.replace(
                    "**Version introduced:** 2.0.0",
                    f"{fence}markdown\n**Version introduced:** 2.0.0\n{fence}",
                )
                with self.assertRaisesRegex(ValueError, "Version introduced"):
                    validate_guide(PATH, text)

    def test_commented_metadata_cannot_replace_actual_metadata(self):
        text = GUIDE.replace(
            "**Version introduced:** 2.0.0",
            "<!--\n**Version introduced:** 2.0.0\n-->",
        )
        with self.assertRaisesRegex(ValueError, "Version introduced"):
            validate_guide(PATH, text)

    def test_duplicate_or_conflicting_metadata_is_rejected(self):
        for version in ("2.0.0", "1.0.0", "3.0.0"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "Version introduced"):
                    validate_guide(PATH, GUIDE + f"\n**Version introduced:** {version}\n")


class ReleaseBoundaryTests(unittest.TestCase):
    def test_initial_and_stable_boundaries_are_supported(self):
        self.assertIsNone(previous_tag("<!-- migration-base:  -->\n"))
        self.assertEqual("v2.0.0", previous_tag("<!-- migration-base: v2.0.0 -->\n"))

    def test_unsupported_boundaries_fail_before_git_or_mutation(self):
        for tag in ("v2.0.0-preview.1", "v2.0.0+build", "main", "2.0.0", "v02.0.0", "v2.0.0-->extra"):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(ValueError, "stable"):
                    previous_tag(f"<!-- migration-base: {tag} -->\n")


class LabelIdentityTests(unittest.TestCase):
    def test_breaking_changes_cannot_skip_using_case_variants(self):
        with patch("migration_notes.git", side_effect=AssertionError("Reject before reading Git")):
            for major in ("semver:major", "SEMVER:MAJOR"):
                for skip in ("skip-changelog", "SKIP-CHANGELOG", "Skip-Changelog"):
                    with self.subTest(major=major, skip=skip):
                        with self.assertRaisesRegex(ValueError, "skip-changelog"):
                            check_pr(ROOT, "base", "head", [major, skip])

    def test_custom_exclusion_label_uses_same_identity_rules(self):
        config = Config(labels=Labels(major="breaking", skip="omit"))
        with patch("migration_notes.git", side_effect=AssertionError("Reject before reading Git")):
            for skip in ("OMIT", "SKIP-CHANGELOG"):
                with self.subTest(skip=skip):
                    with self.assertRaises(ValueError):
                        check_pr(ROOT, "base", "head", ["BREAKING", skip], config)

    def test_major_case_variant_still_requires_new_fragment(self):
        with patch("migration_notes.git", return_value="merge-base"), patch("migration_notes.changed_files", return_value=[]):
            with self.assertRaisesRegex(ValueError, "new migration fragment"):
                check_pr(ROOT, "base", "head", ["SEMVER:MAJOR"])


if __name__ == "__main__":
    unittest.main()
