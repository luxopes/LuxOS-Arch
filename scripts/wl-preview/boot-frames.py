#!/usr/bin/env python3
"""Prubeh obrazu pri startu zkusebni VM: splash Plymouthu az do prihlasovaci obrazovky bez cerne mezery.

  boot-frames.py QMP_SOCK OUT_DIR [SEKUND]

Snimky QMP screendump co 0,1 s, z kazdeho jen par cisel (ulozi se prvni snimek splashe a prvni snimek
greeteru). Snimek je "greeter" (rozostrena tapeta), "splash" (temer cerne pozadi a svetle logo uprostred),
"flat" (jednolita svetla plocha) nebo "dark" (cerna, textova konzole). Vypise casy a skonci kodem 1, kdyz mezi
prvnim snimkem splashe a greeterem byl snimek "flat", temna mezera byla delsi nez DARK_GAP_MAX nebo se splash
vubec neukazal.
"""
import json
import os
import shutil
import socket
import sys
import time

# Mezi splashem a greeterem zustava kratka temna mezera (luxwm modesetuje az po plymouth deactivate a greeter
# kresli prvni snimek az pak); delsi znamena, ze splash skoncil driv nez greeter (cerna obrazovka, konzole)
DARK_GAP_MAX = 3.0

def qmp(path, cmd, args):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(path)
    f = s.makefile("rwb")
    f.readline()
    f.write(b'{"execute":"qmp_capabilities"}\n'); f.flush(); f.readline()
    f.write(json.dumps({"execute": cmd, "arguments": args}).encode() + b"\n"); f.flush()
    while True:
        line = f.readline()
        if not line or b'"return"' in line or b'"error"' in line:
            break
    s.close()


def classify(path):
    with open(path, "rb") as f:
        data = f.read()
    _, w, h, _, px = data.split(maxsplit=4)
    w, h = int(w), int(h)
    values = []
    centre = 0
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            i = (y * w + x) * 3
            v = (px[i] + px[i + 1] + px[i + 2]) // 3
            values.append(v)
            if v > 90 and abs(x - w // 2) < w // 6 and abs(y - h // 2) < h // 4:
                centre += 1
    mean = sum(values) / len(values)
    spread = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if mean > 60:
        return ("greeter" if spread > 6 else "flat"), mean
    if centre >= 4:
        return "splash", mean
    return ("dark" if mean < 20 else "flat"), mean


def main():
    sock, out = sys.argv[1], sys.argv[2]
    limit = float(sys.argv[3]) if len(sys.argv) > 3 else 120
    os.makedirs(out, exist_ok=True)
    frame = os.path.join(out, "frame.ppm")
    t0 = time.monotonic()
    seen = []          # (cas, druh)
    greeter_since = None
    while time.monotonic() - t0 < limit:
        t = time.monotonic() - t0
        try:
            qmp(sock, "screendump", {"filename": frame})
            kind, mean = classify(frame)
        except (OSError, ValueError):
            time.sleep(0.2)
            continue
        if not seen or seen[-1][1] != kind:
            seen.append((t, kind))
            print(f"{t:6.1f} s {kind} (mean {mean:.0f})", flush=True)
            if kind in ("splash", "greeter"):
                shutil.copy(frame, os.path.join(out, f"first-{kind}.ppm"))
        if kind == "greeter":
            greeter_since = greeter_since or t
            if t - greeter_since > 2:
                break
        else:
            greeter_since = None
        time.sleep(0.1)
    os.unlink(frame)
    kinds = [k for _, k in seen]
    if "splash" not in kinds or "greeter" not in kinds:
        print("no splash or no greeter")
        return 1
    first = kinds.index("splash")
    last = kinds.index("greeter", first)
    splash_s = seen[last][0] - seen[first][0]
    # temne pozadi mezi koncem splashe a prvnim snimkem greeteru (plymouth deactivate -> luxwm -> greeter)
    dark_s = sum(seen[i + 1][0] - seen[i][0] for i in range(first, last) if seen[i][1] == "dark")
    print(f"splash_to_greeter_s={splash_s:.1f}")
    print(f"dark_gap_s={dark_s:.1f}")
    if "flat" in kinds[first:last]:
        print("flat (bright) frame between the splash and the greeter")
        return 1
    if dark_s > DARK_GAP_MAX:
        print(f"dark gap longer than {DARK_GAP_MAX} s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
