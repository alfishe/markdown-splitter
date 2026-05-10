#!/usr/bin/env python3
"""mdsplit — Split monolithic markdown into sections, or join sections back.

Single-file tool. Python 3.9+ stdlib only. No external dependencies.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

__version__ = "1.0.0"

# ── Layer 0: Models ──────────────────────────────────────────────────────────

@dataclass
class Section:
    header_text: str       # Raw header line, e.g. "## Installation Guide"
    body: str              # Everything after the header line, up to next split-level header.
                           # Excludes trailing blank lines (those go into trailing_blanks).
    trailing_blanks: int   # Blank lines between this section and the next.
    description: str = ""  # Auto-extracted description for the index.

@dataclass
class Preamble:
    content: str           # Verbatim preamble (may include front matter; in ## fallback mode,
                           # includes the lone # header line).
    trailing_blanks: int   # Blank lines between preamble end and first section header.

@dataclass
class SplitDocument:
    title: str                       # Derived from first # header (or filename fallback).
    preamble: Optional[Preamble]     # None if no preamble.
    sections: List[Section]
    has_trailing_newline: bool       # State of the original document.
    line_ending: str                 # "\n" or "\r\n".
    split_level: int                 # 1 or 2.

@dataclass
class IndexEntry:
    display_name: str       # Header text with markdown stripped.
    relative_path: str      # e.g. "my-document/installation-guide.md".
    description: str        # Auto-extracted or fallback.
    trailing_blanks: int    # Blank lines after this section in the original.

@dataclass
class ParsedIndex:
    title: str
    entries: List[IndexEntry]
    has_trailing_newline: bool


# ── Layer 0: Parser (Pure) ──────────────────────────────────────────────────

HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})\s*")

class MdsplitError(Exception):
    """Base error."""

class SplitError(MdsplitError):
    """Raised by parser for validation failures."""

class JoinError(MdsplitError):
    """Raised by join for missing files / malformed index."""


def detect_line_ending(text: str) -> str:
    """Return '\\n' or '\\r\\n'."""
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def parse_header(line: str) -> Optional[Tuple[int, str]]:
    """Parse an ATX-style header line. Return (level, text) or None."""
    m = HEADER_RE.match(line)
    if m:
        return len(m.group(1)), m.group(2).rstrip()
    return None


def resolve_split_level(lines: List[str]) -> int:
    """Determine split level (1 or 2). Raises SplitError on invalid input.

    Pass 1 — count # headers (ignoring those inside code blocks):
    - Count > 1 → split level = 1.
    - Count == 1 → split level = 2.
    - Count == 0 and any other-level header exists → split level = 2.
    - Count == 0 and no headers at all → raise SplitError.

    Pass 2 — validate header order.
    """
    in_code_block = False
    fence_seq = ""
    h1_count = 0
    any_header = False
    first_h1_idx = -1
    first_split_level_idx = -1
    split_level = 0

    # Pass 1: count headers
    for i, line in enumerate(lines):
        # Code block tracking
        if not in_code_block:
            fm = FENCE_OPEN_RE.match(line)
            if fm:
                in_code_block = True
                fence_seq = fm.group(1)
                continue
        else:
            if line.startswith(fence_seq) and line.strip() == fence_seq:
                in_code_block = False
                fence_seq = ""
                continue
        if in_code_block:
            continue

        hdr = parse_header(line)
        if hdr is None:
            continue
        level, _ = hdr
        any_header = True
        if level == 1:
            h1_count += 1
            if first_h1_idx == -1:
                first_h1_idx = i

    if not any_header:
        raise SplitError("No markdown headers found. Cannot split.")

    if h1_count > 1:
        split_level = 1
    elif h1_count == 1:
        split_level = 2
    else:
        # No h1 but has other headers
        split_level = 2

    # Pass 2: validate header hierarchy
    in_code_block = False
    fence_seq = ""
    found_first_split = False
    found_h1 = False  # Track if we've seen the # header (for split_level==2)

    for line in lines:
        # Code block tracking
        if not in_code_block:
            fm = FENCE_OPEN_RE.match(line)
            if fm:
                in_code_block = True
                fence_seq = fm.group(1)
                continue
        else:
            if line.startswith(fence_seq) and line.strip() == fence_seq:
                in_code_block = False
                fence_seq = ""
                continue
        if in_code_block:
            continue

        hdr = parse_header(line)
        if hdr is None:
            continue
        level, _ = hdr

        if level == 1:
            found_h1 = True

        if level == split_level:
            found_first_split = True
        elif not found_first_split:
            # A header before the first split-level header
            if split_level == 2:
                # In ##-split mode, the # header and anything after it (until
                # first ##) is preamble. Headers deeper than ## between the #
                # and the first ## are part of the preamble content.
                # Only flag headers that appear BEFORE the # (truly orphan).
                if level == 1:
                    continue  # The # header itself — always OK
                elif found_h1:
                    continue  # Sub-header after # but before first ## — preamble content
                else:
                    raise SplitError(
                        "Header hierarchy is inconsistent — a deeper header appears "
                        "before the first split-level header."
                    )
            else:
                # split_level == 1: no deeper header may precede the first #
                raise SplitError(
                    "Header hierarchy is inconsistent — a deeper header appears "
                    "before the first split-level header."
                )
        else:
            # A header after the first split-level header
            # When split_level==2, a level-1 header after H2s is invalid
            if level == 1 and split_level == 2:
                raise SplitError(
                    "Header hierarchy is inconsistent — a deeper header appears "
                    "before the first split-level header."
                )

    # Edge case: single h1 with no h2
    if split_level == 2 and h1_count == 1:
        # Check that at least one h2 exists
        has_h2 = False
        in_code_block = False
        fence_seq = ""
        for line in lines:
            if not in_code_block:
                fm = FENCE_OPEN_RE.match(line)
                if fm:
                    in_code_block = True
                    fence_seq = fm.group(1)
                    continue
            else:
                if line.startswith(fence_seq) and line.strip() == fence_seq:
                    in_code_block = False
                    fence_seq = ""
                    continue
            if in_code_block:
                continue
            hdr = parse_header(line)
            if hdr and hdr[0] == 2:
                has_h2 = True
                break
        if not has_h2:
            raise SplitError(
                "Document has only one section; nothing to split."
            )

    # Edge case: split_level==1 but only one h1
    if split_level == 1 and h1_count == 1:
        raise SplitError(
            "Document has only one section; nothing to split."
        )

    # Edge case: split_level==2 with no h1, check there are at least 2 h2s
    if split_level == 2 and h1_count == 0:
        h2_count = 0
        in_code_block = False
        fence_seq = ""
        for line in lines:
            if not in_code_block:
                fm = FENCE_OPEN_RE.match(line)
                if fm:
                    in_code_block = True
                    fence_seq = fm.group(1)
                    continue
            else:
                if line.startswith(fence_seq) and line.strip() == fence_seq:
                    in_code_block = False
                    fence_seq = ""
                    continue
            if in_code_block:
                continue
            hdr = parse_header(line)
            if hdr and hdr[0] == 2:
                h2_count += 1
        if h2_count < 2:
            raise SplitError(
                "Document has only one section; nothing to split."
            )

    return split_level


def _count_trailing_blanks(lines: List[str], start: int, end: int) -> Tuple[int, int]:
    """Count blank lines at the end of lines[start:end]. Return (count, trimmed_end)."""
    count = 0
    i = end - 1
    while i >= start and lines[i].strip() == "":
        count += 1
        i -= 1
    return count, i + 1


def chunk_sections(
    lines: List[str], split_level: int
) -> Tuple[Optional[Preamble], List[Section]]:
    """Split lines into preamble + sections."""
    in_code_block = False
    fence_seq = ""

    # Find indices of split-level headers
    split_indices: List[int] = []
    for i, line in enumerate(lines):
        if not in_code_block:
            fm = FENCE_OPEN_RE.match(line)
            if fm:
                in_code_block = True
                fence_seq = fm.group(1)
                continue
        else:
            if line.startswith(fence_seq) and line.strip() == fence_seq:
                in_code_block = False
                fence_seq = ""
                continue
        if in_code_block:
            continue

        hdr = parse_header(line)
        if hdr and hdr[0] == split_level:
            split_indices.append(i)

    if not split_indices:
        # Shouldn't happen if resolve_split_level was called
        raise SplitError("No split-level headers found.")

    # Preamble: everything before first split-level header
    preamble: Optional[Preamble] = None
    first_split = split_indices[0]
    if first_split > 0:
        pre_lines = lines[:first_split]
        # Count trailing blanks in preamble
        blanks, trimmed_end = _count_trailing_blanks(pre_lines, 0, len(pre_lines))
        preamble_content = "\n".join(pre_lines[:trimmed_end])
        preamble = Preamble(content=preamble_content, trailing_blanks=blanks)
    elif split_level == 2:
        # In split_level==2 mode with h1, the h1 is in the preamble
        # But if first_split==0, the first line is an h2 — no preamble
        preamble = None

    # For split_level==2: if there's a single h1, it becomes part of preamble
    # We need to find if there's an h1 before the first h2
    if split_level == 2 and split_indices[0] > 0:
        # Check if line before first h2 is an h1
        # Actually, re-scan: find the h1 and include it in preamble
        h1_idx = -1
        in_code_block = False
        fence_seq = ""
        for i, line in enumerate(lines):
            if not in_code_block:
                fm = FENCE_OPEN_RE.match(line)
                if fm:
                    in_code_block = True
                    fence_seq = fm.group(1)
                    continue
            else:
                if line.startswith(fence_seq) and line.strip() == fence_seq:
                    in_code_block = False
                    fence_seq = ""
                    continue
            if in_code_block:
                continue
            hdr = parse_header(line)
            if hdr and hdr[0] == 1:
                h1_idx = i
                break

        if h1_idx >= 0 and h1_idx < first_split:
            # Include h1 and everything between h1 and first h2 in preamble
            pre_lines = lines[:first_split]
            blanks, trimmed_end = _count_trailing_blanks(pre_lines, 0, len(pre_lines))
            preamble_content = "\n".join(pre_lines[:trimmed_end])
            preamble = Preamble(content=preamble_content, trailing_blanks=blanks)

    # Build sections
    sections: List[Section] = []
    for idx, start in enumerate(split_indices):
        if idx + 1 < len(split_indices):
            end = split_indices[idx + 1]
        else:
            end = len(lines)

        header_text = lines[start]
        # Body: lines after header, excluding trailing blanks
        body_start = start + 1
        blanks, trimmed_end = _count_trailing_blanks(lines, body_start, end)

        # Last section: trailing_blanks is always 0
        if idx == len(split_indices) - 1:
            blanks = 0
            trimmed_end = end

        body_lines = lines[body_start:trimmed_end]
        body = "\n".join(body_lines)

        sections.append(Section(
            header_text=header_text,
            body=body,
            trailing_blanks=blanks,
        ))

    return preamble, sections


def strip_markdown_inline(text: str) -> str:
    """Strip inline markdown formatting from text."""
    # Strikethrough
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Bold (** or __)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Italic (* or _)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Images
    text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text


def extract_description(header_text: str, body: str) -> str:
    """Extract description from section body per priority order."""
    if not body or not body.strip():
        return "(empty section)"

    # Strip # marks from header_text for fallback
    hdr = parse_header(header_text)
    if hdr:
        header_display = hdr[1].strip()
    else:
        header_display = header_text.strip()
    header_display = strip_markdown_inline(header_display)

    lines = body.split("\n")
    in_code_block = False
    fence_seq = ""

    for line in lines:
        # Track code blocks
        if not in_code_block:
            fm = FENCE_OPEN_RE.match(line)
            if fm:
                in_code_block = True
                fence_seq = fm.group(1)
                continue
        else:
            if line.startswith(fence_seq) and line.strip() == fence_seq:
                in_code_block = False
                fence_seq = ""
                continue
        if in_code_block:
            continue

        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            continue

        # Skip structural elements
        if FENCE_OPEN_RE.match(stripped):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("!["):
            continue
        if stripped.startswith(">"):
            continue
        # Skip nested headers
        if HEADER_RE.match(stripped):
            continue

        # Found a candidate line
        desc = strip_markdown_inline(stripped)
        if len(desc) > 200:
            desc = desc[:200] + "..."
        return desc

    # No suitable text found — only structural/nested content
    return f"({header_display})"


def parse_markdown(content: str, filename: str = "") -> SplitDocument:
    """Top-level parse: raw markdown string → SplitDocument."""
    line_ending = detect_line_ending(content)

    # Normalize to LF for internal processing
    content = content.replace("\r\n", "\n")

    # Detect trailing newline
    has_trailing_newline = content.endswith("\n")
    if has_trailing_newline:
        content = content[:-1]

    lines = content.split("\n")

    split_level = resolve_split_level(lines)
    preamble, sections = chunk_sections(lines, split_level)

    # Extract descriptions
    for section in sections:
        section.description = extract_description(section.header_text, section.body)

    # Title derivation
    title = ""
    if split_level == 1:
        # Title from first # header
        in_code_block = False
        fence_seq = ""
        for line in lines:
            if not in_code_block:
                fm = FENCE_OPEN_RE.match(line)
                if fm:
                    in_code_block = True
                    fence_seq = fm.group(1)
                    continue
            else:
                if line.startswith(fence_seq) and line.strip() == fence_seq:
                    in_code_block = False
                    fence_seq = ""
                    continue
            if in_code_block:
                continue
            hdr = parse_header(line)
            if hdr and hdr[0] == 1:
                title = hdr[1].strip()
                break
    elif split_level == 2:
        # Title from lone # header (in preamble) or filename
        if preamble and preamble.content:
            for line in preamble.content.split("\n"):
                hdr = parse_header(line)
                if hdr and hdr[0] == 1:
                    title = hdr[1].strip()
                    break
        if not title:
            # No h1 in preamble — try first h2
            in_code_block = False
            fence_seq = ""
            for line in lines:
                if not in_code_block:
                    fm = FENCE_OPEN_RE.match(line)
                    if fm:
                        in_code_block = True
                        fence_seq = fm.group(1)
                        continue
                else:
                    if line.startswith(fence_seq) and line.strip() == fence_seq:
                        in_code_block = False
                        fence_seq = ""
                        continue
                if in_code_block:
                    continue
                hdr = parse_header(line)
                if hdr and hdr[0] == 2:
                    title = hdr[1].strip()
                    break
        if not title:
            title = filename or "Document"

    # Strip markdown from title for display
    title = strip_markdown_inline(title)

    return SplitDocument(
        title=title,
        preamble=preamble,
        sections=sections,
        has_trailing_newline=has_trailing_newline,
        line_ending=line_ending,
        split_level=split_level,
    )


# ── Layer 1: Generator (Pure) ───────────────────────────────────────────────

def sanitize_filename(header_text: str) -> str:
    """Convert header text to a safe filename."""
    # Strip # marks and following whitespace
    name = re.sub(r"^#+\s+", "", header_text)
    # Strip inline markdown
    name = strip_markdown_inline(name)
    # Lowercase
    name = name.lower()
    # Replace spaces and underscores with hyphens
    name = re.sub(r"[ _]", "-", name)
    # Remove all characters except a-z, 0-9, hyphens
    name = re.sub(r"[^a-z0-9-]", "", name)
    # Collapse consecutive hyphens
    name = re.sub(r"-{2,}", "-", name)
    # Strip leading and trailing hyphens
    name = name.strip("-")
    # If empty, use "section"
    if not name:
        name = "section"
    return name + ".md"


def deduplicate_filenames(names: List[str]) -> List[str]:
    """Append -2, -3, etc. to duplicate filenames."""
    seen: dict[str, int] = {}
    result: List[str] = []
    for name in names:
        if name not in seen:
            seen[name] = 1
            result.append(name)
        else:
            seen[name] += 1
            suffix = seen[name]
            base, ext = os.path.splitext(name)
            result.append(f"{base}-{suffix}{ext}")
    return result


def generate_index_string(
    doc: SplitDocument,
    folder_name: str,
    section_filenames: List[str],
) -> str:
    """Generate the index file content as a markdown table."""
    lines: List[str] = []

    # Title line
    lines.append(f"# {doc.title}")
    lines.append("")
    lines.append("<!-- mdsplit-index -->")
    lines.append("| Section | Description |")
    lines.append("|---------|-------------|")

    # Preamble entry
    if doc.preamble is not None:
        blanks_suffix = f" <!-- blanks:{doc.preamble.trailing_blanks} -->" if doc.preamble.trailing_blanks > 0 else ""
        lines.append(f"| [Preamble]({folder_name}/_preamble.md) | Preamble{blanks_suffix} |")

    # Section entries
    for i, section in enumerate(doc.sections):
        hdr = parse_header(section.header_text)
        display_name = hdr[1].strip() if hdr else section.header_text.strip()
        display_name = strip_markdown_inline(display_name)
        rel_path = f"{folder_name}/{section_filenames[i]}"
        desc = section.description
        blanks_suffix = f" <!-- blanks:{section.trailing_blanks} -->" if section.trailing_blanks > 0 else ""
        lines.append(f"| [{display_name}]({rel_path}) | {desc}{blanks_suffix} |")

    lines.append("<!-- /mdsplit-index -->")
    lines.append("")
    lines.append(f"<!-- trailing-newline:{str(doc.has_trailing_newline).lower()} -->")

    return "\n".join(lines) + "\n"


ENTRY_RE = re.compile(
    r"^\|\s*"                                    # leading pipe
    r"\[(.+?)\]"                                 # display_name in brackets
    r"\((.+?)\)"                                 # relative_path in parens
    r"\s*\|\s*"                                  # column separator
    r"(.+?)"                                     # description
    r"(?:\s+<!--\s*blanks:(\d+)\s*-->)?"         # optional blanks
    r"\s*\|$"                                    # trailing pipe
)

TRAILING_NEWLINE_RE = re.compile(r"<!--\s*trailing-newline:(true|false)\s*-->")


def parse_index_string(content: str) -> ParsedIndex:
    """Parse an index file string → ParsedIndex."""
    lines = content.split("\n")

    # Find title
    title = ""
    for line in lines:
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            title = m.group(1).strip()
            break

    # Find markers
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if "<!-- mdsplit-index -->" in line:
            start_idx = i
        if "<!-- /mdsplit-index -->" in line:
            end_idx = i
            break

    if start_idx is None or end_idx is None:
        raise JoinError("Index file is missing required mdsplit-index markers.")

    # Parse entries between markers (table rows)
    entries: List[IndexEntry] = []
    for i in range(start_idx + 1, end_idx):
        line = lines[i].strip()
        if not line or line.startswith("|") and set(line.replace("-", "").replace("|", "").strip()) <= {""}:
            # Skip separator row (|---|---|)
            continue
        if not line.startswith("|"):
            continue
        m = ENTRY_RE.match(line)
        if m:
            display_name = m.group(1)
            relative_path = m.group(2)
            description = m.group(3).strip()
            blanks = int(m.group(4)) if m.group(4) else 0
            entries.append(IndexEntry(
                display_name=display_name,
                relative_path=relative_path,
                description=description,
                trailing_blanks=blanks,
            ))

    # Find trailing-newline marker
    has_trailing_newline = True  # default
    for line in lines:
        m = TRAILING_NEWLINE_RE.search(line)
        if m:
            has_trailing_newline = m.group(1) == "true"
            break

    return ParsedIndex(
        title=title,
        entries=entries,
        has_trailing_newline=has_trailing_newline,
    )


def assemble_markdown_string(
    preamble_content: Optional[str],
    preamble_blanks: int,
    section_contents: List[str],
    blanks: List[int],
    has_trailing_newline: bool,
    line_ending: str,
) -> str:
    """Assemble sections back into a monolithic markdown string."""
    parts: List[str] = []

    if preamble_content is not None:
        # Strip exactly one trailing newline
        if preamble_content.endswith("\n"):
            preamble_content = preamble_content[:-1]
        parts.append(preamble_content)
        for _ in range(preamble_blanks):
            parts.append("")

    for i, (content, trailing_blanks) in enumerate(zip(section_contents, blanks)):
        # Strip exactly one trailing newline from section file content
        if content.endswith("\n"):
            content = content[:-1]
        parts.append(content)
        if i < len(section_contents) - 1:
            for _ in range(trailing_blanks):
                parts.append("")

    result = line_ending.join(parts)

    if has_trailing_newline:
        if not result.endswith(line_ending):
            result += line_ending
    else:
        if result.endswith(line_ending):
            result = result[:-len(line_ending)]

    return result


# ── Layer 2: IO (Side Effects) ──────────────────────────────────────────────

def read_file(path: Path) -> str:
    """Read UTF-8 file content."""
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str) -> None:
    """Write content as UTF-8. Creates parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_to_lf(text: str) -> str:
    """Convert CRLF to LF. Called immediately after read_file."""
    return text.replace("\r\n", "\n")


