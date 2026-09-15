import io
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowContractTests(unittest.TestCase):
    def payload_pins(self):
        pins = []
        for name in ("migration-policy.yml", "release-draft.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            match = re.search(
                r"repository: mthalman/release-automation\n\s+ref: ([0-9a-f]{40})\n",
                text,
            )
            self.assertIsNotNone(match, f"{name} must pin its toolkit to a literal full SHA")
            pins.append(match[1])
            self.assertIn("path: _release-automation", text)
            self.assertIn('-I "$GITHUB_WORKSPACE/_release-automation/toolkit/run.py"', text)
        self.assertEqual(pins[0], pins[1], "Both entrypoints must use the same tested payload")
        return pins[0]

    def test_payload_pins_match_checked_in_toolkit(self):
        pin = self.payload_pins()
        listing = subprocess.check_output(
            ["git", "ls-tree", "-r", pin, "--", "toolkit"], cwd=ROOT, text=True,
        )
        paths = []
        for entry in listing.splitlines():
            metadata, name = entry.split("\t", 1)
            mode, kind, expected = metadata.split()
            self.assertEqual((mode, kind), ("100644", "blob"))
            path = ROOT / name
            self.assertTrue(path.is_file(), f"Payload file removed without updating pin: {name}")
            self.assertFalse(path.is_symlink(), f"Payload file must remain a regular file: {name}")
            actual = subprocess.check_output(
                ["git", "hash-object", "--path", name, str(path)], cwd=ROOT, text=True,
            ).strip()
            self.assertEqual(expected, actual, f"Refresh payload pins after changing {name}")
            paths.append(name)
        proposed = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "toolkit").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        self.assertEqual(set(paths), proposed)
        self.assertGreater(len(paths), 5)

    def test_payload_archive_runs_without_consumer_tooling(self):
        pin = self.payload_pins()
        archive = subprocess.check_output(["git", "archive", pin, "toolkit"], cwd=ROOT)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            with tarfile.open(fileobj=io.BytesIO(archive)) as package:
                package.extractall(destination, filter="data")
            result = subprocess.run(
                [sys.executable, "-I", str(destination / "toolkit" / "run.py"), "--help"],
                cwd=destination, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("configuration", result.stdout)

    def test_external_actions_are_immutable(self):
        for workflow in WORKFLOWS.glob("*.yml"):
            for target in re.findall(r"uses:\s*(\S+)", workflow.read_text(encoding="utf-8")):
                if not target.startswith("./"):
                    self.assertRegex(target, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.assertRegex(ci, r"go install github\.com/rhysd/actionlint/cmd/actionlint@[0-9a-f]{40}\b")

    def test_policy_has_no_head_checkout_or_dependency_install(self):
        text = (WORKFLOWS / "migration-policy.yml").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", text)
        self.assertNotIn("ref: ${{ github.event.pull_request.head.sha }}", text)
        self.assertIn('fetch --no-tags origin "refs/pull/$PR_NUMBER/head"', text)
        self.assertIn('rev-parse FETCH_HEAD)" = "$PR_HEAD_SHA"', text)
        self.assertIn("contents: read", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertNotIn("contents: write", text)

    def test_fetching_pull_ref_preserves_trusted_base_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            consumer = Path(directory) / "consumer"
            source.mkdir()

            def git(repo, *args):
                return subprocess.check_output(
                    ["git", *args], cwd=repo, stderr=subprocess.PIPE, text=True,
                ).strip()

            git(source, "init", "-q", "-b", "main")
            git(source, "config", "user.name", "Pull ref fixture")
            git(source, "config", "user.email", "fixture@example.invalid")
            git(source, "commit", "--allow-empty", "-qm", "Trusted base")
            base = git(source, "rev-parse", "HEAD")
            git(source, "checkout", "--detach")
            (source / "head-only.txt").write_text("Untrusted PR data\n", encoding="utf-8")
            git(source, "add", ".")
            git(source, "commit", "-qm", "Fork-only commit")
            head = git(source, "rev-parse", "HEAD")
            git(source, "update-ref", "refs/pull/7/head", head)
            git(source, "checkout", "main")
            git(Path(directory), "clone", "-q", str(source), str(consumer))
            git(consumer, "fetch", "--no-tags", "origin", "refs/pull/7/head")
            self.assertEqual(head, git(consumer, "rev-parse", "FETCH_HEAD"))
            self.assertNotEqual(base, git(consumer, "rev-parse", "FETCH_HEAD"))
            self.assertEqual(base, git(consumer, "rev-parse", "HEAD"))
            self.assertFalse((consumer / "head-only.txt").exists())

    def test_draft_serializes_entire_lifecycle(self):
        text = (WORKFLOWS / "release-draft.yml").read_text(encoding="utf-8")
        self.assertIn("group: release-drafter\n  cancel-in-progress: false", text)
        positions = [
            text.index(f"- name: {name}")
            for name in (
                "Checkout latest default branch", "Freeze commit and Release Drafter configuration",
                "Snapshot releases", "Preview release boundary", "Prepare versioned migration guides",
                "Open documentation pull request", "Verify documentation pull request",
                "Wait for merged migration guides", "Update draft with links to merged guides",
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("dry-run: true", text)
        self.assertIn("publish: false", text)
        self.assertIn("draft: always-true", text)
        self.assertIn("path: consumer", text)
        self.assertIn("config-name: file:${{ steps.configuration.outputs.config-file }}", text)
        self.assertIn("ref: ${{ steps.repository.outputs.branch }}", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("${{ steps.guides.outputs.add-state-path }}", text)
        self.assertIn("if: steps.docs-pr.outputs.pull-request-number != ''", text)
        self.assertIn('--pr "$PR_NUMBER" --require-draft "$REQUIRE_DRAFT"', text)

    def test_dogfooding_separates_proposed_code_from_trusted_policy(self):
        policy = (WORKFLOWS / "policy.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", policy)
        self.assertIn("ready_for_review", policy)
        self.assertIn("uses: ./.github/workflows/migration-policy.yml", policy)
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        self.assertIn("uses: ./.github/workflows/release-draft.yml", release)
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", ci)
        self.assertNotIn("pull_request_target:", ci)
        self.assertIn("python -m unittest discover -s tests -q", ci)
        self.assertNotIn("contents: write", ci)


if __name__ == "__main__":
    unittest.main()
