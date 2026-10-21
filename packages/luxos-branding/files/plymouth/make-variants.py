#!/usr/bin/env python3
"""LuxOS - barevne varianty boot splashe (Plymouth).

Pouziti: make-variants.py LOGO.png SCRIPT_TEMPLATE OUTDIR [--preview DIR]

Pro kazdou variantu vytvori v OUTDIR/<motiv>/ kompletni motiv Plymouth (obrazky,
luxos.script, <motiv>.plymouth) a v OUTDIR/previews/<varianta>.png nahled pro Nastaveni.
Kazda varianta je samostatny motiv - aktivni se vybira v /etc/plymouth/plymouthd.conf
(luxos-splash set), do initramfs se tak dostane jen jedna sada obrazku.
"""
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float) / 255


# varianta: motiv, okraj a stred pozadi (temer cerne, jen nadech barvy), barva loga a zare,
# vypln/draha baru (jasna vypln, tlumena draha)
VARIANTS = {
    "blue":   dict(theme="luxos", name="Blue", edge="#010207", center="#081226", tint="#5d95ff",
                   glow="#3a76ff", core="#f2f7ff", fill="#eef4ff", track=("#7f9fe0", 0.15), dark=True),
    "purple": dict(theme="luxos-purple", name="Purple", edge="#030108", center="#110a26", tint="#a07cff",
                   glow="#7f4dff", core="#f7f2ff", fill="#f3eeff", track=("#a993e0", 0.15), dark=True),
    "orange": dict(theme="luxos-orange", name="Orange", edge="#050201", center="#1d0f05", tint="#ff9a52",
                   glow="#ff7417", core="#fff6ee", fill="#fff3e8", track=("#e0aa84", 0.15), dark=True),
    "green":  dict(theme="luxos-green", name="Green", edge="#010402", center="#06180d", tint="#4fd68c",
                   glow="#1fbf66", core="#effff5", fill="#ecfcf2", track=("#86d0a8", 0.15), dark=True),
    "light":  dict(theme="luxos-light", name="Light", edge="#d6d6da", center="#f0f0f2", tint="#2a2c32",
                   glow="#000000", core="#6b6f78", fill="#2a2c32", track=("#2a2c32", 0.12), dark=False),
}

CANVAS = 640          # logo.png: platno se zari
MARK = 384            # velikost znacky uvnitr platna (pomer MARK/CANVAS = 0.6, viz luxos.script)
SS = 4                # nadvzorkovani pro hladke tvary


def rounded(w, h, color, alpha=1.0, outline=None):
    """Zaobleny obdelnik (bar, pole hesla) s vyhlazenymi okraji."""
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = tuple(int(v * 255) for v in rgb(color)) + (int(alpha * 255),)
    if outline:
        oc = tuple(int(v * 255) for v in rgb(outline[0])) + (int(outline[1] * 255),)
        d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=h * SS // 2, fill=oc)
        d.rounded_rectangle([SS, SS, w * SS - 1 - SS, h * SS - 1 - SS], radius=h * SS // 2 - SS, fill=c)
    else:
        d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=h * SS // 2, fill=c)
    return big.resize((w, h), Image.LANCZOS)


def circle(size, color, alpha=1.0):
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    c = tuple(int(v * 255) for v in rgb(color)) + (int(alpha * 255),)
    ImageDraw.Draw(big).ellipse([SS // 2, SS // 2, size * SS - SS // 2, size * SS - SS // 2], fill=c)
    return big.resize((size, size), Image.LANCZOS)


def colored(layer_alpha, color, opacity):
    img = Image.new("RGBA", layer_alpha.size, tuple(int(v * 255) for v in rgb(color)) + (0,))
    img.putalpha(layer_alpha.point(lambda a: int(a * opacity)))
    return img


def blur(a, r):
    img = Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8), "L")
    return np.asarray(img.filter(ImageFilter.GaussianBlur(r))).astype(float) / 255


def make_logo(src, v):
    """Logo v barve varianty: svetle jadro podel cepeli (bily lesk), syta barva u okraju, mekka zare."""
    m = src.resize((MARK, MARK), Image.LANCZOS)
    a = np.asarray(m).astype(float) / 255
    alpha = a[..., 3]
    # stinovani predlohy bez tmaveho lemu (normalizovana konvoluce vahou alfa)
    lum = blur(a[..., :3].mean(2) * alpha, 1.2) / np.maximum(blur(alpha, 1.2), 1e-3)
    lum = np.clip((lum - 0.45) / 0.55, 0, 1)
    # "jadro" cepele: vnitrek tvaru daleko od okraju -> bily lesk podel tahu
    core = np.clip((blur(alpha, MARK * 0.012) * alpha - 0.55) / 0.40, 0, 1)
    t, c = rgb(v["tint"]), rgb(v["core"])
    if v["dark"]:
        col = t * (0.85 + 0.30 * lum[..., None])
        hl = np.clip(0.75 * core + 0.45 * lum ** 2, 0, 1)[..., None]
        col = col + (c - col) * hl
    else:
        # grafitove logo na svetle sedem pozadi, jen jemny svetlejsi lesk
        hl = np.clip(0.35 * core * lum + 0.25 * lum ** 3, 0, 1)[..., None]
        col = t + (c - t) * hl
    mark = Image.fromarray((np.dstack([np.clip(col, 0, 1), alpha]) * 255 + .5).astype(np.uint8), "RGBA")

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    off = (CANVAS - MARK) // 2
    shape = Image.new("L", (CANVAS, CANVAS), 0)
    shape.paste(mark.split()[3], (off, off))
    # bez tecky (prani uzivatele): jen znacka se zarou
    if v["dark"]:
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.14)), v["glow"], 0.55))
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.045)), v["glow"], 0.85))
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.010)), v["tint"], 0.55))
    else:
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.05)), "#000000", 0.16))
    canvas.alpha_composite(mark, (off, off))
    return canvas


