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
                r"repository: mthalman/release-automation\n"
                r"(?:[ \t]+#[^\n]*\n)*[ \t]+ref: ([0-9a-f]{40})\n",
                text,
            )
            self.assertIsNotNone(match, f"{name} must pin its toolkit to a literal full SHA")
            pins.append(match[1])
            self.assertIn("path: _release-automation", text)
            self.assertIn('-I "$GITHUB_WORKSPACE/_release-automation/toolkit/run.py"', text)
        self.assertEqual(pins[0], pins[1], "Both entrypoints must use the same tested payload")
        publishing = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
        action_pins = re.findall(
            r"uses: mthalman/release-automation/actions/(?:prepare|finalize)-release@([0-9a-f]{40})",
            publishing,
        )
        self.assertEqual(action_pins, [pins[0], pins[0]])
        return pins[0]

    def test_payload_pins_match_checked_in_toolkit(self):
        pin = self.payload_pins()
        listing = subprocess.check_output(
            ["git", "ls-tree", "-r", pin, "--", "toolkit", "actions"], cwd=ROOT, text=True,
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
            for directory in ("toolkit", "actions")
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        self.assertEqual(set(paths), proposed)
        self.assertGreater(len(paths), 5)

    def test_payload_archive_runs_without_consumer_tooling(self):
        pin = self.payload_pins()
        archive = subprocess.check_output(["git", "archive", pin, "toolkit", "actions"], cwd=ROOT)
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
            for action in ("prepare-release", "finalize-release"):
                self.assertTrue((destination / "actions" / action / "action.yml").is_file())
            publication = subprocess.run(
                [sys.executable, "-I", str(destination / "toolkit" / "publish.py"), "--help"],
                cwd=destination, capture_output=True, text=True,
            )
            self.assertEqual(publication.returncode, 0, publication.stderr)
            self.assertIn("{prepare,finalize}", publication.stdout)

    def test_external_actions_are_immutable(self):
        for workflow in [*WORKFLOWS.glob("*.yml"), *(ROOT / "actions").glob("*/action.yml")]:
            for target in re.findall(r"uses:\s*(\S+)", workflow.read_text(encoding="utf-8")):
                if not target.startswith("./"):
                    self.assertRegex(target, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("go install", ci)

    def test_external_actions_have_release_comments_except_internal_payload(self):
        for workflow in [*WORKFLOWS.glob("*.yml"), *(ROOT / "actions").glob("*/action.yml")]:
            text = workflow.read_text(encoding="utf-8")
            for target, comment in re.findall(r"uses:[ \t]*(\S+)([^\n]*)", text):
                with self.subTest(file=workflow.name, target=target):
                    if target.startswith(("./", "mthalman/release-automation/")):
                        self.assertEqual(comment.strip(), "")
                    else:
                        self.assertRegex(comment, r"^ # v[0-9]+\.[0-9]+\.[0-9]+$")

    def test_dependabot_does_not_update_internal_payload_actions(self):
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        actions = dependabot.split("package-ecosystem: github-actions\n", 1)[1]
        actions = actions.split("  - package-ecosystem:", 1)[0]
        self.assertIn(
            '    ignore:\n'
            '      - dependency-name: "mthalman/release-automation"\n'
            '      - dependency-name: "mthalman/release-automation/*"\n',
            actions,
        )
        self.assertNotIn("versions:", actions)
        self.assertNotIn("update-types:", actions)

    def test_actionlint_uses_dependabot_managed_tools_module(self):
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("go-version-file: tools/go.mod", ci)
        self.assertIn("cache-dependency-path: tools/go.sum", ci)
        self.assertIn(
            'go -C tools build -mod=readonly -o "$RUNNER_TEMP/bin/actionlint" '
            'github.com/rhysd/actionlint/cmd/actionlint',
            ci,
        )
        self.assertIn('run: \'"$RUNNER_TEMP/bin/actionlint" -color\'', ci)
        module = (ROOT / "tools" / "go.mod").read_text(encoding="utf-8")
        self.assertIn("tool github.com/rhysd/actionlint/cmd/actionlint", module)
        version = re.search(r"^\s*(?:require )?github\.com/rhysd/actionlint (v\S+)", module, re.MULTILINE)
        self.assertIsNotNone(version)
        checksums = (ROOT / "tools" / "go.sum").read_text(encoding="utf-8")
        self.assertIn(f"github.com/rhysd/actionlint {version[1]} h1:", checksums)
        self.assertIn(f"github.com/rhysd/actionlint {version[1]}/go.mod h1:", checksums)
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertRegex(
            dependabot,
            r"package-ecosystem: gomod\n\s+directory: /tools\n\s+schedule:\n\s+interval: weekly"
            r"\n\s+allow:\n\s+- dependency-type: all",
        )

    def test_actionlint_queue_compatibility_suppression_is_narrow(self):
        text = (ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8")
        diagnostic = (
            r'^unexpected key "queue" for "concurrency" section\. '
            r'expected one of "cancel-in-progress", "group"$'
        )
        expected = "paths:\n" + "".join(
            f"  .github/workflows/{name}:\n"
            f"    ignore:\n"
            f"      - '{diagnostic}'\n"
            for name in ("release-draft.yml", "publish.yml")
        )
        self.assertEqual(text, expected)

    def test_policy_has_no_head_checkout_or_dependency_install(self):
        text = (WORKFLOWS / "migration-policy.yml").read_text(encoding="utf-8")
        self.assertIn(
            "\nconcurrency:\n"
            "  group: migration-note-policy-${{ github.event.pull_request.number }}\n"
            "  cancel-in-progress: true\n\n",
            text,
        )
        self.assertNotRegex(text, r"(?m)^\s*queue:")
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

    def test_release_workflows_preserve_pending_runs(self):
        for name in ("release-draft.yml", "publish.yml"):
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn(
                    "\nconcurrency:\n"
                    "  group: release-drafter\n"
                    "  cancel-in-progress: false\n"
                    "  queue: max\n\n",
                    text,
                )
                self.assertEqual(len(re.findall(r"(?m)^\s*concurrency:", text)), 1)
        caller = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        self.assertNotRegex(caller, r"(?m)^\s*concurrency:")

    def test_documented_release_queue_and_caller_lock_placement(self):
        for name in ("installation.md", "workflows.md", "tag-publishing.md"):
            with self.subTest(document=name):
                text = (ROOT / "docs" / name).read_text(encoding="utf-8")
                self.assertIn("`queue: max`", text)
        for name, workflow_count in (("installation.md", 2), ("tag-publishing.md", 1)):
            text = (ROOT / "docs" / name).read_text(encoding="utf-8")
            workflows = [
                block for block in re.findall(r"```yaml\n(.*?)\n```", text, re.DOTALL)
                if re.search(r"(?m)^on:", block)
            ]
            self.assertEqual(len(workflows), workflow_count)
            for block in workflows:
                with self.subTest(document=name, workflow=block.splitlines()[0]):
                    if name == "tag-publishing.md":
                        self.assertIn(
                            "\nconcurrency:\n"
                            "  group: release-drafter\n"
                            "  cancel-in-progress: false\n"
                            "  queue: max\n\n",
                            block,
                        )
                        self.assertEqual(len(re.findall(r"(?m)^\s*concurrency:", block)), 1)
                    else:
                        self.assertNotRegex(block, r"(?m)^\s*concurrency:")

    def test_draft_serializes_entire_lifecycle(self):
        text = (WORKFLOWS / "release-draft.yml").read_text(encoding="utf-8")
        positions = [
            text.index(f"- name: {name}")
            for name in (
                "Checkout latest default branch", "Freeze commit and Release Drafter configuration",
                "Snapshot releases", "Preview release boundary", "Prepare versioned migration guides",
                "Open documentation pull request", "Report a blocked documentation pull request",
                "Verify documentation pull request",
                "Wait for merged migration guides", "Update draft with links to merged guides",
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("dry-run: true", text)
        self.assertIn("publish: false", text)
        self.assertIn("draft: always-true", text)
        self.assertIn("path: consumer", text)
        self.assertIn("config-name: file:/release-drafter.json", text)
        self.assertIn('--output "$GITHUB_WORKSPACE/release-drafter.json"', text)
        self.assertNotIn('--output "$RUNNER_TEMP/release-drafter.json"', text)
        self.assertIn(
            'gh api "repos/$GITHUB_REPOSITORY/labels" --paginate > "$RUNNER_TEMP/release-labels.json"',
            text,
        )
        self.assertFalse(
            [line for line in text.splitlines() if "--slurp" in line and "--jq" in line],
            "gh rejects --slurp combined with --jq",
        )
        self.assertEqual(text.count('--labels "$RUNNER_TEMP/release-labels.json"'), 3)
        self.assertIn("ref: ${{ steps.repository.outputs.branch }}", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("${{ steps.guides.outputs.add-state-path }}", text)
        self.assertIn("if: steps.docs-pr.outputs.pull-request-number != ''", text)
        self.assertIn('--pr "$PR_NUMBER" --require-draft "$REQUIRE_DRAFT"', text)
        self.assertIn(
            "labels: |\n"
            "            ${{ steps.configuration.outputs.patch-label }}\n"
            "            ${{ steps.configuration.outputs.documentation-label }}",
            text,
        )

    def test_blocked_documentation_pull_request_ends_the_run(self):
        text = (WORKFLOWS / "release-draft.yml").read_text(encoding="utf-8")
        blocked = text.index("- name: Report a blocked documentation pull request")
        opened = text.index("- name: Open documentation pull request")
        step = text[opened:text.index("\n      - name:", opened)]
        self.assertIn("id: docs-pr", step)
        self.assertIn("continue-on-error: true", step)
        self.assertIn("if: steps.docs-pr.outcome == 'failure'", text[blocked:])
        self.assertIn("Allow GitHub Actions to create and approve pull requests", text[blocked:])
        self.assertIn("exit 1", text[blocked:text.index("- name: Verify documentation pull request")])
        self.assertLess(blocked, text.index("- name: Update draft with links to merged guides"))

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
        self.assertIn("name: Release Drafter contract", ci)
        self.assertIn("repository: release-drafter/release-drafter", ci)
        self.assertIn("ref: 34d80673e067bdc0c24568d3af899c216adcfaa9", ci)
        self.assertIn('node-version: "24"', ci)
        self.assertIn('npm --prefix "$GITHUB_WORKSPACE/_release-drafter" ci --ignore-scripts --omit=dev', ci)
        self.assertIn('node tests/drafter-contract.mjs "$GITHUB_WORKSPACE/_release-drafter" python', ci)

    def test_tag_publishing_requires_successful_consumer_steps(self):
        text = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
        self.assertIn('tags: ["v*"]', text)
        self.assertNotIn("workflow_dispatch", text)
        self.assertNotIn("pull_request", text)
        positions = [
            text.index(f"- name: {name}") for name in (
                "Prepare tagged release", "Checkout the validated source",
                "Install toolkit test dependencies", "Run toolkit tests",
                "Publish prepared GitHub release",
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count("if: steps.prepare.outputs.already-published != 'true'"), 3)
        self.assertIn("ref: ${{ steps.prepare.outputs.sha }}", text)
        self.assertIn("context: ${{ steps.prepare.outputs.context }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("always()", text)
        self.assertNotIn("continue-on-error", text)
        finalizer = text[text.index("- name: Publish prepared GitHub release"):]
        self.assertIn("if: success()", finalizer)
        self.assertEqual(text.count("contents: write"), 1)
        self.assertIn("    permissions:\n      contents: write", text)
        self.assertNotIn("id-token:", text)


if __name__ == "__main__":
    unittest.main()
