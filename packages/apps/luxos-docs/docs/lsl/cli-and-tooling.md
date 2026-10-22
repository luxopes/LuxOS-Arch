# LSL command line and tooling

All subcommands of the `lsl` command (0.10.2), the offline manual, the terminal editor, colors
and updates. Library management (`install`, `search`, `list`, `check`, `origin`) is detailed
in [modules.md](modules.md#installing-libraries-from-the-registry).

## Usage summary (`lsl help`)

```text
lsl [SOURCE [ARG...]]                       compile and run a program (stdin when no SOURCE)
lsl compile [--unsafe] [--target NAME] SOURCE OUTPUT
lsl config ENTRY                            evaluate a configuration module graph
lsl install NAME | --config FILE | --tui    install per-user libraries
lsl list                                    installed libraries (bundled / user)
lsl search [QUERY]                          search the registry catalog
lsl check NAME                              is a library installed? (exit 0/1/2)
lsl man [--plain] [TOPIC]                   offline manual
lsl help [TOPIC]                            short help for a command, keyword, builtin or module
lsl about [NAME]                            about LSL / short description of a library
lsl --tui [FILE]                            terminal editor
lsl update [NAME]                           update LSL or a per-user library
lsl update [--check | --rollback] [--system] [--allow-downgrade]
lsl origin [NAME]                           registry URL / verify a library's SHA-256 and origin
lsl server [OPTIONS]                        static HTTP(S) file server
lsl sandbox [OPTIONS] SOURCE [ARG...]       run in a capability sandbox
lsl version                                 print the version (also lsl --version)
```

Options: `-h`, `--help`, `--version`; environment `NO_COLOR` disables colors.

## Running and compiling

- `lsl file.lsl args...` compiles in memory and runs. Arguments: `arg(1)`, `arg_count()`.
- `lsl compile SOURCE OUTPUT` creates a native statically linked ELF (static PIE, non-executable
  stack, no symbol table). Compilation does not run the program. The default is **checked**
  compilation, which rejects private `__lsl_*`, native and thread operations outside an
  `unsafe:` block (also in imported user modules).
- `--unsafe` enables the unsafe compiler mode explicitly (needed e.g. for the directive
  `# lsl: unchecked-intarray`). The low-level `lslc` is the explicit trust-core compiler.
- `--target NAME` cross-compiles: `linux-arm64`, `linux-riscv64`, `linux-arm`, `linux-x86`,
  `windows-x86_64`, `windows-arm64`, `macos-x86_64`, `macos-arm64`, `wasm32-wasi`,
  `wasm32-wasi-threads`, `baremetal-riscv64`.
- Exit status of `lsl FILE` is the program's status; an uncaught runtime error exits with 1 and
  prints `error[Kind]` with position and help to stderr.

```bash
lsl compile app.lsl app && ./app
lsl compile --target linux-arm64 app.lsl app-arm64
```

## help and man

```bash
lsl help              # usage summary
lsl help install      # help for a subcommand or topic (unknown topic: exit 1)
lsl man               # offline manual browser (TUI)
lsl man random        # one chapter; topic can be a unique part of the id
lsl man --plain reference   # plain text (automatic when piped)
lsl about             # what LSL is, version, website, license
lsl about random      # short description of a library
```

`lsl man` contains the same Markdown chapters as the website, bundled with the release (no
internet). In the browser: Enter opens a chapter, arrows/PgUp/PgDn scroll, `/` searches
(chapter list or text), `n` next match, Esc back, `q` quit.

Inside programs: `help()` prints the topic index; `help("print")`, `help("random")` or
`help(topic_variable)` print help for a command, keyword, builtin or module (works in a
standalone ELF too). It returns `None`; an unknown topic raises `HelpError`.

Help topics in 0.10.2 include: Bool, ByteArray, Dictionary, Error, Float, FloatArray, Int,
IntArray, List, RealArray, String, Tuple, about, abs, ai, appendfile, arg, arg_count, bigint,
break, capture, check, chr, class, clock, compile, config, continue, ctype, cuda, dedup, del,
exit, fd, for, function, gc, global, help, httpserver, if, input, install, json, last_error,
len, list, load, lock, loop, man, math, max, min, monotonic, ord, origin, os, print, printl,
printr, process, random, rang, range, readbytes, readfile, requests, return, run, safe,
sandbox, search, server, set, sorted, sqrt, sum, system, tensor, time, try, tui, type,
unsafe, update, version, while, writebytes, writefile.

## Interactive mode

`lsl` without a file on a terminal: syntax highlighting, history (up/down), Home/End, Tab = 4
spaces, auto-indent inside blocks (`...` prompt). A line `exit` or Ctrl-D compiles and runs the
collected program; Ctrl-C clears the line. From a pipe or heredoc everything until EOF is one
program.

## Terminal editor: lsl --tui

`lsl --tui [FILE]` opens a Vim-style editor with LSL syntax highlighting (files up to 4 MiB;
it never runs code or a shell – run with `lsl FILE` after saving).

| Mode | Keys |
|---|---|
| Normal | `h j k l`/arrows, `w`/`b` word, `0`/`$` line start/end, `gg`/`G` file start/end, PgUp/PgDn |
| Normal | `x` delete char, `dd` delete line, `yy` copy line, `p`/`P` paste below/above, `u` undo |
| Normal | `i`/`a`/`A`/`I` insert, `o`/`O` new line below/above, `/text` search, `n` next, `:` command |
| Commands | `:w [FILE]` save, `:q` quit (refuses unsaved), `:q!` quit without saving, `:wq` |
| Insert | text, Enter keeps indentation, Backspace joins lines, Tab = 4 spaces, Esc back to normal |

## Colors

Colors only on terminals. `NO_COLOR` wins over `FORCE_COLOR`; `FORCE_COLOR=1` forces colors into
pipes, `FORCE_COLOR=0` disables them; `TERM=dumb` and pipes get no ANSI sequences. IDEs that set
`NO_COLOR=1` must add colors themselves.

## Updating LSL

```bash
lsl update --check                                   # is a newer LSL available?
lsl update                                           # update a self-installed LSL
lsl update textkit                                   # update a per-user library
sudo /usr/local/bin/lsl update --system              # system installation in /usr/local
sudo /usr/local/bin/lsl update --system --rollback   # restore the previous version
```

The signed updater verifies the Ed25519 manifest signature, version, platform, size and SHA-256
before activation, installs the new generation next to the active one and keeps the previous
one for rollback. `--allow-downgrade` is a developer override.

**On LuxOS** LSL comes from the `lsl` package in `/usr/bin` and `/usr/lib/lsl`; update it with
`lux update` (system updates) instead of `lsl update --system`.

## lsl config and lsl sandbox

- `lsl config ENTRY` evaluates a validated LSL configuration graph (modules using `load config`)
  with time and resource limits and prints the merged configuration. See
  [stdlib-system.md](stdlib-system.md#config-and-lsl-config).
- `lsl sandbox [--profile strict|server] [--timeout S] [--memory BYTES] [--read PATH]
  [--write PATH] SOURCE [ARG...]` compiles and runs in a short-lived capability sandbox:
  `strict` (default) has a private network namespace, `server` shares the network; `--read`
  paths appear as `/input/N`, `--write` paths as `/output/N`; timeout 1..3600 s (default 30),
  memory 64 MiB..8 GiB (default 1 GiB). Requires the system sandbox tools and a systemd user
  session. Unsafe source is refused.

## Other tools in the LuxOS package

`lslc` (low-level trust-core compiler), `luxir` (LuxIR backend: code generation, built-in
assembler and linker for x86, x86_64, ARM, ARM64, RISC-V 64), `lsl-configure` (native
configuration evaluator generator), `lsl-cuda-worker` (CUDA worker process).
