# LSL built-in functions

Functions and statements available everywhere without `load` (section 1 of the official LSL
function reference), with notes where the tested **0.10.2** compiler differs. `help("NAME")`
inside a program and `lsl help NAME` print the built-in help text for most of them.

## Output and input

| Function | Description |
|---|---|
| `print arg1, arg2, ...` | print arguments separated by a space, end with a newline |
| `printl "text {expr}"` | print an interpolated string (expressions in `{...}` are replaced) and a newline |
| `printr arg1, ...` | print values exactly, no separators and no newline (0.9.1+) |
| `l"text {expr}"` | first-class interpolated String; can be assigned, returned and passed |
| `input "prompt"` / `input("prompt")` | print the prompt, read one line from stdin, return a String without the trailing LF |

## Type conversion and construction

| Function | Description |
|---|---|
| `Int(value)` | convert to integer (Int) |
| `Float(value)` | convert to Float |
| `String(value)` | convert to text |
| `Bool(value)` | convert to truth value |
| `List(value)` / `Tuple(value)` / `Dictionary(value)` | convert, or create an empty one |
| `IntArray()` / `FloatArray()` / `ByteArray()` | empty packed array (unboxed Int64 / Float64 / bytes 0–255) |
| `set()` / `set(iterable)` | Set of unique immutable values; a Dictionary provides its keys |
| `sorted(iterable)` | new stable ascending List; input unchanged; one argument, no `key`/`reverse` |
| `dedup(list)` | shallow List without duplicates in first-occurrence order (nested collections allowed) |
| `type(value)` | type name as String, e.g. `"Int"`, `"String"` |