def apply_line_ending(text: str, line_ending: str) -> str:
    """Convert LF to target line ending. Called immediately before write_file."""
    if line_ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def resolve_conflict(base_path: Path) -> Path:
    """If base_path exists, append -2, -3, etc. until unique.

    For files: insert counter before the last hyphen-segment.
      design-index.md → design-2-index.md
    For folders: append to folder name.
      design/ → design-2/
    """
    if not base_path.exists():
        return base_path

    if base_path.is_file() or (not base_path.exists() and base_path.suffix):
        # File: insert counter before the last hyphen-segment in the stem
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
        # Find the last hyphen in the stem
        last_hyphen = stem.rfind("-")
        if last_hyphen > 0:
            prefix = stem[:last_hyphen]
            tail = stem[last_hyphen:]  # includes the hyphen
        else:
            prefix = stem
            tail = ""
        n = 2
        while True:
            candidate = parent / f"{prefix}-{n}{tail}{suffix}"
            if not candidate.exists():
                return candidate
            n += 1
    else:
        # Folder: append to name
        name = base_path.name
        parent = base_path.parent
        n = 2
        while True:
            candidate = parent / f"{name}-{n}"
            if not candidate.exists():
                return candidate
            n += 1


def backup_path(target: Path) -> Path:
    """Rename target to .bak (with conflict resolution). Return backup path."""
    backup = target.parent / (target.name + ".bak")
    if backup.exists():
        n = 1
        while True:
            candidate = target.parent / (target.name + f".bak.{n}")
            if not candidate.exists():
                backup = candidate
                break
            n += 1
    os.rename(str(target), str(backup))
    return backup


