import json
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_configuration import CUSTOM, ROOT, GitFixture

from configuration import load_config
from entrypoint import execute, verify_documentation_pr
from migration_guides import (
    committed_guides, guides_ready, linked_notes, plan_guides, write_guides,
)
from migration_notes import check_pr, render, validate_fragment, validate_guide
from update_release_draft import combine_notes, process_preview, verify_main
from release_metadata import MARKER, preparation


NOTE = """### Client timeout contract

#### Previous behavior

Requests waited indefinitely.

#### New behavior

Requests fail after the configured timeout.

#### Type of breaking change

Behavioral change.

#### Reason for change

Prevent stalled requests from consuming resources indefinitely.

#### Recommended action

Set the timeout explicitly and handle timeout failures.

#### Affected APIs

`Client.SendAsync`.
"""


def release_record(*, draft=True, tag="v2.0.0", body="Existing release body", commit="main"):
    return {
        "id": 17, "tag_name": tag, "name": tag[1:], "draft": draft,
        "prerelease": False, "target_commitish": commit,
        "updated_at": "2026-09-01T00:00:00Z",
        "published_at": None if draft else "2026-09-01T00:00:00Z",
        "body": body,
    }


class ReleaseLifecycle:
    branch = "main"
    overrides = None

    def setUp(self):
        super().setUp()
        if self.branch != "main":
            self.git("branch", "-m", self.branch)
        self.config_path = ""
        if self.overrides:
            self.config_path = ".automation/release.json"
            self.base = self.config_commit(self.overrides, self.config_path)
        self.config = load_config(self.repo, self.base, self.config_path, self.branch)
        self.git("remote", "add", "origin", str(self.repo))
        self.api_writes = []
        self.snapshot = []

    def preview(self, base="v1.0.0", breaking=True):
        category = self.config.categories.breaking if breaking else self.config.categories.fix
        return (
            f"<!-- migration-base: {base} -->\n"
            f"## What's Changed\n\n### {category}\n\n- Consumer change (#42)\n"
        )

    def fake_api(self, endpoint, method="GET", payload=None):
        self.assertTrue(endpoint.startswith("repos/example/consumer/releases"))
        if payload is None:
            self.assertEqual(method, "GET")
            return self.snapshot
        self.assertIn(method, ("PATCH", "POST"))
        self.api_writes.append((endpoint, method, payload.copy()))
        return {"id": 17, "published_at": None, **payload}

    def process(self, head, preview, *, prepare, tag="v2.0.0"):
        with patch("update_release_draft.api", side_effect=self.fake_api):
            return process_preview(
                self.repo, head, preview, tag[1:], tag, "example/consumer",
                self.snapshot, prepare=prepare, config=self.config,
            )

    def fragment(self, slug="client-timeouts", text=NOTE):
        return self.write(f"{self.config.fragment_root}/+{slug}.breaking.md", text)

    def test_fragment_git_paths_reject_backslash_separators_on_every_platform(self):
        valid = f"{self.config.fragment_root}/+client-timeouts.breaking.md"
        validate_fragment(valid, NOTE, self.config)
        invalid_paths = {
            valid.replace("/", "\\"),
            f"{self.config.fragment_root}\\+client-timeouts.breaking.md",
        }
        for name in invalid_paths:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_fragment(name, NOTE, self.config)

    def run_cli(self, command, *args, env=None):
        environment = os.environ.copy()
        for name in ("GITHUB_OUTPUT", "RELEASE_PREVIEW", "RELEASE_NAME", "RELEASE_TAG"):
            environment.pop(name, None)
        environment.update({"TMP": str(self.workspace), "TEMP": str(self.workspace)})
        if env:
            environment.update(env)
        options = [
            sys.executable, "-I", str(ROOT / "toolkit" / "run.py"), command,
            "--repo", str(self.repo), "--default-branch", self.branch,
        ]
        if self.config_path:
            options.extend(("--config-path", self.config_path))
        return subprocess.run(
            [*options, *args], cwd=self.repo, env=environment,
            capture_output=True, text=True, encoding="utf-8",
        )

    def test_real_render_prepare_merge_and_update_use_exact_committed_documents(self):
        self.git("tag", "v1.0.0")
        self.fragment()
        head = self.commit()
        check_pr(self.repo, self.base, head, [self.config.labels.major], self.config)
        notes = render(self.repo, "refs/tags/v1.0.0", head, self.config)
        self.assertIn("## Breaking changes and migration", notes)
        self.assertIn("<!-- migration-topic: client-timeouts -->", notes)
        self.assertIn("### Client timeout contract", notes)
        documents = plan_guides(self.repo, head, notes, "v2.0.0", [], self.config)
        expected_paths = {
            f"{self.config.guide_root}/README.md",
            f"{self.config.guide_root}/2.0.0/README.md",
            f"{self.config.guide_root}/2.0.0/client-timeouts.md",
            self.config.state_path,
        }
        self.assertEqual(set(documents), expected_paths)
        self.assertEqual(json.loads(documents[self.config.state_path]),
                         {"pending_versions": ["2.0.0"]})
        for name, text in documents.items():
            if name != self.config.state_path:
                validate_guide(name, text, self.config)
        self.assertIn("(client-timeouts.md)",
                      documents[f"{self.config.guide_root}/2.0.0/README.md"])
        self.assertFalse(self.process(head, self.preview(), prepare=True))
        self.assertEqual(self.api_writes, [])
        self.assertFalse(guides_ready(self.repo, head, documents, self.config))
        self.git("add", "-A")
        self.assertFalse(guides_ready(self.repo, head, documents, self.config))
        merged = self.commit()
        self.assertTrue(guides_ready(self.repo, merged, documents, self.config))
        self.assertEqual(committed_guides(self.repo, merged, self.config), documents)
        for name, expected in documents.items():
            actual = subprocess.check_output(
                ["git", "show", f"{merged}:{name}"], cwd=self.repo
            )
            self.assertEqual(actual, expected.encode("utf-8"))
        self.write(f"{self.config.guide_root}/2.0.0/client-timeouts.md", "Uncommitted edit")
        self.assertTrue(guides_ready(self.repo, merged, documents, self.config))
        self.assertTrue(self.process(merged, self.preview(), prepare=False))
        _, method, payload = self.api_writes[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(payload["target_commitish"], merged)
        self.assertTrue(payload["draft"])
        self.assertFalse(payload["prerelease"])
        expected_url = (
            f"https://github.com/example/consumer/blob/{self.branch}/"
            f"{self.config.guide_root}/2.0.0/client-timeouts.md"
        )
        self.assertIn(expected_url, payload["body"])
        self.assertIn(f"### {self.config.categories.breaking}", payload["body"])
        self.assertNotIn("#### Recommended action", payload["body"])
        self.assertEqual(self.git("branch", "--show-current"), self.branch)

    def test_initial_empty_repository_requires_review_of_root_index(self):
        self.assertEqual(render(self.repo, None, self.base, self.config), "")
        documents = plan_guides(self.repo, self.base, "", "v1.0.0", [], self.config)
        self.assertEqual(set(documents), {f"{self.config.guide_root}/README.md"})
        self.assertIn("No versioned migration guides", next(iter(documents.values())))
        self.assertFalse(self.process(
            self.base, self.preview(base="", breaking=False), prepare=True, tag="v1.0.0"
        ))
        with self.assertRaisesRegex(ValueError, "existing release draft has not been changed"):
            self.process(self.base, self.preview(base="", breaking=False),
                         prepare=False, tag="v1.0.0")
        self.assertEqual(self.api_writes, [])
        merged = self.commit()
        self.assertTrue(self.process(
            merged, self.preview(base="", breaking=False), prepare=False, tag="v1.0.0"
        ))
        body = self.api_writes[-1][2]["body"]
        self.assertIn("- Consumer change (#42)", body)
        self.assertNotIn("Migration guides", body)
        self.assertNotIn("migration-notes:start", body)
        self.assertNotIn(f"### {self.config.categories.breaking}", body)

    def test_initial_cli_prepare_outputs_allow_real_git_add_without_state_file(self):
        output = self.workspace / "github-output.txt"
        preset = self.workspace / "drafter.json"
        snapshot = self.workspace / "snapshot.json"
        snapshot.write_text("[]", encoding="utf-8")
        labels = self.workspace / "labels.json"
        labels.write_text("[]", encoding="utf-8")
        options = [
            "--repo", str(self.repo), "--default-branch", self.branch,
            "--head", self.base, "--labels", str(labels),
        ]
        if self.config_path:
            options.extend(("--config-path", self.config_path))
        environment = {
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "example/consumer",
            "GITHUB_SERVER_URL": "https://github.com",
            "RELEASE_PREVIEW": self.preview(base="", breaking=False),
            "RELEASE_NAME": "1.0.0",
            "RELEASE_TAG": "v1.0.0",
        }
        with patch("entrypoint.os.environ", {**os.environ, **environment}):
            with patch("sys.argv", [
                "run.py", "configuration", *options, "--output", str(preset),
            ]):
                execute()
            with patch("sys.argv", [
                "run.py", "prepare", *options, "--snapshot", str(snapshot),
            ]), patch("update_release_draft.api", side_effect=self.fake_api), patch("entrypoint.api", return_value=[]):
                execute()
        outputs = dict(
            line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(outputs["guides-ready"], "false")
        self.assertEqual(outputs["guide-root"], self.config.guide_root)
        self.assertEqual(outputs["add-state-path"], "")
        self.assertFalse(self.repo.joinpath(*self.config.state_path.split("/")).exists())
        paths = [outputs["guide-root"]]
        if outputs["add-state-path"]:
            paths.append(outputs["add-state-path"])
        self.git("add", "--", *paths)
        self.assertEqual(
            self.git("diff", "--cached", "--name-only"),
            f"{self.config.guide_root}/README.md",
        )
        self.git("commit", "-qm", "Review initial migration guide index")
        documents = committed_guides(self.repo, self.git("rev-parse", "HEAD"), self.config)
        self.assertEqual(set(documents), {f"{self.config.guide_root}/README.md"})
        self.assertIn("No versioned migration guides", next(iter(documents.values())))
        self.assertEqual(self.api_writes, [])

    def test_nonbreaking_release_updates_existing_draft_without_migration_block(self):
        documents = plan_guides(self.repo, self.base, "", "v1.0.0", [], self.config)
        write_guides(self.repo, self.base, documents, self.config)
        self.commit()
        self.git("tag", "v1.0.0")
        self.write("source.txt", "A compatible bug fix\n")
        head = self.commit()
        self.snapshot = [release_record(tag="v1.0.1", commit=self.branch)]
        self.assertTrue(self.process(
            head, self.preview(breaking=False), prepare=False, tag="v1.0.1"
        ))
        endpoint, method, payload = self.api_writes[-1]
        self.assertTrue(endpoint.endswith("/17"))
        self.assertEqual(method, "PATCH")
        self.assertEqual(payload["tag_name"], "v1.0.1")
        self.assertEqual(payload["body"].split(MARKER)[0].rstrip(),
                         self.preview(breaking=False).split("-->\n", 1)[1].rstrip())
        self.assertEqual(preparation(payload["body"])["commit"], payload["target_commitish"])
        self.assertEqual(self.snapshot[0]["body"], "Existing release body")

    def test_missing_or_inexact_guides_leave_existing_draft_untouched(self):
        self.git("tag", "v1.0.0")
        self.fragment()
        head = self.commit()
        self.snapshot = [release_record(commit=self.branch)]
        with self.assertRaisesRegex(ValueError, "Waiting for migration guides"):
            self.process(head, self.preview(), prepare=False)
        self.assertEqual(self.api_writes, [])
        self.assertFalse(self.process(head, self.preview(), prepare=True))
        self.commit()
        topic = f"{self.config.guide_root}/2.0.0/client-timeouts.md"
        text = self.repo.joinpath(*topic.split("/")).read_text(encoding="utf-8")
        self.write(topic, text.replace("Set the timeout explicitly", "Choose a timeout explicitly"))
        changed = self.commit()
        with self.assertRaisesRegex(ValueError, "Waiting for migration guides"):
            self.process(changed, self.preview(), prepare=False)
        self.assertEqual(self.api_writes, [])
        self.assertEqual(self.snapshot[0]["body"], "Existing release body")

    def test_readiness_requires_exact_line_endings_in_committed_guides(self):
        self.git("tag", "v1.0.0")
        self.fragment()
        head = self.commit()
        notes = render(self.repo, "refs/tags/v1.0.0", head, self.config)
        documents = plan_guides(self.repo, head, notes, "v2.0.0", [], self.config)
        write_guides(self.repo, head, documents, self.config)
        merged = self.commit()
        self.assertTrue(guides_ready(self.repo, merged, documents, self.config))
        name = f"{self.config.guide_root}/2.0.0/client-timeouts.md"
        crlf = documents[name].replace("\n", "\r\n").encode("utf-8")
        self.repo.joinpath(*name.split("/")).write_bytes(crlf)
        changed = self.commit()
        actual = subprocess.check_output(["git", "show", f"{changed}:{name}"], cwd=self.repo)
        self.assertEqual(actual, crlf)
        self.assertFalse(guides_ready(self.repo, changed, documents, self.config))
        self.snapshot = [release_record(commit=self.branch)]
        with self.assertRaises(ValueError):
            self.process(changed, self.preview(), prepare=False)
        self.assertEqual(self.api_writes, [])
        self.assertEqual(self.snapshot[0]["body"], "Existing release body")

    def test_published_reviewed_corrections_are_preserved_in_next_release(self):
        self.git("tag", "v1.0.0")
        self.fragment()
        head = self.commit()
        self.process(head, self.preview(), prepare=True)
        self.commit()
        self.git("tag", "v2.0.0")
        old_topic = f"{self.config.guide_root}/2.0.0/client-timeouts.md"
        corrected = self.repo.joinpath(*old_topic.split("/")).read_text(encoding="utf-8")
        corrected = corrected.replace("Set the timeout explicitly", "Use a measured timeout explicitly")
        self.write(old_topic, corrected)
        self.fragment(text=NOTE.replace("Set the timeout explicitly", "Use a measured timeout explicitly"))
        self.fragment("connection-limits", NOTE.replace("Client timeout contract", "Connection limits"))
        head = self.commit()
        published_body = (
            f"[Reviewed guide](https://github.com/example/consumer/blob/old/default/"
            f"{self.config.guide_root}/2.0.0/client-timeouts.md)"
        )
        self.snapshot = [release_record(draft=False, body=published_body)]
        notes = render(self.repo, "refs/tags/v2.0.0", head, self.config)
        self.assertIn("Connection limits", notes)
        self.assertNotIn("### Client timeout contract", notes)
        documents = plan_guides(self.repo, head, notes, "v3.0.0", self.snapshot, self.config)
        self.assertEqual(documents[old_topic], corrected)
        self.assertEqual(json.loads(documents[self.config.state_path]),
                         {"pending_versions": ["3.0.0"]})
        index = documents[f"{self.config.guide_root}/README.md"]
        self.assertLess(index.index("3.0.0/README.md"), index.index("2.0.0/README.md"))
        self.assertFalse(self.process(head, self.preview("v2.0.0"), prepare=True, tag="v3.0.0"))
        merged = self.commit()
        self.assertTrue(self.process(merged, self.preview("v2.0.0"),
                                     prepare=False, tag="v3.0.0"))
        self.assertEqual(self.snapshot[0]["body"], published_body)
        self.assertNotIn("old/default", self.api_writes[-1][2]["body"])

    def test_pending_links_with_old_branch_are_retained_on_version_change(self):
        self.git("tag", "v1.0.0")
        self.fragment()
        head = self.commit()
        self.process(head, self.preview(), prepare=True)
        merged = self.commit()
        old_topic = f"{self.config.guide_root}/2.0.0/client-timeouts.md"
        old_documents = committed_guides(self.repo, merged, self.config)
        body = f"[Old draft](https://github.com/example/consumer/blob/old/default/{old_topic})"
        self.snapshot = [release_record(body=body)]
        notes = render(self.repo, "refs/tags/v1.0.0", merged, self.config)
        documents = plan_guides(self.repo, merged, notes, "v3.0.0", self.snapshot, self.config)
        self.assertEqual(documents[old_topic], old_documents[old_topic])
        self.assertEqual(json.loads(documents[self.config.state_path]),
                         {"pending_versions": ["2.0.0", "3.0.0"]})
        self.assertIn(f"{self.config.guide_root}/3.0.0/client-timeouts.md", documents)
        self.assertEqual(self.snapshot[0]["body"], body)

    def test_default_branch_verification_checks_selected_branch_and_commit(self):
        verify_main(self.repo, self.base, self.config)
        self.write("source.txt", "Advanced default branch\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "changed during generation"):
            verify_main(self.repo, self.base, self.config)

    def test_frozen_cli_render_and_configuration_ignore_consumer_assets(self):
        self.fragment()
        frozen = self.commit()
        expected = render(self.repo, None, frozen, self.config)
        sentinel = self.workspace / "consumer-code-executed"
        code = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
        self.write("sitecustomize.py", code)
        self.write("towncrier/__main__.py", code)
        self.write("toolkit/run.py", code)
        self.write("towncrier.toml", '[tool.towncrier]\ntemplate = "migration-notes.md.jinja"\n')
        self.write("migration-notes.md.jinja", "UNTRUSTED CONSUMER TEMPLATE")
        self.write("pyproject.toml", '[tool.towncrier]\ndirectory = "wrong-root"\n')
        frozen = self.commit()
        self.write("migration-notes.md.jinja", "UNCOMMITTED CONSUMER TEMPLATE")
        self.fragment(text=NOTE.replace("Client timeout contract", "Uncommitted replacement"))
        if self.config_path:
            self.write(self.config_path, '{"version":1,"fragment_root":"wrong-root"}')
        result = self.run_cli("render", "--head", frozen,
                              env={"PYTHONPATH": str(self.repo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        destination = self.workspace / "generated-drafter.json"
        labels = self.workspace / "labels.json"
        labels.write_text("[]", encoding="utf-8")
        result = self.run_cli("configuration", "--head", frozen, "--output", str(destination),
                              "--labels", str(labels))
        self.assertEqual(result.returncode, 0, result.stderr)
        materialized = json.loads(destination.read_text(encoding="utf-8"))
        self.assertIn(self.config.categories.breaking, json.dumps(materialized))
        self.assertIn(self.config.labels.major, json.dumps(materialized))
        self.assertFalse(sentinel.exists())
        self.assertNotIn("UNTRUSTED", expected)
        self.assertNotIn("Uncommitted replacement", expected)

    def test_pr_head_code_and_config_cannot_change_base_commit_policy(self):
        if not self.config_path:
            self.config_path = ".automation/release.json"
            self.base = self.config_commit({"version": 1})
        sentinel = self.workspace / "pr-code-executed"
        code = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
        for name in ("toolkit/run.py", "sitecustomize.py", "configuration.py",
                     "migration_notes.py", "towncrier/__main__.py"):
            self.write(name, code)
        self.write("towncrier.toml", '[tool.towncrier]\ntemplate = "migration-notes.md.jinja"\n')
        self.write("migration-notes.md.jinja", "{{ invalid_consumer_template }}")
        self.write(self.config_path, json.dumps({
            "version": 1, "fragment_root": "attacker-notes",
            "labels": {"major": "attacker-major"},
        }))
        self.write("attacker-notes/+decoy.breaking.md", NOTE)
        head = self.commit()
        event_path = self.workspace / "event.json"

        def check_event(commit):
            event_path.write_text(json.dumps({"pull_request": {
                "base": {"sha": self.base}, "head": {"sha": commit},
                "labels": [{"name": self.config.labels.major}],
            }}), encoding="utf-8")
            return self.run_cli("check", "--event", str(event_path),
                                env={"PYTHONPATH": str(self.repo)})

        rejected = check_event(head)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(self.config.labels.major, rejected.stderr)
        self.assertIn(self.config.fragment_root, rejected.stderr)
        self.assertFalse(sentinel.exists())
        self.fragment()
        accepted = check_event(self.commit())
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("policy passed", accepted.stdout)
        self.assertFalse(sentinel.exists())

    def test_custom_documentation_pr_labels_and_release_category_contract(self):
        valid = {
            "draft": True,
            "labels": [{"name": self.config.labels.patch},
                       {"name": self.config.labels.documentation}],
        }
        verify_documentation_pr(valid, self.config)
        for extra in (self.config.labels.major, self.config.labels.skip, self.config.labels.fix):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    verify_documentation_pr(
                        {**valid, "labels": valid["labels"] + [{"name": extra}]}, self.config
                    )
        with self.assertRaises(ValueError):
            verify_documentation_pr({**valid, "draft": False}, self.config)
        self.fragment()
        notes = render(self.repo, None, self.commit(), self.config)
        links = linked_notes(notes, "v2.0.0", "example/consumer", self.config)
        body = combine_notes(self.preview(breaking=False), links, self.config)
        self.assertIn(f"### {self.config.categories.breaking}", body)
        self.assertIn(f"### {self.config.categories.fix}", body)
        self.assertIn(links.strip(), body)
        if self.overrides:
            self.assertNotIn("### Breaking Changes", body)
            with self.assertRaisesRegex(ValueError, re.escape(self.config.labels.skip)):
                check_pr(self.repo, self.base, self.git("rev-parse", "HEAD"),
                         [self.config.labels.major, self.config.labels.skip], self.config)

    def test_ready_unchanged_documentation_pr_relaxes_only_draft_requirement(self):
        expected = [
            {"name": self.config.labels.patch},
            {"name": self.config.labels.documentation},
        ]
        ready = {"draft": False, "labels": expected}
        with self.assertRaises(ValueError):
            verify_documentation_pr(ready, self.config)
        verify_documentation_pr(ready, self.config, require_draft=False)
        for extra in (
            self.config.labels.major, self.config.labels.minor,
            self.config.labels.feature, self.config.labels.fix,
            self.config.labels.dependencies, self.config.labels.skip,
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                verify_documentation_pr(
                    {**ready, "labels": [*expected, {"name": extra}]},
                    self.config, require_draft=False,
                )
        for unrelated in ("semver:unexpected", "SemVer:unexpected", "triaged"):
            with self.subTest(unrelated=unrelated):
                verify_documentation_pr(
                    {**ready, "labels": [*expected, {"name": unrelated}]},
                    self.config, require_draft=False,
                )
        for missing in range(len(expected)):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                verify_documentation_pr(
                    {**ready, "labels": expected[:missing] + expected[missing + 1:]},
                    self.config, require_draft=False,
                )


class DefaultConsumerTests(ReleaseLifecycle, GitFixture):
    pass


class NestedConsumerTests(ReleaseLifecycle, GitFixture):
    branch = "trunk/dev"
    overrides = CUSTOM


if __name__ == "__main__":
    unittest.main()
