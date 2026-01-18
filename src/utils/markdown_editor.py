"""Markdown utilities for the text editor.

Provides bidirectional conversion between rich text display and Markdown storage.
"""

import re
from typing import Tuple
from enum import Enum


class MarkdownStyle(Enum):
    """Markdown formatting styles."""
    NORMAL = "normal"
    TITLE = "title"  # #
    HEADING_1 = "h1"  # ##
    HEADING_2 = "h2"  # ###
    HEADING_3 = "h3"  # ####
    HEADING_4 = "h4"  # #####
    BOLD = "bold"  # **text**
    ITALIC = "italic"  # *text* or _text_
    BOLD_ITALIC = "bold_italic"  # ***text***


# Heading prefix mapping
HEADING_PREFIXES = {
    MarkdownStyle.TITLE: "# ",
    MarkdownStyle.HEADING_1: "## ",
    MarkdownStyle.HEADING_2: "### ",
    MarkdownStyle.HEADING_3: "#### ",
    MarkdownStyle.HEADING_4: "##### ",
}

def get_line_style(line: str) -> Tuple[MarkdownStyle, str]:
    """Determine the Markdown style of a line and extract content.

    Args:
        line: A single line of text

    Returns:
        Tuple of (style, content without prefix)
    """
    stripped = line.lstrip()

    # Check for headings (most specific first)
    if stripped.startswith("##### "):
        return MarkdownStyle.HEADING_4, stripped[6:]
    elif stripped.startswith("#### "):
        return MarkdownStyle.HEADING_3, stripped[5:]
    elif stripped.startswith("### "):
        return MarkdownStyle.HEADING_2, stripped[4:]
    elif stripped.startswith("## "):
        return MarkdownStyle.HEADING_1, stripped[3:]
    elif stripped.startswith("# "):
        return MarkdownStyle.TITLE, stripped[2:]

    return MarkdownStyle.NORMAL, line


def apply_heading_to_line(line: str, style: MarkdownStyle) -> str:
    """Apply a heading style to a line.

    Args:
        line: The line content (may already have a heading prefix)
        style: The style to apply

    Returns:
        Line with appropriate Markdown prefix
    """
    # First, remove any existing heading prefix
    _, content = get_line_style(line)
    content = content.strip()

    if style == MarkdownStyle.NORMAL:
        return content

    prefix = HEADING_PREFIXES.get(style, "")
    return prefix + content


def toggle_inline_style(text: str, style: MarkdownStyle) -> str:
    """Toggle an inline style (bold/italic) on text.

    Args:
        text: Selected text
        style: BOLD, ITALIC, or BOLD_ITALIC

    Returns:
        Text with style toggled
    """
    if style == MarkdownStyle.BOLD:
        # Check if already bold
        if text.startswith("**") and text.endswith("**") and len(text) > 4:
            return text[2:-2]  # Remove bold
        return f"**{text}**"

    elif style == MarkdownStyle.ITALIC:
        # Check if already italic (but not bold-italic)
        if text.startswith("*") and text.endswith("*") and not text.startswith("**"):
            return text[1:-1]  # Remove italic
        if text.startswith("_") and text.endswith("_"):
            return text[1:-1]
        return f"*{text}*"

    elif style == MarkdownStyle.BOLD_ITALIC:
        if text.startswith("***") and text.endswith("***") and len(text) > 6:
            return text[3:-3]
        return f"***{text}***"

    return text


def is_text_bold(text: str) -> bool:
    """Check if text is bold (surrounded by **)."""
    return text.startswith("**") and text.endswith("**") and len(text) > 4


def is_text_italic(text: str) -> bool:
    """Check if text is italic (surrounded by * or _)."""
    if text.startswith("**"):
        return False  # Bold, not italic
    return (text.startswith("*") and text.endswith("*") and len(text) > 2) or \
           (text.startswith("_") and text.endswith("_") and len(text) > 2)


def strip_markdown(markdown_text: str) -> str:
    """Strip all Markdown formatting, returning plain text.

    Args:
        markdown_text: Markdown formatted text

    Returns:
        Plain text without formatting
    """
    lines = []
    for line in markdown_text.split('\n'):
        _, content = get_line_style(line)
        # Remove inline formatting
        content = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', content)
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
        content = re.sub(r'\*(.+?)\*', r'\1', content)
        content = re.sub(r'_(.+?)_', r'\1', content)
        lines.append(content)

    return '\n'.join(lines)


# Style name mapping for UI
STYLE_NAMES = {
    "Normal": MarkdownStyle.NORMAL,
    "Title": MarkdownStyle.TITLE,
    "Heading 1": MarkdownStyle.HEADING_1,
    "Heading 2": MarkdownStyle.HEADING_2,
    "Heading 3": MarkdownStyle.HEADING_3,
    "Heading 4": MarkdownStyle.HEADING_4,
}

STYLE_TO_NAME = {v: k for k, v in STYLE_NAMES.items()}
