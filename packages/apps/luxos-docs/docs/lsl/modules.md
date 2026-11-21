# LSL modules, libraries and packages

How `load` works, where modules are searched, which libraries are bundled with LSL 0.11.1,
system bindings that may call C, and how to install per-user libraries from the LSL registry.

## load syntax

```lsl
load json                     # members as json.encode(...)
load tensor as t              # alias: t.from_values(...)
load os, time                 # several modules (max 32) in one line
load time, os as a            # shared alias: a.monotonic() and a.which(...)
from helpers load area        # import a single symbol
from helpers load area as surface
from helpers load area, perimeter as p   # several symbols (since 0.10.10)
```

- Each `.lsl` file is a module; its public variables, functions and classes are available under
  the prefix `name.`.
- With a shared alias, a member is looked up in the listed modules in order and the first module
  that exports it wins; if none does, the error points at the first module.
- Imports are **static**: everything is resolved at compile time and linked into the program.
  No module loader runs at run time, so a compiled ELF contains all code it needs. Scripts run
  with `lsl file.lsl` pick up changed libraries on the next run; standalone binaries must be
  recompiled.
- Module symbols get a deterministic namespace prefix. Classes marked `ctype Private` are not
  reachable from outside; public classes can be constructed directly.

- `from MODULE load NAME` checks the name at the import: a module without that function, class
  or global is error **E3003** (since 0.10.10), e.g. `from lux load l` (the `lux` module has no
  `l`).

## Search order

`load foo.bar` looks for `foo/bar.lsl` in this order:

1. bundled/compiler-internal modules (`<prefix>/lib/lsl/stdlib/`, `/usr/lib/lsl/stdlib` on
   LuxOS),
2. system bindings (since 0.11.0): each `--system-bindings DIR` in order, then
   `<prefix>/lib/lsl/system/` (`/usr/lib/lsl/system` on LuxOS),
3. relative to the importing source file,
4. per-user libraries `~/.local/lib/lsl/stdlib/`.

Bundled modules **cannot be shadowed** by a local or per-user file of the same name, and a
system binding wins over a same-named file next to the program. Exception
(since 0.9.1): `load ai` uses a per-user `aikit.lsl` if it is newer than the bundled `ai`.

A missing library is error **E3001** with the name and the exact import location (also for
imports inside another library); the message suggests checking the local file and
`lsl search NAME` / `lsl install NAME`. Nothing is downloaded automatically. A missing bundled
module means a damaged LSL installation. An existing but unreadable module is **E3002**.

## Bundled libraries in 0.11.1

Listed by `lsl list` as `bundled` (descriptions from `lsl about NAME`):

| Module | Purpose |
|---|---|
| `ai` | OpenAI-compatible chat client with tools (function calling), live SSE streaming, structured errors and retries |
| `bigint` | arbitrary-precision signed integers (`BigInt`) |
| `cairo` | 2D drawing with Cairo in GTK draw handlers or into PNG images (gnu) |
| `config` | helpers for declarative configuration modules evaluated by `lsl config` |
| `configure` | generates the native configuration evaluator wrapper (internal, used by `lsl-configure`) |
| `crypto` | system OpenSSL hashes, HMAC, EC P-256 keys, ECDSA signatures, self-signed certificates (gnu) |
| `cuda` | optional NVIDIA CUDA backend in a separate worker process |
| `env` | environment variables and `.env` files |
| `fd` | raw file-descriptor I/O for devices, sockets, ioctl/mmap, bounded procfs/sysfs reads |
| `gio` | D-Bus over GIO: method calls, properties, signals, name watching and ownership (gnu) |
| `glib` | GLib main loop, timers, UNIX signals, process spawning, GObject signals (gnu) |
| `gtk` | GTK 3 windows, widgets and signal handlers over the GLib main loop (gnu) |
| `http` | HTTP(S) client (dictionary results) |
| `httpserver` | bounded HTTP/1.1 server and static files (also behind `lsl server`) |
| `json` | JSON encoder/decoder (4 MiB input limit, strict errors) |
| `lconf` | strict dependency-manifest codec (`config.lconf`) for `.lux` package archives |
| `lux` | core module with LSL version metadata (`lux.version`) and small shared helpers |
| `luxos` | declarative system configuration engine for LuxOS |
| `math` | mathematics and statistics |
| `mdns` | DNS-SD browse and announce over Avahi D-Bus with a raw mDNS fallback (gnu) |
| `native` | restricted fork-isolated ABI for self-contained native kernels |
| `net` | TCP and UDP sockets with timeouts, IPv6 link-local, UDP multicast, interface addresses (gnu) |
| `os` | run programs via direct `execve` with argv, PATH lookup; never a shell |
| `pango` | text layout with system fonts, wrapping, ellipsis and markup over cairo (gnu) |
| `plugin` | process plugin ABI v1 (JSON on stdin/stdout) |
| `process` | structured process helpers (separate stdout/stderr, stdin, streaming) |
| `random` | Python-style pseudo-random numbers (MT19937 `Random(seed)`, `SystemRandom`) |
| `requests` | Python-style HTTP client with `Response` objects |
| `sandbox` | capability-oriented process sandbox used by `lsl sandbox` |
| `system` | imperative LuxOS/Debian administration helpers (packages, services, users, files) |
| `tensor` | dense CPU tensors over FloatArray with optional CUDA dispatch |
| `time` | wall clock, monotonic timing, sleep, UTC formatting |
| `tls` | TLS 1.2/1.3 over system OpenSSL with key pinning, mTLS, ALPN, cipher control (gnu) |
| `tui` | full-screen terminal toolkit (cbreak, alternate screen, key decoding) |
| `unixsock` | Unix-domain sockets with file-descriptor passing |

