# LSL (Lux Simple Lang) overview

LSL – **Lux Simple Lang** – is a small, readable, compiled programming language by the LuxOS
author. Source files are UTF-8 with the extension `.lsl`. The production compiler is
self-hosted (written in LSL) and produces native, statically linked executables; there is no
interpreter or virtual machine at run time. Website and downloads: <https://lsl.lux-ai.cz>.

This library describes **LSL 0.10.2**, the version packaged for LuxOS. Its content is
translated from the official LSL manual and function reference (LSL-Web 0.10.2) and from the
built-in `help()` texts of the 0.10.2 compiler. Places where the tested 0.10.2 compiler behaves
differently from the reference are marked **Note (0.10.2)**.

## LSL on LuxOS

| Item | Value |
|---|---|
| Package | `lsl` in the `[luxos-apps]` repository (`lux install lsl`) |
| Version | 0.10.2 (official binary release, `lsl-0.10.2-linux-x86_64.tar.gz`) |
| Commands | `/usr/bin/lsl`, `lslc` (low-level compiler), `luxir` (backend: assembler + linker), `lsl-configure`, `lsl-cuda-worker` |
| Bundled libraries | `/usr/lib/lsl/stdlib/*.lsl` (found relative to the `lsl` executable) |
| Per-user libraries | `~/.local/lib/lsl/stdlib/` (installed with `lsl install NAME`, no sudo) |
| Docs | `/usr/share/doc/lsl/README.md`, `RELEASE_NOTES.md`; offline manual `lsl man` |
| License | MIT (backend LuxIR derived from QBE, license in `/usr/share/licenses/lsl/`) |

On LuxOS the `lsl` package is updated by the system package manager (`lux update`). The
built-in self-updater (`lsl update`, `sudo /usr/local/bin/lsl update --system`) is meant for
installations made with the official installer under `/usr/local` or `~/.local`; on LuxOS
prefer `lux update`. `lsl update NAME` still updates per-user libraries.

LuxOS integrates LSL in its shell `lsh`: LSL statements can be typed directly at the shell
prompt (`print 6 * 7`), `lsl-session` opens an LSL session, and `./script.lsl` is run through
`lsl`. See [the LuxOS shell page](../luxos/shell.md).

## Running programs

```bash
lsl hello.lsl              # compile in memory and run immediately
lsl hello.lsl arg1 arg2    # program arguments: arg(1), arg(2)
lsl compile hello.lsl hello   # build a standalone native ELF
./hello                    # runs without LSL installed
lsl version                # prints e.g. 0.10.2 (same as lsl --version)
```

`hello.lsl`:

```lsl
print "Hello, world!"
```

Running `lsl FILE` compiles the whole file to machine code and runs it. `lsl compile` writes
an executable that no longer depends on LSL and can be copied to another Linux machine with
the same architecture. Since 0.10.2 the LuxIR backend has a built-in assembler and linker, so
GNU binutils are no longer needed to compile on Linux.

## Interactive mode, pipes and heredocs

`lsl` without arguments reads one program from stdin.

- On a terminal it shows a banner and the `>>>` prompt (with syntax highlighting, history,
  auto-indent; inside a block the prompt becomes `...`). Lines are collected, not executed one
  by one. A line containing only `exit`, or Ctrl-D, compiles and runs everything at once.
  Ctrl-C clears the current line.
- All lines form a single program, so variables from earlier lines are visible later.
- From a pipe or heredoc, input ends at EOF; no `exit` line is needed and no prompts are
  printed.

```bash
printf 'print 6 * 7\n' | lsl          # prints 42
lsl <<'EOF'
print "Result:", 100 + 200
EOF
```

The interactive `exit` terminator is not part of the language and is different from the
`exit(status)` function.

## Platforms and targets

The compiler runs on Linux x86_64, ARM64 and RISC-V 64, and since 0.10.1 natively on Windows
10/11 (x64, ARM64) and macOS (Apple Silicon, Intel). `lsl compile --target NAME` can produce:
`linux-arm64`, `linux-riscv64`, `linux-arm` (armv7 hard-float, 32-bit), `linux-x86` (i686),
`windows-x86_64`, `windows-arm64`, `macos-x86_64`, `macos-arm64`, `wasm32-wasi`,
`wasm32-wasi-threads` and `baremetal-riscv64`. LSL values stay 64-bit on 32-bit targets.
WebAssembly has no processes or sockets; the process sandbox is Linux-only.

## Language at a glance

```lsl
# comment
name = input "Name: "            # input always returns a String
age = Int(input("Age: "))
if age >= 18:
    printl "Hello {name}, you are an adult."
else:
    print "Hello", name
end

function square(x):
    return x * x
end

for i in rang(1, 4):
    print i, square(i)
end
call square(2)                   # a call used as a statement needs `call`
```

- One statement per line, no semicolons; `#` and `/* ... */` comments.
- Blocks start with a header (`if`, `for`, `function`, ...) with an optional `:` and end with
  a line containing `end`. Indentation is ignored (4 spaces recommended).
- Names are case sensitive.
- `^` is power, `~` is XOR / bitwise NOT, `//` is floor division.

## Where to go next

| Topic | Page |
|---|---|
| Lexical rules, variables, operators, strings, output | [syntax.md](syntax.md) |
| Types and collections (List, Dictionary, Set, arrays...) | [types-and-collections.md](types-and-collections.md) |
| if / for / while / loop | [control-flow.md](control-flow.md) |
| Functions, globals, classes, inheritance | [functions-and-classes.md](functions-and-classes.md) |
| `safe`, `try/else`, `Error`, `check`, `last_error` | [errors.md](errors.md) |
| `load`, module search, libraries and packages | [modules.md](modules.md) |
| Built-in functions | [builtins.md](builtins.md) |
| Standard library | [stdlib-core.md](stdlib-core.md), [stdlib-system.md](stdlib-system.md), [stdlib-network-ai.md](stdlib-network-ai.md), [stdlib-graphics-io.md](stdlib-graphics-io.md), [stdlib-compute.md](stdlib-compute.md) |
| Command line tools (`lsl compile`, `lsl install`, `lsl man`...) | [cli-and-tooling.md](cli-and-tooling.md) |
| Worked examples | [examples.md](examples.md) |
| Lux Code and LSL IDE | [lux-code.md](lux-code.md) |
