# wl-test: Wayland test harness

Runs Wayland compositors (stock labwc now, `luxwm` later) and Wayland clients without a real screen.
It takes screenshots, injects pointer and keyboard input, and checks frame sequences for flicker.
Every package of the 1.1.0 Wayland desktop tests through it (see `docs/proposals/wayland-desktop-1.1.0.md`, WP-1).

The harness is shell plus small C tools. Python is used only in tests.

| File | Purpose |
|---|---|
| `wlt` | main command: sessions, clients, input, screenshots, capture, memory |
| `fetch-sysroot.sh` | downloads the pinned labwc/wlroots 0.20/grim/wlr-randr closure (`packages.lock`, sha256-checked) to `out/wl-test/sysroot` |
| `vm-image.sh` | builds a minimal Arch image with labwc for the VM matrix (podman, like `build.sh`) |
| `vm-matrix.sh` | boots the image in QEMU with different graphics cards, captures frames via QMP, runs the flicker detector |
| `src/wlt-input.c` | input through `zwlr_virtual_pointer_v1` and `zwp_virtual_keyboard_v1` |
| `src/wlt-client.c` | test window (xdg-shell, server-side decorations, striped content, no fonts); `--events` prints input it receives |
| `src/wlt-bar.c` | test bar through layer-shell (top or bottom edge, exclusive zone, solid colour) |
| `src/wlt-qmp.c` | QMP client: `screendump` capture at a fixed fps, input via `input-send-event` |
| `src/wlt-frames.c` | PPM statistics and the flicker detector |
| `labwc/` | deterministic labwc config for tests (centered windows, no shadows, fixed root menu) |
| `tests/test_wl_harness.py` | unittest for the harness itself |

Everything generated goes to `out/wl-test/` (`WLT_OUT`): `bin/`, `sysroot/`, `sessions/`, `vm/`, `vm-runs/`.

## Safety

- A compositor only ever gets `WLR_BACKENDS=headless` or `x11`, plus `WLR_RENDERER=pixman`, `WLR_DRM_DEVICES=/nonexistent` and `WLR_LIBINPUT_NO_DEVICES=1`. It never touches the host's DRM or input devices.
- Sessions start from `env -i`. Nothing from the real session is passed on: no `DISPLAY`, `WAYLAND_DISPLAY`, session bus or `HOME`. `XDG_RUNTIME_DIR`, `HOME` and `XDG_CONFIG_HOME` are private under `out/wl-test/sessions/NAME/`.
- Nested mode starts its own Xvfb on display :200–:299 (the test guard uses :90–:199).
- The compositor runs under `systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -p MemorySwapMax=0` (`WLT_MEMORY_MAX` changes the limit) (set `WLT_SCOPE=0` to skip this) and `timeout`. Clients run under `timeout`. `wlt stop` kills only PIDs the session started.
- Still run whole tests under `systemd-run --user --scope -p TasksMax=300 -- timeout ...`, with the `env -u DISPLAY ...` prefix from the plan.

## Setup

```sh
scripts/wl-test/fetch-sysroot.sh      # ~90 MB of packages, extracted to ~390 MB
scripts/wl-test/wlt build             # C tools (wlt builds them on demand anyway)
```

Binaries are taken from the sysroot first, then from the system. `WLT_SYSROOT=none` uses only the system, for example once `packages/wlroots0.20` and `luxwm` are installed. To update the pin, regenerate `packages.lock` from a fresh `pacman -Sw` and record the date in its header.

## Sessions

```sh
s=$(scripts/wl-test/wlt start --mode headless --size 1280x800)    # prints the session directory
scripts/wl-test/wlt run "$s" --bg wlt-client --events --title Test
scripts/wl-test/wlt input "$s" 'move 640 400' 'click' 'type hello' 'key ctrl+a'
scripts/wl-test/wlt input "$s" 'drag 640 237 300 150 800'      # window title bar -> elsewhere in 0.8 s
scripts/wl-test/wlt input "$s" 'move 1000 100' 'click right'    # labwc root menu
scripts/wl-test/wlt shot "$s" shot.png                         # .ppm or .png
scripts/wl-test/wlt mem "$s"                                   # compositor_pss_kb=... (xvfb_pss_kb=...)
scripts/wl-test/wlt stop "$s"
```

