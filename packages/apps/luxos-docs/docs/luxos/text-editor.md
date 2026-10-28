# Text Editor (luxos-text)

**Text Editor** (Czech: *Textový editor*, command `luxos-text`, package `luxos-text`) is the default
text and code editor of LuxOS since 1.0. It replaces Mousepad: a small C program on GTK 3 and
GtkSourceView 4 (the same editing engine as Mousepad), so it starts faster and uses less memory, and it
adds a macOS-style window with a folder sidebar, a syntax selector, a document outline and a status bar
with counts, encoding and line endings. Open it from Launchpad, the Dock, Search ("Text Editor",
"Textový editor", "notepad"…), by double-clicking a text file in Files, or with *Open With › Text Editor*.

## The window

- **Title bar**: the window buttons, the **sidebar button**, the file name (with "— Edited" when there are
  unsaved changes) and the folder below it, the **syntax pill** ("Plain Text", "Markdown", "Python"…), the
  **(i)** button and the **⋯** menu.
- **Syntax pill**: the language is detected from the file name, the first line (`#!/usr/bin/env python3`,
  `#!/bin/bash`, `#!/usr/bin/lsh`, `#!/usr/bin/env lsl`) and the content type. Click the pill to choose
  another language (type to filter, Enter picks the first); a manual choice is kept until the tab is closed.
  LSL files (`*.lsl`) are highlighted too.
- **(i) Document Info** (Ctrl+I): path, size on disk, encoding, line endings, syntax, created and
  modified time.
- **Navigation bar** under the title bar: **‹ ›** jump to the previous/next item of the outline, and the
  outline menu shows the heading or function where the cursor is – Markdown headings (`#`, `##`,
  underlined `===`/`---`), Python/LSL/Ruby `def`/`function`/`class`, C/C++ function definitions, shell
  functions, JavaScript/TypeScript functions and classes, Rust, Go, Java, C#, Kotlin, PHP, Lua, Perl,
  INI/desktop/TOML sections, Makefile targets, LaTeX sections, CSS selectors, YAML top-level keys and
  HTML headings. Click it for the whole outline.
- **Editor**: line numbers, highlighted current line, matching brackets, automatic indentation,
  soft wrap (on by default), smart Home/End. Indentation follows the file: tabs if most indented lines
  start with a tab, otherwise 4 spaces. *Invisible Characters* in the ⋯ menu shows line ends (↵), tabs,
  non-breaking spaces and trailing spaces.
- **Status bar**: Lines, Characters (without line ends), Words, cursor position (line:column – click for
  Go to Line), size in bytes as it will be saved (encoding, BOM and line ends included), the **encoding**
  and **line endings** selectors.
- **Light and dark**: follows the system appearance (Control Center, `luxos-appearance`) immediately;
  the colours are LuxOS's own (`luxos-light`, `luxos-dark` GtkSourceView styles).

## Files, folders and tabs

- Every `luxos-text` call opens a **new window** in the running editor (one process for all windows,
  like TextEdit); several files in one call open as **tabs** of that window. A file that is already
  open is just shown. `luxos-text FOLDER` opens the folder in the sidebar; `luxos-text +42 FILE` jumps
  to line 42. A file that does not exist yet is created on the first save.
- **Sidebar** (F9 or the sidebar button): the folder as a tree – folders first, sorted like Files,
  hidden and backup files left out, icons by file type. The open file is highlighted and its folders are
  expanded. A click opens a file (in the same window, as a tab). The tree updates itself when files
  change on disk. **+** at the bottom creates a new file (opened right away) or folder in the selected
  folder. Without an opened folder the sidebar shows the folder of the current file.
- **Open Recent** in the ⋯ menu lists the last 15 files (with *Clear Menu*).
- Drag files from Files onto the text to open them (a folder opens in the sidebar).
- **Unsaved changes**: closing a tab or window asks *Save*, *Don't Save* or *Cancel*.
- **Changed on disk**: when another program changes or deletes the open file, a bar above the text
  offers *Reload* or *Ignore* (it also checks when the window gets focus again).

## Encodings and line endings

The editor detects the encoding when opening and **keeps it when saving**, together with the line endings:

- UTF-8 (with or without BOM), UTF-16 LE/BE (with a BOM, or detected from zero bytes without one).
- Other files: Central European Windows-1250 or ISO 8859-2, Western Windows-1252, Cyrillic
  Windows-1251 – chosen by which one gives sensible text, with your language deciding a tie (Czech,
  Slovak, Polish and Hungarian prefer Windows-1250, Ukrainian Windows-1251).
- Line endings LF, CRLF (Windows) or CR – the most common one in the file is used for the whole file.
- Binary files are not opened.

