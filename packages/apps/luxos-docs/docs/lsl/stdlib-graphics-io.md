# LSL standard library: terminal, graphics and low-level I/O

`tui`, `fd`, `unixsock`, `native`, `plugin` (bundled) and the graphics modules `display`,
`gfx`, `ui`, `css`, `input` (since 0.8.2 **optional registry packages**: `lsl install display`,
`lsl install gfx`, `lsl install ui`, `lsl install css`, `lsl install input`).

## tui — full-screen terminal programs

`load tui`. Pure LSL (fd runtime plus `stty`, no curses): cbreak mode, alternate screen, ANSI
rendering and a normalized key decoder. Always restore the terminal on errors and cancellation.

```lsl
load tui

term = tui.Terminal()          # or tui.open()
call term.enter()              # cbreak + alternate screen
try:
    call term.query_size()     # updates term.rows / term.cols
    call term.clear()
    call term.text_at(1, 1, "Press q to quit")
    call term.flush()
    loop:
        key = term.read_key()  # normalized: "up", "down", "char:x", ...
        if key == "char:q":
            break
        end
    end
else:
    print last_error()
end
call term.leave()              # always restore the terminal
```

Drawing: `clear`, `clear_line`, `move(row, col)`, `text_at(row, col, text)`, `emit(text)`,
`flush`. Style: `reset_style`, `set_fg(code)`, `set_bg(code)`, `bold`, `invert`. Input:
`read_byte(timeout)`, `read_key()`. `emit` + `flush` also give smooth output without newlines
in normal programs (e.g. streaming AI text).

The registry package `term` offers lower-level raw terminal control (termios ioctls,
single-key reads).

## fd — file descriptors

`load fd`. For devices (framebuffer, evdev), sockets and bounded reads. Errors: `FDError` /
`FileError`.

| Function | Description |
|---|---|
| `fd.open(path, flags)` | open a file or device (syscall `open`) |
| `fd.read(handle, buffer, count)` / `fd.write(handle, buffer, count)` | read into / write from a ByteArray |
| `fd.seek(handle, position)` | move the position |
| `fd.close(handle)` | close |
| `fd.ioctl(handle, request, buffer)` | `ioctl` syscall |
| `fd.mmap(handle, length, offset)` | map into memory |
| `fd.socket(domain, kind)` | raw socket |
| `fd.connect_unix(path)` | connect to a Unix domain socket |
| `fd.read_all(path)` / `fd.read_all_limit(path, limit)` | whole file as ByteArray |
| `fd.read_text(path)` / `fd.read_text_limit(path, limit)` | whole file as String |

```lsl
load fd
print fd.read_text_limit("/proc/version", 4096).strip()
```

## unixsock — Unix sockets with descriptor passing

`load unixsock`. `SCM_RIGHTS` file-descriptor passing as needed by a display server.
`unixsock.listen_unix(path, backlog)`, `accept_unix(server)`, `send_bytes(handle, payload,
count)`, `send_fd(handle, payload, count, descriptor)`, `send_from(...)`, `send_from_fd(...)`,
`recv_fds(handle, payload, count, fds)`, helpers `memfd(name, size)`, `pipe_nonblock()`,
`set_nonblocking(handle)`, `chmod_path`, `chown_path`. Errors: `UnixSocketError`.

## native — fork-isolated native kernels

| Function | Description |
|---|---|
| `native.open(path)` | load a trusted self-contained ET_DYN image, return a handle |
| `native.symbol(library, name)` | look up a symbol in SHT_DYNSYM, return an opaque Function |
| `native.call(func, [args...])` | call in a short-lived strict-seccomp child process with max 6 Int arguments, return an Int |
| `native.close(library)` | release the library |

Only self-contained Linux x86_64 ET_DYN Int64 kernels; general relocatable/libc plugins are not
part of ABI v1. Native operations must be inside an `unsafe:` block under checked compilation.

## plugin — process plugin ABI

| Function | Description |
|---|---|
| `plugin.request(executable, operation, payload)` | run the plugin as a process, exchange JSON over stdin/stdout, check the exit status |
| `plugin.request_input(executable, operation, payload)` | compatible alias of `request` |
| `plugin.request_argv(executable, operation, payload)` | legacy argv transport; do not use for secrets |

