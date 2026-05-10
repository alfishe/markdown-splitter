"""Tests for file-system operations: split, join, backup, conflict (Phase 8)."""

import sys
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdsplit
from mdsplit import (
    resolve_conflict, backup_path, read_file, write_file,
    split_operation, join_operation, main,
)


class TestResolveConflict(unittest.TestCase):
    def test_no_conflict_returns_same_path(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "new.md"
            self.assertEqual(resolve_conflict(p), p)

    def test_conflict_appends_2(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "doc-index.md"
            p.touch()
            result = resolve_conflict(p)
            self.assertEqual(result.name, "doc-2-index.md")

    def test_conflict_increments(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "doc-index.md"
            p.touch()
            (Path(tmp) / "doc-2-index.md").touch()
            result = resolve_conflict(p)
            self.assertEqual(result.name, "doc-3-index.md")

    def test_folder_conflict(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "doc"
            os.makedirs(p)
            result = resolve_conflict(p)
            self.assertEqual(result.name, "doc-2")


class TestBackup(unittest.TestCase):
    def test_backup_renames_file(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            original.write_text("# Test\n")
            bp = backup_path(original)
            self.assertTrue(bp.exists())
            self.assertFalse(original.exists())
            self.assertEqual(bp.name, "doc.md.bak")

    def test_backup_increments(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            original.write_text("# Test\n")
            (Path(tmp) / "doc.md.bak").touch()
            bp = backup_path(original)
            self.assertEqual(bp.name, "doc.md.bak.1")


class TestWriteCreatesParentDirs(unittest.TestCase):
    def test_nested_path(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "dir" / "file.md"
            write_file(p, "content")
            self.assertTrue(p.exists())
            self.assertEqual(p.read_text(), "content")


class TestSplitPreservesOriginal(unittest.TestCase):
    def test_non_destructive(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            content = "# A\nText A\n\n# B\nText B\n"
            original.write_text(content)
            split_operation(original)
            self.assertEqual(original.read_text(), content)


class TestJoinPreservesIndexAndSections(unittest.TestCase):
    def test_non_destructive(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            content = "# A\nText A\n\n# B\nText B\n"
            original.write_text(content)
            split_operation(original)
            index = Path(tmp) / "doc-index.md"
            self.assertTrue(index.exists())
            join_operation(index)
            self.assertTrue(index.exists())
            self.assertTrue((Path(tmp) / "doc").exists())


class TestDestructiveSplit(unittest.TestCase):
    def test_creates_bak(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            content = "# A\nText A\n\n# B\nText B\n"
            original.write_text(content)
            split_operation(original, destructive=True)
            self.assertTrue((Path(tmp) / "doc.md.bak").exists())
            self.assertTrue((Path(tmp) / "doc-index.md").exists())


class TestDestructiveJoin(unittest.TestCase):
    def test_backs_up_index_and_folder(self):
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "doc.md"
            content = "# A\nText A\n\n# B\nText B\n"
            original.write_text(content)
            split_operation(original)
            index = Path(tmp) / "doc-index.md"
            join_operation(index, destructive=True)
            self.assertTrue((Path(tmp) / "doc-index.md.bak").exists())


if __name__ == "__main__":
    unittest.main()