def diff_strings(expected: str, actual: str, label_a: str, label_b: str) -> str:
    """Produce a unified diff. Empty string if identical."""
    if expected == actual:
        return ""
    return "".join(difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile=label_a, tofile=label_b, n=3,
    ))


# ── Layer 3: Orchestrators ──────────────────────────────────────────────────

def split_operation(
    input_file: Path,
    destructive: bool = False,
    dry_run: bool = False,
    verify: bool = False,
    output: Optional[Path] = None,
) -> int:
    """Execute the split operation. Returns exit code."""
    # Read
    raw = read_file(input_file)
    content_lf = normalize_to_lf(raw)

    # Parse
    doc = parse_markdown(content_lf, input_file.stem)

    # Determine output paths
    parent = input_file.parent
    base_name = output.stem if output else input_file.stem
    base_parent = output.parent if output else parent

    index_path = base_parent / f"{base_name}-index.md"
    folder_path = base_parent / base_name

    # Conflict resolution (non-destructive only)
    if not destructive:
        index_path = resolve_conflict(index_path)
        folder_path = resolve_conflict(folder_path)
        # Keep them paired: derive base from the actual index name
        if index_path.stem != f"{base_name}-index":
            actual_base = index_path.stem.replace("-index", "")
            folder_path = base_parent / actual_base

    # Section filenames
    filenames = [sanitize_filename(s.header_text) for s in doc.sections]
    filenames = deduplicate_filenames(filenames)

    # If destructive: backup original
    if destructive:
        bp = backup_path(input_file)
        print(f"Backup: {bp}")

    # Generate index
    index_str = generate_index_string(doc, folder_path.name, filenames)

    # Build section file contents
    section_file_map: List[Tuple[str, str]] = []  # (relative_path, content)
    if doc.preamble is not None:
        pre_content = doc.preamble.content + "\n"
        section_file_map.append((f"{folder_path.name}/_preamble.md", pre_content))

    for i, section in enumerate(doc.sections):
        sec_content = section.header_text + "\n"
        if section.body:
            sec_content += section.body + "\n"
        section_file_map.append((f"{folder_path.name}/{filenames[i]}", sec_content))

    # Dry run
    if dry_run:
        print(f"Would create: {index_path}")
        for rel_path, _ in section_file_map:
            print(f"Would create: {base_parent / rel_path}")
        return 0

    # Write
    write_file(index_path, apply_line_ending(index_str, doc.line_ending))
    print(f"Created: {index_path}")

    for rel_path, content in section_file_map:
        full_path = base_parent / rel_path
        write_file(full_path, apply_line_ending(content, doc.line_ending))
        print(f"Created: {full_path}")

    # Verify
    if verify:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Run join in temp dir
            rejoined = _verify_join(index_path, tmp_path, doc.line_ending)
            d = diff_strings(raw, rejoined, "original", "rejoined")
            if d:
                print(d)
                print("Error: Round-trip verification failed — output differs from original.", file=sys.stderr)
                return 2

    return 0


