import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from migration_guides import guide_documents
from migration_notes import (
    REQUIRED_SECTIONS, find_section, markdown_lines, shift_heading_levels,
    validate_fragment, validate_guide,
)


TITLE = "### Timeout changes\n\n"
INTRODUCTION = "Requests now time out instead of waiting indefinitely.\n\n"
SECTIONS = "".join(
    f"#### {heading}\n\nCompleted {heading.lower()} guidance.\n\n"
    for heading in REQUIRED_SECTIONS
)
FRAGMENT = TITLE + INTRODUCTION + SECTIONS
FRAGMENT_PATH = ".changes/+timeout.breaking.md"
GUIDE_PATH = "docs/migrations/2.0.0/timeout.md"
METADATA = "**Version introduced:** 2.0.0\n\n"


def documents(fragment):
    yield "fragment", fragment, lambda text: validate_fragment(FRAGMENT_PATH, text)
    yield "standalone", (
        "# Timeout changes\n\n" + METADATA
        + fragment.removeprefix(TITLE).replace("#### ", "## ")
    ), lambda text: validate_guide(GUIDE_PATH, text)
    yield "legacy", (
        "# Upgrade to 2.0.0\n\n" + METADATA
        + "## Breaking changes and migration\n\n" + fragment
    ), lambda text: validate_guide(GUIDE_PATH, text)


