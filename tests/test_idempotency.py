"""Tests for byte-identical round-trip verification (Phase 9 — CRITICAL)."""

import sys
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import (
    parse_markdown, generate_index_string, parse_index_string,
    assemble_markdown_string, normalize_to_lf, apply_line_ending,
    sanitize_filename, deduplicate_filenames, split_operation,
    join_operation, read_file,
)


def _round_trip(original: str, filename: str = "doc.md") -> None:
    """Split then join and verify byte-identical output."""
    doc = parse_markdown(original, filename)

    # Generate section filenames
    filenames = [sanitize_filename(s.header_text) for s in doc.sections]
    filenames = deduplicate_filenames(filenames)

    # Generate index
    idx = generate_index_string(doc, filename.replace(".md", ""), filenames)

    # Build section contents dict
    section_dict: dict[str, str] = {}
    if doc.preamble is not None:
        pre_key = f"{filename.replace('.md', '')}/_preamble.md"
        section_dict[pre_key] = doc.preamble.content + "\n"
    for i, section in enumerate(doc.sections):
        key = f"{filename.replace('.md', '')}/{filenames[i]}"
        content = section.header_text + "\n"
        if section.body:
            content += section.body + "\n"
        section_dict[key] = content

    # Parse index and assemble
    parsed = parse_index_string(idx)

    preamble_content = None
    preamble_blanks = 0
    section_contents: list[str] = []
    blanks: list[int] = []

    for entry in parsed.entries:
        content = section_dict.get(entry.relative_path, "")
        content_lf = normalize_to_lf(content)

        if entry.display_name == "Preamble" and entry.relative_path.endswith("_preamble.md"):
            preamble_content = content_lf
            preamble_blanks = entry.trailing_blanks
        else:
            section_contents.append(content_lf)
            blanks.append(entry.trailing_blanks)

    joined = assemble_markdown_string(
        preamble_content, preamble_blanks,
        section_contents, blanks,
        doc.has_trailing_newline, "\n",
    )

    # Normalize original for comparison (both in LF)
    original_lf = original.replace("\r\n", "\n")
    if doc.line_ending == "\r\n":
        # For CRLF docs, compare in CRLF too
        joined_crlf = apply_line_ending(joined, "\r\n")
        assert original == joined_crlf, (
            f"Round-trip mismatch:\n--- Original\n+++ Joined\n"
            f"Original length: {len(original)}, Joined length: {len(joined_crlf)}\n"
            f"Original repr: {repr(original[:200])}\n"
            f"Joined repr: {repr(joined_crlf[:200])}"
        )
    else:
        assert original_lf == joined, (
            f"Round-trip mismatch:\n--- Original\n+++ Joined\n"
            f"Original length: {len(original_lf)}, Joined length: {len(joined)}\n"
            f"Original repr: {repr(original_lf[:200])}\n"
            f"Joined repr: {repr(joined[:200])}"
        )


def _full_round_trip_on_disk(original: str) -> None:
    """Split to disk then join from disk and verify byte-identical output."""
    with TemporaryDirectory() as tmp:
        doc_path = Path(tmp) / "doc.md"
        doc_path.write_text(original, encoding="utf-8")

        split_operation(doc_path)
        index_path = Path(tmp) / "doc-index.md"
        join_operation(index_path)

        joined_path = Path(tmp) / "doc-joined.md"
        self_result = joined_path.read_text(encoding="utf-8")
        assert original == self_result, (
            f"Disk round-trip mismatch:\n"
            f"Original: {repr(original[:200])}\n"
            f"Joined: {repr(self_result[:200])}"
        )


