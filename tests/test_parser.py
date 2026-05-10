"""Tests for parser — header detection, validation, chunking, whitespace, description (Phases 1-3)."""

import sys
import os
import unittest

# Ensure we import from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import (
    parse_header, resolve_split_level, SplitError, detect_line_ending,
    chunk_sections, parse_markdown, extract_description, strip_markdown_inline,
)


class TestParseHeader(unittest.TestCase):
    def test_h1(self):
        self.assertEqual(parse_header("# Title"), (1, "Title"))

    def test_h2(self):
        self.assertEqual(parse_header("## Section"), (2, "Section"))

    def test_h6(self):
        self.assertEqual(parse_header("###### Deep"), (6, "Deep"))

    def test_not_header_no_space(self):
        self.assertIsNone(parse_header("#nope"))

    def test_not_header_plain_text(self):
        self.assertIsNone(parse_header("Just text"))

    def test_not_header_empty(self):
        self.assertIsNone(parse_header(""))


class TestResolveSplitLevel(unittest.TestCase):
    def test_multiple_h1_split_on_h1(self):
        lines = ["# First", "Text", "# Second", "Text"]
        self.assertEqual(resolve_split_level(lines), 1)

    def test_single_h1_split_on_h2(self):
        lines = ["# Doc", "Intro", "## A", "Text", "## B", "Text"]
        self.assertEqual(resolve_split_level(lines), 2)

    def test_zero_h1_with_h2(self):
        lines = ["## First", "Text", "## Second", "Text"]
        self.assertEqual(resolve_split_level(lines), 2)

    def test_no_headers_error(self):
        lines = ["Just text", "No headers here"]
        with self.assertRaises(SplitError) as cm:
            resolve_split_level(lines)
        self.assertIn("No markdown headers found", str(cm.exception))

    def test_single_h1_no_h2_error(self):
        lines = ["# Only One", "Some content"]
        with self.assertRaises(SplitError) as cm:
            resolve_split_level(lines)
        self.assertIn("only one section", str(cm.exception))

    def test_h2_before_h1_error(self):
        lines = ["## Sub", "Text", "# Main", "Text"]
        with self.assertRaises(SplitError) as cm:
            resolve_split_level(lines)
        self.assertIn("inconsistent", str(cm.exception))

    def test_h3_before_h2_after_h1_is_preamble(self):
        """# Title followed by ### then ## is valid — ### is preamble content."""
        lines = ["# Title", "### Deep", "## Section", "Text"]
        self.assertEqual(resolve_split_level(lines), 2)

    def test_h3_before_h1_error(self):
        """### before any # header is an error."""
        lines = ["### Deep", "## Section", "Text"]
        with self.assertRaises(SplitError) as cm:
            resolve_split_level(lines)
        self.assertIn("inconsistent", str(cm.exception))

    def test_non_contiguous_ok(self):
        """# A followed by ### Jump is valid (non-contiguous allowed)."""
        lines = ["# A", "### Jump", "# B", "Text"]
        self.assertEqual(resolve_split_level(lines), 1)

    def test_header_inside_codeblock_ignored(self):
        lines = ["# Real", "```", "# Fake", "```", "# Also Real", "Text"]
        self.assertEqual(resolve_split_level(lines), 1)

    def test_single_h1_only_one_section_error(self):
        lines = ["# Lone", "Content only"]
        with self.assertRaises(SplitError):
            resolve_split_level(lines)


class TestDetectLineEnding(unittest.TestCase):
    def test_lf(self):
        self.assertEqual(detect_line_ending("line1\nline2\n"), "\n")

    def test_crlf(self):
        self.assertEqual(detect_line_ending("line1\r\nline2\r\n"), "\r\n")


# ── Phase 2: Section chunking & whitespace ─────────────────────────────────

