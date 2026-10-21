#!/usr/bin/env python3
"""LuxOS - logo pro fastfetch vykreslene znaky Unicode (barvy 24 bit, bez obrazkoveho protokolu).

Pouziti: render-terminal-logo.py [--rows N] [--aspect A] [--out SOUBOR] [--preview PNG]

Tvar se bere primo z vektoru luxos-logo.svg (cesta M/C/Z), stinovani (lesk) z luxos-logo.png.
Kazda bunka terminalu se porovna se sadou znaku, ktere VTE (xfce4-terminal) kresli sam
bez ohledu na font: bloky a ctvrtiny (U+2580-259F), sextanty (U+1FB00-1FB3B) a sikme kliny
(U+1FB3C-1FB67). Vybere se znak s nejmensi odchylkou od pokryti, barva popredi = prumer
prechodu modra -> fialova se svetlym leskem; pozadi zustava pruhledne (svetly i tmavy motiv).
Vystup se commituje (beh terminalu tak nepotrebuje Python ani knihovny).
"""
import argparse
import os
import re
import unicodedata

import cairo
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "packages/luxos-branding/files/logo/luxos-logo.svg")
PNG = os.path.join(ROOT, "packages/luxos-branding/files/logo/luxos-logo.png")
OUT = os.path.join(ROOT, "packages/luxos-shell/files/fastfetch/logo.ans")

SW, SH = 12, 26          # rozliseni jedne bunky pri porovnavani tvaru (sirka x vyska)

# Prechod loga (stejny jako v SVG) a barva lesku
STOPS = [(0.0, (0x7a, 0xb8, 0xff)), (0.5, (0x5b, 0x7c, 0xff)), (1.0, (0xa0, 0x6b, 0xff))]
G1, G2 = np.array([40.0, 30.0]), np.array([225.0, 230.0])
HIGHLIGHT = np.array([236.0, 242.0, 255.0])


def svg_path():
    d = re.search(r'\sd="([^"]+)"', open(SVG).read()).group(1)
    return re.findall(r"[MCZ]|-?\d+(?:\.\d+)?", d)


def rasterize(tokens, w, h, x0, y0, scale):
    """Pokryti 0..1 (vyhlazene) cesty loga do mrizky w x h."""
    surf = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
    cr = cairo.Context(surf)
    cr.translate(-x0 * scale, -y0 * scale)
    cr.scale(scale, scale)
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "M":
            cr.move_to(float(tokens[i + 1]), float(tokens[i + 2])); i += 3
        elif t == "C":
            cr.curve_to(*map(float, tokens[i + 1:i + 7])); i += 7
        elif t == "Z":
            cr.close_path(); i += 1
        else:
            raise SystemExit("neznamy prikaz cesty: " + t)
    cr.fill()
    surf.flush()
    stride = surf.get_stride()
    a = np.frombuffer(surf.get_data(), np.uint8).reshape(h, stride)[:, :w]
    return a.astype(float) / 255


def gradient(px, py):
    """Barva prechodu SVG v souradnicich loga (px, py)."""
    d = G2 - G1
    t = np.clip(((px - G1[0]) * d[0] + (py - G1[1]) * d[1]) / (d @ d), 0, 1)
    out = np.zeros(t.shape + (3,))
    for (o1, c1), (o2, c2) in zip(STOPS, STOPS[1:]):
        m = (t >= o1) & (t <= o2)
        f = ((t - o1) / (o2 - o1))[..., None]
        out[m] = (np.array(c1) * (1 - f) + np.array(c2) * f)[m]
    return out


# --- masky znaku ---------------------------------------------------------
def _box(x0, y0, x1, y1):
    m = np.zeros((SH, SW))
    m[int(round(y0 * SH)):int(round(y1 * SH)), int(round(x0 * SW)):int(round(x1 * SW))] = 1
    return m


PTS = {"UPPER LEFT": (0, 0), "UPPER CENTRE": (.5, 0), "UPPER RIGHT": (1, 0),
       "UPPER MIDDLE LEFT": (0, 1 / 3), "UPPER MIDDLE RIGHT": (1, 1 / 3),
       "LOWER MIDDLE LEFT": (0, 2 / 3), "LOWER MIDDLE RIGHT": (1, 2 / 3),
       "LOWER LEFT": (0, 1), "LOWER CENTRE": (.5, 1), "LOWER RIGHT": (1, 1)}


