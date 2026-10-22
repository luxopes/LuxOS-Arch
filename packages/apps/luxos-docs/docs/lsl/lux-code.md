# Lux Code and LSL IDE

Two development tools from the `[luxos-apps]` repository that build on LSL and the shared LuxAI
account: **Lux Code**, a terminal AI coding agent written in LSL, and **LSL IDE**, a graphical
editor for LSL. Sources: the Lux Code README and TOOLS.md (version 0.1.2) and the LSL IDE 1.0.0
README.

## Lux Code

| Item | Value |
|---|---|
| Package | `lux-code` 0.1.2 (`lux install lux-code`) |
| Command | `lux-code` (menu entry **Lux Code**); program in `/usr/lib/lux-code/lux-code` |
| Built from | LSL sources (`chat.lsl`), compiled to a native ELF with LSL 0.10.2 at package build time |
| Docs | `/usr/share/doc/lux-code/README.md`, `TOOLS.md`, `env.example` |
| User data | `$LUX_CODE_HOME`, on LuxOS `~/.local/share/lux-code` (an existing older `~/.local/state/lux-code` keeps being used) |
| Settings | `~/.config/lux-code/.env` (or `LUX_CODE_CONFIG`); environment variables take precedence |

Run `lux-code` in a project directory, or `lux-code --cwd /path/to/project`. The agent reads
only `AGENTS.md` directly in the working directory (not the home directory or parents). It can
read files, edit code, run checks and continue from the results; it keeps a plan for larger
tasks. Other options: `--plain` (line mode), `--prompt 'TEXT'` (one task), `--resume ID`.

### Sign-in

On LuxOS Lux Code uses the shared **LuxAI account**: when `~/.config/luxai/account.json` has a
session token, chat requests go to `https://lux-ai.cz/api/ide/chat/completions` with header
`X-Lux-Client: lux-code` and usage is billed to the account (models `flash` and `lite`). Without
the account file it uses an API key `LUX_AI_API` from `.env`. `LUX_CODE_AUTH=account|apikey|auto`
forces the method. On HTTP 401/403 it asks you to run `luxos-account login`; it only reads the
account file and never prints the token. See [the LuxAI account page](../luxos/luxai-account.md).

### Terminal UI

- `/` opens command suggestions (↑↓ select, Tab complete, Enter confirm, Esc hide).
- Enter sends, Alt+Enter inserts a newline; you can type and queue tasks while the agent works.
- Ctrl+C or Esc interrupts the running request or shell command; Ctrl+C on an empty line quits.
- Ctrl+V / Alt+V (or `/paste`) attaches an image from the clipboard (`xclip` on X11).
- F2 switches between changes and plan, F3 expands tool details, Ctrl+←/→ selects a changed
  file, Ctrl+↑/↓ scrolls the diff.

| Command | Purpose |
|---|---|
| `/tools [filter]` | tool catalog |
| `/model [name]` | choose a model from the API catalog |
| `/reasoning [auto\|none\|low\|medium\|high\|xhigh\|max]` | reasoning effort |
| `/new`, `/sessions`, `/resume [ID]`, `/rename NAME`, `/save`, `/export FILE.md` | sessions |
| `/compact` | summarize the context and archive the original |
| `/retry` | continue after an error or interruption |
| `/cd PATH` | change working directory and reload instructions |
| `/diff`, `/diff all`, `/undo` | changes made in this session / whole workspace; undo the last file edit |
| `/plan`, `/jobs`, `/context`, `/references`, `/lang cs\|en` | plan, background jobs, context info, reference library, UI language |
| `/permissions readonly\|ask\|full` | tool permission mode (saved in `$LUX_CODE_HOME/permissions.json`) |
| `/clear`, `/quit` | clear screen, save and quit |

Permission modes: `readonly` allows reading files and the web only; `ask` asks before each
other action; `full` runs everything without confirmation. This is a check inside the app, not
operating-system isolation – an approved shell command runs with the user's normal rights.

### Tools

113 tools; the API receives up to 64 definitions per request, specialized ones are found with
`tool_search` and run through `call_tool`. Areas: files (read with line numbers, exact edits,
diffs, undo, JSON, search, tree), development (bash without timeout, tests, git status/diff/
log/blame, explicit staging, new branches), background services with logs, web (search through
the LuxAI account – 20 queries/minute and 500/day – or own Tavily key, page extraction, HTTP),
Firefox debugging through `ff-rdp` (DOM, console, network, screenshots, clicks), desktop
(screenshots, windows, mouse, keys, clipboard via `xdotool`/`xclip`), Android via `adb`, and
agent tools (plan, ask user, project memory in `.lux-code/memory.md`, images).

### Reference library

