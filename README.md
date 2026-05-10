# mdsplit

Large markdown documents waste LLM context — loading a 2000-line file to edit one section costs 2000 lines of tokens. **mdsplit** fixes this by splitting documents into section files behind a lightweight index (typically 1-3% of the original size). An LLM reads the index first, then loads only the sections it needs — using approximately 1/N of the tokens for a document with N sections.

Round-trips are byte-identical: split then join recovers the exact original file, preserving whitespace and line endings. Zero external dependencies — requires Python 3.9+ only.

## Quick Start

```
python mdsplit.py split design-doc.md          # → index + section files
python mdsplit.py join design-doc-index.md     # → original document back
```

## Synopsis

`python mdsplit.py split` *file* [*options*]

`python mdsplit.py join` *index-file* [*options*]

## How It Works

mdsplit detects the header structure of your document and splits at the top level:

- **Multiple `#` headers** → splits on `#` (one file per H1 section)
- **One `#` header + multiple `##` headers** → splits on `##` (the `#` becomes a preamble)

Everything inside a section — nested headers, code blocks, tables — stays in that section's file. No content is transformed.

Content before the first section header (intro paragraphs, YAML front matter) is saved as `_preamble.md`.

## Commands

### `split` *file*

Split *file* into an index and a folder of section files.

| Output | Description |
|--------|-------------|
| *name*`-index.md` | Table of contents with links and descriptions |
| *name*`/` | Folder with one `.md` file per section |

### `join` *index-file*

Reassemble sections listed in *index-file* into a single document.

| Output | Description |
|--------|-------------|
| *name*`-joined.md` | Reconstructed document |

Both commands are **non-destructive by default** — original files are never modified or deleted.

## Options

| Flag | Applies to | Description |
|------|------------|-------------|
| `--verify` | both | Verify byte-identical round-trip in a temp directory |
| `--dry-run` | both | Print what would be created, without writing files |
| `--destructive` | both | Back up originals (`.bak`), write outputs in their place |
| `--output` *path* | both | Custom output path (split: base name; join: file path) |
| `--help` | — | Show usage information |
| `--version` | — | Show version number |

## Examples

### Split a document

Before:
```
project/
└── design-doc.md          ← 3 sections, 450 lines
```

```
python mdsplit.py split design-doc.md
```

After:
```
project/
├── design-doc.md          ← original (preserved)
├── design-doc-index.md    ← table of contents (~25 lines)
└── design-doc/
    ├── _preamble.md       ← intro paragraph
    ├── architecture.md    ← # Architecture section
    └── api.md             ← # API section
```

### Rejoin sections

```
python mdsplit.py join design-doc-index.md
```

Produces `design-doc-joined.md` — byte-identical to the original `design-doc.md`. The index and section files are preserved.

### Verify round-trip integrity

```
python mdsplit.py split design-doc.md --verify
python mdsplit.py join design-doc-index.md --verify
```

### Preview without writing files

```
python mdsplit.py split design-doc.md --dry-run
```

### Overwrite the original (with backup)

```
python mdsplit.py join design-doc-index.md --destructive
```

Backs up `design-doc-index.md` → `.bak`, then writes `design-doc.md` in its place.

## Index Format

The index is a markdown table — readable by humans and LLMs alike:

```markdown
# design-doc

<!-- mdsplit-index -->
| Section | Description |
|---------|-------------|
| [Preamble](design-doc/_preamble.md) | Preamble |
| [Architecture](design-doc/architecture.md) | The system uses a layered design. |
| [API](design-doc/api.md) | REST endpoints below. |
<!-- /mdsplit-index -->
```

Hidden metadata (`blanks`, `trailing-newline`) is stored in HTML comments to ensure byte-identical round-trips. You can reorder or remove entries in the index — join respects whatever order you set.

## Features

- **Byte-identical round-trips** — split then join recovers the exact original
- **Whitespace preservation** — blank lines between sections and trailing newlines preserved via metadata
- **YAML front matter** — preserved verbatim in the preamble
- **Line endings** — CRLF/LF auto-detected and preserved
- **Zero dependencies** — Python 3.9+ stdlib only

## Running Tests

```
python -m unittest discover tests/ -v
```

## License

MIT