- `start` options:
  - `--mode headless|nested`
  - `--outputs N`
  - `--size WxH`: custom mode for every output, set via wlr-output-management
  - `--name NAME`
  - `--timeout SEC`: hard limit, 900 by default
  - `--config DIR`: labwc config directory
  - `-- COMMAND...`: another compositor, e.g. `-- luxwm -d`. The compositor must support `wlr-output-management` (for `--size` and the readiness check) and virtual pointer/keyboard (for `input`).
  - `WLT_COMPOSITOR_ENV="VAR=x ..."` adds variables to the compositor's environment.
- `wlt-bar [--height N] [--bottom] [--color RRGGBB]` is a layer-shell bar with an exclusive zone, for placement tests below a bar or above a dock.
- `wlt-client --events` prints `focus US` (CLOCK_MONOTONIC in µs) when it gets keyboard focus, for latency measurements.
- `run S CMD...` runs a client in the session environment. With `--bg`, output goes to `S/clients.log`, so you can read what `wlt-client --events` received.
- `input` commands, one per argument or one per stdin line (`src/scen.c`):
  - `move X Y`
  - `down|up|click [left|right|middle]`
  - `drag X1 Y1 X2 Y2 [MS] [BTN]`
  - `key NAME[+NAME...]` (xkb names: `Return`, `Escape`, `ctrl+alt+t`, `super`)
  - `keydown NAME`, `keyup NAME`: hold a key across commands, e.g. `keydown alt` `key Tab` `key Tab` `keyup alt`
  - `type TEXT` (US layout)
  - `sleep SEC`

  Coordinates are pixels of the whole output layout (`S/layout`).
- `env S` prints `export` lines for the session, e.g. for running an LSL client by hand.
- Logs: `S/compositor.log`, `S/clients.log`, `S/xvfb.log`. For a debug log, use `wlt start -- labwc -d`.

## Flicker detector

```sh
scripts/wl-test/wlt capture "$s" frames 30 10   # headless/nested: grim at 30 fps for 10 s
scripts/wl-test/wlt check frames                 # exit 1 and FLAG lines when something is wrong
```

How it works:

1. Each frame is reduced to a grid of 16x16 px block means.
2. Consecutive identical frames are merged into runs: the screen did not change between them.
3. The run sequence is checked for three kinds of problem:
   - `black`: the frame is ≥ 99.5 % black (`--allow-black` for scenarios with a blank screen).
   - `transient`: a short run (≤ `--max-run` frames, default 2) differs from both neighbours in blocks where the neighbours agree with each other, in ≥ 2 % of the screen. This catches black or garbage flashes and half-drawn frames, such as a window missing for one frame.
   - `regressed`: a short run matches an older run (up to `--back` 8 runs back) and the next run continues from the run before it. The screen showed an older state for a moment.
4. Only the stronger frame of a neighbouring pair is reported.

A state that stays on screen longer than `--max-run` captures is real, not a glitch: for example, a window resting at the end of a drag before it is dragged back. So scenarios pause about 0.3 s at direction reversals.

Limitations:
- Tearing, where a frame is half old content and half new, looks like a legitimate in-between state and is not flagged.
- Fast motion of a striped window across the stripes (≥ ~50 px per frame, e.g. a workspace slide) is flagged as `transient`:
  two-colour stripes shifted by ~100 px agree by chance in about half of the blocks, and the frame between differs there.
  Test windows for horizontal slides therefore use `wlt-client --hstripes`.
- A real one-frame state change, such as a 1-frame menu highlight covering ≥ 2 % of the screen, would be flagged. Scenarios move the pointer in small steps.
- grim copies finished frames (ext-image-copy-capture), so headless capture shows regressions but never half-drawn buffers. Half-drawn buffers are only visible in VM capture, where `screendump` reads the scanout buffer.