class TestRoundTrip(unittest.TestCase):
    def test_simple_h1_sections(self):
        _round_trip("# A\nText A\n\n# B\nText B\n")

    def test_h2_sections_with_title(self):
        _round_trip("# Title\nIntro\n\n## A\nText A\n\n## B\nText B\n")

    def test_with_preamble(self):
        _round_trip("Intro text\n\n# A\nText\n\n# B\nText\n")

    def test_with_front_matter(self):
        _round_trip("---\ntitle: Test\n---\n\n# A\nText\n\n# B\nText\n")

    def test_empty_sections(self):
        _round_trip("# A\n\n# B\n\n# C\n")

    def test_nested_content(self):
        _round_trip("# A\n## Sub\n### SubSub\nText\n\n# B\nText\n")

    def test_code_blocks_with_hashes(self):
        _round_trip("# A\n```\n# Not a header\n```\n\n# B\nText\n")

    def test_varying_blank_lines(self):
        _round_trip("# A\nText\n\n# B\nText\n\n\n\n# C\nText\n")

    def test_crlf_line_endings(self):
        _round_trip("# A\r\nText A\r\n\r\n# B\r\nText B\r\n")

    def test_no_trailing_newline(self):
        _round_trip("# A\nText A\n\n# B\nText B")

    def test_special_chars_in_headers(self):
        _round_trip("# A & B\nText\n\n# C++ / D\nText\n")

    def test_duplicate_header_names(self):
        _round_trip("# Introduction\nFirst\n\n# Introduction\nSecond\n")

    def test_multiple_cycles(self):
        """Split → join → split → join (3 cycles) all identical."""
        original = "# A\nText A\n\n# B\nText B\n\n# C\nText C\n"
        text = original
        for _ in range(3):
            _round_trip(text)
            # Simulate full cycle
            doc = parse_markdown(text, "doc.md")
            filenames = [sanitize_filename(s.header_text) for s in doc.sections]
            filenames = deduplicate_filenames(filenames)
            idx = generate_index_string(doc, "doc", filenames)
            parsed = parse_index_string(idx)

            section_dict: dict[str, str] = {}
            if doc.preamble is not None:
                section_dict["doc/_preamble.md"] = doc.preamble.content + "\n"
            for i, section in enumerate(doc.sections):
                key = f"doc/{filenames[i]}"
                content = section.header_text + "\n"
                if section.body:
                    content += section.body + "\n"
                section_dict[key] = content

            preamble_content = None
            preamble_blanks = 0
            section_contents: list[str] = []
            blanks: list[int] = []
            for entry in parsed.entries:
                content = section_dict.get(entry.relative_path, "")
                content_lf = normalize_to_lf(content)
                if entry.display_name == "Preamble" and entry.relative_path.endswith("_preamble.md"):
                    preamble_content = content_lf
                    preamble_blanks = entry.trailing_blanks
                else:
                    section_contents.append(content_lf)
                    blanks.append(entry.trailing_blanks)

            text = assemble_markdown_string(
                preamble_content, preamble_blanks,
                section_contents, blanks,
                doc.has_trailing_newline, "\n",
            )
        self.assertEqual(original, text)

    def test_preamble_h1_fallback(self):
        _round_trip("# My Doc\nIntro paragraph\n\n## First\nContent\n\n## Second\nContent\n")

    def test_front_matter_with_intro(self):
        _round_trip("---\nlayout: post\ntitle: Hello\n---\n\n# Intro\nSome content\n\n# Details\nMore\n")


class TestRoundTripOnDisk(unittest.TestCase):
    def test_simple_disk_round_trip(self):
        original = "# A\nText A\n\n# B\nText B\n"
        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text(original, encoding="utf-8")
            split_operation(doc_path)

            index_path = Path(tmp) / "doc-index.md"
            self.assertTrue(index_path.exists())

            join_operation(index_path)
            joined_path = Path(tmp) / "doc-joined.md"
            self.assertTrue(joined_path.exists())
            self.assertEqual(joined_path.read_text(encoding="utf-8"), original)

    def test_h2_disk_round_trip(self):
        original = "# Title\nIntro\n\n## Section A\nContent A\n\n## Section B\nContent B\n"
        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text(original, encoding="utf-8")
            split_operation(doc_path)

            index_path = Path(tmp) / "doc-index.md"
            join_operation(index_path)

            joined_path = Path(tmp) / "doc-joined.md"
            self.assertEqual(joined_path.read_text(encoding="utf-8"), original)

    def test_preamble_disk_round_trip(self):
        original = "Some intro\n\n# A\nText\n\n# B\nText\n"
        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text(original, encoding="utf-8")
            split_operation(doc_path)

            index_path = Path(tmp) / "doc-index.md"
            join_operation(index_path)

            joined_path = Path(tmp) / "doc-joined.md"
            self.assertEqual(joined_path.read_text(encoding="utf-8"), original)

    def test_front_matter_disk_round_trip(self):
        original = "---\ntitle: Test\n---\n\n# A\nContent\n\n# B\nContent\n"
        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text(original, encoding="utf-8")
            split_operation(doc_path)

            index_path = Path(tmp) / "doc-index.md"
            join_operation(index_path)

            joined_path = Path(tmp) / "doc-joined.md"
            self.assertEqual(joined_path.read_text(encoding="utf-8"), original)

    def test_no_trailing_newline_disk(self):
        original = "# A\nText A\n\n# B\nText B"
        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text(original, encoding="utf-8")
            split_operation(doc_path)

            index_path = Path(tmp) / "doc-index.md"
            join_operation(index_path)

            joined_path = Path(tmp) / "doc-joined.md"
            self.assertEqual(joined_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