"(gnu)" marks modules that need `--target linux-x86_64-gnu` (see
[cli-and-tooling.md](cli-and-tooling.md#running-and-compiling)); since 0.10.12 `lsl install`
refuses the name of a bundled module.

Optional registry packages (install with `lsl install NAME`) include `display` (X11 /
framebuffer / DRM output), `gfx` (2D raster graphics), `ui` (widgets), `css` (styles),
`input` (evdev keyboard/pointer), `x11`, `term` (raw terminal control), `shell` (explicit
`/bin/sh -c` runner), `sqlite` (SQLite through the `sqlite3` CLI) and `aikit` (standalone
updatable AI library). Run `lsl search` for the current catalog.

API details: [stdlib-core.md](stdlib-core.md), [stdlib-system.md](stdlib-system.md),
[stdlib-network-ai.md](stdlib-network-ai.md), [stdlib-graphics-io.md](stdlib-graphics-io.md),
[stdlib-compute.md](stdlib-compute.md).

## System bindings

Since 0.11.0 a module that calls C (a binding shipped by the distribution) belongs in a system
bindings directory: `<prefix>/lib/lsl/system/` (`/usr/lib/lsl/system/` on LuxOS) or a directory
passed with `--system-bindings DIR` to `lsl compile` or `lslc` (repeatable). Such a module is
trusted like the bundled stdlib: it may call C (`__lsl_qbe_*`, `__lsl_symbol`) even when a
normal program loads it with `load NAME`, it needs no `# lsl: internal-abi` header and it runs
in the normal ABI. The same code in a file next to the program is refused ("unsafe operation
outside an unsafe block"). C calls link only for `--target linux-x86_64-gnu`.

```bash
# sys/demo_bind.lsl:  function pid(): return __lsl_qbe_call0(__lsl_symbol("getpid")) > 0 ...
lsl compile --target linux-x86_64-gnu --system-bindings sys app/main.lsl app/main
```

LuxOS installs its bindings there: `luxos_*` modules (`luxos_gtk`, `luxos_glib`, `luxos_gio`,
`luxos_sys`, ...) from `luxos-desktop` and `luxui` from `luxos-sdk`. Write applications without
`# lsl: internal-abi`: outside the LSL sources and these directories it gives warning `W3001`,
and in that raw ABI Int 0 and `None` are the same word (details and the 0.11.1 gaps in
[cli-and-tooling.md](cli-and-tooling.md#lslc)).

## Installing libraries from the registry

```bash
lsl search                 # whole catalog
lsl search text            # search names and descriptions (case-insensitive)
lsl install textkit        # download, verify SHA-256, compile-check, install atomically
lsl install --config libs.conf   # install names from an LF-separated file
lsl install --tui          # interactive catalog
lsl update textkit         # update one per-user library
lsl list                   # bundled and user libraries with paths (offline)
lsl check textkit          # exit 0 if installed, 1 if missing, 2 invalid arguments (offline)
lsl origin textkit         # verify recorded SHA-256 and print origin/source URL
lsl about textkit          # short description (leading comment of the source)
```

- Registry: `https://lsl.lux-ai.cz/packages` (catalog v1 `catalog.json`); `LSL_REGISTRY`
  overrides it for development. Metadata: name, version, description, license, size, source,
  SHA-256. Invalid names, duplicates, unsafe paths and control characters are rejected.
- Install verifies the real source and its SHA-256 and checks that it compiles, without running
  it. Declared dependencies are verified and installed first; a cycle or bad hash stops the
  installation (already installed dependencies may stay).
- `lsl search` exit codes: 0 match, 1 no match or registry error, 2 invalid arguments. A
  network error is an error, not an empty catalog.
- Downloads use the system `curl`, verification the system `sha256sum`; no shell install scripts
  are run.

### TUI package manager (`lsl install --tui`)

Arrows, Home/End, PageUp/PageDown browse; `/` filters (Enter confirm, Esc cancel); Space or
Enter marks a library (marks survive filter changes); `i` offers to install the marked ones and
`y` confirms; `q`, Ctrl-C or Ctrl-D quit. A failed item does not undo earlier successful
installs (not a transaction). Requires an interactive terminal other than `dumb`.

### Libraries and sudo

Per-user libraries live in `~/.local/lib/lsl/stdlib` of the user who ran `lsl install`. With
`sudo`, `HOME` usually becomes `/root`, so `sudo lsl list`, `sudo lsl check NAME` or
`sudo lsl program.lsl` do not see the normal user's libraries, and `sudo lsl install NAME`
installs for root. Install and verify user libraries **without sudo**. Updating LSL itself does
not delete user libraries.

## Project layout

A larger project usually keeps a main file and modules next to it:

```text
myapp/
  main.lsl          # load helpers ; load util.text
  helpers.lsl
  util/text.lsl
  .env              # read by `load env` (keep secrets out of the source)
```

Run with `lsl main.lsl` or build with `lsl compile main.lsl myapp`.
