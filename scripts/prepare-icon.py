#!/usr/bin/env python3
"""Pripravi ikonu aplikace z obrazku na bilem pozadi.

  prepare-icon.py VSTUP.png VYSTUP.png

Desku ikony najde prahem proti bile, prolozi ji superelipsou (tvar a zaobleni
se dopocitaji podle obrazku) a jeji vyhlazenou masku pouzije jako pruhlednost.
Vystup ma 512x512 px s deskou 448 px jako ikony WhiteSur.
"""
import sys

import numpy as np
from PIL import Image

SIZE, PLATE = 512, 448
SS = 4  # nadvzorkovani masky kvuli vyhlazeni hran


def superellipse(w, h, n, inset=0.0):
    """Maska superelipsy |x|^n + |y|^n <= 1 vepsane do w x h (hodnoty 0..1)."""
    ys, xs = np.mgrid[0:h * SS, 0:w * SS]
    cx, cy = (w * SS - 1) / 2, (h * SS - 1) / 2
    rx, ry = cx - inset * SS, cy - inset * SS
    inside = (np.abs((xs - cx) / rx) ** n + np.abs((ys - cy) / ry) ** n) <= 1
    return inside.reshape(h, SS, w, SS).mean(axis=(1, 3))


def main(src, dst):
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(np.int32)
    # Deska = vse, co se zretelne lisi od bileho pozadi
    plate = (255 * 3 - rgb.sum(axis=2)) > 45
    ys, xs = np.where(plate)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = rgb[y0:y1, x0:x1]
    ref = plate[y0:y1, x0:x1]
    h, w = ref.shape

    # Exponent superelipsy s nejlepsi shodou s prahovanou deskou (v nizsim rozliseni)
    small = Image.fromarray(ref.astype(np.uint8) * 255).resize((w // 4, h // 4))
    small = np.asarray(small) > 127
    best = max(np.arange(3.0, 8.01, 0.25),
               key=lambda n: (superellipse(w // 4, h // 4, n) > 0.5)[small].mean()
               - (superellipse(w // 4, h // 4, n) > 0.5)[~small].mean())

    # Mirne zuzena maska odrizne svetly lem po bilem pozadi
    alpha = superellipse(w, h, best, inset=max(w, h) * 0.006)
    rgba = np.dstack([crop, (alpha * 255).round()]).astype(np.uint8)
    icon = Image.fromarray(rgba, "RGBA").resize((PLATE, PLATE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(icon, ((SIZE - PLATE) // 2, (SIZE - PLATE) // 2))
    out.save(dst, optimize=True)
    print(f"{dst}: plate {w}x{h}, n={best}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
