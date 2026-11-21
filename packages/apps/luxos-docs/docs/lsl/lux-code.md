# Lux Code and LSL IDE

Two development tools from the `[luxos-apps]` repository that build on LSL and the shared LuxAI
account: **Lux Code**, a terminal AI coding agent built on Oh My Pi, and **LSL IDE**, a graphical
editor for LSL. Sources: the Lux Code 0.6.5 README and the LSL IDE 1.0.0 README.

## Lux Code

**Lux Code** is an AI coding agent for the terminal. Tell it what you need and it works in your
project: it reads the code, edits files, runs commands and tests in the LuxOS shell `lsh` and
continues from the results. It uses the same assistant and the same account as LuxAI,
but works in the terminal and is aimed at programming. Since LuxOS 1.0.3 Lux Code (version 0.6) is
built on the open-source [Oh My Pi](https://omp.sh) (MIT) with a LuxOS layer: the LuxAI account and
models, `lsh` as the shell, the LuxOS manual and LuxOS rules.

### Install and run

```bash
lux install lux-code      # from the [luxos-apps] repository (needs bun from Arch, installed with it)
cd my-project
lux-code                  # interactive; lux-code -p "TASK" for a single task
```

| Item | Value |
|---|---|
| Package | `lux-code` 0.6.5 (replaces `lux-code-next` and the original Lux Code 0.1) |
| Command | `lux-code` (also a menu entry **Lux Code**); `lux-code-next` still works |
| Settings | `~/.config/lux-code/agent/config.yml` (also editable with `/settings`) |
| Project instructions | `AGENTS.md` directly in the working directory only (not parent folders) |
| Docs on disk | `/usr/share/doc/lux-code/README.md` |

Settings of the earlier test version in `~/.config/lux-code-next` are moved to
`~/.config/lux-code` on the first start. The original Lux Code 0.1 kept its data in
`~/.local/share/lux-code`; it is left untouched.

### Sign-in

On LuxOS, Lux Code uses the shared **LuxAI account** (see [LuxAI account](../luxos/luxai-account.md)); if
you are not signed in, run `/luxai login` or `luxos-account login`. Requests count toward the
account's monthly credits. Without the account Lux Code can use an API key (`LUX_AI_API`).

### Terminal interface

| Command | Purpose |
|---|---|
| `/help` | all commands |
| `/model flash`, `/model lite` | choose LuxAI Flash or Lite |
| `/usage` | LuxAI credits this month (bar, credits left, renewal date) |
| `/luxai`, `/luxai login` | account status and personalization; sign in |
| `/cd DIR` | change the working directory (`/cd` = home, `/cd -` = previous, Tab completes) |
| `/settings` | settings, e.g. turning off LuxAI personalization for Lux Code |
| `/hub` or Alt+A | what the subagents are doing |
| `/notifications on\|off` | desktop notifications |
| `/mouse off` | classic inline view with the terminal's own scrollback |

- The model's thinking is hidden behind one line; Ctrl+T shows it.
- The mouse works like in other coding agents: drag to select and copy, double click selects a
  word, triple click a line, the wheel and PgUp/PgDn scroll the conversation.
- Subagents run in the background (at most 3 at a time) while the main agent keeps working.
- Long sessions are summarized automatically before they reach the LuxAI request limits.

### Tools

The model gets a small core set (files, edits, search, shell commands in `lsh`, web) and loads the
rest when needed with `tool_search`: desktop and screenshots, clipboard, Android via `adb`, Firefox
debugging, system information, language servers and the offline LuxOS and LSL manual from
`/usr/share/luxos/docs`. Commands that LuxOS does differently are redirected: `pacman`, `yay` and
similar are refused with the matching `lux` command, and passwords are never piped to `sudo`.

Lux Code is not a sandbox: an approved shell command runs with your normal rights. For untrusted
code use the [Sandbox](../luxos/sandbox.md).

### Configuration

| Variable | Meaning |
|---|---|
| `LUX_AI_API` | API key (when no account is signed in) |
| `LUX_CODE_MOUSE` | `0` = classic inline view without mouse handling |
| `LUX_CODE_MAX_MESSAGES`, `LUX_CODE_MAX_BODY` | LuxAI request limits for summarizing (also `agent/luxai-limits.json`) |
| `LUX_CODE_NAME` | name of the settings folder (`~/.config/<name>`), default `lux-code` |

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
  compiler's code, message and `help:` hint (warnings too). The compiler reports one error at a
  time (verified with LSL 0.11.1). Because the check uses `lsl compile`, it does not show
  `W3001` for `# lsl: internal-abi` in 0.11.1 (only `lslc` reports it).
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
  e-mail code); usage counts toward the account's monthly credits (shown in the LuxAI account
  settings; currently 20 000 credits per month, shared by all models). Tools: read/write/edit project files, search, compiler check,
  run with timeout, manual search; writes and runs are confirmed unless disabled. Ctrl+Shift+E
  sends the selection to the agent.
- **LuxAI Cloud** (Ctrl+Shift+C): code stored with the LuxAI account (128 MB per account, files
  up to 4 MB), available on every computer with LSL IDE.
- UI language Czech or English (View → Language, `LSL_IDE_LANG=en`).

Key shortcuts: Ctrl+N/O/S new/open/save, Ctrl+Shift+O open folder, F7 check now, Ctrl+Space
completion, Ctrl+F/H/G find/replace/go to line, Alt+↑/↓ move line, Ctrl+Shift+D/K duplicate/
delete line, Alt+1/2/3 Output/Problems/Manual, F11 full screen, Ctrl+Shift+F11 editor only.