def _verify_join(index_path: Path, tmp_dir: Path, line_ending: str) -> str:
    """Join the split output in a temp dir and return the result."""
    raw_index = read_file(index_path)
    index_text = normalize_to_lf(raw_index)
    parsed = parse_index_string(index_text)

    # Read section files
    preamble_content = None
    preamble_blanks = 0
    section_contents: List[str] = []
    blanks: List[int] = []

    for entry in parsed.entries:
        section_path = index_path.parent / entry.relative_path
        content = read_file(section_path)
        content_lf = normalize_to_lf(content)

        if entry.display_name == "Preamble" and entry.relative_path.endswith("_preamble.md"):
            preamble_content = content_lf
            preamble_blanks = entry.trailing_blanks
        else:
            section_contents.append(content_lf)
            blanks.append(entry.trailing_blanks)

    return assemble_markdown_string(
        preamble_content, preamble_blanks,
        section_contents, blanks,
        parsed.has_trailing_newline, line_ending,
    )


def join_operation(
    index_file: Path,
    destructive: bool = False,
    dry_run: bool = False,
    verify: bool = False,
    output: Optional[Path] = None,
) -> int:
    """Execute the join operation. Returns exit code."""
    # Read index
    raw_index = read_file(index_file)
    line_ending = detect_line_ending(raw_index)
    index_text = normalize_to_lf(raw_index)

    # Parse
    parsed = parse_index_string(index_text)

    # Validate section files exist and read them
    preamble_content = None
    preamble_blanks = 0
    section_contents: List[str] = []
    blanks: List[int] = []
    folder_path: Optional[Path] = None

    for entry in parsed.entries:
        section_path = index_file.parent / entry.relative_path
        if not section_path.exists():
            raise JoinError(f"Section file not found: {section_path}")

        content = read_file(section_path)
        content_lf = normalize_to_lf(content)

        if entry.display_name == "Preamble" and entry.relative_path.endswith("_preamble.md"):
            preamble_content = content_lf
            preamble_blanks = entry.trailing_blanks
            # Derive folder path from preamble entry
            folder_path = (index_file.parent / entry.relative_path).parent
        else:
            section_contents.append(content_lf)
            blanks.append(entry.trailing_blanks)
            if folder_path is None:
                folder_path = (index_file.parent / entry.relative_path).parent

    # Determine output path
    base_stem = index_file.stem
    if base_stem.endswith("-index"):
        base_stem = base_stem[:-6]  # Strip "-index"

    if output:
        out_path = output
    else:
        out_path = index_file.parent / f"{base_stem}-joined.md"

    if not destructive:
        out_path = resolve_conflict(out_path)

    # If destructive: backup
    if destructive:
        if folder_path and folder_path.exists():
            bp = backup_path(folder_path)
            print(f"Backup: {bp}")
        bp = backup_path(index_file)
        print(f"Backup: {bp}")

    # Assemble
    joined_lf = assemble_markdown_string(
        preamble_content, preamble_blanks,
        section_contents, blanks,
        parsed.has_trailing_newline, "\n",
    )
    joined = apply_line_ending(joined_lf, line_ending)

    # Dry run
    if dry_run:
        print(f"Would create: {out_path}")
        return 0

    # Write
    write_file(out_path, joined)
    print(f"Created: {out_path}")

    # Verify
    if verify:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Split the joined output in temp dir
            tmp_joined = tmp_path / "joined.md"
            write_file(tmp_joined, joined)
            # Run split
            split_op_result = split_operation(tmp_joined, destructive=False, dry_run=False)
            if split_op_result != 0:
                print("Error: Verify split failed.", file=sys.stderr)
                return 2
            # Find the generated index
            tmp_index = tmp_path / "joined-index.md"
            if not tmp_index.exists():
                print("Error: Verify could not find split index.", file=sys.stderr)
                return 2
            # Join again
            rejoined_lf = _verify_join(tmp_index, tmp_path, line_ending)
            rejoined = apply_line_ending(rejoined_lf, line_ending)
            d = diff_strings(joined, rejoined, "first-join", "second-join")
            if d:
                print(d)
                print("Error: Round-trip verification failed — output differs from original.", file=sys.stderr)
                return 2

    return 0