Other options: `--block N`, `--thr T` (colour difference, default 12), `--min F`, `--same F`.

## VM matrix

```sh
scripts/wl-test/vm-image.sh                       # out/wl-test/vm/{root.img,vmlinuz,initramfs.img}
scripts/wl-test/vm-matrix.sh                      # all configurations
scripts/wl-test/vm-matrix.sh std-pixman virtio-auto-swcursor
```

Configuration names are `CARD-RENDERER[-swcursor]`:

| Card | QEMU device | Guest driver |
|---|---|---|
| `std` | `VGA,xres=1024,yres=768` | bochs-drm |
| `virtio` | `virtio-vga,xres=1024,yres=768`, no virgl | virtio-gpu |
| `vmware` | `vmware-svga` | vmwgfx |

- Renderer: `auto` lets wlroots choose; `pixman` and `gles2` set `WLR_RENDERER`.
- `-swcursor` adds `WLR_NO_HARDWARE_CURSORS=1`.

Compositor: `WLT_VM_COMP=labwc` (default) or `WLT_VM_COMP=luxcomp`. For luxcomp, build the image with the local packages:

```sh
./build.sh one wlroots0.20 && ./build.sh one luxcomp            # LUXOS_SIGNING_DIR=none for unsigned
scripts/wl-test/vm-image.sh out/single/wlroots0.20-*.pkg.tar.zst out/single/luxcomp-*.pkg.tar.zst
WLT_VM_COMP=luxcomp scripts/wl-test/vm-matrix.sh std-auto virtio-auto
```