class MarkdownCommentTests(unittest.TestCase):
    def assert_invalid_documents(self, fragment, error):
        for kind, text, validate in documents(fragment):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, error):
                    validate(text)

    def test_introduction_requires_a_completed_paragraph(self):
        for introduction in (
            "", "TODO", "TBD.", "N/A", "<!-- Briefly describe the change. -->",
            "**TODO**", "_TBD._", "`N/A`",
            "<!--\nRequests now time out.\n-->", "TO<!-- hidden -->DO",
            "```text\nRequests now time out.\n```",
            "~~~text\nRequests now time out.\n~~~",
            "    Requests now time out.", "\tRequests now time out.",
            " \tRequests now time out.", "  \tRequests now time out.",
            "   \tRequests now time out.",
            "- Requests now time out.", "1. Requests now time out.",
            "> Requests now time out.", "---", "***", "___",
            "#### Summary\n\nRequests now time out.",
            "Requests now time out.\n===",
            "Requests now time out.\n---",
            "TODO\n```text\nRequests now time out.\n```",
            "TBD.\n- Requests now time out.",
            "[summary]: https://example.com/timeout",
            "**Version introduced:** 2.0.0",
        ):
            for newline in ("\n", "\r\n"):
                with self.subTest(introduction=introduction, newline=newline):
                    for kind, text, validate in documents(TITLE + introduction + "\n\n" + SECTIONS):
                        with self.subTest(kind=kind):
                            with self.assertRaisesRegex(ValueError, "introductory paragraph|Version introduced"):
                                validate(text.replace("\n", newline))

    def test_introduction_supports_wrapped_prose_and_inline_markdown(self):
        for introduction in (
            "Requests now time out instead of\nwaiting indefinitely.",
            "Requests now time out instead of\n    waiting indefinitely.",
            "Requests now time out instead of\n \twaiting indefinitely.",
            "```timeout``` is now required for all requests.",
            "````timeout```` is now required for all requests.",
            "***Requests*** now time out instead of waiting indefinitely.",
            "<!-- Context -->Requests now **time out** instead of waiting.",
            "The `timeout` option is now required; see <https://example.com/timeout>.",
            "The `<!-- timeout -->` setting is no longer recognized.",
        ):
            for newline in ("\n", "\r\n"):
                with self.subTest(introduction=introduction, newline=newline):
                    for kind, text, validate in documents(TITLE + introduction + "\n\n" + SECTIONS):
                        with self.subTest(kind=kind):
                            validate(text.replace("\n", newline))

    def test_blocks_after_introduction_do_not_invalidate_paragraph(self):
        for block in (
            "```sh\nlookup --owner example\n```",
            "~~~sh\nlookup --owner example\n~~~",
            "   ````markdown\n# Literal heading\n```\n   ````",
            "- Set an explicit timeout.",
            "1. Set an explicit timeout.",
            "> Set an explicit timeout.",
            "***",
        ):
            introduction = INTRODUCTION.rstrip() + "\n" + block
            fragment = TITLE + introduction + "\n\n" + SECTIONS
            for newline in ("\n", "\r\n"):
                with self.subTest(block=block, newline=newline):
                    for kind, text, validate in documents(fragment):
                        with self.subTest(kind=kind):
                            validate(text.replace("\n", newline))
                    notes = (
                        "## Breaking changes and migration\n\n"
                        "<!-- migration-topic: timeout -->\n" + fragment
                    ).replace("\n", newline)
                    topic = guide_documents(notes, "v2.0.0")["timeout.md"]
                    self.assertIn(introduction, topic)
                    validate_guide(GUIDE_PATH, topic)

    def test_comment_wrapping_all_required_sections_is_rejected(self):
        self.assert_invalid_documents(TITLE + "<!--\n" + SECTIONS + "-->\n", "Previous behavior")

    def test_unclosed_comment_wrapping_sections_is_rejected(self):
        self.assert_invalid_documents(TITLE + "<!--\n" + SECTIONS, "Previous behavior")

    def test_comments_spanning_multiple_sections_are_rejected(self):
        for start in range(len(REQUIRED_SECTIONS) - 1):
            first, last = REQUIRED_SECTIONS[start:start + 2]
            text = FRAGMENT.replace(f"#### {first}", f"<!--\n#### {first}").replace(
                f"Completed {last.lower()} guidance.",
                f"Completed {last.lower()} guidance.\n-->",
            )
            with self.subTest(first=first):
                self.assert_invalid_documents(text, first)

    def test_hidden_required_heading_cannot_claim_visible_content(self):
        for heading in REQUIRED_SECTIONS:
            for hidden in (f"<!-- #### {heading} -->", f"<!--\n#### {heading}\n-->"):
                with self.subTest(heading=heading, hidden=hidden):
                    self.assert_invalid_documents(
                        FRAGMENT.replace(f"#### {heading}", hidden), heading
                    )

    def test_comments_spanning_content_and_next_heading_are_rejected(self):
        text = FRAGMENT.replace(
            "Completed previous behavior guidance.",
            "Visible previous behavior.\n<!-- Hidden remainder.",
        ).replace(
            "Completed new behavior guidance.",
            "-->\nVisible new behavior does not supply its hidden heading.",
        )
        self.assert_invalid_documents(text, "New behavior")

    def test_visible_sections_with_commented_completion_remain_incomplete(self):
        for heading in REQUIRED_SECTIONS:
            for placeholder in ("", "TODO", "TBD.", "N/A"):
                with self.subTest(heading=heading, placeholder=placeholder):
                    self.assert_invalid_documents(
                        FRAGMENT.replace(
                            f"Completed {heading.lower()} guidance.",
                            f"<!-- Completed\nhidden guidance. -->\n{placeholder}",
                        ),
                        heading,
                    )

    def test_unclosed_comment_cannot_complete_final_section(self):
        self.assert_invalid_documents(
            FRAGMENT.replace("Completed affected apis guidance.", "<!-- Hidden guidance."),
            "Affected APIs",
        )

    def test_inline_comments_cannot_disguise_placeholder_only_content(self):
        for placeholder in ("TO<!-- hidden -->DO", "T<!-- hidden -->BD.", "N/<!-- hidden -->A"):
            with self.subTest(placeholder=placeholder):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed affected apis guidance.", placeholder),
                    "Affected APIs",
                )

    def test_fragment_title_must_have_visible_text(self):
        for title in ("### <!-- Timeout -->\n\n", "<!--\n### Timeout\n-->\n\n"):
            with self.subTest(title=title):
                with self.assertRaisesRegex(ValueError, "title"):
                    validate_fragment(FRAGMENT_PATH, title + SECTIONS)

    def test_standalone_title_cannot_be_hidden(self):
        for title in ("<!--\n# Timeout\n-->\n", "# <!-- Timeout -->\n"):
            text = METADATA + title + SECTIONS.replace("#### ", "## ")
            with self.subTest(title=title):
                with self.assertRaisesRegex(ValueError, "title"):
                    validate_guide(GUIDE_PATH, text)

    def test_hidden_legacy_heading_and_title_do_not_select_legacy_format(self):
        text = (
            METADATA + "<!--\n## Breaking changes and migration\n"
            + TITLE + "-->\n" + SECTIONS
        )
        with self.assertRaisesRegex(ValueError, "title"):
            validate_guide(GUIDE_PATH, text)

    def test_comment_opened_on_legacy_heading_stays_active_after_slicing(self):
        text = (
            METADATA + "## Breaking changes and migration <!--\n"
            + FRAGMENT + "-->\n"
        )
        with self.assertRaises(ValueError):
            validate_guide(GUIDE_PATH, text)

    def test_commented_legacy_preamble_does_not_hide_valid_standalone_topic(self):
        preamble = "<!--\n## Breaking changes and migration\n### Fake topic\n-->\n"
        guide = "# Timeout\n\n" + METADATA + INTRODUCTION + SECTIONS.replace("#### ", "## ")
        validate_guide(GUIDE_PATH, preamble + guide)

    def test_fence_looking_lines_inside_comments_do_not_open_fences(self):
        for fence in ("```", "~~~~", "   ````"):
            comment = f"<!--\n{fence}markdown\n# Hidden title\n-->\n"
            with self.subTest(fence=fence):
                for kind, text, validate in documents(TITLE + comment + INTRODUCTION + SECTIONS):
                    with self.subTest(kind=kind):
                        validate(text)

    def test_inline_comments_leave_visible_guidance_valid(self):
        fragment = FRAGMENT.replace("Completed ", "<!-- before -->Completed ").replace(
            " guidance.", " <!-- middle -->guidance.<!-- after -->"
        )
        for kind, text, validate in documents(fragment):
            with self.subTest(kind=kind):
                validate(text)

    def test_comment_hidden_extra_headings_are_not_body_headings(self):
        fragment = FRAGMENT + "\n<!--\n# Hidden\n## Hidden\n### Hidden\n-->\n"
        validate_fragment(FRAGMENT_PATH, fragment)

    def test_fenced_comment_literals_and_fake_headings_are_preserved(self):
        for fence in ("```", "~~~~", "   ````"):
            for comment in ("<!-- literal -->", "<!--\n# Fake title\n#### Fake section\n-->",
                            "<!-- unclosed literal"):
                example = f"{fence}markdown\n{comment}\n{fence}\n"
                fragment = FRAGMENT.replace(
                    "Completed recommended action guidance.", example
                )
                with self.subTest(fence=fence, comment=comment):
                    validate_fragment(FRAGMENT_PATH, fragment)
                    self.assertIn(example, shift_heading_levels(fragment, -2))
                    notes = (
                        "## Breaking changes and migration\n\n"
                        "<!-- migration-topic: timeout -->\n" + fragment
                    )
                    guide = guide_documents(notes, "v2.0.0")["timeout.md"]
                    self.assertIn(example, guide)
                    validate_guide(GUIDE_PATH, guide)

    def test_raw_lines_and_hidden_headings_survive_heading_transformation(self):
        text = "#### Visible\r\n<!--\r\n```\r\n# Hidden\r\n-->\r\n#### Next\r\n"
        self.assertEqual("".join(line for line, _ in markdown_lines(text)), text)
        self.assertEqual(
            shift_heading_levels(text, -2),
            "## Visible\r\n<!--\r\n```\r\n# Hidden\r\n-->\r\n## Next\r\n",
        )

    def test_find_section_keeps_original_line_positions(self):
        text = "<!--\n#### Hidden\n-->\n#### Visible\n\nVisible content.\n"
        self.assertEqual(find_section(text, "Hidden"), (-1, ""))
        self.assertEqual(find_section(text, "Visible"), (3, "\nVisible content.\n"))

    def test_matched_inline_code_keeps_comment_openers_literal(self):
        for example in (
            "Use `<!--` to open a comment.",
            "Use ``<!--`` to open a comment.",
            "Use ```<!--``` to open a comment.",
            "Use ``a ` <!-- b`` to open a comment.",
            "Use `a `` <!-- b` to open a comment.",
            "Use `<!--\\` to open a comment.",
            "Use \\``<!--` to open a comment.",
            "Use \\\\`<!--` to open a comment.",
        ):
            fragment = FRAGMENT.replace("Completed previous behavior guidance.", example)
            with self.subTest(example=example):
                for kind, text, validate in documents(fragment):
                    with self.subTest(kind=kind):
                        validate(text)
                self.assertIn(example, shift_heading_levels(fragment, -2))
                self.assertEqual(
                    "".join(line for line, _ in markdown_lines(fragment, hide_comments=True)),
                    fragment,
                )
                notes = (
                    "## Breaking changes and migration\n\n"
                    "<!-- migration-topic: timeout -->\n" + fragment
                )
                guide = guide_documents(notes, "v2.0.0")["timeout.md"]
                self.assertIn(example, guide)
                validate_guide(GUIDE_PATH, guide)

    def test_unmatched_or_escaped_backticks_do_not_shield_real_comments(self):
        for prefix in ("Use `", "Use ``", "Use \\`", "Use ``mismatched `"):
            with self.subTest(prefix=prefix):
                self.assert_invalid_documents(
                    FRAGMENT.replace(
                        "Completed previous behavior guidance.",
                        prefix + "<!-- Hidden remaining sections.",
                    ),
                    "New behavior",
                )

    def test_backticks_on_other_lines_cannot_hide_required_sections(self):
        for boundary in (
            "\n\n", "\n#### Details\n", "\n```text\n", "\n<!--\n",
            "\n- ", "\n1. ", "\n> ", "\n---\n", "\n***\n", "\n___\n", "\n===\n",
        ):
            text = (
                TITLE + "#### Previous behavior\n\nUse `<!-- Hidden."
                + boundary + "matching ` but still hidden\n" + SECTIONS + "-->\n"
            )
            with self.subTest(boundary=boundary):
                self.assert_invalid_documents(text, "New behavior|Inline code.*single line")

    def test_real_comment_after_matched_inline_code_remains_hidden(self):
        fragment = FRAGMENT.replace(
            "Completed previous behavior guidance.",
            "Use `<!--` literally. <!-- Hide the remaining sections.",
        )
        self.assert_invalid_documents(fragment, "New behavior")

    def test_backticks_inside_comments_do_not_shield_comment_closers(self):
        fragment = FRAGMENT.replace(
            "Completed previous behavior guidance.",
            "<!-- ignored ` -->Use `<!--` literally.",
        )
        for kind, text, validate in documents(fragment):
            with self.subTest(kind=kind):
                validate(text)

    def test_singleline_inline_code_preserves_raw_crlf_and_heading_positions(self):
        text = "#### Visible\r\nUse ``example with <!-- inside``.\r\n#### Next\r\n"
        self.assertEqual("".join(line for line, _ in markdown_lines(text)), text)
        self.assertEqual(
            shift_heading_levels(text, -2),
            "## Visible\r\nUse ``example with <!-- inside``.\r\n## Next\r\n",
        )
        self.assertEqual(find_section(text, "Next"), (2, ""))

    def test_multiline_inline_code_requires_fenced_examples(self):
        for example in (
            "Use `old\nnew` behavior.",
            "Use `old\r\nnew` behavior.",
            "Use `<!--\ncontinued code` to open a comment.",
            "Use ``example\nwith <!-- inside`` to open a comment.",
            'Use `example\n<span title="HTML">literal</span>`.',
            "Use ```old\nnew``` behavior.",
        ):
            with self.subTest(example=example):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed previous behavior guidance.", example),
                    "Inline code.*single line.*fenced",
                )

    def test_unmatched_backticks_remain_plain_text(self):
        for example in (
            "A single ` delimiter is plain text.",
            "Two `` delimiters do not match a single `.",
            "A single ` on this paragraph.\n\nAnother ` on a separate paragraph.",
        ):
            with self.subTest(example=example):
                fragment = FRAGMENT.replace("Completed previous behavior guidance.", example)
                for kind, text, validate in documents(fragment):
                    with self.subTest(kind=kind):
                        validate(text)

    def test_list_containers_cannot_borrow_code_delimiters_across_lines(self):
        for marker in ("-", "1."):
            with self.subTest(marker=marker):
                self.assert_invalid_documents(
                    FRAGMENT.replace(
                        "Completed previous behavior guidance.",
                        f"{marker} Use `text\n    <div><!-- `",
                    ),
                    "Raw HTML|Inline code.*single line",
                )

    def test_raw_html_backticks_cannot_shield_unclosed_comments(self):
        for content in (
            '<div title="`"></div><!-- `',
            '<div\n title="`"></div><!-- `',
            '<div>\n`<!-- `\n</div>',
        ):
            with self.subTest(content=content):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed previous behavior guidance.", content),
                    "Raw HTML.*Markdown.*code example",
                )

    def test_raw_html_constructs_require_markdown_or_code_examples(self):
        for content in (
            "<div>Use the replacement API.</div>",
            "<script>alert('example')</script>",
            "<style>p { color: red; }</style>",
            "<pre>Example</pre>",
            "<details><summary>Example</summary>Details</details>",
            "<svg><text>Example</text></svg>",
            "Use <span>the replacement</span>.",
            "Use <custom-element data-name='example'/>.",
            "<DIV\n title='multiline'>Example</DIV>",
            "<div\n title=\"`\"></div><!-- `",
            "</div>", "</custom-element\n>", "<div", "<div title='unfinished",
            "<?processing instruction?>",
            "<!DOCTYPE html>",
            "<![CDATA[example]]>",
        ):
            with self.subTest(content=content):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed previous behavior guidance.", content),
                    "Raw HTML.*Markdown.*code example",
                )

    def test_unmatched_code_cannot_shield_raw_html(self):
        for content in (
            "Use `<div> without closing code.",
            "Use ``<span> mismatched ` code.",
            "Use \\`<pre> escaped delimiter.",
            "Use `text\n<div title=\"`\"></div><!-- `",
            "Use `text\n<SCRIPT>var x = '`';</SCRIPT>",
            "Use `text\n<?instruction `?>",
        ):
            with self.subTest(content=content):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed previous behavior guidance.", content),
                    "Raw HTML.*Markdown.*code example|Inline code.*single line",
                )

    def test_html_inside_actual_code_examples_is_literal(self):
        for example in (
            '`<div title="example">HTML</div>`',
            '``<div title="`"></div><!-- ` ``',
            '`<script>example</script><style>example</style>`',
            '`<?instruction?><!DOCTYPE html><![CDATA[example]]>`',
            '```html\n<span title="HTML">\nMultiline literal\n</span>\n```\n',
            '```html\n<div title="`"></div><!-- `\n<?instruction?>\n```\n',
            '~~~~html\n<script>\n`<!-- `\n</script>\n~~~~\n',
        ):
            fragment = FRAGMENT.replace(
                "Completed previous behavior guidance.", "Use " + example
                if not example.startswith(("```html", "~~~~html")) else example
            )
            with self.subTest(example=example):
                for kind, text, validate in documents(fragment):
                    with self.subTest(kind=kind):
                        validate(text)
                self.assertIn(example, shift_heading_levels(fragment, -2))
                notes = (
                    "## Breaking changes and migration\n\n"
                    "<!-- migration-topic: timeout -->\n" + fragment
                )
                guide = guide_documents(notes, "v2.0.0")["timeout.md"]
                self.assertIn(example, guide)
                validate_guide(GUIDE_PATH, guide)

    def test_comments_escaped_angles_and_autolinks_remain_supported(self):
        for content in (
            '<!-- <div title="`">ignored</div> -->Use Markdown.',
            r"Use \<div> and \</div> as literal text.",
            r"Use \<?instruction?> and \<!DOCTYPE html> as literal text.",
            "Use &lt;div&gt; as literal text.",
            "Read <https://example.com/guide> or contact <user@example.com>.",
            "Read <https://example.com/a`b> or contact <user`x@example.com>.",
            "Compare x < y and y > 3.",
        ):
            with self.subTest(content=content):
                fragment = FRAGMENT.replace("Completed previous behavior guidance.", content)
                for kind, text, validate in documents(fragment):
                    with self.subTest(kind=kind):
                        validate(text)

    def test_autolink_backticks_cannot_shield_a_following_comment(self):
        for content in (
            "<https://example.com/a`b><!-- `",
            "<https://example.test/`><!-- `",
            "<user`x@example.com><!-- `",
        ):
            with self.subTest(content=content):
                self.assert_invalid_documents(
                    FRAGMENT.replace("Completed previous behavior guidance.", content),
                    "New behavior",
                )

    def test_raw_html_restriction_applies_to_guide_preambles(self):
        for kind, guide, validate in documents(FRAGMENT):
            if kind != "fragment":
                with self.subTest(kind=kind):
                    with self.assertRaisesRegex(ValueError, "Raw HTML.*Markdown.*code example"):
                        validate("<div>Introduction</div>\n\n" + guide)

    def test_nonvalidation_markdown_iteration_preserves_release_drafter_html(self):
        text = "<details>\n<summary>Dependencies</summary>\n\n- Update packages\n\n</details>\n"
        self.assertEqual("".join(line for line, _ in markdown_lines(text)), text)


