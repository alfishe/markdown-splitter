"""Tests for CLI argument parsing and output formatting (Phase 10)."""

import sys
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import main


class TestCLISplit(unittest.TestCase):
    def test_split_command_creates_files(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            result = main(["split", str(doc)])
            self.assertEqual(result, 0)
            self.assertTrue((Path(tmp) / "doc-index.md").exists())
            self.assertTrue((Path(tmp) / "doc").exists())

    def test_join_command_creates_file(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            main(["split", str(doc)])
            index = Path(tmp) / "doc-index.md"
            result = main(["join", str(index)])
            self.assertEqual(result, 0)
            self.assertTrue((Path(tmp) / "doc-joined.md").exists())


class TestCLIDryRun(unittest.TestCase):
    def test_dry_run_no_files(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            main(["split", str(doc), "--dry-run"])
            self.assertFalse((Path(tmp) / "doc-index.md").exists())


class TestCLIErrors(unittest.TestCase):
    def test_error_no_file(self):
        result = main(["split", "/nonexistent/doc.md"])
        self.assertEqual(result, 1)

    def test_error_no_headers(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("Just text\nNo headers\n")
            result = main(["split", str(doc)])
            self.assertEqual(result, 2)

    def test_error_missing_section(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            main(["split", str(doc)])
            # Delete a section file
            section = Path(tmp) / "doc" / "a.md"
            section.unlink()
            index = Path(tmp) / "doc-index.md"
            result = main(["join", str(index)])
            self.assertEqual(result, 2)


class TestCLIVerify(unittest.TestCase):
    def test_verify_flag_success(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            result = main(["split", str(doc), "--verify"])
            self.assertEqual(result, 0)

    def test_verify_join_success(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            main(["split", str(doc)])
            index = Path(tmp) / "doc-index.md"
            result = main(["join", str(index), "--verify"])
            self.assertEqual(result, 0)


class TestCLIOutputFlag(unittest.TestCase):
    def test_output_flag_split(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            out = Path(tmp) / "custom"
            main(["split", str(doc), "--output", str(out)])
            self.assertTrue((Path(tmp) / "custom-index.md").exists())
            self.assertTrue((Path(tmp) / "custom").exists())

    def test_output_flag_join(self):
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("# A\nText A\n\n# B\nText B\n")
            main(["split", str(doc)])
            index = Path(tmp) / "doc-index.md"
            out = Path(tmp) / "result.md"
            main(["join", str(index), "--output", str(out)])
            self.assertTrue(out.exists())


class TestCLIVersion(unittest.TestCase):
    def test_version_flag(self):
        # argparse --version calls sys.exit(0)
        with self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