def make_background(v, w=768, h=432):
    """Temer cerne (svetle u Light) pozadi, za logem jen jemny nadech barvy; dithering proti pruhum."""
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    r = np.sqrt(((xx / w - 0.5) * 1.25) ** 2 + ((yy / h - 0.44) * 0.95) ** 2)
    f = np.clip(1 - r / 0.62, 0, 1) ** 2.2
    col = rgb(v["edge"]) * (1 - f[..., None]) + rgb(v["center"]) * f[..., None]
    rnd = np.random.default_rng(7)
    col = col * 255 + rnd.uniform(-0.5, 0.5, col.shape) + rnd.uniform(-0.5, 0.5, col.shape)
    return Image.fromarray(np.clip(col + .5, 0, 255).astype(np.uint8), "RGB")


def script_for(template, v):
    tr, tg, tb = (1, 1, 1) if v["dark"] else (0.13, 0.13, 0.15)
    er, eg, eb = rgb(v["edge"])
    block = (f"# @variant-begin (dosazuje make-variants.py: {v['name']})\n"
             f"bg_r = {er:.3f}; bg_g = {eg:.3f}; bg_b = {eb:.3f};\n"
             f"text_r = {tr}; text_g = {tg}; text_b = {tb};\n"
             f"# @variant-end")
    out, n = re.subn(r"# @variant-begin.*?# @variant-end", block, template, flags=re.S)
    if n != 1:
        sys.exit("luxos.script: chybi blok @variant-begin/@variant-end")
    return out


def preview(theme_dir, v, w, h):
    """Slozeni obrazovky stejne jako luxos.script (pro nahledy a kontrolu)."""
    img = Image.open(os.path.join(theme_dir, "background.png")).convert("RGBA").resize((w, h), Image.BILINEAR)
    logo_size = max(int(h * 0.16), 80)
    lw = int(logo_size / (MARK / CANVAS))
    logo = Image.open(os.path.join(theme_dir, "logo.png")).resize((lw, lw), Image.LANCZOS)
    ly = h / 2 - logo_size / 2 - h * 0.04
    img.alpha_composite(logo, (int(w / 2 - lw / 2), int(ly - (lw - logo_size) / 2)))
    track = Image.open(os.path.join(theme_dir, "bar-track.png"))
    fill = Image.open(os.path.join(theme_dir, "bar-fill.png"))
    s = max(w / 1920, 0.35)
    bw, bh = max(int(track.width * s), 8), max(int(track.height * s), 2)
    by = int(ly + logo_size + h * 0.07)
    bx = int(w / 2 - bw / 2)
    img.alpha_composite(track.resize((bw, bh), Image.LANCZOS), (bx, by))
    img.alpha_composite(fill.resize((int(bw * 0.55), bh), Image.LANCZOS), (bx, by))
    return img.convert("RGB")


def main():
    args = sys.argv[1:]
    prev_dir = None
    if "--preview" in args:
        i = args.index("--preview")
        prev_dir = args[i + 1]
        del args[i:i + 2]
    logo_path, template_path, out = args
    src = Image.open(logo_path).convert("RGBA")
    template = open(template_path).read()
    os.makedirs(os.path.join(out, "previews"), exist_ok=True)
    for key, v in VARIANTS.items():
        d = os.path.join(out, v["theme"])
        os.makedirs(d, exist_ok=True)
        make_logo(src, v).save(os.path.join(d, "logo.png"), optimize=True)
        make_background(v).save(os.path.join(d, "background.png"), optimize=True)
        rounded(220, 6, v["fill"]).save(os.path.join(d, "bar-fill.png"))
        rounded(220, 6, v["track"][0], v["track"][1]).save(os.path.join(d, "bar-track.png"))
        if v["dark"]:
            rounded(260, 36, v["tint"], 0.10, outline=("#ffffff", 0.35)).save(os.path.join(d, "entry.png"))
            circle(10, "#ffffff").save(os.path.join(d, "bullet.png"))
        else:
            rounded(260, 36, "#ffffff", 0.75, outline=("#000000", 0.28)).save(os.path.join(d, "entry.png"))
            circle(10, "#26272c").save(os.path.join(d, "bullet.png"))
        with open(os.path.join(d, "luxos.script"), "w") as f:
            f.write(script_for(template, v))
        with open(os.path.join(d, v["theme"] + ".plymouth"), "w") as f:
            f.write("[Plymouth Theme]\n"
                    f"Name=LuxOS ({v['name']})\n"
                    f"Description=LuxOS boot splash, {v['name'].lower()} variant\n"
                    "ModuleName=script\n\n[script]\n"
                    f"ImageDir=/usr/share/plymouth/themes/{v['theme']}\n"
                    f"ScriptFile=/usr/share/plymouth/themes/{v['theme']}/luxos.script\n")
        # nahled pro Nastaveni: stred obrazovky 1920x1080 (logo a bar), at je v malem videt
        preview(d, v, 1920, 1080).crop((480, 220, 1440, 760)).resize((240, 135), Image.LANCZOS).save(
            os.path.join(out, "previews", key + ".png"), optimize=True)
        if prev_dir:
            os.makedirs(prev_dir, exist_ok=True)
            preview(d, v, 1920, 1080).save(os.path.join(prev_dir, f"splash-{key}.png"))


if __name__ == "__main__":
    main()