Variable declarations (`Int(x) = 10`), `i++` and initialization rules are described in
[syntax.md](syntax.md#type-constrained-declarations).

## Math

| Function | Description |
|---|---|
| `min(a, b, ...)` / `min(iterable)` | smallest argument or element |
| `max(a, b, ...)` / `max(iterable)` | largest argument or element |
| `sum(collection)` | sum of the elements |
| `abs(x)` | absolute value (Int, Bool or Float) |
| `sqrt(x)` | square root as Float; negative input raises `ValueError` |
| `round(x)` | round a Float to the nearest integer |

## Bits

| Operator / function | Description |
|---|---|
| `a & b`, `a \| b`, `a ~ b` | AND, OR, XOR of two Int (`^` is power) |
| `~a` | NOT (ones' complement) |
| `a << b`, `a >> b` | shifts (see [syntax.md](syntax.md#bitwise-operators)) |
| `popcount(x)` | number of one bits of the raw 64-bit Int |
| `trailing_zeros(x)` | number of zero bits from the right; `64` for `0` |

## Characters

| Function | Description |
|---|---|
| `chr(code)` | one-character String for a Unicode code point |
| `ord(char)` | Unicode code point of the first character |

## Time and processes (basic)

| Function | Description |
|---|---|
| `clock()` | readable date and time String `YYYY-MM-DD HH:MM:SS UTC` (not for arithmetic) |
| `monotonic()` | monotonic seconds (Float) for intervals and timeouts |
| `system(command)` | alias of `os.run(command)` without `load`; command String or argv List, PATH lookup, no shell, returns exit status |

## Threads and atomics

| Function | Description |
|---|---|
| `cpu_count()` | number of CPUs in the process affinity mask (respects taskset/cgroups); `1` on error |
| `thread_spawn(function)` | inside an `unsafe:` block, run a zero-argument function in a shared-memory worker thread; returns a thread id or `-1` (max 127 workers, 8 MiB stack each) |
| `thread_join(tid)` | wait for the worker; returns `0`, or `126` for an unknown tid |
| `atomic_add(array, index, delta)` | atomically add to an `IntArray` slot, return the previous value |
| `atomic_xchg(array, index, value)` | atomically exchange a slot, return the previous value |
| `atomic_cas(array, index, expected, desired)` | compare-and-swap, return the previous value |
| `atomic_pause()` | CPU pause hint for spin-wait loops |
| `gc()` | request garbage collection now (normally automatic); in a worker returns `0` |

Threads share memory (Linux `clone` with `CLONE_VM|CLONE_THREAD`). The worker's return value
is discarded; an uncaught error in a worker prints `LSL worker error: ...`. Plain writes to
shared collections are not synchronized: use the atomics or a `lock` block over an `IntArray`
slot. Workers take work indexes from a global `IntArray` counter via `atomic_add`.

```lsl
counter = IntArray()
counter.append(0)

function bump():
    i = 0
    while i < 1000:
        call atomic_add(counter, 0, 1)
        i += 1
    end
    return None
end

unsafe:
    t = thread_spawn(bump)
    u = thread_spawn(bump)
end
print thread_join(t), thread_join(u), counter[0]   # 0 0 2000
```

## Text files

| Function | Description |
|---|---|
| `readfile(path)` | read the whole file as a UTF-8 String (bounded reads: `fd.read_text_limit`) |
| `writefile(path, text)` | write text, replacing the file |
| `appendfile(path, text)` | append text to the end |
| `exists(path)` | `True` if the path exists |

## Binary files

| Function | Description |
|---|---|
| `readbytes(path)` | read the whole file as a ByteArray |
| `writebytes(path, data)` | write a ByteArray (an ELF output is made executable) |

## File system

| Function | Description |
|---|---|
| `mkdir(path)` | create a directory |
| `cwd()` | absolute path of the working directory – **Note (0.10.2):** not available, compile error "unknown native function" |
| `chdir(path)` | change the working directory – **Note (0.10.2):** not available |
| `remove_path(path)` | delete a file or empty directory – **Note (0.10.2):** not available |

In 0.10.2 use the `os` module instead, e.g. `os.run(["rm", "-f", path])`,
`os.capture("pwd")`, or `system.remove_file(path)` from the `system` module.

## Process and arguments

| Function | Description |
|---|---|
| `arg(index)` | program argument at a position (0 = program name, 1 = first user argument), or `None` |
| `arg_count()` | number of arguments including the program name |
| `args` | global List of all arguments – **Note (0.10.2):** not available (unknown variable); use `arg()` and `arg_count()` |
| `run(program, arguments)` | run a program with an argv List, no shell; returns the exit status |
| `capture(program, arguments)` | run and return stdout as String |
| `capture_stream(program, arguments, callback)` | run and stream output chunks to a callback |
| `capture_input(program, arguments, input_text)` | run with stdin text, return stdout |
| `capture_input_stream(program, arguments, input_text, callback)` | send stdin and stream stdout to a callback |
| `capture_status()` | exit status of the last `capture*()` call |
| `capture_stderr()` | stderr of the last `capture*()` call |
| `exit(status)` | terminate the program with the exit code |

Status codes: exit code of the program, `128 + signal` when killed by a signal, `126` when fork
or wait failed, `127` when exec failed. In 0.10.2 `run`/`capture` need a path to the
executable (`capture("/usr/bin/echo", ["hi"])`); `capture("echo", ...)` returned status 127.
Use `system()` or the `os` module for PATH lookup.

```lsl
out = capture("/usr/bin/uname", ["-r"])
if capture_status() == 0:
    print "kernel:", out.strip()
end
```

## Errors

| Function | Description |
|---|---|
| `last_error()` | text of the caught error; `None` before the first error and after a successful `safe`/`try` |
| `Error(Type: "message")` | raise a named, catchable error |
| `check(condition, "message")` | raise an error when the condition is false |

See [errors.md](errors.md).

## Other

| Function | Description |
|---|---|
| `len(value)` | length of a String (Unicode characters), list, dictionary or array |
| `help()` / `help("TOPIC")` | print the topic list / help for a command, construct or module; accepts a runtime String, returns `None`; unknown topic raises `HelpError`. For a library the output starts with the same short description as `lsl about NAME` and works for installed user libraries too. Full manual: `lsl man` |
| `del(x)` | delete a variable, collection element or instance member |
| `rang(...)` / `range(...)` | integer sequences (see [control-flow.md](control-flow.md#rang--range)) |

## Native FloatArray kernels

`float_zeros`, `float_fill`, `float_sum`, `float_dot`, `float_axpy`, `float_matmul` are
documented in [stdlib-compute.md](stdlib-compute.md).
