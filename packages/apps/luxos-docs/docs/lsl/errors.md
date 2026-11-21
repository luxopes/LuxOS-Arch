# LSL error handling

How Lux Simple Lang raises, catches and reports errors: `safe`, `try/else`, `Error`, `check`,
`last_error`, the format of uncaught errors, and compiler diagnostics.

## Overview

| Tool | Syntax | When to use |
|---|---|---|
| `safe` | `safe: ... end` | ignore an error and continue after the block |
| `try/else` | `try: ... else: ... end` | run a fallback when the block fails |
| `Error()` | `Error(Type: "message")` | raise your own error |
| `check()` | `check(condition, "message")` | assert a precondition, fail otherwise |
| `last_error()` | `last_error()` | text of the error that was caught |

An error interrupts normal flow and propagates out of functions until a `safe` or `try`
catches it. If nothing catches it, the program prints the error to stderr and exits with
status 1.

## safe

When a runtime error happens inside `safe`, the rest of the block is skipped and the program
continues after `end`.

```lsl
print "Start"
safe:
    x = 10 / 0                 # error here
    print "never printed"
end
print "Program continues"
```

`safe` hides what went wrong; inspect `last_error()` afterwards:

```lsl
safe:
    config = readfile("config.json")
end
if last_error() != None:
    print "Could not read the configuration, using defaults."
    config = "{\"port\": 8080}"
end
```

`safe` is **not a security sandbox** and does not roll back files, I/O or collection changes
already made.

## try / else

`else` runs **only** when the `try` block fails; inside `else`, `last_error()` gives the error
text. If `try` succeeds, `else` is skipped.

```lsl
try:
    data = readfile("/etc/app/config.json")
else:
    try:
        data = readfile("config.json")
    else:
        print "Nothing loaded:", last_error()
        data = "{}"
    end
end
```

There is no `finally` block: do cleanup before `end` or duplicate it in `else`.

## Error — raising your own error

```lsl
Error(TypeError: "expected Int, got String")
Error(ValueError: "value must be positive")
Error(DatabaseUnavailable: "database is not reachable")
```

The name before the colon is any identifier you choose; the text explains what happened.

```lsl
function find_user(name, database):
    if name not in database:
        Error(UserNotFound: "user '" + name + "' does not exist")
    end
    return database[name]
end
```

## check — preconditions

`check(condition, "message")` raises an error (reported as `CheckError`, verified in 0.11.1) when the
condition is false. Division by zero raises `ZeroDivisionError`.

```lsl
function safe_divide(a, b):
    check(b != 0, "division by zero")
    return a / b
end
```

Equivalent to `if not condition: Error(...) end`. Ideal for validating arguments.

## last_error()

Returns the text of the caught error (String), or `None` before the first error and after a
**successful** `safe`/`try` body (success also clears an older error, including when the body
is left with `return`, `break` or `continue`). The text stays available in `else` and after a
caught error; the state is per thread. Reading it does not clear it. If the handler runs
another `safe`/`try`, store the text in a variable first.

Caught text looks like `TypeError: sequence index must be Int at program.lsl:2:18` or
`ValueError: invalid Int String`.

## What can be caught

Runtime errors are caught. Since 0.8.2, inside `safe`/`try` and inside function bodies, unknown
functions/variables, missing methods and statically detectable type or argument errors become
runtime `NameError` / `AttributeError` / `TypeError`, so a caller can catch them. Outside
functions and protective blocks they stay compile-time diagnostics.

**Not** caught: syntax (parse) errors, missing imports, unsupported constructs, violations of
`safe`/sandbox rules, allocator exhaustion, operating-system signals and `exit()`.

## Uncaught errors

Since 0.9.1 an uncaught runtime error is printed in the same format as compiler errors:

```text
error[TypeError]: sequence index must be Int, got String
 --> program.lsl:2:18
  |
2 |     return items[key]
  |                  ^~~
 help: convert the index with Int(...)
```

Colors follow `NO_COLOR` / `FORCE_COLOR` / `TERM=dumb`. The source line is shown only for
`.lsl` files, so errors pointing into `.env` or configuration do not print secret values. A
worker thread that dies with an uncaught error prints `LSL worker error: ...`; other threads
and the main program continue. An error in a GLib/GTK handler (target `linux-x86_64-gnu`) prints
`LSL callback error: ...` and the handler returns 0; the main loop keeps running. A callback from
a thread other than the main one aborts the process (`LSL callback from non-main thread`).

## Error types used by standard modules

| Module | Error type | Meaning |
|---|---|---|
| `json` | `JsonError` | invalid JSON |
| `os` | `OSCommandError` | command failed (`os.check`) |
| `process` | `ProcessError` | process failed (`process.check`) |
| `system` | `PackageError`, `SystemError` | packaging / system administration error |
| `tensor` | `TensorShapeError`, `TensorIndexError`, `TensorLayoutError` | bad shape, index out of range, non-contiguous tensor |
| `config` | `ConfigCycleError` | cyclic configuration dependency |
| `fd`, `listdir`, `crypto` | `FileError` | file or socket error |
| `net` | `OSError`, `TimeoutError` | socket error, timeout |
| `tls` | `TLSError`, `TimeoutError` | handshake/verification failure, write after a reset (0.10.13+) |
| `crypto` | `CryptoError` | OpenSSL operation failed |
| `mdns` | `MDNSError` | DNS-SD / mDNS failure |
| `gio` | `DBusError` | D-Bus call or name error |
| `chr`, `cairo`, many modules | `ValueError` | argument out of range |
| built-in `help()` | `HelpError` | documented for an unknown topic, but in 0.11.1 `help("unknown")` only prints `No help available ...` and returns `None` |
| X11 output | `X11Error` | display disconnected or timed out |

```lsl
load json

try:
    data = json.decode("{invalid json")
else:
    print "JSON parsing failed:", last_error()
    data = {}
end
```

## Compiler diagnostics

Compile errors and warnings have codes and point at the source:

| Code | Meaning (examples seen in the manual and 0.11.1) |
|---|---|
| `E0011` | unterminated block comment |
| `E1100` | expected an expression (syntax) |
| `E1119` | comma before `for` in a comprehension (`[0, for x in rang(3)]`) |
| `E1248` | nested function definition (define it at module level; 0.10.7+) |
| `E2001` | unknown function/variable (also `round`), wrong operand types, or a discarded function result without `call` (`f()` must be `call f()`; instance method calls such as `a.m()` are exempt) |
| `E2002` | local variable read before it is assigned on every path |
| `E2003` | conflicting type-constraint declarations |
| `W2004` | assignment inside a function creates a local that shadows a global (use `global`) |
| `E3001` | library not found (`load NAME`): check `./NAME.lsl`, or `lsl search NAME` / `lsl install NAME` |
| `E3002` | library exists but cannot be read |
| `E3003` | `from MODULE load NAME`: the module has no such function, class or global (0.10.10+) |
| `W3001` | `# lsl: internal-abi` outside the LSL sources and system binding directories (`lslc` only in 0.11.1); an error in a later release. Since 0.11.1 the help line explains that Int 0 and `None` are the same word in that ABI |

The compiler reports the first error it finds. `lsl compile` (checked mode) also rejects private
`__lsl_*`, native and thread operations outside an `unsafe:` block ("unsafe operation outside an
unsafe block"), except in trusted system bindings (see
[modules.md](modules.md#system-bindings)). Warnings do not stop compilation.

## How to choose

```
Can this error happen in normal operation?
  no  -> check()   (fail early and loudly)
  yes -> do I need to know that it failed?
           yes -> try/else
           no  -> safe (optionally last_error() for logging)
```
