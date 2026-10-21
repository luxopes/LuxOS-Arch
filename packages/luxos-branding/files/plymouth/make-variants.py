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


# varianta: motiv, okraj a stred pozadi, barva loga, zare, tecka, vypln/draha baru, text
VARIANTS = {
    "blue":   dict(theme="luxos", name="Blue", edge="#03060f", center="#0f2148", tint="#5f97ff",
                   glow="#3f7bff", dot="#dfe9ff", fill="#d2e2ff", track=("#8aa6e0", 0.28), dark=True),
    "purple": dict(theme="luxos-purple", name="Purple", edge="#05030f", center="#1c1040", tint="#a47dff",
                   glow="#8657ff", dot="#ece4ff", fill="#e3d6ff", track=("#a993e0", 0.28), dark=True),
    "orange": dict(theme="luxos-orange", name="Orange", edge="#080503", center="#2b1608", tint="#ff9d55",
                   glow="#ff7722", dot="#fff0e2", fill="#ffdcbd", track=("#e0aa84", 0.28), dark=True),
    "green":  dict(theme="luxos-green", name="Green", edge="#030805", center="#0b2618", tint="#5cd391",
                   glow="#26b868", dot="#e2fbec", fill="#c9f4da", track=("#86d0a8", 0.28), dark=True),
    "light":  dict(theme="luxos-light", name="Light", edge="#dedcd6", center="#f7f6f2", tint="#6d7078",
                   glow="#ffffff", dot="#2a2b30", fill="#26272c", track=("#26272c", 0.16), dark=False),
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


def make_logo(src, v):
    """Logo v barve varianty, mekka zare a tecka vpravo nahore."""
    m = src.resize((MARK, MARK), Image.LANCZOS)
    a = np.asarray(m).astype(float) / 255
    lum = np.clip((a[..., :3].mean(2) - 0.45) / 0.55, 0, 1)[..., None]   # stinovani predlohy 0..1
    t = rgb(v["tint"])
    if v["dark"]:
        col = t * (0.62 + 0.38 * lum)
        col = col + (1 - col) * (lum ** 2.2) * 0.62              # svetla do bila (kovovy lesk)
    else:
        col = rgb("#3b3d44") * (1 - lum) + rgb("#b9bcc4") * lum   # sedy kov na svetlem pozadi
    mark = Image.fromarray((np.dstack([np.clip(col, 0, 1), a[..., 3:]]) * 255 + .5).astype(np.uint8), "RGBA")

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    off = (CANVAS - MARK) // 2
    shape = Image.new("L", (CANVAS, CANVAS), 0)
    shape.paste(mark.split()[3], (off, off))
    # tecka: v souradnicich znacky 256x256 na (212, 64), polomer 9
    k = MARK / 256
    dsz = int(round(18 * k)) | 1
    dot = circle(dsz, v["dot"])
    dpos = (int(off + 212 * k - dsz / 2), int(off + 64 * k - dsz / 2))
    shape.paste(255, dpos, dot.split()[3])
    if v["dark"]:
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.11)), v["glow"], 0.45))
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.035)), v["glow"], 0.75))
    else:
        canvas.alpha_composite(colored(shape.filter(ImageFilter.GaussianBlur(MARK * 0.06)), "#000000", 0.10))
    canvas.alpha_composite(mark, (off, off))
    canvas.alpha_composite(dot, dpos)
    return canvas


def make_background(v, w=768, h=432):
    """Tonovane pozadi: svetlejsi stred za logem, tmavsi okraje (s ditheringem proti pruhum)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    r = np.sqrt(((xx / w - 0.5) * 1.25) ** 2 + ((yy / h - 0.44) * 0.95) ** 2)
    f = np.clip(1 - r / 0.75, 0, 1) ** 1.6
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