On first interactive start Lux Code downloads references into `$LUX_CODE_HOME/references`
(including the official LSL manual for the installed compiler version). The model accesses them
with `reference_catalog`, `reference_search` and `reference_read`. The current Lux Code
development version also reads this offline LuxOS/LSL library from `/usr/share/luxos/docs`
(`LUX_CODE_DOCS_DIR`): `reference_search` searches it first and `reference_read` can return a
document by id (e.g. `luxos/package-management.md`) or one section by heading. The packaged
0.1.2 may not include this yet.

### Configuration variables

| Variable | Default / meaning |
|---|---|
| `LUX_CODE_CONFIG` | explicit path to the `.env` file |
| `LUX_AI_API` | API key (used when no LuxAI account is signed in) |
| `LUX_CODE_AUTH` | `auto`, `account` or `apikey` |
| `LUX_CODE_ACCOUNT_FILE` | `~/.config/luxai/account.json` |
| `LUX_AI_MODEL` | `flash` |
| `LUX_AI_ENDPOINT` | `https://api.lux-ai.cz/v1/chat/completions` |
| `LUX_AI_REASONING` | `low` (`auto` omits the parameter) |
| `LUX_CODE_SHELL` | `/bin/bash` |
| `LUX_CODE_HOME` | user data directory (see above) |
| `LUX_CODE_PLAIN` | `1` = line mode |
| `LUX_CODE_BROWSER_PORT` / `FF_RDP` | `6010` / `~/.local/bin/ff-rdp` |
| `LUX_CODE_RECONNECT` | `0` disables automatic retry on network errors |
| `LUX_CODE_REFERENCES` | `0` disables automatic reference download |

Sessions are stored in `$LUX_CODE_HOME/sessions` (directory 700, files 600); diagnostics in
`$LUX_CODE_HOME/artifacts/errors.log`.

## LSL IDE

| Item | Value |
|---|---|
| Package | `lsl-ide` 1.0.0 (`lux install lsl-ide`), depends on `python`, `pyside6`, `lsl` |
| Command | `lsl-ide [file.lsl \| folder]` |
| Settings | `~/.config/lsl-ide/lsl-ide.conf` |
| Own toolchain (optional) | `~/.local/share/lsl-ide/toolchain/lsl-VERSION/` (active via symlink `current`) |
| Cloud files cache | `~/.local/share/lsl-ide/cloud/<account>/` |

A Qt 6 development environment that uses the installed `lsl` for everything:

- **Editor:** LSL syntax highlighting, line numbers, auto-indent and automatic `end`, bracket
  matching, comment toggle (Ctrl+/), find/replace, tabs, 11 color themes (Neon default).
- **Errors:** background check by running `lsl compile` on a hidden copy about 0.7 s after
  typing (retried with `--unsafe` when needed); squiggles and a Problems panel with the
  compiler's code, message and `help:` hint. The compiler reports one error at a time.
- **Completion and symbols:** keywords, built-ins, local functions/classes, modules from
  `lsl list` and their functions; F12/Ctrl+click go to definition (also into stdlib), Ctrl+I
  symbol info, F1 manual.
- **Running:** F5 runs (also unsaved code) in a pseudo-terminal with stdin and colors, including
  `tui` programs; Shift+F5 with arguments; Ctrl+F5 compiles a binary; Shift+F6 stops. Programs
  run with an address-space limit (default half of RAM, max 2 GB) so runaway allocation ends
  with `MemoryError` instead of freezing the computer.
- **Libraries:** a manager over `lsl list`, the registry catalog, `lsl update NAME`,
  `lsl origin`, `lsl check` (Ctrl+Shift+P).
- **Manual:** offline `lsl man --plain` rendered as HTML.
- **LuxAI agent** (Ctrl+Shift+A): coding agent signed in with the LuxAI account (password or
  e-mail code); usage counts toward the account's monthly limit (Flash 50k / Lite 1M tokens
  according to the IDE README). Tools: read/write/edit project files, search, compiler check,
  run with timeout, manual search; writes and runs are confirmed unless disabled. Ctrl+Shift+E
  sends the selection to the agent.
- **LuxAI Cloud** (Ctrl+Shift+C): code stored with the LuxAI account (128 MB per account, files
  up to 4 MB), available on every computer with LSL IDE.
- UI language Czech or English (View → Language, `LSL_IDE_LANG=en`).

Key shortcuts: Ctrl+N/O/S new/open/save, Ctrl+Shift+O open folder, F7 check now, Ctrl+Space
completion, Ctrl+F/H/G find/replace/go to line, Alt+↑/↓ move line, Ctrl+Shift+D/K duplicate/
delete line, Alt+1/2/3 Output/Problems/Manual, F11 full screen, Ctrl+Shift+F11 editor only.
