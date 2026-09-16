import base64
import copy
import io
import json
import os
import subprocess
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from test_configuration import CUSTOM, GitFixture
from test_integration import NOTE, release_record

import publication
from configuration import Config, load_config
from migration_guides import linked_notes, plan_guides, write_guides
from migration_notes import MIGRATION_END, MIGRATION_START, render
from release_metadata import (
    MARKER, config_digest, digest, preparation, prepared_body, published_digest,
    release_identity,
)
from update_release_draft import combine_notes, process_preview


REPOSITORY = "example/consumer"
TAG = "v2.0.0"


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.commit = "a" * 40
        self.published = release_record(draft=False, tag="v1.0.0", commit="b" * 40)
        self.body = prepared_body(
            "Reviewed release notes\n\n", self.commit, "v1.0.0", "b" * 40,
            [self.published], self.config, tag=TAG,
        )

    def encoded(self, value):
        text = value if isinstance(value, str) else json.dumps(value)
        return MARKER + base64.urlsafe_b64encode(text.encode()).decode() + " -->\n"

    def test_preparation_roundtrip_contains_only_versioned_provenance(self):
        self.assertEqual(preparation(self.body), {
            "version": 1, "tag": TAG, "commit": self.commit, "base": "v1.0.0",
            "base_commit": "b" * 40, "config": config_digest(self.config),
            "published": published_digest([self.published]),
            "guide_references": [],
        })
        self.assertTrue(self.body.startswith("Reviewed release notes\n\n" + MARKER))
        initial = prepared_body("Notes", self.commit, None, None, [], self.config, tag=TAG)
        self.assertIsNone(preparation(initial)["base"])
        self.assertIsNone(preparation(initial)["base_commit"])

    def test_reserved_marker_cannot_be_supplied_in_notes(self):
        for body in (self.body, "Notes " + MARKER, "```\n" + MARKER + "fake\n```"):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "reserved"):
                prepared_body(body, self.commit, None, None, [], self.config, tag=TAG)

    def test_preparation_records_sorted_retained_guide_references(self):
        body = prepared_body("Notes", self.commit, None, None, [], self.config,
                             guide_references=["3.0.0", "2.0.0"], tag=TAG)
        self.assertEqual(preparation(body)["guide_references"], ["2.0.0", "3.0.0"])

    def test_preparation_parses_crlf_without_normalizing_release_identity(self):
        crlf_body = self.body.replace("\n", "\r\n")
        self.assertEqual(preparation(crlf_body), preparation(self.body))
        release = release_record(body=self.body)
        self.assertNotEqual(release_identity(release), release_identity({**release, "body": crlf_body}))

    def test_missing_duplicate_malformed_and_non_utf8_markers_fail(self):
        for body in (
            "", "Unprepared old release", self.body + self.body,
            self.body + MARKER, MARKER + "%%% -->", MARKER + "a -->",
            MARKER + "_w== -->", self.encoded("not json"), self.encoded('{"a":1,"a":2}'),
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                preparation(body)

    def test_schema_rejects_nonobjects_extra_missing_and_wrong_versions(self):
        metadata = preparation(self.body)
        cases = [None, [], 1, {**metadata, "extra": True}]
        cases.extend({key: value for key, value in metadata.items() if key != missing}
                     for missing in metadata)
        cases.extend({**metadata, "version": version} for version in (0, 2, True, 1.0, "1"))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                preparation(self.encoded(value))

    def test_digest_is_canonical_and_published_digest_ignores_order_and_drafts(self):
        self.assertEqual(digest({"b": "é", "a": 1}), digest({"a": 1, "b": "é"}))
        other = {**self.published, "id": 42, "tag_name": "v0.9.0"}
        self.assertEqual(published_digest([self.published, other]),
                         published_digest([other, release_record(), self.published]))
        self.assertNotEqual(published_digest([self.published]),
                            published_digest([{**self.published, "body": "Correction"}]))

    def test_asset_uploads_do_not_change_release_identity_but_metadata_edits_do(self):
        release = release_record()
        uploaded = {**release, "updated_at": "later", "assets": [{"id": 81}],
                    "draft": False, "published_at": "later"}
        self.assertEqual(release_identity(release), release_identity(uploaded))
        for field in ("id", "tag_name", "name", "prerelease", "target_commitish", "body"):
            with self.subTest(field=field):
                self.assertNotEqual(release_identity(release),
                                    release_identity({**release, field: "changed"}))

    def test_config_digest_casefolds_labels_but_not_paths_or_titles(self):
        uppercase = replace(self.config, labels=replace(
            self.config.labels, major=self.config.labels.major.upper(),
        ))
        self.assertEqual(config_digest(self.config), config_digest(uppercase))
        for changed in (
            replace(self.config, fragment_root="other-notes"),
            replace(self.config, default_branch="trunk"),
            replace(self.config, categories=replace(self.config.categories, breaking="Changed")),
        ):
            with self.subTest(config=changed):
                self.assertNotEqual(config_digest(self.config), config_digest(changed))


class PublicationTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("tempfile.tempdir", str(self.workspace)))
        self.enterContext(patch("publication.os.environ", {**os.environ, "GITHUB_REPOSITORY": REPOSITORY}))
        self.branch = "main"
        self.config_path = ""
        self.config = Config()
        self.previous = None
        self.previous_commit = None
        self.releases = []
        self.notes = ""
        self.documents = plan_guides(self.repo, self.base, "", TAG, [], self.config)
        write_guides(self.repo, self.base, self.documents, self.config)
        self.source = self.commit()
        self.git("tag", TAG, self.source)
        self.release = self.prepared_release()
        self.releases = [self.release]

    def prepared_release(self, body="Reviewed release notes"):
        release = release_record(commit=self.source, body=prepared_body(
            body, self.source, self.previous, self.previous_commit,
            self.releases, self.config, tag=TAG,
        ))
        release["html_url"] = f"https://github.com/{REPOSITORY}/releases/tag/untagged-synthetic"
        return release

    def validate(self, release=None, *, sha=None, after=None, releases=None):
        self.git("update-ref", f"refs/remotes/origin/{self.branch}", f"refs/heads/{self.branch}")
        return publication.validate_source(
            self.repo, self.branch, TAG, sha or self.source, after or self.source,
            self.release if release is None else release,
            self.releases if releases is None else releases, self.config_path,
        )

    def retag(self):
        self.source = self.commit()
        self.git("tag", "-f", TAG, self.source)

    def breaking_release(self, *, custom=False):
        if custom:
            self.config_path = ".automation/release.json"
            self.config_commit(CUSTOM, self.config_path)
            self.config = load_config(self.repo, "HEAD", self.config_path, self.branch)
        self.previous = "v1.0.0"
        self.previous_commit = self.git("rev-parse", "HEAD")
        self.git("tag", self.previous)
        previous = release_record(draft=False, tag=self.previous, commit=self.previous_commit)
        previous["id"] = 5
        self.releases = [previous]
        self.write(f"{self.config.fragment_root}/+client-timeouts.breaking.md", NOTE)
        head = self.commit()
        self.notes = render(self.repo, self.previous, head, self.config)
        self.documents = plan_guides(self.repo, head, self.notes, TAG, self.releases, self.config)
        write_guides(self.repo, head, self.documents, self.config)
        self.retag()
        links = linked_notes(self.notes, TAG, REPOSITORY, self.config)
        self.release = self.prepared_release(combine_notes(
            "<!-- migration-base: v1.0.0 -->\n## What's Changed\n\n- Consumer change\n",
            links, self.config,
        ))
        self.releases.append(self.release)

    def event(self):
        ref = f"refs/tags/{TAG}"
        environment = {
            "GITHUB_EVENT_NAME": "push", "GITHUB_REF_TYPE": "tag", "GITHUB_REF": ref,
            "GITHUB_SHA": self.source, "GITHUB_REPOSITORY": REPOSITORY,
        }
        event = {"ref": ref, "deleted": False, "created": True, "forced": False,
                 "before": "0" * 40, "after": self.source,
                 "repository": {"full_name": REPOSITORY}}
        return environment, event

    @contextmanager
    def remote(self, snapshots=None, *, branch_values=None, tag_objects=None, base_objects=None,
               branch_heads=None):
        snapshots = snapshots or [self.releases, self.releases]
        branches = iter(branch_values or [self.branch, self.branch])
        tags = iter(tag_objects or [self.git("rev-parse", f"refs/tags/{TAG}")])
        bases = iter(base_objects or ([self.previous_commit] if self.previous else []))
        heads = iter(branch_heads or [self.git("rev-parse", f"refs/heads/{self.branch}")])

        def github(endpoint, payload=None):
            self.assertIsNone(payload, "Inspection must never mutate GitHub")
            if endpoint == f"repos/{REPOSITORY}":
                return {"default_branch": next(branches)}
            if endpoint == f"repos/{REPOSITORY}/git/ref/heads/{quote(self.branch, safe='')}":
                return {"object": {"type": "commit", "sha": next(heads)}}
            if endpoint == f"repos/{REPOSITORY}/git/ref/tags/{TAG}":
                return {"object": {"type": "commit", "sha": next(tags)}}
            if endpoint == f"repos/{REPOSITORY}/git/ref/tags/{self.previous}":
                return {"object": {"type": "commit", "sha": next(bases)}}
            self.fail(f"Unexpected remote endpoint: {endpoint}")

        def fetch(repo, repository, branch, tag, base):
            self.assertEqual(repository, REPOSITORY)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            refs = [f"refs/heads/{branch}:refs/remotes/origin/{branch}",
                    f"refs/tags/{tag}:refs/tags/{tag}"]
            if base:
                refs.append(f"refs/tags/{base}:refs/tags/{base}")
            subprocess.run(["git", "fetch", "--quiet", "--no-tags", str(self.repo), *refs],
                           cwd=repo, check=True)
            self.assertFalse((repo / "source.txt").exists())

        with ExitStack() as stack:
            reads = stack.enter_context(patch("publication.api", side_effect=copy.deepcopy(snapshots)))
            remote = stack.enter_context(patch("publication.github", side_effect=github))
            fetches = stack.enter_context(patch("publication.fetch_source", side_effect=fetch))
            yield reads, remote, fetches

    def inspect(self):
        return publication.inspect_release(REPOSITORY, TAG, self.source, self.source, self.config_path)

    def test_stable_push_event_is_accepted(self):
        environment, event = self.event()
        self.assertEqual(publication.tag_event(environment, event), (TAG, self.source, self.source))

    def test_event_requires_new_tag_creation_even_when_after_matches_prepared_source(self):
        environment, event = self.event()
        self.assertEqual(event["after"], self.release["target_commitish"])
        cases = [
            {**event, field: value}
            for field, values in (
                ("forced", (True, None, 0, 1, "false", [], {})),
                ("created", (False, None, 0, 1, "true", [], {})),
                ("before", (self.base, self.source, None, 0, "", "0" * 39)),
            )
            for value in values
        ]
        cases.extend(
            {key: value for key, value in event.items() if key != missing}
            for missing in ("forced", "created", "before")
        )
        cases.extend(
            {**event, "created": False, "forced": forced, "before": self.base}
            for forced in (False, True)
        )
        for invalid in cases:
            with self.subTest(event=invalid), self.assertRaisesRegex(ValueError, "creation push"):
                publication.tag_event(environment, invalid)

    def test_event_rejects_branches_manual_deletion_mismatches_and_bad_objects(self):
        environment, event = self.event()
        cases = [
            ({"GITHUB_EVENT_NAME": "workflow_dispatch"}, {}),
            ({"GITHUB_REF_TYPE": "branch"}, {}),
            ({"GITHUB_REF": "refs/heads/main"}, {}),
            ({}, {"ref": "refs/tags/v1.0.0"}), ({}, {"deleted": True}),
            ({}, {"deleted": None}), ({}, {"deleted": 0}),
            ({}, {"repository": {"full_name": "other/consumer"}}),
            ({"GITHUB_REPOSITORY": "other/consumer"}, {}),
        ]
        for value in ("", "a" * 39, "A" * 40, "g" * 40, "main", "a" * 40 + "\n"):
            cases.extend([({"GITHUB_SHA": value}, {}), ({}, {"after": value})])
        cases.append(({}, {"after": 42}))
        for env_changes, event_changes in cases:
            with self.subTest(env=env_changes, event=event_changes), self.assertRaises(ValueError):
                publication.tag_event({**environment, **env_changes}, {**event, **event_changes})
        for tag in (
            "2.0.0", "v02.0.0", "v2.0", "v2.0.0-rc.1", "v2.0.0+build",
            "product/v2.0.0", "v1\u0662.0.0", "v1.1\uff12.0",
        ):
            ref = f"refs/tags/{tag}"
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                publication.tag_event({**environment, "GITHUB_REF": ref}, {**event, "ref": ref})

    def test_selection_requires_exactly_one_matching_release_and_one_draft(self):
        self.assertIs(publication.select_release(self.releases, TAG), self.release)
        for releases in (
            [], [release_record(tag="v3.0.0")], [self.release, self.release.copy()],
            [self.release, {**release_record(tag="v3.0.0"), "id": 99}],
            [self.release, {**release_record(tag="nightly"), "id": 99, "prerelease": True}],
        ):
            with self.subTest(releases=releases), self.assertRaises(ValueError):
                publication.select_release(releases, TAG)

    def test_selection_rejects_wrong_title_prerelease_id_body_and_status(self):
        cases = [
            {"name": TAG}, {"name": "Next release"}, {"prerelease": True},
            {"prerelease": 0}, {"id": 0}, {"id": -1}, {"id": True}, {"id": "17"},
            {"body": None}, {"body": " \n"}, {"draft": 1}, {"published_at": "already"},
            {"draft": False, "published_at": None},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                publication.select_release([{**self.release, **changes}], TAG)

    def test_lightweight_and_annotated_tag_accept_raw_or_peeled_event_ids(self):
        self.assertEqual(self.validate()["tag-object"], self.source)
        self.git("tag", "-f", "-a", TAG, "-m", "Reviewed release", self.source)
        raw = self.git("rev-parse", f"refs/tags/{TAG}")
        self.assertNotEqual(raw, self.source)
        for sha in (raw, self.source):
            for after in (raw, self.source):
                with self.subTest(sha=sha, after=after):
                    identity = self.validate(sha=sha, after=after)
                    self.assertEqual(identity["sha"], self.source)
                    self.assertEqual(identity["tag-object"], raw)

    def test_source_rejects_event_target_and_receipt_commit_mismatches(self):
        for sha, after in ((self.base, self.source), (self.source, self.base)):
            with self.subTest(sha=sha, after=after), self.assertRaisesRegex(ValueError, "same commit"):
                self.validate(sha=sha, after=after)
        for target in ("main", self.base, TAG):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "same commit"):
                self.validate({**self.release, "target_commitish": target})
        body = prepared_body("Notes", self.base, None, None, [], self.config, tag=TAG)
        with self.assertRaisesRegex(ValueError, "same commit"):
            self.validate({**self.release, "body": body})
        body = prepared_body("Notes", self.source, None, None, [], self.config, tag="v1.9.0")
        with self.assertRaisesRegex(ValueError, "same commit"):
            self.validate({**self.release, "body": body})

    def test_source_requires_marker_even_for_published_noop(self):
        for draft in (True, False):
            with self.subTest(draft=draft), self.assertRaisesRegex(ValueError, "redraft"):
                self.validate({**self.release, "draft": draft, "body": "Old unprepared notes"})

    def test_manually_renamed_and_retagged_no_migration_draft_cannot_reuse_preparation(self):
        new_tag = "v3.0.0"
        self.git("tag", new_tag, self.source)
        self.git("update-ref", f"refs/remotes/origin/{self.branch}", f"refs/heads/{self.branch}")
        changed = {**self.release, "tag_name": new_tag, "name": new_tag[1:]}
        environment, event = self.event()
        environment["GITHUB_REF"] = event["ref"] = f"refs/tags/{new_tag}"
        tag, sha, after = publication.tag_event(environment, event)
        selected = publication.select_release([changed], tag)
        self.assertEqual(preparation(selected["body"])["tag"], TAG)
        self.assertEqual(selected["target_commitish"], self.source)
        self.assertNotIn(MIGRATION_START, selected["body"])
        with self.assertRaisesRegex(ValueError, "same commit"):
            publication.validate_source(
                self.repo, self.branch, tag, sha, after, selected, [selected], self.config_path,
            )

    def test_default_branch_can_advance_but_source_must_remain_ancestor(self):
        self.write("source.txt", "New default branch work\n")
        self.commit()
        self.assertEqual(self.validate()["sha"], self.source)
        self.git("branch", "unrelated", self.base)
        self.branch = "unrelated"
        with self.assertRaisesRegex(ValueError, "default-branch history"):
            self.validate()

    def test_tagged_config_is_used_instead_of_new_head_or_dirty_worktree(self):
        self.breaking_release(custom=True)
        self.config_commit({"version": 1, "fragment_root": "new-head-notes"}, self.config_path)
        self.write(self.config_path, '{"version":999}')
        self.write(f"{self.config.guide_root}/2.0.0/client-timeouts.md", "Dirty guide")
        self.write(f"{self.config.fragment_root}/+client-timeouts.breaking.md", "Dirty fragment")
        self.assertEqual(self.validate()["sha"], self.source)

    def test_missing_committed_config_does_not_use_worktree(self):
        self.config_path = ".automation/release.json"
        self.write(self.config_path, json.dumps(CUSTOM))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.validate()

    def test_config_digest_mismatch_fails_before_publication(self):
        changed = replace(self.config, fragment_root="other-notes")
        body = prepared_body("Notes", self.source, None, None, [], changed, tag=TAG)
        with self.assertRaisesRegex(ValueError, "configuration"):
            self.validate({**self.release, "body": body})

    def test_invalid_retained_guide_references_are_rejected(self):
        metadata = preparation(self.release["body"])
        for references in (None, "2.0.0", [1], ["v2.0.0"], ["2.0.0-rc.1"], ["../../other"]):
            encoded = base64.urlsafe_b64encode(json.dumps({
                **metadata, "guide_references": references,
            }).encode()).decode()
            release = {**self.release, "body": f"Notes\n\n{MARKER}{encoded} -->\n"}
            with self.subTest(references=references), self.assertRaisesRegex(ValueError, "retention references"):
                self.validate(release)

    def test_committed_breaking_guides_and_previous_tag_receipt_are_validated(self):
        self.breaking_release()
        self.assertEqual(self.validate()["sha"], self.source)
        metadata = preparation(self.release["body"])
        self.assertEqual((metadata["base"], metadata["base_commit"]),
                         (self.previous, self.previous_commit))
        self.assertIn("/blob/main/docs/migrations/2.0.0/client-timeouts.md", self.release["body"])

    def test_missing_stale_guide_index_and_pending_state_are_rejected(self):
        self.breaking_release()
        original_source = self.source
        original_release = self.release
        cases = [
            ("docs/migrations/2.0.0/client-timeouts.md", None),
            ("docs/migrations/2.0.0/client-timeouts.md",
             self.documents["docs/migrations/2.0.0/client-timeouts.md"].replace(
                 "Requests waited", "Clients waited",
             )),
            ("docs/migrations/2.0.0/README.md", "# Stale index\n"),
            ("docs/migrations/README.md", "# Stale root index\n"),
            (self.config.state_path, None),
            (self.config.state_path, '{"pending_versions":[]}'),
        ]
        for name, content in cases:
            with self.subTest(name=name, content=content):
                self.git("reset", "--hard", original_source)
                if content is None:
                    self.repo.joinpath(*name.split("/")).unlink()
                else:
                    self.write(name, content)
                self.retag()
                notes = original_release["body"].split(MARKER)[0]
                release = self.prepared_release(notes)
                with self.assertRaises(ValueError):
                    self.validate(release)

    def test_initial_release_also_requires_committed_root_index(self):
        self.git("tag", "-f", TAG, self.base)
        self.source = self.base
        self.release = self.prepared_release()
        with self.assertRaisesRegex(ValueError, "exact prepared migration"):
            self.validate()

    def test_tagged_historical_published_guide_corrections_are_preserved(self):
        self.breaking_release()
        corrected = self.documents["docs/migrations/2.0.0/client-timeouts.md"].replace(
            "**Version introduced:** 2.0.0", "**Version introduced:** 1.0.0",
        ).replace("Set the timeout explicitly", "Use the reviewed timeout setting")
        self.write("docs/migrations/1.0.0/client-timeouts.md", corrected)
        self.write("docs/migrations/1.0.0/README.md",
                   self.documents["docs/migrations/2.0.0/README.md"].replace("2.0.0", "1.0.0"))
        head = self.commit()
        documents = plan_guides(self.repo, head, self.notes, TAG, self.releases, self.config)
        self.assertEqual(documents["docs/migrations/1.0.0/client-timeouts.md"], corrected)
        write_guides(self.repo, head, documents, self.config)
        self.retag()
        self.release = self.prepared_release(self.release["body"].split(MARKER)[0])
        self.releases[-1] = self.release
        self.assertEqual(self.validate()["sha"], self.source)
        self.assertEqual(self.git("show", f"{self.source}:docs/migrations/1.0.0/client-timeouts.md"),
                         corrected.strip())

    def test_migration_links_cannot_be_missing_stale_duplicated_or_unexpected(self):
        self.breaking_release()
        body = self.release["body"]
        block = body[body.index(MIGRATION_START):body.index(MIGRATION_END) + len(MIGRATION_END)]
        for changed in (
            body.replace(block, ""), body.replace("/blob/main/", "/blob/other/"),
            body.replace("/2.0.0/", "/1.0.0/"), body + block,
            body.replace(MIGRATION_END, ""), body.replace(MIGRATION_START, ""),
        ):
            with self.subTest(body=changed), self.assertRaisesRegex(ValueError, "migration links"):
                self.validate({**self.release, "body": changed})
        self.notes = ""
        for marker in (MIGRATION_START, MIGRATION_END):
            release = self.prepared_release("Notes\n" + marker)
            with patch("publication.render", return_value=""), patch(
                "publication.plan_guides", return_value=self.documents,
            ), self.assertRaisesRegex(ValueError, "Unexpected migration"):
                self.validate(release)

    def test_previous_tag_movement_and_published_metadata_changes_reject_receipt(self):
        self.breaking_release()
        self.git("tag", "-f", self.previous, self.source)
        with self.assertRaisesRegex(ValueError, "previous release tag changed"):
            self.validate()
        self.git("tag", "-f", self.previous, self.previous_commit)
        for field, value in (("body", "Reviewed correction"), ("name", "Renamed"),
                             ("id", 66), ("target_commitish", self.source)):
            releases = copy.deepcopy(self.releases)
            releases[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Published release state"):
                self.validate(releases=releases)

    def test_publication_must_advance_even_with_a_matching_fresh_receipt(self):
        for tag in (TAG, "v3.0.0"):
            published = {**release_record(draft=False, tag=tag), "id": 55}
            self.releases = [published]
            release = self.prepared_release()
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "advance"):
                self.validate(release, releases=[published, release])

    def test_published_rerun_preserves_edited_notes_and_ignores_later_releases_and_old_guides(self):
        published = {**self.release, "draft": False, "published_at": "now",
                     "body": "Reviewed historical correction\n" + self.release["body"]}
        later = {**release_record(draft=False, tag="v3.0.0"), "id": 99}
        self.releases = [published, later, release_record(tag="v4.0.0")]
        self.write("docs/migrations/README.md", "# Corrected historical index\n")
        self.commit()
        with patch("publication.render", side_effect=AssertionError("Do not regenerate historical guides")):
            with self.remote():
                selected, identity = self.inspect()
        with patch("publication.github") as writes:
            result = publication.finalize(REPOSITORY, selected, identity, identity.copy())
        writes.assert_not_called()
        self.assertEqual(result, published)
        self.assertEqual(result["body"], published["body"])

    def test_inspect_reads_fresh_remote_state_and_returns_opaque_context(self):
        with self.remote() as (reads, remote, fetches):
            release, identity = self.inspect()
        self.assertEqual(release, self.release)
        self.assertEqual(identity, {
            "sha": self.source, "tag-object": self.source,
            "release": digest(release_identity(self.release)), "version": 1,
            "repository": REPOSITORY, "tag": TAG, "release-id": 17,
            "config-path": "", "default-branch": self.branch,
        })
        self.assertEqual(reads.call_args_list,
                         [unittest.mock.call(f"repos/{REPOSITORY}/releases")] * 2)
        self.assertEqual(remote.call_count, 4)
        self.assertEqual(fetches.call_count, 1)

    def test_inspect_quotes_default_branch_in_final_head_recheck(self):
        self.branch = "trunk/releases"
        self.git("branch", "-m", self.branch)
        self.config = replace(self.config, default_branch=self.branch)
        self.release = self.prepared_release()
        self.releases = [self.release]
        with self.remote() as (_, remote, _):
            _, identity = self.inspect()
        self.assertEqual(identity["default-branch"], self.branch)
        remote.assert_any_call(f"repos/{REPOSITORY}/git/ref/heads/trunk%2Freleases")

    def test_inspect_rejects_metadata_edits_and_published_state_races(self):
        cases = [
            {"body": self.release["body"] + "\nEdited"}, {"name": "New title"}, {"id": 88},
            {"target_commitish": self.base}, {"prerelease": True},
            {"draft": False, "published_at": "now"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                changed = [{**self.release, **changes}]
                with self.remote([self.releases, changed]), self.assertRaises(ValueError):
                    self.inspect()
        published = {**release_record(draft=False, tag="v1.0.0"), "id": 5}
        with self.remote([self.releases, [self.release, published]]), self.assertRaises(ValueError):
            self.inspect()

    def test_inspect_allows_asset_uploads_between_reads(self):
        uploaded = {**self.release, "updated_at": "later", "assets": [{"id": 81, "name": "binary.zip"}]}
        with self.remote([self.releases, [uploaded]]):
            _, identity = self.inspect()
        self.assertEqual(identity["release"], digest(release_identity(uploaded)))

    def test_inspect_rejects_default_branch_tag_and_base_tag_races(self):
        with self.remote(branch_values=["main", "trunk"]), self.assertRaisesRegex(ValueError, "changed"):
            self.inspect()
        with self.remote(tag_objects=[self.base]), self.assertRaisesRegex(ValueError, "changed"):
            self.inspect()
        with self.remote(branch_heads=[self.base]), self.assertRaisesRegex(ValueError, "changed"):
            self.inspect()
        self.breaking_release()
        with self.remote(base_objects=[self.source]), self.assertRaisesRegex(ValueError, "previous release tag"):
            self.inspect()

    def test_inspect_api_failure_never_fetches_or_mutates(self):
        error = subprocess.CalledProcessError(1, ["gh", "api"])
        with patch("publication.api", side_effect=error), patch("publication.github") as github:
            with patch("publication.fetch_source") as fetch, self.assertRaises(subprocess.CalledProcessError):
                self.inspect()
        github.assert_not_called()
        fetch.assert_not_called()

    def test_invalid_previous_tag_receipt_is_rejected_before_fetch(self):
        for base in ("main", "v1.0.0-rc.1", "v1\u0662.0.0", "v1.1\uff12.0", 1, []):
            release = {**self.release, "body": prepared_body(
                "Notes", self.source, base, self.base, [], self.config, tag=TAG,
            )}
            with self.subTest(base=base), patch("publication.api", return_value=[release]):
                with patch("publication.fetch_source") as fetch, self.assertRaisesRegex(
                    ValueError, "previous release tag",
                ):
                    self.inspect()
                fetch.assert_not_called()

    def test_inspect_rejects_replaced_annotated_object_even_at_same_commit(self):
        self.git("tag", "-f", "-a", TAG, "-m", "Original", self.source)
        original = self.git("rev-parse", f"refs/tags/{TAG}")
        self.git("tag", "-f", "-a", TAG, "-m", "Replacement", self.source)
        replacement = self.git("rev-parse", f"refs/tags/{TAG}")
        self.git("update-ref", f"refs/tags/{TAG}", original)
        self.assertNotEqual(original, replacement)
        with self.remote(tag_objects=[replacement]), self.assertRaisesRegex(ValueError, "changed"):
            self.inspect()

    def test_finalize_allows_uploads_after_cross_job_json_roundtrip_and_only_patches_flags(self):
        with self.remote() as (_, _, prepare_fetches):
            _, context = self.inspect()
        context = json.loads(json.dumps(context, sort_keys=True, separators=(",", ":")))
        uploaded = {**self.release, "updated_at": "later", "assets": [{"id": 81}]}
        self.releases = [uploaded]
        with self.remote() as (_, _, fetches):
            selected, identity = self.inspect()
        self.assertEqual(prepare_fetches.call_count, 1)
        self.assertEqual(fetches.call_count, 1)
        self.assertNotEqual(prepare_fetches.call_args.args[0], fetches.call_args.args[0])
        published = {**uploaded, "draft": False, "published_at": "now"}
        with patch("publication.github", return_value=published) as writes:
            result = publication.finalize(REPOSITORY, selected, identity, context)
        writes.assert_called_once_with(f"repos/{REPOSITORY}/releases/17",
                                       {"draft": False, "make_latest": "true"})
        self.assertEqual(result["body"], self.release["body"])
        self.assertEqual(result["assets"], uploaded["assets"])

    def test_finalize_rejects_metadata_edits_between_phases_before_any_write(self):
        with self.remote():
            _, context = self.inspect()
        for field, value in (
            ("body", self.release["body"] + "\nCorrection"),
            ("body", self.release["body"].replace("\n", "\r\n")),
            ("id", 81),
        ):
            changed = {**self.release, field: value}
            self.releases = [changed]
            with self.subTest(field=field), self.remote():
                selected, identity = self.inspect()
            with patch("publication.github") as writes, self.assertRaisesRegex(ValueError, "context changed"):
                publication.finalize(REPOSITORY, selected, identity, context)
            writes.assert_not_called()
        for field, value in (("name", "Edited release"), ("tag_name", "v3.0.0"),
                             ("target_commitish", self.base)):
            self.releases = [{**self.release, field: value}]
            with self.subTest(field=field), self.remote(), self.assertRaises(ValueError):
                self.inspect()

    def test_crlf_migration_notes_before_prepare_are_preserved_through_finalization(self):
        self.breaking_release()
        crlf_body = self.release["body"].replace("\n", "\r\n")
        self.release = {**self.release, "body": crlf_body}
        self.releases[-1] = self.release
        with self.remote():
            _, context = self.inspect()
        with self.remote():
            release, identity = self.inspect()
        published = {**release, "draft": False, "published_at": "now"}
        with patch("publication.github", return_value=published) as writes:
            result = publication.finalize(REPOSITORY, release, identity, context)
        self.assertEqual(result["body"], crlf_body)
        self.assertEqual(identity["release"], digest(release_identity(self.release)))
        writes.assert_called_once_with(f"repos/{REPOSITORY}/releases/17",
                                       {"draft": False, "make_latest": "true"})

    def test_default_branch_advancement_between_phases_does_not_change_context(self):
        with self.remote():
            _, context = self.inspect()
        self.write("source.txt", "Later default-branch commit\n")
        self.commit()
        with self.remote():
            _, identity = self.inspect()
        self.assertEqual(identity, context)

    def test_annotated_tag_replacement_between_phases_invalidates_context(self):
        self.git("tag", "-f", "-a", TAG, "-m", "Original receipt", self.source)
        with self.remote():
            _, context = self.inspect()
        self.git("tag", "-f", "-a", TAG, "-m", "Replacement receipt", self.source)
        with self.remote():
            release, identity = self.inspect()
        self.assertEqual(identity["sha"], context["sha"])
        self.assertNotEqual(identity["tag-object"], context["tag-object"])
        with patch("publication.github") as writes, self.assertRaisesRegex(ValueError, "context changed"):
            publication.finalize(REPOSITORY, release, identity, context)
        writes.assert_not_called()

    def test_finalize_rejects_every_stale_or_missing_context_field(self):
        with self.remote():
            selected, identity = self.inspect()
        for field in identity:
            for context in ({**identity, field: "changed"},
                            {key: value for key, value in identity.items() if key != field}):
                with self.subTest(field=field, context=context), patch("publication.github") as writes:
                    with self.assertRaisesRegex(ValueError, "context changed"):
                        publication.finalize(REPOSITORY, selected, identity, context)
                    writes.assert_not_called()
        with patch("publication.github") as writes, self.assertRaises(ValueError):
            publication.finalize(REPOSITORY, selected, identity, {**identity, "extra": True})
        writes.assert_not_called()

    def test_finalize_rejects_unexpected_patch_response_and_api_failure(self):
        identity = self.validate()
        published = {**self.release, "draft": False, "published_at": "now"}
        for changes in ({"draft": True}, {"published_at": None}, {"id": 55},
                        {"body": "Changed"}, {"target_commitish": self.base},
                        {"name": "Changed"}, {"tag_name": "v3.0.0"}, {"prerelease": True}):
            with self.subTest(changes=changes), patch("publication.github", return_value={
                **published, **changes,
            }), self.assertRaisesRegex(ValueError, "expected published"):
                publication.finalize(REPOSITORY, self.release, identity, identity)
        error = subprocess.CalledProcessError(1, ["gh", "api"])
        with patch("publication.github", side_effect=error), self.assertRaises(subprocess.CalledProcessError):
            publication.finalize(REPOSITORY, self.release, identity, identity)

    def cli(self, command, *, context=None, environment=None):
        env, event = self.event()
        event_path = self.workspace / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        output = self.workspace / "outputs.txt"
        output.unlink(missing_ok=True)
        env.update({
            "GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output),
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
            "CONFIG_PATH": self.config_path,
        })
        if context is not None:
            env["RELEASE_CONTEXT"] = context if isinstance(context, str) else json.dumps(context)
        env.update(environment or {})
        stdout, stderr = io.StringIO(), io.StringIO()
        inherited = {key: value for key, value in os.environ.items()
                     if key not in ("RELEASE_CONTEXT", "CONFIG_PATH")}
        with patch("publication.os.environ", {**inherited, **env}), patch(
            "sys.argv", ["publication.py", command],
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                publication.execute()
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        return values, stdout.getvalue()

    def test_prepare_cli_outputs_single_line_context_and_finalize_reuses_config_path(self):
        self.breaking_release(custom=True)
        with self.remote():
            outputs, message = self.cli("prepare")
        self.assertEqual(outputs["tag"], TAG)
        self.assertEqual(outputs["version"], "2.0.0")
        self.assertEqual(outputs["sha"], self.source)
        self.assertEqual(outputs["release-id"], "17")
        self.assertEqual(outputs["release-url"],
                         f"https://github.com/{REPOSITORY}/releases/tag/untagged-synthetic")
        self.assertEqual(outputs["already-published"], "false")
        context = json.loads(outputs["context"])
        self.assertEqual(context["config-path"], self.config_path)
        self.assertIn("prepared.", message)
        published = {
            **self.release, "draft": False, "published_at": "now",
            "html_url": f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
        }
        with self.remote(), patch("publication.finalize", return_value=published) as finalize:
            values, message = self.cli("finalize", context=outputs["context"],
                                       environment={"CONFIG_PATH": "ignored.json"})
        self.assertEqual(finalize.call_args.args[3], context)
        self.assertEqual(set(values), {"release-id", "release-url", "already-published"})
        self.assertEqual(values["release-url"], published["html_url"])
        self.assertNotEqual(values["release-url"], outputs["release-url"])
        self.assertIn("published.", message)

    def test_published_cli_reports_noop_without_mutation(self):
        published_url = f"https://github.com/{REPOSITORY}/releases/tag/{TAG}"
        self.releases = [{
            **self.release, "draft": False, "published_at": "now", "html_url": published_url,
        }]
        with self.remote():
            outputs, message = self.cli("prepare")
        self.assertEqual(outputs["already-published"], "true")
        self.assertEqual(outputs["release-url"], published_url)
        self.assertIn("already published.", message)
        with self.remote():
            values, message = self.cli("finalize", context=outputs["context"])
        self.assertEqual(values["already-published"], "true")
        self.assertEqual(values["release-url"], published_url)
        self.assertIn("already published.", message)

    def test_cross_job_context_cannot_authorize_another_repository_release_or_commit(self):
        with self.remote():
            outputs, _ = self.cli("prepare")
        context = json.loads(outputs["context"])
        tampered = {
            **context, "repository": "other/victim", "release-id": 999,
            "sha": self.base, "tag": "v3.0.0",
        }
        with self.remote() as (_, _, fetches), patch(
            "publication.inspect_release", wraps=publication.inspect_release,
        ) as inspect:
            with self.assertRaisesRegex(ValueError, "context changed"):
                self.cli("finalize", context=json.dumps(tampered))
        inspect.assert_called_once_with(
            REPOSITORY, TAG, self.source, self.source, self.config_path,
        )
        self.assertEqual(fetches.call_count, 1)
        self.assertEqual(fetches.call_args.args[1:4], (REPOSITORY, self.branch, TAG))

    def test_cli_rejects_invalid_context_repository_host_and_configuration(self):
        for context in ("not json", "[]", '{"config-path":1}',
                        '{"config-path":"","config-path":"other"}', '{}'):
            with self.subTest(context=context), patch("publication.inspect_release") as inspect:
                with self.assertRaises((ValueError, KeyError)):
                    self.cli("finalize", context=context)
                inspect.assert_not_called()
        with self.remote(), patch("publication.github", wraps=publication.github) as github:
            with self.assertRaisesRegex(ValueError, "context changed"):
                self.cli("finalize", context="null")
            self.assertTrue(all(len(call.args) == 1 for call in github.call_args_list))
        for environment in (
            {"GITHUB_SERVER_URL": "https://github.example"},
            {"GITHUB_API_URL": "https://api.github.example"},
            {"GITHUB_REPOSITORY": "example/consumer/other"},
            {"GITHUB_REPOSITORY": "example/consumer\ninjected=value"},
        ):
            with self.subTest(environment=environment), patch("publication.inspect_release") as inspect:
                with self.assertRaises(ValueError):
                    self.cli("prepare", environment=environment)
                inspect.assert_not_called()

    def test_main_reports_errors_and_exits_without_traceback(self):
        for error in (ValueError("Invalid tag"), KeyError("config-path"), TypeError("Invalid record"),
                      OSError("No event file"), subprocess.CalledProcessError(1, ["gh", "api"])):
            stderr = io.StringIO()
            with self.subTest(error=error), patch("publication.execute", side_effect=error):
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as exit:
                    publication.main()
            self.assertEqual(exit.exception.code, 1)
            self.assertIn("Release publication failed:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_drafting_records_marker_only_on_final_ready_write(self):
        self.git("remote", "add", "origin", str(self.repo))
        preview = "<!-- migration-base:  -->\n## What's Changed\n\n- Consumer fix\n"
        writes = []

        def api(endpoint, method="GET", payload=None):
            if payload is None:
                return []
            writes.append((endpoint, method, payload))
            return {"id": 17, "published_at": None, **payload}

        with patch("update_release_draft.api", side_effect=api), patch(
            "update_release_draft.prepared_body", wraps=prepared_body,
        ) as marker:
            self.assertTrue(process_preview(
                self.repo, self.source, preview, "2.0.0", TAG, REPOSITORY, [],
                prepare=True, config=self.config,
            ))
            marker.assert_not_called()
            self.assertEqual(writes, [])
            self.assertTrue(process_preview(
                self.repo, self.source, preview, "2.0.0", TAG, REPOSITORY, [],
                prepare=False, config=self.config,
            ))
            marker.assert_called_once()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], "POST")
        metadata = preparation(writes[0][2]["body"])
        self.assertEqual(metadata["commit"], self.source)
        self.assertEqual(metadata["published"], published_digest([]))
        self.assertIsNone(metadata["base"])
        self.assertTrue(writes[0][2]["draft"])

    def test_unready_drafting_never_adds_marker_or_mutates_release(self):
        self.git("remote", "add", "origin", str(self.repo))
        self.write(".changes/+client-timeouts.breaking.md", NOTE)
        head = self.commit()
        preview = "<!-- migration-base:  -->\n## What's Changed\n\n- Breaking fix\n"
        with patch("update_release_draft.api", return_value=[]), patch(
            "update_release_draft.prepared_body",
        ) as marker, patch("update_release_draft.update_draft") as write:
            with self.assertRaisesRegex(ValueError, "Waiting for migration guides"):
                process_preview(self.repo, head, preview, "2.0.0", TAG, REPOSITORY, [],
                                prepare=False, config=self.config)
        marker.assert_not_called()
        write.assert_not_called()

    def test_draft_update_receipt_replays_previous_boundary_and_guide_retention(self):
        self.breaking_release()
        self.git("remote", "add", "origin", str(self.repo))
        writes = []

        def api(endpoint, method="GET", payload=None):
            if payload is None:
                return self.releases
            writes.append((endpoint, method, payload))
            return {"id": 17, "published_at": None, **payload}

        preview = "<!-- migration-base: v1.0.0 -->\n## What's Changed\n\n- Consumer change\n"
        with patch("update_release_draft.api", side_effect=api):
            self.assertTrue(process_preview(
                self.repo, self.source, preview, "2.0.0", TAG, REPOSITORY, self.releases,
                prepare=False, config=self.config,
            ))
        self.assertEqual(len(writes), 1)
        endpoint, method, payload = writes[0]
        self.assertEqual((endpoint, method), (f"repos/{REPOSITORY}/releases/17", "PATCH"))
        metadata = preparation(payload["body"])
        self.assertEqual(metadata["base"], self.previous)
        self.assertEqual(metadata["base_commit"], self.previous_commit)
        self.assertEqual(metadata["published"], published_digest(self.releases))
        self.assertEqual(metadata["guide_references"], ["2.0.0"])
        release = {**self.release, **payload}
        self.assertEqual(self.validate(release)["sha"], self.source)

    def test_draft_replacement_replays_retention_after_old_migration_link_disappears(self):
        self.breaking_release()
        for name, text in self.documents.items():
            if "/2.0.0/" in name:
                self.write(name.replace("/2.0.0/", "/1.5.0/"), text.replace("2.0.0", "1.5.0"))
        self.write(self.config.state_path, '{"pending_versions":["1.5.0","2.0.0"]}\n')
        old_link = "https://github.com/example/consumer/blob/main/docs/migrations/1.5.0/client-timeouts.md"
        self.releases[-1] = {**self.release, "body": self.release["body"] + "\n" + old_link}
        head = self.commit()
        documents = plan_guides(self.repo, head, self.notes, TAG, self.releases, self.config)
        write_guides(self.repo, head, documents, self.config)
        self.retag()
        self.git("remote", "add", "origin", str(self.repo))
        writes = []

        def api(endpoint, method="GET", payload=None):
            if payload is None:
                return self.releases
            writes.append({"id": 17, "published_at": None, **payload})
            return writes[-1]

        preview = "<!-- migration-base: v1.0.0 -->\n## What's Changed\n\n- Consumer change\n"
        with patch("update_release_draft.api", side_effect=api):
            self.assertTrue(process_preview(
                self.repo, self.source, preview, "2.0.0", TAG, REPOSITORY, self.releases,
                prepare=False, config=self.config,
            ))
        self.assertEqual(len(writes), 1)
        release = writes[0]
        self.assertNotIn(old_link, release["body"])
        self.assertEqual(preparation(release["body"])["guide_references"], ["1.5.0", "2.0.0"])
        self.releases[-1] = release
        self.assertEqual(self.validate(release)["sha"], self.source)

    def test_fetch_source_uses_explicit_refs_ephemeral_auth_and_no_checkout(self):
        destination = self.workspace / "fetched"
        destination.mkdir()
        real_run = subprocess.run

        def run_local(args, **kwargs):
            if args[:2] == ["git", "fetch"]:
                return subprocess.CompletedProcess(args, 0)
            return real_run(args, **kwargs)

        inherited = {**os.environ, "GH_TOKEN": "synthetic-test-token"}
        initial_count = int(inherited.get("GIT_CONFIG_COUNT", "0"))
        inherited.update({
            "GIT_CONFIG_COUNT": str(initial_count + 2),
            f"GIT_CONFIG_KEY_{initial_count}": "safe.bareRepository",
            f"GIT_CONFIG_VALUE_{initial_count}": "explicit",
            f"GIT_CONFIG_KEY_{initial_count + 1}": "core.fsmonitor",
            f"GIT_CONFIG_VALUE_{initial_count + 1}": "",
        })
        auth_index = initial_count + 2
        with patch("publication.os.environ", inherited), patch(
            "publication.subprocess.run", side_effect=run_local,
        ) as run:
            publication.fetch_source(destination, REPOSITORY, "main", TAG, "v1.0.0")
        args = run.call_args.args[0]
        self.assertEqual(args, [
            "git", "fetch", "--quiet", "--no-tags", "origin",
            "+refs/heads/main:refs/remotes/origin/main", f"+refs/tags/{TAG}:refs/tags/{TAG}",
            "+refs/tags/v1.0.0:refs/tags/v1.0.0",
        ])
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(environment["GIT_CONFIG_COUNT"], str(auth_index + 1))
        for index in range(auth_index):
            for field in ("KEY", "VALUE"):
                key = f"GIT_CONFIG_{field}_{index}"
                self.assertEqual(environment[key], inherited[key])
        self.assertEqual(environment[f"GIT_CONFIG_KEY_{auth_index}"], "http.https://github.com/.extraheader")
        encoded = environment[f"GIT_CONFIG_VALUE_{auth_index}"].removeprefix("AUTHORIZATION: basic ")
        self.assertEqual(base64.b64decode(encoded).decode(), "x-access-token:synthetic-test-token")
        config = (destination / ".git" / "config").read_text(encoding="utf-8")
        self.assertIn(f"https://github.com/{REPOSITORY}.git", config)
        self.assertNotIn("synthetic-test-token", config)
        self.assertNotIn("extraheader", config)
        self.assertFalse((destination / "source.txt").exists())

    def test_real_local_fetch_with_main_as_initial_default_branch_never_checks_out_source(self):
        destination = self.workspace / "actual-fetch"
        destination.mkdir()
        git_config = self.workspace / "isolated-gitconfig"
        git_config.write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        real_git = publication.git
        real_run = subprocess.run
        substitutions = []

        def local_git(repo, *args):
            if args[:3] == ("remote", "add", "origin"):
                self.assertEqual(args[3], f"https://github.com/{REPOSITORY}.git")
                substitutions.append(args[3])
                return real_git(repo, *args[:3], str(self.repo))
            return real_git(repo, *args)

        def run_with_environment(args, **kwargs):
            kwargs.setdefault("env", dict(os.environ))
            return real_run(args, **kwargs)

        with patch("publication.os.environ", {
            **os.environ,
            "GH_TOKEN": "synthetic-test-token", "GIT_CONFIG_GLOBAL": str(git_config),
            "GIT_CONFIG_NOSYSTEM": "1",
        }), patch("publication.git", side_effect=local_git), patch(
            "publication.subprocess.run", side_effect=run_with_environment,
        ):
            publication.fetch_source(destination, REPOSITORY, "main", TAG, None)
        self.assertEqual(len(substitutions), 1)
        self.assertEqual(real_git(destination, "symbolic-ref", "HEAD").strip(), "refs/heads/main")
        self.assertEqual(real_git(destination, "rev-parse", "refs/remotes/origin/main").strip(),
                         self.source)
        self.assertEqual(real_git(destination, "rev-parse", f"refs/tags/{TAG}").strip(), self.source)
        self.assertEqual(real_git(destination, "ls-files").strip(), "")
        self.assertFalse((destination / "source.txt").exists())
        self.assertFalse((destination / "docs").exists())

    def test_fetch_source_rejects_empty_or_multiline_token_before_network(self):
        real_run = subprocess.run

        def run_local(args, **kwargs):
            self.assertNotEqual(args[:2], ["git", "fetch"], "Invalid credentials must not reach GitHub")
            return real_run(args, **kwargs)

        for index, token in enumerate(("", "token\nheader", "token\rheader")):
            destination = self.workspace / f"fetch-{index}"
            destination.mkdir()
            with self.subTest(token=token), patch("publication.os.environ", {**os.environ, "GH_TOKEN": token}):
                with patch("publication.subprocess.run", side_effect=run_local), self.assertRaisesRegex(
                    ValueError, "token",
                ):
                    publication.fetch_source(destination, REPOSITORY, "main", TAG, None)


class PublicationTransportTests(unittest.TestCase):
    def test_github_uses_explicit_host_json_stdin_and_only_patch_for_mutation(self):
        payload = {"draft": False, "make_latest": "true"}
        with patch("publication.subprocess.check_output", return_value='{"id":17}') as run:
            self.assertEqual(publication.github("repos/example/consumer", payload), {"id": 17})
        self.assertEqual(run.call_args.args[0], [
            "gh", "api", "--hostname", "github.com", "repos/example/consumer",
            "--method", "PATCH", "--input", "-",
        ])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        with patch("publication.subprocess.check_output", return_value='{"default_branch":"main"}') as run:
            publication.github("repos/example/consumer")
        self.assertNotIn("--method", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["input"])

    def test_remote_tag_quotes_ref_and_rejects_invalid_objects(self):
        with patch("publication.github", return_value={"object": {"type": "tag", "sha": "a" * 40}}) as api:
            self.assertEqual(publication.remote_tag(REPOSITORY, "topic/tag #1"), "a" * 40)
        api.assert_called_once_with(f"repos/{REPOSITORY}/git/ref/tags/topic%2Ftag%20%231")
        for obj in ({"type": "tree", "sha": "a" * 40}, {"type": "blob", "sha": "a" * 40},
                    {"type": "commit", "sha": "bad"}):
            with self.subTest(obj=obj), patch("publication.github", return_value={"object": obj}):
                with self.assertRaises(ValueError):
                    publication.remote_tag(REPOSITORY, TAG)

    def test_previous_remote_tag_peels_annotated_chain_and_has_depth_limit(self):
        replies = [
            {"object": {"type": "tag", "sha": "a" * 40}},
            {"object": {"type": "tag", "sha": "b" * 40}},
            {"object": {"type": "commit", "sha": "c" * 40}},
        ]
        with patch("publication.github", side_effect=replies) as api:
            self.assertEqual(publication.remote_tag_commit(REPOSITORY, "v1.0.0"), "c" * 40)
        self.assertEqual(api.call_args_list, [
            unittest.mock.call(f"repos/{REPOSITORY}/git/ref/tags/v1.0.0"),
            unittest.mock.call(f"repos/{REPOSITORY}/git/tags/{'a' * 40}"),
            unittest.mock.call(f"repos/{REPOSITORY}/git/tags/{'b' * 40}"),
        ])
        for obj in ({"type": "tag", "sha": "a" * 40}, {"type": "blob", "sha": "a" * 40},
                    {"type": "commit", "sha": "invalid"}):
            with self.subTest(obj=obj), patch("publication.github", return_value={"object": obj}) as api:
                with self.assertRaisesRegex(ValueError, "Cannot resolve"):
                    publication.remote_tag_commit(REPOSITORY, "v1.0.0")
                self.assertLessEqual(api.call_count, 17)

    def test_output_rejects_line_injection(self):
        with patch("publication.os.environ", {**os.environ, "GITHUB_OUTPUT": "unused-output.txt"}), patch(
            "pathlib.Path.open", unittest.mock.mock_open(),
        ):
            for value in ("good\ninjected=true", "good\rinjected=true"):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Multiline"):
                    publication.output_values({"context": value})


if __name__ == "__main__":
    unittest.main()
