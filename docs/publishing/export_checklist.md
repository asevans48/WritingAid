# Export checklist (piece 9.2)

What an exported manuscript must be, for each publishing route. Every line
with a test name is checked on a real exported file by
`tests/test_export_import.py`. Lines marked **by hand** need a person (or a
validator that is not installed) to check.

**Sources.** *Shunn sample*: William Shunn's sample novel manuscript
(https://www.shunn.net/format/novel/, the PDF linked there), which shows the
format but does not list rules. *Common standard*: widely used manuscript
conventions that the sample does not show and that could not be confirmed
from Shunn's pages in this session. An agent's or publisher's own
guidelines always override.

## Agent submission: standard manuscript format (Export ▸ Export Publisher Ready, .docx)

| # | Line | Source | Test |
|---|---|---|---|
| A1 | Title page: author's name at the top left | Shunn sample | `test_title_page` |
| A2 | Title page: title centered about halfway down, "A Novel by …" (or "A Novella by …") under it | Shunn sample | `test_title_page`, `test_novella_kind_on_the_title_page` |
| A3 | Title page: "about N words" near the bottom, rounded (nearest 1,000 from 10,000 words, nearest 100 below) | Shunn sample shows "about 80,000 words"; the rounding rule is common standard | `test_word_count_is_rounded` |
| A4 | Title page has no header and no page number | Shunn sample | `test_title_page` |
| A5 | Every text page: header at the right, "Surname / Title / N" | Shunn sample | `test_running_header_numbered_from_one` |
| A6 | Page numbers start at 1 on the first page of text | Shunn (stated on his novel page) | `test_running_header_numbered_from_one` |
| A7 | Times New Roman, 12 point | Common standard (Shunn's sample uses Courier; both are widely accepted) | `test_body_font_spacing_indent` |
| A8 | Double-spaced, no extra space between paragraphs | Shunn sample | `test_body_font_spacing_indent` |
| A9 | First line of each paragraph indented half an inch | Shunn sample (indent); half an inch is common standard | `test_body_font_spacing_indent` |
| A10 | Left-aligned, not justified | Shunn sample | `test_body_font_spacing_indent` |
| A11 | 1-inch margins | Common standard | `test_margins_one_inch_on_every_section` |
| A12 | Each chapter starts on a new page | Shunn (stated) | `test_each_chapter_starts_on_a_new_page_with_a_plain_centered_heading` |
| A13 | Chapter heading about a third of the way down, centered, in the body font: "Chapter N", then the title on its own line | Shunn sample | same test |
| A14 | Scene breaks: a centered "#" | Common standard (background.md); not shown in the sample | `test_scene_break_is_a_centered_hash` |
| A15 | Italics and bold come out as italics and bold, never as asterisks | Common standard (the sample underlines instead, the older convention) | `test_italics_are_italics_not_asterisks` |
| A16 | Curly quotes and dashes are kept as written | — | `test_italics_are_italics_not_asterisks` |
| A17 | Contact details (address, phone, email) under the name on the title page | Shunn sample | **Not possible yet**: the app holds no contact details. Add them by hand, or see the open question in 9.2's Outcome |
| A18 | The file opens in Word and Pages and looks right | — | **By hand** |

## Self-publishing: EPUB (Export ▸ Export for Kindle / Barnes & Noble)

| # | Line | Test |
|---|---|---|
| E1 | Title, author and language in the book's metadata | `test_epub_metadata_toc_and_a_stable_identifier` |
| E2 | An identifier that stays the same for the same title and author (so a store sees an update, not a new book) | same test |
| E3 | A table of contents with every chapter, by title | same test |
| E4 | Each chapter's file is well-formed XHTML: "&" and "<" in the prose are escaped | `test_epub_chapters_are_valid_xhtml_with_real_italics` |
| E5 | Italics and bold as `<em>` and `<strong>`, never asterisks | same test |
| E6 | Scene breaks as a centered "* * *" | same test |
| E7 | The file passes EPUBCheck and the store's previewer (Kindle Previewer, B&N's upload check) | **By hand**: neither tool is installed |
| E8 | Cover, front matter (copyright page) | **Not built**: not part of the export today |

## Other formats (Export as Word Document; the document formats)

| # | Line | Test |
|---|---|---|
| O1 | Word: italics and bold as runs, no asterisks | `test_word_rtf_text_keep_formatting_without_asterisks` |
| O2 | Plain text: the Markdown markers removed | same test |
| O3 | RTF: italics and bold as RTF codes | same test |

## Import from Word (Write ▸ Draft ▾ ▸ Import from Word)

| # | Line | Test |
|---|---|---|
| I1 | Italics, bold and headings survive the import *and the save* (they become the editor's Markdown) | `test_import_keeps_italics_bold_and_headings` |
| I2 | A chapter exported in standard format and imported again keeps every paragraph of prose | `test_round_trip_through_standard_format_keeps_the_prose` |
| I3 | Importing into a chapter with text asks first, and Cancel is the default | `test_import_asks_before_replacing_text_and_defaults_to_cancel` |
| I4 | The import is one undo step: Ctrl+Z puts the old text back | `test_importing_into_a_chapter_is_one_undo_step` |
| I5 | Font names, sizes and colours from Word are not kept (the editor's text has no place for them) | — (stated, by design) |

## The Export menu

| # | Line | Test |
|---|---|---|
| M1 | The route's format comes first: Publisher Ready for agent submission, Kindle for self-publishing | `test_the_route_s_format_comes_first` |
