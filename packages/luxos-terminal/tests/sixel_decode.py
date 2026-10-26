#!/usr/bin/env python3
"""Jednoduchy dekoder SIXEL pro testy (palety v RGB procentech, opakovani !N, $ a -).

    sixel_decode.py VSTUP.six VYSTUP.png [POZADI #rrggbb]
"""
import re
import sys


def decode(data):
    """Vrati (sirka, vyska, pixely) - pixely: slovnik (x, y) -> (r, g, b) jen nakreslenych bodu."""
    start = data.index("\x1bP")
    q = data.index("q", start)
    body = data[q + 1:data.index("\x1b\\", q)]
    w = h = 0
    m = re.match(r'"(\d+);(\d+);(\d+);(\d+)', body)
    if m:
        w, h = int(m.group(3)), int(m.group(4))
        body = body[m.end():]
    pal, px = {}, {}
    color, x, y = 0, 0, 0
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "#":
            m = re.match(r"#(\d+)(?:;(\d+);(\d+);(\d+);(\d+))?", body[i:])
            color = int(m.group(1))
            if m.group(2):
                pal[color] = tuple(round(int(m.group(k)) * 255 / 100) for k in (3, 4, 5))
            i += m.end()
            continue
        if c == "!":
            m = re.match(r"!(\d+)(.)", body[i:])
            reps, ch = int(m.group(1)), m.group(2)
            i += m.end()
        elif "?" <= c <= "~":
            reps, ch = 1, c
            i += 1
        else:
            if c == "$":
                x = 0
            elif c == "-":
                x, y = 0, y + 6
            i += 1
            continue
        bits = ord(ch) - 63
        for _ in range(reps):
            for k in range(6):
                if bits & (1 << k):
                    px[(x, y + k)] = pal.get(color, (0, 0, 0))
            x += 1
    return w, h, px


def main():
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    data = open(sys.argv[1], encoding="latin-1").read()
    w, h, px = decode(data)
    bg = sys.argv[3] if len(sys.argv) > 3 else "#000000"
    bgc = tuple(int(bg[k:k + 2], 16) for k in (1, 3, 5))
    buf = bytearray(bytes(bgc) * (w * h))
    for (x, y), rgb in px.items():
        if x < w and y < h:
            buf[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes(rgb)
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(buf)), GdkPixbuf.Colorspace.RGB, False, 8, w, h, w * 3)
    pb.savev(sys.argv[2], "png", [], [])
    print(f"{w}x{h}, {len(px)} pixels")


if __name__ == "__main__":
    main()
