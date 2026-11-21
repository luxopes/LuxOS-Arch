#!/usr/bin/env python3
"""Porovnani dvou snimku stejne velikosti (PNG 8 bit RGB/RGBA) jako v testech zamku: pixel se lisi, kdyz se nektery
kanal lisi o vic nez THRESHOLD; rozdil "za hranou vyhlazeni" je jen takovy, pro ktery ani jeden obrazek nema v okoli
3x3 pixel shodny s druhym (posun hrany o pixel, vyhlazeni textu). Bez numpy/PIL.

    pixdiff.py A.png B.png [--diff OUT.png] [--threshold 16]
"""
import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

THRESHOLD = 16


def png_read(path):
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                raise ValueError(f"{path}: only 8-bit RGB/RGBA without interlace")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = width * bpp
    out = bytearray(width * height * 3)
    prev = bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + (a + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if bpp == 3:
            out[y * width * 3:(y + 1) * width * 3] = line
        else:
            row = out[y * width * 3:(y + 1) * width * 3]
            row[0::3], row[1::3], row[2::3] = line[0::4], line[1::4], line[2::4]
            out[y * width * 3:(y + 1) * width * 3] = row
    return width, height, bytes(out)


def png_write(path, width, height, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\0" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def wallpaper(path, dark, w=1600, h=1000):
    """Umela tapeta pro vzory (nezavisla na balicku tapet): plynule vlny ve svetlych nebo tmavych barvach LuxOS,
    s dost strukturou, aby se ukazal posun matnych prvku proti rozmazane tapete."""
    if dark:
        a, b, c = (22, 26, 58), (88, 44, 130), (18, 96, 128)
    else:
        a, b, c = (250, 196, 120), (238, 104, 112), (150, 204, 120)
    rows = []
    for y in range(h):
        row = bytearray(w * 3)
        cy = math.cos(y / 97.0)
        for x in range(w):
            t = x / w
            wave = 0.5 + 0.5 * math.sin(x / 83.0 + y / 61.0) * cy
            k = min(1.0, max(0.0, y / h * 0.65 + wave * 0.35))
            o = x * 3
            for i in range(3):
                top = a[i] + (b[i] - a[i]) * t
                row[o + i] = int(top + (c[i] - top) * k * 0.7)
        rows.append(bytes(row))
    png_write(path, w, h, b"".join(rows))


def close(a, i, b, j, t):
    return abs(a[i] - b[j]) <= t and abs(a[i + 1] - b[j + 1]) <= t and abs(a[i + 2] - b[j + 2]) <= t


def compare(a_path, b_path, threshold=THRESHOLD, diff_path=None):
    """-> dict(width, height, differ (pocet), beyond (za hranou vyhlazeni), ratio, boxes)"""
    w, h, a = png_read(a_path)
    w2, h2, b = png_read(b_path)
    if (w, h) != (w2, h2):
        raise ValueError(f"size {w}x{h} != {w2}x{h2}")
    differ = 0
    bad = []
    t = threshold
    # rychly pruchod po radcich: shodne radky preskocit
    for y in range(h):
        ra = a[y * w * 3:(y + 1) * w * 3]
        rb = b[y * w * 3:(y + 1) * w * 3]
        if ra == rb:
            continue
        for x in range(w):
            i = (y * w + x) * 3
            if close(a, i, b, i, t):
                continue
            differ += 1
            ok = False
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if xx < 0 or xx >= w or (dx == 0 and dy == 0):
                        continue
                    j = (yy * w + xx) * 3
                    if close(a, i, b, j, t) or close(b, i, a, j, t):
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                bad.append((x, y))
    if diff_path:
        out = bytearray(bytes(v // 3 for v in a))
        for x, y in bad:
            i = (y * w + x) * 3
            out[i:i + 3] = b"\xff\x00\xff"
        png_write(diff_path, w, h, bytes(out))
    box = None
    if bad:
        xs = [p[0] for p in bad]
        ys = [p[1] for p in bad]
        box = (min(xs), min(ys), max(xs), max(ys))
    return {"width": w, "height": h, "differ": differ, "beyond": len(bad), "ratio": len(bad) / (w * h), "box": box}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--diff")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    args = ap.parse_args()
    r = compare(args.a, args.b, args.threshold, args.diff)
    print(f"{r['beyond']} px beyond AA ({100 * r['ratio']:.3f} %), {r['differ']} differ, box {r['box']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
