# Lux Code – terminal AI coding agent

**Lux Code** is an AI coding agent for the terminal. Tell it what you need and it works in your
project: it reads the code, edits files, runs commands and tests in the LuxOS shell `lsh` and
continues from the results. It uses the same assistant and the same account as [LuxAI](luxai.html),
but works in the terminal and is aimed at programming. Since LuxOS 1.0.3 Lux Code (version 0.6) is
built on the open-source [Oh My Pi](https://omp.sh) (MIT) with a LuxOS layer: the LuxAI account and
models, `lsh` as the shell, the LuxOS manual and LuxOS rules.

## Install and run

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

## Sign-in

On LuxOS, Lux Code uses the shared **LuxAI account** (see [LuxAI account](luxai-account.html)); if
you are not signed in, run `/luxai login` or `luxos-account login`. Requests count toward the
account's monthly credits. Without the account Lux Code can use an API key (`LUX_AI_API`).

## Terminal interface

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

## Tools

The model gets a small core set (files, edits, search, shell commands in `lsh`, web) and loads the
rest when needed with `tool_search`: desktop and screenshots, clipboard, Android via `adb`, Firefox
debugging, system information, language servers and the offline LuxOS and LSL manual from
`/usr/share/luxos/docs`. Commands that LuxOS does differently are redirected: `pacman`, `yay` and
similar are refused with the matching `lux` command, and passwords are never piped to `sudo`.

Lux Code is not a sandbox: an approved shell command runs with your normal rights. For untrusted
code use the [Sandbox](sandbox.html).

## Configuration

| Variable | Meaning |
|---|---|
| `LUX_AI_API` | API key (when no account is signed in) |
| `LUX_CODE_MOUSE` | `0` = classic inline view without mouse handling |
| `LUX_CODE_MAX_MESSAGES`, `LUX_CODE_MAX_BODY` | LuxAI request limits for summarizing (also `agent/luxai-limits.json`) |
| `LUX_CODE_NAME` | name of the settings folder (`~/.config/<name>`), default `lux-code` |

## See also

- [Lux Code and LSL IDE](../lsl/lux-code.html) – full reference including LSL IDE
- [LuxAI](luxai.html), [LuxAI account](luxai-account.html)
- [LSL overview](../lsl/overview.html)