def glyphs():
    g = {" ": np.zeros((SH, SW)), "█": np.ones((SH, SW)),
         "▀": _box(0, 0, 1, .5), "▄": _box(0, .5, 1, 1), "▌": _box(0, 0, .5, 1), "▐": _box(.5, 0, 1, 1),
         "▔": _box(0, 0, 1, 1 / 8), "▕": _box(7 / 8, 0, 1, 1)}
    for k in range(1, 8):                                    # ▁..▇ a ▉..▏
        g[chr(0x2580 + k)] = _box(0, 1 - k / 8, 1, 1)
        g[chr(0x2590 - k)] = _box(0, 0, k / 8, 1)
    quads = {"▖": "3", "▗": "4", "▘": "1", "▙": "134", "▚": "14", "▛": "123", "▜": "124",
             "▝": "2", "▞": "23", "▟": "234"}
    qpos = {"1": (0, 0), "2": (.5, 0), "3": (0, .5), "4": (.5, .5)}
    for ch, parts in quads.items():
        g[ch] = sum(_box(x, y, x + .5, y + .5) for x, y in (qpos[p] for p in parts))
    for c in range(0x1FB00, 0x1FB3C):                        # sextanty 1..6 (2 sloupce x 3 radky)
        parts = unicodedata.name(chr(c)).split("-")[1]
        m = np.zeros((SH, SW))
        for p in parts:
            n = int(p) - 1
            m = np.maximum(m, _box((n % 2) / 2, (n // 2) / 3, (n % 2) / 2 + .5, (n // 2 + 1) / 3))
        g[chr(c)] = m
    yy, xx = (np.mgrid[0:SH, 0:SW] + .5) / np.array([SH, SW])[:, None, None]
    for c in range(0x1FB3C, 0x1FB68):                        # kliny: cast bunky u jmenovaneho rohu
        corner, line = unicodedata.name(chr(c)).split(" BLOCK DIAGONAL ")
        a, b = (PTS[s] for s in line.split(" TO "))
        cx, cy = PTS[corner]
        side = lambda x, y: (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        m = (np.sign(side(xx, yy)) == np.sign(side(cx, cy))).astype(float)
        # skoro plne / skoro prazdne kliny delaji na mirne zakrivene hrane pilu - vynechat
        if 0.2 <= m.mean() <= 0.8:
            g[chr(c)] = m
    return g


def _soft(m):
    """Lehke rozmazani (3x3) - hrany pak maji smer, ktery se da porovnat."""
    p = np.pad(m, 1, mode="edge")
    return sum(p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
               for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9


def features(m):
    """Pokryti + smer hran (gradienty); zuby na rovne hrane maji jiny smer nez predloha."""
    s = _soft(m)
    gy, gx = np.gradient(s)
    return np.concatenate([m.reshape(-1), EDGE * gx.reshape(-1) * SW, EDGE * gy.reshape(-1) * SH])


EDGE = 0.0
WEDGE = 0.01


def main():
    global EDGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=18)
    ap.add_argument("--aspect", type=float, default=2.1, help="vyska/sirka bunky terminalu")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--edge", type=float, default=EDGE, help="vaha smeru hran pri vyberu znaku")
    ap.add_argument("--wedge", type=float, default=WEDGE, help="penalizace sikmych klinu (proti zubum)")
    ap.add_argument("--preview", help="PNG s idealnim vykreslenim znaku (kontrola bez terminalu)")
    args = ap.parse_args()
    EDGE = args.edge

    tokens = svg_path()
    # bbox z hustych vzorku (kontrolni body Bezierovych krivek lezi mimo tvar)
    probe = rasterize(tokens, 1024, 1024, 0, 0, 4)
    ys, xs = np.nonzero(probe > 0.02)
    bx0, bx1, by0, by1 = xs.min() / 4, (xs.max() + 1) / 4, ys.min() / 4, (ys.max() + 1) / 4

    rows = args.rows
    scale = rows * SH / (by1 - by0)                           # px rastru na jednotku SVG
    cols = int(np.ceil((bx1 - bx0) / (by1 - by0) * rows * args.aspect))
    w, h = cols * SW, rows * SH
    # vycentrovat vodorovne v celych bunkach
    x0 = (bx0 + bx1) / 2 - w / scale / 2
    cov = rasterize(tokens, w, h, x0, by0, scale)

    # barvy: prechod + lesk z PNG predlohy (svetle hrany cepeli)
    py, px = np.mgrid[0:h, 0:w].astype(float)
    lx, ly = x0 + (px + .5) / scale, by0 + (py + .5) / scale
    col = gradient(lx, ly)
    src = np.asarray(Image.open(PNG).convert("RGBA")).astype(float) / 255
    sx = np.clip((lx / 256 * src.shape[1]).astype(int), 0, src.shape[1] - 1)
    sy = np.clip((ly / 256 * src.shape[0]).astype(int), 0, src.shape[0] - 1)
    lum = np.clip((src[sy, sx, :3].mean(-1) - 0.55) / 0.45, 0, 1)
    col = col * (0.80 + 0.20 * lum[..., None])
    col = col + (HIGHLIGHT - col) * (lum ** 2.0 * 0.55)[..., None]

    g = glyphs()
    names = list(g)
    masks = np.stack([g[n] for n in names]).reshape(len(names), -1)
    feats = np.stack([features(g[n]) for n in names])
    is_wedge = np.array([0x1FB3C <= ord(n) <= 0x1FB67 for n in names])
    bias = is_wedge * args.wedge * SW * SH
    lines, prev = [], np.zeros((h, w))
    for r in range(rows):
        out, last, prev_k = [], None, 0
        for c in range(cols):
            cell2 = cov[r * SH:(r + 1) * SH, c * SW:(c + 1) * SW]
            cell = cell2.reshape(-1)
            err = ((feats - features(cell2)) ** 2).sum(1) + bias
            # stejny klin vedle sebe = pila; radsi rovna hrana
            if c and is_wedge[prev_k]:
                err[prev_k] += args.wedge * SW * SH * 2
            k = int(np.argmin(err))
            ch = names[k]
            prev_k = k
            if ch == " ":
                if last is not None:
                    out.append("\x1b[39m"); last = None
                out.append(" ")
                continue
            m = masks[k] * np.maximum(cell, 0.3)
            cc = col[r * SH:(r + 1) * SH, c * SW:(c + 1) * SW].reshape(-1, 3)
            rgbv = tuple(int(round(v)) for v in (cc * m[:, None]).sum(0) / m.sum())
            if rgbv != last:
                out.append("\x1b[38;2;%d;%d;%dm" % rgbv); last = rgbv
            out.append(ch)
            prev[r * SH:(r + 1) * SH, c * SW:(c + 1) * SW] = masks[k].reshape(SH, SW) * 255
        lines.append("".join(out).rstrip(" ") + "\x1b[0m")
    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{args.out}: {cols}x{rows}")
    if args.preview:
        Image.fromarray(prev.astype(np.uint8)).save(args.preview)


if __name__ == "__main__":
    main()
