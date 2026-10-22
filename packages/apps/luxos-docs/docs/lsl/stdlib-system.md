# LSL standard library: processes and system administration

`os`, `process`, `system`, `luxos`, `config`/`configure` and `sandbox`. Basic process
built-ins (`run`, `capture`, `system()`) are in [builtins.md](builtins.md#process-and-arguments).

## os — run programs (never a shell)

`load os`. Programs are started by direct PATH lookup and `execve` with an argv list – never
`/bin/sh -c`, so there are no pipes, redirections or expansions, and arguments with spaces,
quotes or special characters are safe. A command is either a String (tokenized without a shell)
or an argv List.

| Function | Description |
|---|---|
| `os.run(command)` | run, inherit stdio, return the exit status |
| `os.system(command)` | alias of `os.run` (also the built-in `system(command)`) |
| `os.capture(command)` | return stdout as String (status/stderr via `capture_status()`, `capture_stderr()`) |
| `os.capture_result(command)` | return `{stdout, stderr, status, ok}` |
| `os.check(command)` | return stdout; non-zero status raises `OSCommandError` |
| `os.run_argv(program, arguments)` | explicit two-argument variant of `run` |
| `os.capture_argv(program, arguments)` | explicit two-argument variant of `capture` (`os.capture_argv_clean` also exists) |
| `os.which(name)` | path of an executable in PATH, or `None` (`os.which_trusted(name)` searches only trusted system directories) |
| `os.executable(name)` | checked path to an executable |

Errors: `OSCommandError` (non-zero status in `check`), `OSError` (invalid arguments).

```lsl
load os

status = os.run("ls -al")
result = os.capture_result(["echo", "hello"])
print result["stdout"].strip(), result["status"], result["ok"]   # hello 0 True
if os.which("python3") != None:
    print "python3 found"
end
try:
    text = os.check(["cat", "missing.txt"])
else:
    print "cannot read:", last_error()
end
```

For a real shell use the optional registry package `shell` (`lsl install shell`), which runs
`/bin/sh -c` explicitly and returns a structured result.

## process — structured process API

`load process`. Status codes as for built-ins (exit code, `128 + signal`, 126 fork/wait
failure, 127 exec failure).

| Function | Description |
|---|---|
| `process.capture_result(program, arguments)` | run, return `{stdout, stderr, status, ok}` |
| `process.capture_input_result(program, arguments, input_text)` | same with stdin input |
| `process.capture_input_stream_result(program, arguments, input_text, callback)` | send stdin, stream stdout to the callback, return the structured result |
| `process.check(program, arguments)` | return stdout; non-zero status raises `ProcessError` |
| `process.check_input(program, arguments, input_text)` | `check` with stdin input |
| `process.check_input_stream(program, arguments, input_text, callback)` | `check_input` that also streams stdout to the callback |

```lsl
load process
result = process.capture_input_result("/usr/bin/sort", [], "c\na\nb\n")
print result["stdout"]
```

## system — imperative LuxOS/Debian administration

`load system`. Functions really change the machine and need the corresponding privileges.
Every command is argv, never a shell. Package names are validated against `[A-Za-z0-9._+-]`.
Errors: `SystemError` (invalid input, missing tool, failed command), `PackageError`.

| Function | Description |
|---|---|
| `system.install(package)` / `update(package)` / `remove(package)` | detect the package manager (`lux`, fallback `apt`) and run the action; return the backend used |
| `system.refresh()` | refresh package lists (`apt update`) |
| `system.detected_lux()` / `detected_apt()` | path to the tool or `None` |
| `system.required_tool(name)` | path to a tool or `SystemError` |
| `system.enable_service(name)` / `disable_service(name)` / `restart_service(name)` | systemd service control |
| `system.service_active(name)` | `True` if the service runs |
| `system.set_hostname(name)` / `set_timezone(zone)` / `set_locale(locale)` | identity (`"Europe/Prague"`, `"C.UTF-8"`) |
| `system.ensure_group(name)` / `remove_group(name)` | idempotent group management |
| `system.ensure_user(name, shell, groups)` / `remove_user(name)` | idempotent user management |
| `system.write_file(path, content, mode)` | atomic write with permissions |
| `system.write_owned_file(path, content, mode, owner, group)` | atomic write with owner |
| `system.ensure_directory(path, mode)` | create a directory with permissions |
| `system.remove_file(path)` | delete a file |
| `system.ensure_mount(device, target, fs, options)` / `unmount(target)` | mounts |
| `system.check_system(config_path)` / `apply_system(config_path)` / `dry_run_system(config_path)` | run `lux check -c` / `lux apply` on a declarative configuration |
| `system.lux_status()` / `generations()` / `rollback(generation)` / `rollback_dry(generation)` | status, generations and rollback through `lux` |
| `system.validate_package(p)`, `validate_name(v, label)`, `validate_account_name(v, label)`, `validate_account_list(vs, label)` | input validation |

Every function also has a `_with` variant that takes explicit tool paths, e.g.
`system.install_with(p, lux, apt)`, `system.enable_service_with(n, systemctl)`,
`system.ensure_user_with(n, shell, groups, id, useradd, usermod)`,
`system.write_file_with(p, content, mode, owner, group, tool)`,
`system.rollback_with(g, dry_run, lux)`.

**On LuxOS:** `system.install("git")` runs `lux install git` (the LuxOS package manager),
which asks for confirmation and administrator rights like any `lux` call.
`system.update(package)` runs `lux update PACKAGE`, and LuxOS `lux update` always updates the
whole system (it ignores a package name). The declarative
functions (`check_system`, `apply_system`, `lux_status`, `generations`, `rollback`) call
`lux check`/`lux apply`/... subcommands from the LSL world; the LuxOS `lux` package manager
(0.9.x) has no such subcommands, so do not rely on them on LuxOS.

```lsl
load system
backend = system.install("git")             # "lux" or "apt"
call system.enable_service("nginx.service")
call system.ensure_directory("/etc/myapp", "0750")
call system.write_file("/etc/myapp/config", "port=8080\n", "0640")
```

## luxos — declarative system configuration

`load luxos`. Applies a manifest (hostname, motd, packages, users) to the running system and
records generations for rollback.

| Function | Description |
|---|---|
| `luxos.defaults()` | `{"hostname": "luxos", "locale": "C", "timezone": "UTC", "keymap": "us", "motd": None, "packages": [], "users": []}` |
| `luxos.apply(config)` | validate and apply; with `LUXOS_DRY_RUN` only print planned changes; returns the list of changes and records a generation |
| `luxos.apply_manifest()` | apply the manifest from `LUXOS_MANIFEST` (current `config.lconf` + configuration) |
| `luxos.previous_manifest()` / `luxos.latest_generation()` | manifest of the previous generation / last generation |
| `luxos.record_generation(config)` | record an evaluated configuration as a new generation |
| `luxos.validate_config(config)` / `luxos.field(config, name, fallback)` | validation / field access |

Errors: `ValueError` for an invalid manifest. This engine belongs to the LSL project; LuxOS
(Arch-based, 0.9.x) does not use it for its own configuration.

## config and lsl config

`load config` declares options for configuration modules evaluated by `lsl config ENTRY`, which
prints the merged configuration (JSON). Evaluation runs with time and resource limits and is
pure: `env` and other impure functions are not allowed.

| Function | Description |
|---|---|
| `config.option(type, default, description)` | option with a type (`"Int"`, `"Float"`, `"String"`, `"Bool"`, `"List"`, `"Dictionary"`, `"None"`, `"Any"` or unions like `"Int\|None"`), default and description |
| `config.required(type, description)` | required option without default |
| `config.mkOverride(priority, value)` | value with an explicit merge priority |
| `config.mkDefault(value)` | default value (priority 100, can be overridden) |
| `config.mkForce(value)` | forced value (priority 1000, overrides everything) |
| `config.lazy(thunk)` | defer evaluation of a zero-argument function |
| `config.mkIf(condition, value)` | omit the value when the condition is `False` (also in lists) |

Lists and dictionaries with the same priority are merged. Errors: `ConfigError`,
`ConfigCycleError`. `configure.collect(path, seen, active, order)` (internal) collects modules
in post-order for the native evaluator generated by `lsl-configure`.

## sandbox — capability isolation

`load sandbox`; the engine behind `lsl sandbox`. The program sees an empty tmpfs root, minimal
`/proc` and `/dev`, its own read-only executable and only paths bound into `/input/N` or
`/output/N`. Network namespaces, a systemd cgroup, prlimit and a timeout are set before start.
Requires the system sandbox tools and a systemd user session (Linux x86-64).

| Function | Description |
|---|---|
| `sandbox.run(executable, args, policy)` | run in the namespace/cgroup sandbox, return the status (max 4096 args) |
| `sandbox.command(executable, args, policy)` | build the sandbox argv |
| `sandbox.available()` | `True` if the host tools are present |
| `sandbox.is_active()` | `True` inside `lsl sandbox` |
| `sandbox.profile()` | `"strict"`, `"server"` or `None` |
| `sandbox.input_path(n)` / `sandbox.output_path(n)` | `/input/N` / `/output/N` |

Policy: `{"profile": "strict" | "server", "timeout": 1..3600 (default 30), "memory": 64 MiB..8 GiB,
"read": [paths], "write": [paths]}`. Errors: `SandboxError`.

```bash
lsl sandbox --profile strict --timeout 10 --memory 268435456 --read data.txt app.lsl
```

`lsl sandbox` refuses to compile unsafe source. This is unrelated to the LuxOS system sandbox
(`luxos-sandbox`, see [the LuxOS sandbox page](../luxos/sandbox.md)).
