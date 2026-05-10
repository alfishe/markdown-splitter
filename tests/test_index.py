"""Tests for index render/parse round-trips and markdown assembly (Phases 5-7)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import (
    parse_markdown, generate_index_string, parse_index_string,
    assemble_markdown_string, JoinError, sanitize_filename,
    deduplicate_filenames, SplitDocument, Section, Preamble,
)


class TestIndexGeneration(unittest.TestCase):
    def _make_doc(self) -> SplitDocument:
        return SplitDocument(
            title="My Doc",
            preamble=Preamble(content="Intro text", trailing_blanks=1),
            sections=[
                Section(header_text="# First", body="Content A", trailing_blanks=2, description="Content A"),
                Section(header_text="# Second", body="", trailing_blanks=0, description="(empty section)"),
            ],
            has_trailing_newline=True,
            line_ending="\n",
            split_level=1,
        )

    def test_index_has_markers(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("<!-- mdsplit-index -->", idx)
        self.assertIn("<!-- /mdsplit-index -->", idx)

    def test_index_has_title(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertTrue(idx.startswith("# My Doc"))

    def test_preamble_entry_first(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        lines = idx.split("\n")
        # Find first entry after opening marker (skip header and separator rows)
        for i, line in enumerate(lines):
            if "<!-- mdsplit-index -->" in line:
                # Skip table header and separator, find first data row
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("|") and not lines[j].startswith("|-") and not lines[j].strip() == "| Section | Description |":
                        self.assertIn("Preamble", lines[j])
                        return
        self.fail("Preamble entry not found")

    def test_blanks_metadata(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("blanks:1", idx)
        self.assertIn("blanks:2", idx)

    def test_no_blanks_when_zero(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        # Second section has blanks:0 — should NOT appear
        # Check that there's no "blanks:0" in the Second entry
        self.assertNotIn("blanks:0", idx)

    def test_trailing_newline_marker_true(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("trailing-newline:true", idx)

    def test_trailing_newline_marker_false(self):
        doc = self._make_doc()
        doc.has_trailing_newline = False
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("trailing-newline:false", idx)

    def test_entry_format(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("[First](my-doc/first.md)", idx)

    def test_relative_paths_include_folder(self):
        doc = self._make_doc()
        idx = generate_index_string(doc, "my-doc", ["first.md", "second.md"])
        self.assertIn("my-doc/first.md", idx)


class TestIndexParseRoundTrip(unittest.TestCase):
    def test_generate_then_parse(self):
        doc = SplitDocument(
            title="Doc",
            preamble=Preamble(content="Pre", trailing_blanks=1),
            sections=[
                Section(header_text="# A", body="Text A", trailing_blanks=2, description="Text A"),
                Section(header_text="# B", body="Text B", trailing_blanks=0, description="Text B"),
            ],
            has_trailing_newline=True,
            line_ending="\n",
            split_level=1,
        )
        idx = generate_index_string(doc, "doc", ["a.md", "b.md"])
        parsed = parse_index_string(idx)
        self.assertEqual(parsed.title, "Doc")
        self.assertEqual(len(parsed.entries), 3)  # preamble + 2 sections
        self.assertTrue(parsed.has_trailing_newline)

    def test_parse_preserves_order(self):
        doc = SplitDocument(
            title="Doc",
            preamble=None,
            sections=[
                Section(header_text="# Alpha", body="", trailing_blanks=0, description="A"),
                Section(header_text="# Beta", body="", trailing_blanks=0, description="B"),
                Section(header_text="# Gamma", body="", trailing_blanks=0, description="C"),
            ],
            has_trailing_newline=True,
            line_ending="\n",
            split_level=1,
        )
        idx = generate_index_string(doc, "doc", ["alpha.md", "beta.md", "gamma.md"])
        parsed = parse_index_string(idx)
        names = [e.display_name for e in parsed.entries]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])

    def test_parse_extracts_blanks(self):
        doc = SplitDocument(
            title="Doc",
            preamble=None,
            sections=[
                Section(header_text="# A", body="", trailing_blanks=3, description="A"),
                Section(header_text="# B", body="", trailing_blanks=0, description="B"),
            ],
            has_trailing_newline=True,
            line_ending="\n",
            split_level=1,
        )
        idx = generate_index_string(doc, "doc", ["a.md", "b.md"])
        parsed = parse_index_string(idx)
        self.assertEqual(parsed.entries[0].trailing_blanks, 3)
        self.assertEqual(parsed.entries[1].trailing_blanks, 0)

    def test_parse_extracts_trailing_newline(self):
        doc = SplitDocument(
            title="Doc",
            preamble=None,
            sections=[Section(header_text="# A", body="", trailing_blanks=0, description="A")],
            has_trailing_newline=False,
            line_ending="\n",
            split_level=1,
        )
        idx = generate_index_string(doc, "doc", ["a.md"])
        parsed = parse_index_string(idx)
        self.assertFalse(parsed.has_trailing_newline)

    def test_parse_ignores_extra_content(self):
        idx = "# Doc\n\nSome note\n\n<!-- mdsplit-index -->\n| Section | Description |\n|---------|-------------|\n| [A](doc/a.md) | Desc |\n<!-- /mdsplit-index -->\n\n<!-- trailing-newline:true -->\n"
        parsed = parse_index_string(idx)
        self.assertEqual(len(parsed.entries), 1)

    def test_parse_missing_markers_error(self):
        idx = "# Doc\n- [A](a.md) — Desc\n"
        with self.assertRaises(JoinError):
            parse_index_string(idx)

    def test_parse_default_blanks_zero(self):
        idx = "# Doc\n\n<!-- mdsplit-index -->\n| Section | Description |\n|---------|-------------|\n| [A](doc/a.md) | Desc |\n<!-- /mdsplit-index -->\n\n<!-- trailing-newline:true -->\n"
        parsed = parse_index_string(idx)
        self.assertEqual(parsed.entries[0].trailing_blanks, 0)


class TestMarkdownAssembly(unittest.TestCase):
    def test_assemble_basic(self):
        result = assemble_markdown_string(
            preamble_content=None,
            preamble_blanks=0,
            section_contents=["# A\nText A\n", "# B\nText B\n"],
            blanks=[0, 0],
            has_trailing_newline=True,
            line_ending="\n",
        )
        self.assertEqual(result, "# A\nText A\n# B\nText B\n")

    def test_assemble_with_blanks(self):
        result = assemble_markdown_string(
            preamble_content=None,
            preamble_blanks=0,
            section_contents=["# A\nText\n", "# B\nText\n"],
            blanks=[2, 0],
            has_trailing_newline=True,
            line_ending="\n",
        )
        self.assertEqual(result, "# A\nText\n\n\n# B\nText\n")

    def test_assemble_with_preamble(self):
        result = assemble_markdown_string(
            preamble_content="Intro\n",
            preamble_blanks=1,
            section_contents=["# A\nText\n"],
            blanks=[0],
            has_trailing_newline=True,
            line_ending="\n",
        )
        self.assertEqual(result, "Intro\n\n# A\nText\n")

    def test_assemble_trailing_newline_true(self):
        result = assemble_markdown_string(
            preamble_content=None,
            preamble_blanks=0,
            section_contents=["# A\nText\n"],
            blanks=[0],
            has_trailing_newline=True,
            line_ending="\n",
        )
        self.assertTrue(result.endswith("\n"))

    def test_assemble_trailing_newline_false(self):
        result = assemble_markdown_string(
            preamble_content=None,
            preamble_blanks=0,
            section_contents=["# A\nText\n"],
            blanks=[0],
            has_trailing_newline=False,
            line_ending="\n",
        )
        self.assertFalse(result.endswith("\n"))

    def test_assemble_crlf(self):
        result = assemble_markdown_string(
            preamble_content=None,
            preamble_blanks=0,
            section_contents=["# A\nText\n"],
            blanks=[0],
            has_trailing_newline=True,
            line_ending="\r\n",
        )
        self.assertIn("\r\n", result)
        self.assertTrue(result.endswith("\r\n"))


if __name__ == "__main__":
    unittest.main()