class TestChunkSections(unittest.TestCase):
    def test_basic_two_sections(self):
        lines = ["# A", "Text A", "# B", "Text B"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertIsNone(preamble)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].body, "Text A")
        self.assertEqual(sections[1].body, "Text B")

    def test_nested_headers_in_body(self):
        lines = ["# A", "## Nested", "Text", "# B"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertEqual(len(sections), 2)
        self.assertIn("## Nested", sections[0].body)

    def test_trailing_blanks_counted(self):
        lines = ["# A", "Text", "", "", "# B", "Text"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertEqual(sections[0].trailing_blanks, 2)

    def test_last_section_trailing_blanks_zero(self):
        lines = ["# A", "Text", "# B", "Text", "", ""]
        preamble, sections = chunk_sections(lines, 1)
        self.assertEqual(sections[1].trailing_blanks, 0)

    def test_empty_section(self):
        lines = ["# A", "", "# B"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertEqual(sections[0].body, "")

    def test_preamble_captured(self):
        lines = ["Intro", "# A", "Text"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertIsNotNone(preamble)
        self.assertEqual(preamble.content, "Intro")

    def test_no_preamble(self):
        lines = ["# A", "Text"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertIsNone(preamble)

    def test_preamble_with_front_matter(self):
        lines = ["---", "yaml: true", "---", "Intro", "# A", "Text"]
        preamble, sections = chunk_sections(lines, 1)
        self.assertIsNotNone(preamble)
        self.assertIn("---", preamble.content)
        self.assertIn("Intro", preamble.content)

    def test_single_h1_preamble_includes_title(self):
        lines = ["# Doc", "Intro", "## A", "Text"]
        preamble, sections = chunk_sections(lines, 2)
        self.assertIsNotNone(preamble)
        self.assertIn("# Doc", preamble.content)
        self.assertIn("Intro", preamble.content)
        self.assertEqual(len(sections), 1)

    def test_crlf_preserved(self):
        doc = parse_markdown("# A\r\nText\r\n\r\n# B\r\nText\r\n")
        self.assertEqual(doc.line_ending, "\r\n")

    def test_trailing_newline_true(self):
        doc = parse_markdown("# A\nText\n\n# B\nText\n")
        self.assertTrue(doc.has_trailing_newline)

    def test_trailing_newline_false(self):
        doc = parse_markdown("# A\nText\n\n# B\nText")
        self.assertFalse(doc.has_trailing_newline)


# ── Phase 3: Description extraction ─────────────────────────────────────────

class TestStripMarkdownInline(unittest.TestCase):
    def test_bold(self):
        self.assertEqual(strip_markdown_inline("**Bold**"), "Bold")

    def test_italic(self):
        self.assertEqual(strip_markdown_inline("*Italic*"), "Italic")

    def test_code(self):
        self.assertEqual(strip_markdown_inline("`code`"), "code")

    def test_link(self):
        self.assertEqual(strip_markdown_inline("[text](url)"), "text")

    def test_image(self):
        self.assertEqual(strip_markdown_inline("![alt](url)"), "alt")

    def test_strikethrough(self):
        self.assertEqual(strip_markdown_inline("~~del~~"), "del")


class TestExtractDescription(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(extract_description("# Header", "First line\nSecond"), "First line")

    def test_bold_stripped(self):
        self.assertEqual(extract_description("# Header", "**Bold** text"), "Bold text")

    def test_link_stripped(self):
        self.assertEqual(extract_description("# Header", "See [docs](url)"), "See docs")

    def test_code_stripped(self):
        self.assertEqual(extract_description("# Header", "Use `foo`"), "Use foo")

    def test_code_block_skipped(self):
        self.assertEqual(
            extract_description("# Header", "```\ncode\n```\nReal desc"),
            "Real desc",
        )

    def test_table_skipped(self):
        self.assertEqual(
            extract_description("# Header", "| A | B |\n|---|---|\nDesc"),
            "Desc",
        )

    def test_image_skipped(self):
        self.assertEqual(
            extract_description("# Header", "![alt](img.png)\nCaption"),
            "Caption",
        )

    def test_blockquote_skipped(self):
        self.assertEqual(
            extract_description("# Header", "> Quote\nActual"),
            "Actual",
        )

    def test_empty_body_fallback(self):
        self.assertEqual(extract_description("# Header", ""), "(empty section)")

    def test_only_nested_headers_fallback(self):
        self.assertEqual(
            extract_description("# Main", "### Sub\n### Sub2"),
            "(Main)",
        )

    def test_truncation(self):
        long_line = "A" * 300
        result = extract_description("# Header", long_line)
        self.assertEqual(len(result), 203)  # 200 + "..."
        self.assertTrue(result.endswith("..."))


if __name__ == "__main__":
    unittest.main()