class GuideCommentMetadataTests(unittest.TestCase):
    def test_unclosed_comment_cannot_supply_metadata(self):
        guide = "# Timeout\n\n" + SECTIONS.replace("#### ", "## ")
        with self.assertRaisesRegex(ValueError, "Version introduced"):
            validate_guide(GUIDE_PATH, guide + "<!--\n" + METADATA)

    def test_commented_fence_does_not_hide_visible_metadata(self):
        guide = (
            "<!--\n```markdown\n-->\n# Timeout\n\n" + METADATA
            + INTRODUCTION + SECTIONS.replace("#### ", "## ")
        )
        validate_guide(GUIDE_PATH, guide)

    def test_fenced_comment_delimiters_do_not_hide_duplicate_metadata(self):
        guide = (
            "# Timeout\n\n" + METADATA + SECTIONS.replace("#### ", "## ")
            + "```html\n<!--\n```\n" + METADATA + "```html\n-->\n```\n"
        )
        with self.assertRaisesRegex(ValueError, "Version introduced"):
            validate_guide(GUIDE_PATH, guide)

    def test_comment_spanning_fence_looking_lines_cannot_supply_metadata(self):
        guide = (
            "# Timeout\n\n<!--\n```\n-->\n```\n" + METADATA + "```\n\n"
            + SECTIONS.replace("#### ", "## ")
        )
        with self.assertRaisesRegex(ValueError, "Version introduced"):
            validate_guide(GUIDE_PATH, guide)


if __name__ == "__main__":
    unittest.main()
