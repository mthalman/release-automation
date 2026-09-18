from fnmatch import fnmatchcase
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = {
    ".github/workflows/migration-policy.yml",
    ".github/workflows/release-draft.yml",
    "actions/prepare-release",
    "actions/finalize-release",
}
RELEASE_SHA = "a2018dd1e9ab1371dd6c2f180c35bd94dc7becf3"
RELEASE_TAG = "v1.0.0"
RELEASE_REFERENCE = re.compile(
    r"mthalman/release-automation/([^@\s]+)@([0-9a-f]{40})"
    r" # (v[0-9]+\.[0-9]+\.[0-9]+)"
)


class DocumentationPinTests(unittest.TestCase):
    def test_installation_templates_require_sha_and_matching_tag_for_all_entrypoints(self):
        targets = []
        for name in ("installation.md", "tag-publishing.md"):
            text = (ROOT / "docs" / name).read_text(encoding="utf-8")
            blocks = re.findall(r"```yaml\n(.*?)\n```", text, re.DOTALL)
            for block in blocks:
                for reference in re.findall(
                    r"uses: (mthalman/release-automation/[^\n]+)", block,
                ):
                    self.assertIn(
                        "@REPLACE_WITH_REVIEWED_COMMIT_SHA # vMAJOR.MINOR.PATCH", reference,
                    )
                    rendered = reference.replace(
                        "REPLACE_WITH_REVIEWED_COMMIT_SHA", RELEASE_SHA,
                    ).replace("vMAJOR.MINOR.PATCH", RELEASE_TAG)
                    match = RELEASE_REFERENCE.fullmatch(rendered)
                    self.assertIsNotNone(match, reference)
                    targets.append(match[1])
        self.assertCountEqual(targets, [*ENTRYPOINTS, "actions/finalize-release"])

    def test_published_reference_examples_use_one_verified_release_pair(self):
        text = (ROOT / "docs" / "upgrading.md").read_text(encoding="utf-8")
        references = re.findall(r"^uses: (.+)$", text, re.MULTILINE)
        targets = []
        for reference in references:
            match = RELEASE_REFERENCE.fullmatch(reference)
            self.assertIsNotNone(match, reference)
            targets.append(match[1])
            self.assertEqual((match[2], match[3]), (RELEASE_SHA, RELEASE_TAG))
        self.assertCountEqual(targets, ENTRYPOINTS)
        self.assertIn("not the recommended installation", text)
        self.assertIn("predates the shared `queue: max` fix", text)

    def test_release_reference_contract_accepts_comments_but_not_floating_refs(self):
        prefix = "mthalman/release-automation/actions/prepare-release@"
        self.assertIsNotNone(RELEASE_REFERENCE.fullmatch(f"{prefix}{RELEASE_SHA} # {RELEASE_TAG}"))
        for suffix in (
            RELEASE_SHA,
            f"{RELEASE_SHA[:7]} # {RELEASE_TAG}",
            f"v1.0.0 # {RELEASE_TAG}",
            f"main # {RELEASE_TAG}",
            f"{RELEASE_SHA} # v1",
            f"{RELEASE_SHA} # v1.0.1-rc.1",
            f"{RELEASE_SHA} # vMAJOR.MINOR.PATCH",
        ):
            with self.subTest(reference=suffix):
                self.assertIsNone(RELEASE_REFERENCE.fullmatch(prefix + suffix))

    def test_consumer_dependabot_group_covers_workflows_and_actions(self):
        text = (ROOT / "docs" / "upgrading.md").read_text(encoding="utf-8")
        blocks = [
            block for block in re.findall(r"```yaml\n(.*?)\n```", text, re.DOTALL)
            if block.startswith("version: 2\n")
        ]
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].startswith(
            "version: 2\nupdates:\n  - package-ecosystem: github-actions\n"
            "    directory: /\n    schedule:\n      interval: weekly\n"
            "    groups:\n      release-automation:\n        patterns:\n",
        ))
        patterns = re.findall(r'^          - "([^"]+)"$', blocks[0], re.MULTILINE)
        self.assertEqual(patterns, ["mthalman/release-automation", "mthalman/release-automation/*"])
        for dependency in ["mthalman/release-automation", *(
            f"mthalman/release-automation/{entrypoint}" for entrypoint in ENTRYPOINTS
        )]:
            with self.subTest(dependency=dependency):
                self.assertTrue(any(fnmatchcase(dependency, pattern) for pattern in patterns))
        for dependency in ("actions/checkout", "mthalman/release-automation-other"):
            self.assertFalse(any(fnmatchcase(dependency, pattern) for pattern in patterns))
        self.assertNotIn("update-types:", blocks[0])
        self.assertNotIn("ignore:", blocks[0])

    def test_unreleased_dependabot_exception_is_explicit(self):
        text = (ROOT / "docs" / "upgrading.md").read_text(encoding="utf-8")
        self.assertIn(
            '    ignore:\n'
            '      - dependency-name: "mthalman/release-automation"\n'
            '      - dependency-name: "mthalman/release-automation/*"\n',
            text,
        )
        self.assertIn("Remove only these temporary toolkit exclusions", text)
        self.assertIn("these internal exclusions remain in place", text)

    def test_upgrade_guidance_covers_manual_sync_and_unreleased_exceptions(self):
        text = (ROOT / "docs" / "upgrading.md").read_text(encoding="utf-8")
        for contract in (
            "releases/tags/TAG",
            "commits/TAG",
            "`draft: false`, `prerelease: false`",
            "does **not** update SHA-pinned\n   Markdown links",
            "/blob/<old SHA>/",
            "/tree/<old SHA>/",
            "Leave\nthose `uses` lines without version comments",
            "Do not attach W's release tag to P",
            "Dependabot can update bare-SHA reusable workflow\nand Action",
            "do not rely on missing comments to prevent Dependabot updates",
            "../MAINTAINERS.md#update-the-immutable-payload-pins",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)


if __name__ == "__main__":
    unittest.main()
