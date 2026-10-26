# Lux Code – terminal AI coding agent

**Lux Code** is an AI coding agent for the terminal. It is written in [LSL](../lsl/overview.html),
the LuxOS programming language, and compiled to a native program. It reads your project, edits
files, runs commands and tests, and continues from the results. It uses the same assistant and the
same account as [LuxAI](luxai.html), but works in the terminal and is aimed at programming.

## Install and run

```bash
lux install lux-code      # from the [luxos-apps] repository
cd my-project
lux-code                  # or: lux-code --cwd /path/to/project
```

Other options: `--plain` (line mode), `--prompt 'TEXT'` (one task), `--resume ID` (continue a
saved session). The agent reads project instructions only from an `AGENTS.md` file directly in the
working directory (not from parent folders or your home folder).

| Item | Value |
|---|---|
| Package | `lux-code` 0.1.2 |
| Command | `lux-code` (also a menu entry **Lux Code**) |
| Docs on disk | `/usr/share/doc/lux-code/README.md`, `TOOLS.md` |
| Settings | `~/.config/lux-code/.env`; environment variables take precedence |
| Sessions | `~/.local/share/lux-code/sessions` (directory 700, files 600) |

## Sign-in

On LuxOS, Lux Code uses the shared **LuxAI account** (see [LuxAI account](luxai-account.html)).
When `~/.config/luxai/account.json` exists, requests go to the LuxAI service, usage counts toward the
account's monthly limit, and the models are `flash` and `lite`. If you are not signed in, run
`luxos-account login`. Without the account file Lux Code can use an API key (`LUX_AI_API`). The
method can be forced with `LUX_CODE_AUTH=account|apikey|auto`. Lux Code only reads the account file
and never prints the token.

## Terminal interface

- `/` shows command suggestions. Enter sends, Alt+Enter adds a new line, and you can queue new tasks
  while the agent is working.
- Ctrl+C or Esc interrupts the running request or command; Ctrl+C on an empty line quits.
- Ctrl+V (or `/paste`) attaches an image from the clipboard.
- F2 switches between changes and plan, F3 expands tool details.

| Command | Purpose |
|---|---|
| `/tools [filter]` | tool catalog |
| `/model [name]` | choose a model |
| `/reasoning [auto\|none\|low\|medium\|high\|xhigh\|max]` | reasoning effort |
| `/new`, `/sessions`, `/resume [ID]`, `/rename NAME`, `/save`, `/export FILE.md` | sessions |
| `/compact` | summarize the context and archive the original |
| `/retry` | continue after an error or interruption |
| `/cd PATH` | change the working directory |
| `/diff`, `/diff all`, `/undo` | changes made in the session or workspace; undo the last file edit |
| `/plan`, `/jobs`, `/context`, `/references`, `/lang cs\|en` | plan, background jobs, context, reference library, UI language |
| `/permissions readonly\|ask\|full` | permission mode |
| `/clear`, `/quit` | clear the screen, save and quit |

## Permissions

`readonly` allows only reading files and the web; `ask` asks before every other action; `full` runs
everything without asking. This is a check inside the application, not operating-system isolation:
an approved shell command runs with your normal rights. For untrusted code use the
[Sandbox](sandbox.html).

## Tools

Lux Code has 113 tools; the model receives up to 64 definitions per request and finds specialised
ones with `tool_search`. The main areas are:

- **files** – read with line numbers, exact edits, diffs, undo, JSON, search, directory tree;
- **development** – shell commands, tests, git status/diff/log/blame, explicit staging, new
  branches;
- **background services** with logs;
- **web** – search through the LuxAI account (20 queries a minute, 500 a day) or your own Tavily key,
  page extraction, HTTP requests;
- **Firefox debugging** (DOM, console, network, screenshots, clicks), **desktop** (screenshots,
  windows, mouse, keys, clipboard) and **Android** via `adb`;
- **agent tools** – a plan, asking the user, project memory in `.lux-code/memory.md`, images.

## Reference library

On the first interactive start Lux Code downloads reference material, including the official LSL
manual for the installed compiler, and the model reads it with `reference_search` and
`reference_read`. The development version also uses the offline LuxOS and LSL manual from
`/usr/share/luxos/docs` (the same pages as this site).

## Configuration

| Variable | Meaning |
|---|---|
| `LUX_CODE_CONFIG` | path to the `.env` file |
| `LUX_AI_API` | API key (when no account is signed in) |
| `LUX_CODE_AUTH` | `auto`, `account` or `apikey` |
| `LUX_AI_MODEL` | model, default `flash` |
| `LUX_AI_REASONING` | default `low` (`auto` omits it) |
| `LUX_CODE_SHELL` | shell for commands, default `/bin/bash` |
| `LUX_CODE_HOME` | data directory |
| `LUX_CODE_PLAIN` | `1` = line mode |
| `LUX_CODE_RECONNECT` | `0` turns off retry on network errors |
| `LUX_CODE_REFERENCES` | `0` turns off the reference download |

## See also

- [Lux Code and LSL IDE](../lsl/lux-code.html) – full reference including LSL IDE
- [LuxAI](luxai.html), [LuxAI account](luxai-account.html)
- [LSL overview](../lsl/overview.html)
