# Obsidian Flavored Markdown (OFM) Reference

Create and edit valid Obsidian Flavored Markdown.

## Internal Links (Wikilinks)
- `[[Note Name]]` - Link to note
- `[[Note Name|Display Text]]` - Custom display text
- `[[Note Name#Heading]]` - Link to heading
- `[[Note Name#^block-id]]` - Link to block

## Embeds
- `![[Note Name]]` - Embed full note
- `![[image.png]]` - Embed image
- `![[image.png|300]]` - Embed image with width

## Callouts
```markdown
> [!note]
> Basic callout.

> [!tip]
> A tip for the user.
```
Types: `note`, `tip`, `warning`, `info`, `example`, `quote`, `bug`, `danger`, `success`, `failure`, `question`, `abstract`, `todo`.

## Properties (Frontmatter)
```yaml
---
title: My Note
tags:
  - project
  - active
---
```
Manage frontmatter by reading the note and patching the YAML block between the two `---` fences. For tag edits, prefer `scripts/tag_manager.py` which parses and rewrites frontmatter safely.