## display — window output (optional package)

`display` opens an X11 window or the framebuffer (and DRM/KMS).

| Function / member | Description |
|---|---|
| `display.open(width, height, title)` | open a window (X11 or framebuffer), return a display object |
| `display.open_framebuffer()` | open `/dev/fb0` directly |
| `display.x11_available()` | `True` if an X11 server is available |
| `display.open_device(name)` | open a specific device |
| `d.width`, `d.height` | size in pixels |
| `d.should_close()` | `True` when the user closed the window |
| `d.present(pixels, width, height)` | draw pixels and run GC |
| `d.poll()` | List of events `[(kind, a, b), ...]` |
| `d.close()` | close and release resources |

X11 writes continue after partial sends; disconnect or timeout raises a catchable `X11Error`
(close and reopen the window afterwards).

## gfx — 2D raster graphics (optional package)

Colors are Ints `0xRRGGBB`: `gfx.rgb(r, g, b)`, `gfx.red/green/blue(color)`,
`gfx.mix_color(bottom, top, alpha)` (alpha 0–255).

Rasterizers over raw IntArray pixels (`pixels, w, h` first): `raster_clear`, `raster_set`,
`raster_hline`, `raster_vline`, `raster_fill_rect`, `raster_rect`, `raster_line` (Bresenham),
`raster_blit(dst, dw, dh, src, sw, sh, dx, dy)`, `raster_copy_rect`, `raster_fill_circle`,
`raster_fill_pill`, `raster_glyph` / `raster_text` (8×16 font), `raster_glyph_scaled` /
`raster_text_scaled`, `raster_glyph_aa` / `raster_text_aa` (2×2 supersampling),
`raster_gradient(pixels, w, h, top, bottom)`, `raster_round_rect(..., radius, color, alpha,
feather)`, `raster_round_rect_grad`, `raster_shadow(..., radius, color, alpha, blur)`.

Surface object `s = gfx.surface(width, height, color)`: `clear`, `get(x, y)`, `set(x, y, c)`,
`hline`, `vline`, `fill_rect`, `rect`, `line`, `blit`, `text(x, y, value, color)` (returns width),
`glyph`, `save_ppm(path)` (binary P6), fields `pixels` (IntArray), `width`, `height`. Text
metrics: `gfx.text_width(value)`, `gfx.text_height()` (always 16).

```lsl
load gfx
s = gfx.surface(160, 60, gfx.rgb(255, 255, 255))
call s.fill_rect(10, 10, 140, 40, gfx.rgb(30, 90, 200))
call s.text(20, 22, "Hello LSL", gfx.rgb(255, 255, 255))
call s.save_ppm("hello.ppm")
```

## ui — widgets (optional package)

`ui.label(x, y, text)`, `ui.button(x, y, w, h, text, on_click)`, `ui.checkbox(x, y, text,
checked)`, `ui.new_state()` (`{running, key, mouse_x, mouse_y}`), `ui.process(widgets, state,
events)` (hover, click, Esc, close), `ui.paint(pixels, w, h, widgets, background)`. Theme
colors: `ui.color_background`, `color_text`, `color_muted`, `color_accent`,
`color_accent_text`, `color_border`, `color_field`.

## css — declarative styling (optional package)

`css.parse(text)` → `selector → {property: value}`, `css.rule(sheet, selector)`,
`css.value(rules, key, fallback)`, `css.color(text)` (`#rgb`, `#rrggbb`, `rgb()`, `rgba()`),
`css.alpha(text)`, `css.is_gradient(text)`, `css.gradient_top/gradient_bottom(text)`,
`css.number(text)`.

## input — evdev keyboard (optional package)

`input.open_keyboard_device()` (from `/dev/input`), `input.read_key_events(handle)`, key codes
`input.key_esc`, `key_enter`, `key_left`, `key_right`, `key_up`, `key_down`, `key_backspace`,
`key_tab`, `key_space` (the installed version may differ; check `lsl man input`).

A complete graphical example (Snake) in the LSL sources needs `display` and `gfx`.
