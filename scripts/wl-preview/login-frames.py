#!/usr/bin/env python3
"""Prubeh obrazu pri prihlaseni ve zkusebni VM: greeter -> snimek greeteru s barem -> plocha bez cerne mezery.

  login-frames.py VM_DIR OUT_DIR [HESLO] [SEKUND]

Prihlasovaci obrazovka uz musi byt videt. Napise heslo (QMP send-key), stiskne Enter a snimky QMP screendump
bere tak rychle, jak QEMU stihne (jedno spojeni QMP), SEKUND (vychozi 8) od Enteru. Snimek je "dark" (vsech 10
vodorovnych pruhu ma prumerny jas < 25: textova konzole, cerna scena), "torn" (jen nektere pruhy: obraz se
prave prepisuje) nebo "light". Vypise casy zmen a pocty a zmensene snimky ulozi do OUT_DIR (f0000.png...).
Konec kodem 1, kdyz po Enteru byl nejaky tmavy nebo roztrzeny snimek.
"""
import json
import os
import socket
import sys
import time

KEYS = {" ": "spc"}


class Qmp:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(10)
        self.s.connect(path)
        self.f = self.s.makefile("rwb")
        self.f.readline()
        self.call("qmp_capabilities")

    def call(self, cmd, args=None):
        self.f.write(json.dumps({"execute": cmd, "arguments": args or {}}).encode() + b"\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                raise RuntimeError("QMP closed")
            r = json.loads(line)
            if "return" in r or "error" in r:
                return r

    def key(self, *keys):
        self.call("send-key", {"keys": [{"type": "qcode", "data": k} for k in keys]})
        time.sleep(0.05)


def bands(path):
    """Prumerny jas 10 vodorovnych pruhu"""
    with open(path, "rb") as f:
        data = f.read()
    _, w, h, _, px = data.split(maxsplit=4)
    w, h = int(w), int(h)
    out = []
    for k in range(10):
        part = px[k * h // 10 * w * 3:(k + 1) * h // 10 * w * 3:3 * 97]
        out.append(sum(part) / len(part))
    return out


def kind(b):
    dark = sum(1 for v in b if v < 25)
    return "dark" if dark == len(b) else "torn" if dark else "light"


def thumb(src, dst):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(src)
    pb.scale_simple(pb.get_width() // 4, pb.get_height() // 4, GdkPixbuf.InterpType.BILINEAR).savev(dst, "png", [], [])


def main():
    vm, out = sys.argv[1], sys.argv[2]
    password = sys.argv[3] if len(sys.argv) > 3 else "luxos"
    limit = float(sys.argv[4]) if len(sys.argv) > 4 else 8
    os.makedirs(out, exist_ok=True)
    q = Qmp(os.path.join(vm, "qmp.sock"))
    frame = os.path.join(out, "frame.ppm")
    for ch in password:
        q.key(KEYS.get(ch, ch))
    shots = []
    q.key("ret")
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        t = time.monotonic() - t0
        q.call("screendump", {"filename": frame})
        path = os.path.join(out, f"f{len(shots):04d}.ppm")
        os.rename(frame, path)
        shots.append((t, path, bands(path)))
    kinds = [(t, kind(b), sum(b) / len(b), p) for t, p, b in shots]
    prev = None
    for t, k, m, p in kinds:
        if k != prev:
            print(f"{t:6.2f} s {k} (mean {m:.0f}) {os.path.basename(p)}")
            prev = k
    dark = [x for x in kinds if x[1] == "dark"]
    torn = [x for x in kinds if x[1] == "torn"]
    fps = len(shots) / limit
    print(f"frames={len(shots)} fps={fps:.1f} dark_frames={len(dark)} torn_frames={len(torn)}"
          + (f" first_bad={min(x[0] for x in dark + torn):.2f}" if dark or torn else ""))
    for t, p, m in shots:
        thumb(p, p[:-4] + ".png")
        os.unlink(p)
    return 1 if dark or torn else 0


if __name__ == "__main__":
    sys.exit(main())
