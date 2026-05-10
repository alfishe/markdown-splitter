# Markdown Splitter Tool Requirements

## Overview
A Python tool to split monolithic markdown files into section-based files with an index, and reverse the operation to join them back together.

### Problem Statement
Large monolithic markdown documents (hundreds or thousands of lines) are inefficient for LLM-assisted workflows. When an LLM agent needs to read, edit, or reason about a specific part of a document, it typically must load the entire file into context — consuming tokens proportionally to the file's total size rather than the size of the relevant section. This is wasteful, slow, and degrades the quality of LLM interactions.

### Goal
**Drastically improve the efficiency of LLM-assisted documentation workflows** by enabling granular, section-level context loading. Instead of loading a 2000-line document to edit one section, the LLM can:

1. **Read the index file** — a lightweight summary (typically 20-50 lines) that lists all sections with descriptions, allowing the LLM to identify which sections are relevant
2. **Load only the needed section files** — each file contains exactly one top-level section, minimizing token usage
3. **Edit individual sections** — make surgical edits to specific section files without risking unintended changes to other parts of the document
4. **Reassemble when needed** — join sections back into a monolithic file when the full document is required (e.g., for publishing, sharing, or processing by tools that expect a single file)

### Token Efficiency
The primary metric of success is **token reduction**. For a document split into N sections of roughly equal size, loading one section instead of the full document uses approximately 1/N of the tokens. The index file adds minimal overhead (typically 1-3% of the original document size) and acts as a "table of contents" that the LLM reads first to decide what it actually needs.

### Target Workflow
1. Author maintains a monolithic markdown document (e.g., `design-doc.md`)
2. Run `mdsplit split design-doc.md` → produces `design-doc-index.md` + `design-doc/` folder with section files
3. LLM agent reads `design-doc-index.md` to understand document structure (small context cost)
4. LLM agent reads only relevant section files (e.g., `design-doc/architecture.md`) to perform its task
5. LLM agent edits specific section files directly
6. When needed, run `mdsplit join design-doc-index.md` → produces `design-doc-joined.md` (or with `--destructive`, overwrites original)

### Secondary Benefits
- **Parallel editing**: Multiple LLM agents (or human reviewers) can edit different sections simultaneously without merge conflicts on the same file
- **Selective regeneration**: Re-generate or re-write individual sections without touching the rest of the document
- **Review efficiency**: Reviewers (human or AI) can focus on changed sections by examining file-level diffs instead of scrolling through a monolithic document
- **Context window management**: For very large documents that exceed context limits, sections can be processed one at a time

## Core Operations

### Split Operation
- **Input**: Single monolithic markdown file
- **Output**: 
  - Index file: `<original name>-index.md`
  - Section files: `<original name>/` subfolder containing one file per section
- **Behavior**: Non-destructive by default (original file preserved)

### Join Operation
- **Input**: Index file (`<name>-index.md`) and section files in `<name>/` subfolder
- **Output**: Single joined markdown file: `<original name>-joined.md`
  - If original name had `-index` postfix, it is excluded from output name
- **Behavior**: Non-destructive by default (original files preserved)

## Section Definition