The guest then runs `/usr/lib/luxcomp/luxcomp-demo` with `LUXCOMP_STATS=1` on an empty desktop. The host sends it commands
through a second virtio port `wltctl` (a FIFO `ctl` in the run directory, passed on to the demo's stdin). The scenario opens
two test windows (`spawn wlt-client ...`), drags the second one, slides to the empty workspace and back with
Ctrl+Right/Left (420 ms) and closes the second window with its close button. The report adds the renderer line of
libluxcomp, the number of distinct captured frames within 0.6 s of each slide key press, and the frame count and slowest
render time that libluxcomp itself logs for each slide.

Each run does the following:
1. Boots with direct kernel boot and a `-snapshot` root disk. root is logged in automatically on tty1 and labwc runs on DRM with one 400x300 test window.
2. Waits for `WLT READY` on the virtio port `wlt`.
3. Captures 10 s of idle screen at 30 fps via QMP `screendump`.
4. Captures 10 s more while running a scenario through the usb-tablet: drag the window away and back, open the root menu on the desktop, hover all its items, Escape.
5. Runs `wlt-frames check` on both captures.

The guest reports through the virtio port:
- the DRM driver and `/dev/dri` nodes
- the renderer wlroots picked
- labwc PSS after 5 s idle and after the scenario

Results go to `out/wl-test/vm-runs/TIME/report.md`. Every configuration has its own directory with `guest.log`, `console.log`, `*.check` and `*.capture`. Frames are kept only around flags; `WLT_KEEP_FRAMES=1` keeps all of them (~2.3 MB per frame).

If the host QEMU lacks `virtio-vga` (the Arch packages `qemu-hw-display-virtio-*` are optional), `vm-image.sh` downloads the modules matching the host QEMU version from archive.archlinux.org. It checks their signatures in the container and `vm-matrix.sh` loads them via `QEMU_MODULE_DIR`.

Two QMP sockets are used per VM, because QEMU serves one client per socket and capture and input run in parallel.

### Results (2026-11-20)

Guest: linux 7.3.5, wlroots 0.20.2, labwc 0.20.3, mesa 26.3.1. Host: QEMU 11.1.3 with KVM. All captures ran at 30.0–30.1 fps.

| config | /dev/dri | renderer picked | idle / scenario flags | labwc PSS idle |
|---|---|---|---|---|
| std-auto | card0 only | pixman, after failed gles2 + vulkan attempts | 0 / 0 | 47.8 MB |
| std-pixman | card0 only | pixman | 0 / 0 | 24.1 MB |
| virtio-auto | card0 + **renderD128** | **gles2 on Mesa kms_swrast (software)** | 0 / 0 | 116.7 MB (129 MB after scenario) |
| virtio-pixman | card0 + renderD128 | pixman | 0 / 0 | 23.9 MB |
| vmware-* | none | labwc exits | — | — |

What this shows:
- **virtio-gpu without virgl does expose a render node.** wlroots auto-selection therefore picks GLES2 on software rasterisation (Mesa falls back to `kms_swrast`), and the "software rendering" refusal does not trigger. That costs ~93 MB PSS more than pixman.
- **bochs-drm reaches pixman only after failed GLES2 and Vulkan attempts.** The loaded EGL/Vulkan libraries stay mapped: +24 MB.
- So luxwm must choose pixman itself whenever no real GPU is present (WP-2).
- **QEMU's `vmware-svga` is not usable as a stand-in for VMware or VirtualBox.** vmwgfx refuses it: `Hardware has no pitchlock`, `probe with driver vmwgfx failed with error -38`, "unsupported hypervisor". No DRM device exists, so no Wayland compositor can run there. Under Xorg, the X server would use its own non-DRM vmware/fbdev path instead.

VirtualBox VMSVGA cannot be scripted here: there is no VirtualBox on the dev host, and QEMU does not emulate VMSVGA. It uses the same vmwgfx guest driver as `vmware`, but with VirtualBox's own SVGA3 device. wlroots issue #3621 (`drm_dumb: Failed to get PRIME handle`) is VirtualBox-specific. Check by hand in VirtualBox 7 with VMSVGA and 3D off, using `scripts/wl-test/vm-guest/wlt-guest` in an installed system.

### Results with libluxcomp (2026-11-20)

`WLT_VM_COMP=luxcomp`, packages from `./build.sh one` (wlroots0.20 0.20.2-1.1, luxcomp 0.1.0-1), same guest and host as above.
PSS is luxcomp-demo on the empty desktop / after the scenario (one window left). Slides: distinct captured frames within
0.6 s of the key press (out / back; the windows leave the screen halfway through the first slide) and frames rendered
by libluxcomp per 420 ms slide.

| config | renderer picked (headless in the same VM) | idle / scenario flags | PSS idle / after | slides |
|---|---|---|---|---|
| std-auto | pixman, no DRM render node (pixman) | 0 / 0 | 11.3 / 18.1 MB | 6/11 captured, 31-33 rendered, slowest 0.47 ms |
| std-pixman | pixman | 0 / 0 | 11.4 / 18.1 MB | 6/11, 28-33 |
| virtio-auto | **pixman, virtio-gpu without virgl** (pixman) | 0 / 0 (2 runs), 0 / 1 (1 run, see below) | 11.3 / 18.0 MB | 6/12, 31-34 |
| virtio-pixman | pixman | 0 / 0 | 11.3 / 18.1 MB | 6/12, 33 |

Compared with labwc on virtio-auto (116.7 MB idle with GLES2 on kms_swrast), libluxcomp stays on pixman at ~11 MB.
The one virtio-auto flag was a capture stall: `screendump` took 65-70 ms, the guest drew only 18 slide frames, and the
windows jumped further than their own width between two captures, so the frame in between looks like a `transient`.
The frames themselves were complete.

## Tests

```sh
env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
  systemd-run --user --scope -p TasksMax=300 -- timeout 600 \
  python3 -m unittest scripts/wl-test/tests/test_wl_harness.py
# also check the detector on real VM frames (needs a run with WLT_KEEP_FRAMES=1):
WLT_FRAMES_DIR=out/wl-test/vm-runs/TIME/std-auto/scenario python3 -m unittest ...
```
