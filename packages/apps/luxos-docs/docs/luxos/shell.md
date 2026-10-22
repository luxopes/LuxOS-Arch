# Shell: lsh (Lux Shell), aliases and fastfetch

LuxOS users get **lsh** (Lux Shell, `/usr/bin/lsh`) as their login shell. lsh is a fork of
**GNU bash 5.3** (package `lsh`, GPL-3.0) – fully bash compatible – with a few LuxOS additions.
The installer creates users with `useradd -s /usr/bin/lsh`, and `luxos-shell` sets
`SHELL=/usr/bin/lsh` in `/etc/default/useradd` for new users. zsh stays available as an alternative.

## What lsh adds to bash

| Feature | Example |
|---|---|
| `about [shell\|os\|lsl]` builtin | overview of the shell, the system and LSL |
| LSL statements typed directly | `print 6 * 7`, `load time`, `x = 5` |
| LSL session memory | `lsl-session show`, `lsl-session clear` |
| run LSL scripts directly | `./script.lsl args…` (runs `lsl script.lsl args…`) |
| `pip install` outside a venv | works, with a warning; packages go to `~/.local` |

Everything else behaves exactly like bash 5.3. `lsh --version` prints
`lsh (Lux Shell) <version>, based on GNU bash 5.3…`; the variable `LSH_VERSION` holds the lsh version
(`BASH_VERSION` is kept for compatibility).

### about

```bash
about          # all sections
about shell    # what lsh adds
about os       # OS (PRETTY_NAME + ID_LIKE), kernel, host, uptime, memory, CPU, package count ("manage with lux"), desktop, terminal
about lsl      # LSL version, binary, "lsl man, lsl help", session; or "not installed (lux install lsl)"
```

Colours are off when output is not a terminal or `NO_COLOR` is set.

### LSL in the shell

Before the bash parser sees a line, lsh checks whether it is an LSL line:

- it starts with `print ` or `load `, or
- it is an assignment with spaces, `name = expression` (without spaces `x=5` stays a normal shell
  variable; `==` is not an assignment),
- and the first word is not a shell command/builtin/function, and `lsl` is installed.

Such a line is rewritten to `lsl-session run '<line>'`, so parentheses, quotes and `<` `>` work.
Successful `load …` and assignment lines are remembered in `$XDG_RUNTIME_DIR/lsh-lsl-<pid>.lsl` and
prepended to later LSL lines in the same shell; the file is removed when the shell exits.

```bash
load time
x = 5
print x * 2
lsl-session show     # remembered lines
lsl-session clear    # forget them
```

A command ending in `.lsl` (e.g. `./hello.lsl`) is executed as `lsl ./hello.lsl …` even without a
shebang; if `lsl` is missing, normal bash behaviour continues. For the language itself see
[LSL overview](../lsl/overview.md).

### pip outside a virtual environment

`/etc/lsh/lshrc` exports `PIP_BREAK_SYSTEM_PACKAGES=1` and wraps `pip`/`pip3`: `pip install` outside a
venv/conda prints

```
lsh: warning: installing Python packages outside a virtual environment
     they go to ~/.local; for projects prefer: python -m venv .venv
```

and (for non-root users) adds `--user` automatically. System files are not touched. `~/.local/bin`
is added to `PATH`.

## Configuration files

| File | Purpose |
|---|---|
| `/etc/lsh/lshrc` | system lsh config (read by every interactive lsh, including login shells) |
| `~/.lshrc` | your own settings (created from `/etc/skel/.lshrc`) |
| `~/.lsh_profile`, `~/.lsh_login`, `~/.lsh_logout` | lsh equivalents of the bash files |
| `~/.lsh_history` | history |
| `/usr/share/luxos/shell/bashrc` | common LuxOS shell setup (ble.sh, history, aliases, prompt, fastfetch) |
| `/usr/share/luxos/shell/aliases.sh` | aliases shared by bash and zsh |
| `/usr/share/luxos/shell/zshrc` | LuxOS zsh setup (`~/.zshrc` from skel sources it) |
| `~/.config/luxos/shell.conf` | switches: `LUXOS_BLESH=0` (no ble.sh), `LUXOS_FASTFETCH=0` (no greeting) |
| `~/.config/starship.toml` | own prompt (otherwise `/usr/share/luxos/shell/starship.toml`) |
| `/etc/profile.d/luxos.sh` | `XDG_CONFIG_DIRS`, `XDG_DATA_DIRS`, `PATH` additions (see [Configuration](configuration.md)) |

Unlike bash, an interactive **login** lsh (TTY, ssh) also reads the lshrc files.

## Interactive features

- **ble.sh** – autosuggestions and syntax highlighting (not on the Linux console `TERM=linux`); shows
  the exit code (`✘ N`) and run time (`⏱`) of commands that took ≥ 5 s.
- **starship** prompt in graphical terminals (single line, `❯`); simple `✦ dir $` prompt on TTYs.
- **fzf** key bindings/completion, **zoxide** (`z`), history 50 000 entries with timestamps,
  `autocd`, `globstar`, case-insensitive completion.
- **fastfetch** greeting only in the first terminal of a session.

## Aliases (aliases.sh)

| Alias | Command |
|---|---|
| `ls`, `ll`, `la`, `lt` | `eza` with icons/git (`ll` long, `la` all, `lt` tree depth 2); plain `ls --color` if eza is missing |
| `cat` | `bat --paging=never --style=plain` |
| `grep`, `diff`, `ip` | coloured output |
| `df`, `du`, `free` | human-readable sizes (`-h`) |
| `..`, `...`, `....` | go up 1/2/3 directories |
| `open` | `xdg-open` (macOS habit) |
| `pbcopy` / `pbpaste` | `xclip -selection clipboard` (copy / paste with `-o`) |
| `update` | `lux update` |
| `install` | `lux install` |
| `search` | `lux search` |

Environment: `EDITOR=nano` (unless set), `PAGER=less`, `LESS='-R -F -i'`, man pages through `bat`.

## pacman hint

There is no `pacman` command in LuxOS. Typing `pacman …` (or `pacman-*`) prints
`command not found` plus the matching `lux` command(s) from `/usr/lib/lux/pacman-hint` and returns 127,
e.g. `pacman -Syu` → `lux update`, `pacman -S x` → `lux install x`, `pacman -Rns x` → `lux remove x`,
`pacman -Ss x` → `lux search x`, `pacman -Qo f` → `lux owns f`, `pacman -Ql x` → `lux files x`,
`pacman -Qdt` → `lux list --orphans` / `lux autoremove`, `pacman -Sc` → `lux clean`. The hint never runs
anything. See [Package management](package-management.md).

## fastfetch

System config `/etc/xdg/luxos/fastfetch/config.jsonc` (found via `XDG_CONFIG_DIRS`; a personal
`~/.config/fastfetch/config.jsonc` wins). It shows the LuxOS logo (`/usr/share/luxos/fastfetch/logo.ans`,
Unicode block art), "LuxOS – SIMPLE · FAST · SECURE", OS with version, host, kernel, uptime, packages
counted as `(lux)` plus Flatpak/Snap/Nix if present, shell, **Desktop** (`LuxOS Desktop` instead of
Xfce), **Terminal** (`LuxOS Terminal` for xfce4-terminal, via `/usr/lib/luxos/fastfetch-terminal`),
CPU, GPU, memory, disk `/` and colours.