### Header Level Detection
- **Multiple top-level `#` headers present**: Split on `#` headers
- **Only one top-level `#` header**: Split on `##` headers
- **No headers at all**: Exit with error. The tool requires at least one header to determine split points. Print a clear message: `"Error: No markdown headers found. Cannot split."`
- **Nested sections**: All nested headers (###, ####, etc.) remain in the same section file without transformation
- **Content preservation**: Nested sections are preserved exactly as-is in the section file

### Validation Rules
- **Header level ordering**: Split-level headers must not be preceded by deeper headers that belong to a higher level. Specifically:
  - When splitting on `#` (multiple `#` headers): no `##` or deeper header may appear before the first `#`
  - When splitting on `##` (single `#` fallback): `###` or deeper headers must not appear before the first `##`. A `#` header is expected before `##` headers (it becomes the preamble)
  - Violation exits with an error: `"Error: Header hierarchy is inconsistent — a deeper header appears before the first split-level header."`
- **Non-contiguous header levels are allowed**: A document with `#` followed directly by `###` (skipping `##`) is valid — the `###` is treated as nested content within the `#` section
- **Blank lines between headers and content**: Any number of blank lines between a header and its content are preserved as-is

### Title Section (Single `#` Fallback)
When the tool falls back to splitting on `##` because there is only one `#` header:
- The lone `#` header and all content between it and the first `##` header are treated as preamble — stored in `_preamble.md`
- The `#` header text is used as the document title in the index file's `# <title>` header
- The preamble file contains the `#` header line itself followed by any content after it, up to (but not including) the first `##` header
- This means the preamble file starts with a `#` header (unlike the multi-`#` case where the preamble has no header). This is intentional — the `#` is part of the preamble content because it is not a split boundary

### Preamble Content
- **Definition**: Any content appearing before the first split-level header. This includes:
  - **When splitting on `#`**: Any content before the first `#` header (front matter, introductory text, blank lines)
  - **When splitting on `##` (single `#` fallback)**: The lone `#` header and all content between it and the first `##` header
- **Handling**: Preamble content becomes a special section file named `_preamble.md`
- **Index entry**: Listed as the first entry in the index with the description `"Preamble"` (no auto-extracted description)
- **Preamble header**: When splitting on `#`, the preamble file does **not** receive a synthetic header — it contains only the original preamble content verbatim. When splitting on `##` (fallback), the preamble file starts with the `#` header line as-is (since `#` is not a split boundary in this mode)
- **Empty preamble**: If there is no content before the first split-level header (and no lone `#` header in fallback mode), no preamble file is created
- **Idempotency note**: During join, the preamble file content is prepended before the first section without any extra blank lines beyond what was in the original

### YAML Front Matter
- **Definition**: An optional block at the very start of a file delimited by `---` on its own line (opening line must be the very first line of the file, with no preceding blank lines or content)
- **Detection**: Front matter is detected only when `---` appears as the first line of the file. A `---` line appearing elsewhere (e.g., as a thematic break or inside code blocks) is **not** treated as front matter
- **Relationship to preamble**: Front matter is a subset of preamble content. If front matter exists, the preamble file contains: the front matter block (opening `---`, content, closing `---`) followed by any remaining preamble content (introductory text, blank lines) up to the first split-level header. There is no separate `_frontmatter.md` file — front matter always goes into `_preamble.md`
- **No front matter, but preamble exists**: If the file starts with regular content (not `---`) before the first header, the preamble file contains only that content — no front matter block
- **Preservation**: Front matter is preserved verbatim. The tool does not parse, validate, or interpret front matter content (no matching of opening/closing tags required). The priority is to avoid corrupting the file and ensure the split and join operations are perfectly compatible to always recover the original state even after many cycles
- **Join behavior**: If a preamble file exists, its entire content (which includes front matter if present) is placed at the very beginning of the joined file

### Section File Content
- Each section file contains the header and all content under it (including nested sections)
- No transformations to the content structure
- Content is preserved exactly as in the original (including whitespace, formatting)

### Empty Sections
- A section that contains only the header line (no body content) produces a valid section file containing just the header
- The index entry for an empty section uses the description `"(empty section)"`
- During join, empty sections are reconstructed as just the header line followed by whatever trailing blank lines originally followed it

## Index File Format

### Structure
The index file uses a markdown table format for machine-parseable reliability:

```markdown
# <Original Document Title>

<!-- mdsplit-index -->
| Section | Description |
|---------|-------------|
| [Section Display Name](<folder>/<section-filename>.md) | Brief description <!-- blanks:2 --> |
| [Another Section](<folder>/<another-section>.md) | Another description |
<!-- /mdsplit-index -->

<!-- trailing-newline:true -->
```

- **Title**: The first `#` header in the index file echoes the original document's title (derived from the first header found in the source file, or the filename if no header exists). This title is **not** included in the joined output — it is metadata for the index file only
- **Marker comments**: `<!-- mdsplit-index -->` and `<!-- /mdsplit-index -->` wrap the section list, enabling reliable parsing during join
- **Section entries**: Each table row follows the format: `| [<display name>](<relative-path>) | <description> <!-- blanks:N --> |`
  - `<display name>`: The original header text (with markdown formatting stripped)
  - `<relative-path>`: Path to the section file relative to the index file's location (e.g., `my-document/introduction.md`)
  - `<description>`: Auto-extracted description or fallback text
  - `<!-- blanks:N -->`: Number of blank lines between this section and the next in the original document. Omit if 0
- **Separator**: Table columns are separated by `|` pipes
- **Preamble entry**: If present, listed first: `| [Preamble](<folder>/_preamble.md) | Preamble <!-- blanks:1 --> |`
- **Trailing newline marker**: `<!-- trailing-newline:true -->` or `<!-- trailing-newline:false -->` placed after the closing marker, on its own line. Records whether the original file ended with a trailing newline
- **User content outside markers**: Users may add freeform content (notes, additional links, comments) outside the `<!-- mdsplit-index -->` ... `<!-- /mdsplit-index -->` markers. The join operation ignores anything outside the markers. The split operation preserves nothing outside the markers when round-tripping

### Description Extraction
- Extract first paragraph or line after the header (plain text, not markdown)
- Must be implementable in pure Python without external AI/LLM dependencies
- Strip markdown formatting from description (bold, italic, links, etc.)
- Truncate to reasonable length if needed (e.g., 200 characters)
- Handle edge cases (empty sections, sections with only nested headers)
- Use simple heuristics: first non-empty line after header, or first paragraph up to double newline

Description extraction priority order:
1. First non-empty, non-header line after the split-level header
2. Skip structural elements: code blocks (` ``` `), tables (`| ... |`), images (`![...]()`), blockquotes (`>`) — continue to the next line if the first content is one of these
3. Strip all inline markdown formatting: `**bold**` → `bold`, `*italic*` → `italic`, `[text](url)` → `text`, `` `code` `` → `code`, etc.
4. If no suitable text is found (section contains only nested sub-headers, code blocks, or is empty), use the header text itself as the description in parentheses: `(Section Title)`
5. Truncate at 200 characters, appending `...` if truncated

### Order Determination
- Join operation uses the order specified in the index file to reconstruct the original document
- Users may manually reorder entries in the index file between split and join — the join operation will respect the new order
- Users may also delete entries from the index to exclude sections during join
- If a section file referenced in the index is missing, join exits with an error naming the missing file

## File Naming Conventions

### Default Naming
- **Index file**: `<original name>-index.md`
- **Section folder**: `<original name>/`
- **Section files**: Derived from section headers (sanitized for filesystem)
- **Joined file**: `<original name>-joined.md`

### Section File Naming
- Derived from section headers (sanitized for filesystem)
- Sanitization rules (applied in order):
  1. Convert to lowercase
  2. Replace spaces and underscores with hyphens (`-`)
  3. Remove all characters except `a-z`, `0-9`, and hyphens (`-`)
  4. Collapse consecutive hyphens into a single hyphen
  5. Strip leading and trailing hyphens
  6. If the result is empty (header contained no alphanumeric characters), use `section` as the base name
- Format: `lowercase-with-hyphens.md`
- If filename conflicts occur within the same folder, append autoincremented postfix: `-2`, `-3`, etc. (starting at 2 to avoid confusion with the unsuffixed first occurrence)

### Conflict Resolution
- If target file/folder already exists:
  - Append autoincremented postfix: `-<X>` where X starts at 2 and increments until a unique name is found (starting at 2 avoids confusion with the unsuffixed first occurrence)
  - Update index links to reflect the actual filenames (including folder name if the folder was renamed)
- Applies to both files and folders
- Conflict detection applies to both the index file and the section folder
- Example: if `document.md` is split and `document-index.md` already exists, create `document-2-index.md` and `document-2/` folder

## Idempotency

### Consistency Requirement
- Split followed by join must produce content identical to the original
- Multiple split-join cycles must yield the same result each time
- No information loss during round-trip operations
- Idempotency is critical for reliable repeated operations

### Whitespace and Boundary Preservation
This is the core mechanism for achieving idempotency:

- **Trailing newlines in section files**: Each section file ends with exactly one newline (`\n`). Any trailing blank lines that appeared between sections in the original document are **not** included in the section file itself.
- **Separator blank lines**: The exact number of blank lines between consecutive sections in the original document is recorded in the index metadata. During join, this many blank lines are inserted between reconstructed sections.
- **Implementation**: Each index entry includes a hidden metadata comment for blank-line count: `<!-- blanks:N -->` placed after the description, where N is the number of blank lines between this section and the next. Omit if 0 (defaults to 0 when absent)
- **Line endings**: The tool preserves the original file's line ending style (`\n` or `\r\n`). Detected automatically from the input file. All output files use the same line ending style
- **Final newline**: The joined file ends with exactly one newline if the original did, or no trailing newline if the original did not. The original's trailing-newline state is recorded in the index as `<!-- trailing-newline:true -->` or `<!-- trailing-newline:false -->` after the closing marker

### Verification
- Split-join round-trip must produce byte-identical output to the original file
- The tool includes a `--verify` flag:
  - **With `split`**: After splitting, performs a join in a temporary directory and compares the result to the original file
  - **With `join`**: After joining, performs a split on the result in a temporary directory, then joins again, and compares the final output to the just-joined file (join-split-join round trip)
  - Reports any differences to stdout; exits with code 2 if differences are found

## Operation Modes

### Default Mode (Non-destructive)
- Original files are never overwritten
- New files created with modified names as needed

### Dry Run Mode
- Simulate operations without making any file changes
- Report what would be created/modified
- Output includes: list of files that would be created, their derived names, and any conflicts detected
- Useful for previewing changes

### Destructive Mode
- Option to replace original files using a safe backup-and-rename sequence
- Must be explicitly enabled (not default)
- Use with caution
- **When used with `split`**: The original file is renamed to a backup name (`<original name>.bak`), then the new index and section folder are created using the original base name. Print `Backup: <backup path>` to stdout
- **When used with `join`**: The index file is renamed to a backup name (`<index name>.bak`) and the section folder is renamed to a backup name (`<folder name>.bak`), then the joined file is created using the original base name. Print `Backup: <backup path>` (once for index, once for folder) to stdout
- **Backup conflicts**: If a `.bak` file already exists, append autoincremented postfix (`.bak.1`, `.bak.2`, etc.)
- **Atomicity**: The backup rename happens before any new file creation. If creation fails, the backup remains in place (no automatic rollback)

## Command-Line Interface

### Interface
```
mdsplit split <file> [options]
mdsplit join <index-file> [options]
```

### Options
- `--destructive`: Enable destructive mode (backup and replace original files)
- `--dry-run`: Simulate without making changes
- `--verify`: After split or join, verify round-trip integrity in a temporary directory
- `--output <path>`: Specify explicit output path (overrides default naming)
- `--help`: Show usage information
- `--version`: Show version number

### Output Format
- **Success**: Print a summary of files created to stdout (one per line, prefixed with `Created: ` or `Backup: ` in destructive mode)
- **Dry run**: Print planned operations prefixed with `Would create: ` or `Would backup: `
- **Errors**: Print to stderr, prefixed with `Error: `
- **Exit codes**:
  - `0`: Success
  - `1`: General error (file not found, permission denied, etc.)
  - `2`: Validation error (malformed input, missing index markers, missing section files)

## Implementation Requirements

### Technology Stack
- **Language**: Python (3.9+)
- **Dependencies**: Minimize external dependencies. Standard library only is preferred. If needed, at most one lightweight external library (e.g., for CLI argument parsing if argparse is insufficient).
- **No LLM/AI**: All processing must be deterministic and rule-based

### Error Handling
- Handle malformed markdown gracefully
- Validate index file structure before join operation (check for marker comments, verify referenced files exist)
- Provide clear error messages for common issues:
  - Input file does not exist
  - Input file is not readable
  - Output path is not writable
  - Index file is missing required markers
  - Referenced section file not found (with filename)
  - No headers found in input file
  - Permission denied on read/write operations

### Testing Requirements
- Unit tests for header level detection (including edge cases: no headers, single `#`, multiple `#`)
- Unit tests for filename sanitization (unicode, special characters, empty results)
- Unit tests for description extraction (all priority levels)
- Round-trip integration tests: split then join produces byte-identical output for various inputs
- Tests for conflict resolution (existing files/folders)
- Tests for preamble handling
- Tests for front matter handling (including tests to ensure perfectly compatible split/join cycles without corruption)
- Tests for manual index reordering

## Future Considerations

### Potential Enhancements (Out of Scope for MVP)
- Custom naming patterns
- Section filtering (include/exclude specific sections)
- Markdown linting/formatting during split/join
- Support for other markup formats
- Configuration file support
- Git-aware mode (detect and preserve git line endings config)
- Watch mode (auto-split/join on file changes)