The **encoding selector** in the status bar offers also ISO 8859-1/15, KOI8-U, Greek, Turkish, Baltic,
Shift JIS, GB 18030 and EUC-KR. For an unchanged file it asks **Reinterpret** (read the file again in
that encoding – when it was detected wrongly) or **Convert** (keep the text, save it in the new
encoding). If the text has characters the encoding cannot store, saving offers *Save as UTF-8*.
The **line endings selector** (LF / CRLF / CR) converts the document on the next save.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+N / Ctrl+T | New window / new tab |
| Ctrl+O / Ctrl+Shift+O | Open file(s) / open folder in the sidebar |
| Ctrl+S / Ctrl+Shift+S | Save / Save As |
| Ctrl+W / Ctrl+Q | Close tab (the last tab closes the window) / quit |
| Ctrl+F | Find (typing searches, Enter = next, Shift+Enter = previous, Esc closes) |
| Ctrl+H | Find and Replace (press Ctrl+H again to jump to the Replace field) |
| Ctrl+G, F3 / Ctrl+Shift+G, Shift+F3 | Next / previous match |
| Alt+C, Alt+W, Alt+R | Match case, whole words, regular expression |
| Ctrl+L | Go to line (`42` or `42:7` for line and column) |
| Ctrl+Z / Ctrl+Shift+Z, Ctrl+Y | Undo / redo |
| Ctrl+Plus, Ctrl+Minus, Ctrl+0, Ctrl+scroll | Bigger / smaller / default text size |
| Ctrl+I | Document info |
| F9 | Show or hide the sidebar |
| Ctrl+PageUp / Ctrl+PageDown | Previous / next tab |

Find shows "2 of 7" and highlights all matches. With *Regular Expression*, the replacement can use
`\0` (whole match) and `\1`…`\9` (groups). *Replace* replaces the selected match and goes to the next
one, *Replace All* reports how many were replaced; Ctrl+Z undoes it in one step.

## Settings and files

- `~/.config/luxos/text-editor.conf` – `[editor]` `font-size` (default 11 pt, monospace font JetBrains
  Mono without ligatures), `wrap`, `invisibles`, `line-numbers`; `[window]` size of the last closed
  window and sidebar width; `[recent]` `files`.
- Styles and LSL highlighting: `/usr/share/gtksourceview-4/styles/luxos-{light,dark}.xml` and
  `/usr/share/gtksourceview-4/language-specs/lsl.lang` (other GtkSourceView editors can use them too).
- Translations: `/usr/share/luxos/i18n/<language>.tsv` (all 13 LuxOS languages).

## Default editor and Mousepad

- `/etc/xdg/luxos/mimeapps.list` (package `luxos-desktop`) makes Text Editor the default for
  `text/plain` and the common source and data types (Markdown, Python, C/C++, shell, JSON, XML, YAML,
  TOML, CSS, JavaScript, logs, patches…). HTML and SVG stay with the web browser. Your own choice in
  *Open With › Other Application* (`~/.config/mimeapps.list`) always wins.
- New users get Text Editor in the Dock and in the LuxOS menu favourites. On the first login after the
  update, older profiles are switched once (`luxos-session`, marker `~/.config/luxos/text-editor-migrated`):
  the Mousepad Dock icon and menu favourite become Text Editor, and Mousepad entries in
  `~/.config/mimeapps.list` become `luxos-text.desktop`. Profiles whose Dock has no Text Editor get it
  added once after Terminal (marker `~/.config/luxos/text-editor-dock`); if you remove it from the Dock,
  it stays removed.
- The icon is the LuxOS notes icon `luxos-notes` (package `luxos-branding`).
- Mousepad is not part of LuxOS 1.0. After the update to 1.0, a step of `lux update`
  (`/usr/lib/lux/after-update.d/60-luxos-text`) removes it. The command `mousepad` still works and
  opens Text Editor (`/usr/local/bin/mousepad`), so custom keyboard shortcuts and scripts keep working.

## Speed and memory

Measured under Xvfb against Mousepad 0.7 (time from start to the first painted window, median of 9
runs, the same GtkSourceView 4):

| | Text Editor | Mousepad |
|---|---|---|
| small file (3 kB) | 164 ms, PSS 19 MB | 214 ms, PSS 27 MB |
| 1 MB Python file | 203 ms, PSS 35 MB | 240 ms, PSS 43 MB |

A new window in the running editor (`luxos-text FILE` again) appears in about 40 ms.

Counting and the outline run after the window is drawn (1 MB: about 9 ms, repeated at most every
0.4 s while typing in large files). The same minimal prototype (a window with GtkSourceView and a file) took
270 ms and 52 MB in Python (PyGObject) but 160 ms and 34 MB in C, so the editor is written in C.
