"""Tests for filename sanitization + conflict resolution (Phase 4)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import sanitize_filename, deduplicate_filenames


class TestSanitizeFilename(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(sanitize_filename("## Installation Guide"), "installation-guide.md")

    def test_special_chars(self):
        self.assertEqual(sanitize_filename("# API / Endpoints (v2)"), "api-endpoints-v2.md")

    def test_underscores(self):
        self.assertEqual(sanitize_filename("## Step_1"), "step-1.md")

    def test_empty_result(self):
        self.assertEqual(sanitize_filename("## $$$"), "section.md")

    def test_unicode_removed(self):
        self.assertEqual(sanitize_filename("## Café Résumé"), "caf-rsum.md")

    def test_consecutive_hyphens(self):
        self.assertEqual(sanitize_filename("# A -- B"), "a-b.md")

    def test_leading_trailing_hyphens(self):
        self.assertEqual(sanitize_filename("# -Leading-"), "leading.md")

    def test_inline_markdown_stripped(self):
        self.assertEqual(sanitize_filename("## **Bold** Title"), "bold-title.md")

    def test_numbers(self):
        self.assertEqual(sanitize_filename("## Chapter 3"), "chapter-3.md")


class TestDeduplicateFilenames(unittest.TestCase):
    def test_no_duplicates(self):
        self.assertEqual(
            deduplicate_filenames(["a.md", "b.md"]),
            ["a.md", "b.md"],
        )

    def test_dedup_appends_2(self):
        self.assertEqual(
            deduplicate_filenames(["a.md", "a.md"]),
            ["a.md", "a-2.md"],
        )

    def test_dedup_triple(self):
        self.assertEqual(
            deduplicate_filenames(["a.md", "a.md", "a.md"]),
            ["a.md", "a-2.md", "a-3.md"],
        )

    def test_mixed(self):
        result = deduplicate_filenames(["intro.md", "setup.md", "intro.md"])
        self.assertEqual(result, ["intro.md", "setup.md", "intro-2.md"])


if __name__ == "__main__":
    unittest.main()
