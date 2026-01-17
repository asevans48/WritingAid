"""Markdown utilities for the text editor.

Provides bidirectional conversion between rich text display and Markdown storage.
"""

import re
from typing import Tuple, List
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

# Reverse mapping from prefix to style
PREFIX_TO_STYLE = {v.strip(): k for k, v in HEADING_PREFIXES.items()}


def markdown_to_display(markdown_text: str) -> str:
    """Convert Markdown text to display format.

    For the editor, we keep the Markdown visible so users can see/edit it.
    This function is a pass-through but could be extended for live preview.

    Args:
        markdown_text: Raw Markdown text

    Returns:
        Text suitable for display in editor
    """
    return markdown_text


def display_to_markdown(display_text: str) -> str:
    """Convert display text back to Markdown.

    Since we display Markdown directly, this is a pass-through.

    Args:
        display_text: Text from editor

    Returns:
        Markdown text for storage
    """
    return display_text


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


def markdown_to_html(markdown_text: str) -> str:
    """Convert Markdown to HTML for export.

    Args:
        markdown_text: Markdown formatted text

    Returns:
        HTML string
    """
    lines = markdown_text.split('\n')
    html_lines = []

    for line in lines:
        style, content = get_line_style(line)

        # Process inline formatting
        content = _process_inline_formatting(content)

        # Wrap in appropriate tags
        if style == MarkdownStyle.TITLE:
            html_lines.append(f"<h1>{content}</h1>")
        elif style == MarkdownStyle.HEADING_1:
            html_lines.append(f"<h2>{content}</h2>")
        elif style == MarkdownStyle.HEADING_2:
            html_lines.append(f"<h3>{content}</h3>")
        elif style == MarkdownStyle.HEADING_3:
            html_lines.append(f"<h4>{content}</h4>")
        elif style == MarkdownStyle.HEADING_4:
            html_lines.append(f"<h5>{content}</h5>")
        elif content.strip():
            html_lines.append(f"<p>{content}</p>")
        else:
            html_lines.append("<p></p>")

    return '\n'.join(html_lines)


def _process_inline_formatting(text: str) -> str:
    """Process inline Markdown formatting (bold, italic) to HTML.

    Args:
        text: Text with Markdown inline formatting

    Returns:
        Text with HTML formatting
    """
    # Bold italic first (***text***)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)

    # Bold (**text**)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Italic (*text* or _text_)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)

    return text


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