# ── Layer 4: CLI ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdsplit",
        description="Split monolithic markdown into sections, or join sections back",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # split
    split_p = subparsers.add_parser("split", help="Split a markdown file into sections")
    split_p.add_argument("file", help="Input markdown file")
    split_p.add_argument("--destructive", action="store_true", help="Backup and replace original")
    split_p.add_argument("--dry-run", action="store_true", help="Simulate without changes")
    split_p.add_argument("--verify", action="store_true", help="Verify round-trip integrity")
    split_p.add_argument("--output", help="Explicit output base name or path")

    # join
    join_p = subparsers.add_parser("join", help="Join sections back into one file")
    join_p.add_argument("index_file", help="Index file from a previous split")
    join_p.add_argument("--destructive", action="store_true", help="Backup and replace index+folder")
    join_p.add_argument("--dry-run", action="store_true", help="Simulate without changes")
    join_p.add_argument("--verify", action="store_true", help="Verify round-trip integrity")
    join_p.add_argument("--output", help="Explicit output path")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "split":
            input_path = Path(args.file)
            if not input_path.exists():
                print(f"Error: File not found: {input_path}", file=sys.stderr)
                return 1
            output_path = Path(args.output) if args.output else None
            return split_operation(input_path, args.destructive, args.dry_run, args.verify, output_path)
        elif args.command == "join":
            index_path = Path(args.index_file)
            if not index_path.exists():
                print(f"Error: File not found: {index_path}", file=sys.stderr)
                return 1
            output_path = Path(args.output) if args.output else None
            return join_operation(index_path, args.destructive, args.dry_run, args.verify, output_path)
    except SplitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except JoinError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"Error: Permission denied: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
