"""Spolecne pro postupy skupiny d (Tiskarny a skenery, Skener): ukazkove naskenovane stranky
a falesne prikazy v PATH (scanimage, lpq, avahi-browse, ipptool, pkexec) - zadna skutecna tiskarna,
skener, CUPS ani heslo spravce. Soubory zacinajici "_" nejsou postupy."""
import math
import os

W, H = 1240, 1754                 # A4 pri 150 dpi

FAKE_SCANIMAGE = r'''#!/usr/bin/env python3
"""Falesny scanimage pro snimky Obchodu: jeden skener, stranky z DEMO_SCAN_PAGES (dokola)."""
import os, shutil, sys, time
args = sys.argv[1:]

def opt(name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None

if "-f" in args or "-L" in args:
    sys.stdout.write("airscan:e0:HP LaserJet MFP M140w\tHP\tHP LaserJet MFP M140w\teSCL network scanner\n")
    sys.exit(0)
if "-A" in args:
    print("\nAll options specific to device `%s':\n  Scan Mode:\n"
          "    --mode Color|Gray [Color]\n"
          "    --resolution 75|150|300|600dpi [300]\n"
          "    --source Flatbed|ADF [Flatbed]\n" % opt("-d"))
    sys.exit(0)
pages = os.environ["DEMO_SCAN_PAGES"].split(",")
counter = os.environ["DEMO_SCAN_COUNTER"]
n = int(open(counter).read() or 0) if os.path.exists(counter) else 0
with open(counter, "w") as f:
    f.write(str(n + 1))
src = pages[n % len(pages)]
if opt("--mode") == "Gray" and os.path.exists(src[:-4] + "-gray.pnm"):
    src = src[:-4] + "-gray.pnm"
for p in (0, 20, 45, 70, 100):
    sys.stderr.write("Progress: %.1f%%\r" % p)
    sys.stderr.flush()
    time.sleep(0.15)
batch = opt("--batch")
out = (batch % int(opt("--batch-start") or 1)) if batch else opt("-o")
shutil.copy(src, out)
sys.exit(0)
'''


def _text(cr, x, y, text, size, bold=False, rgb=(0.13, 0.13, 0.15)):
    import cairo
    cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)
    cr.set_source_rgb(*rgb)
    cr.move_to(x, y)
    cr.show_text(text)


def _paper(cr):
    # papir s jemnym nadechem skeneru (ne cista bila)
    cr.set_source_rgb(0.985, 0.98, 0.965)
    cr.paint()


def recipe_page(cr):
    """Strana 1: recept s barevnou ilustraci."""
    import cairo
    _paper(cr)
    _text(cr, 110, 190, "Lemon Drizzle Cake", 78, True)
    _text(cr, 112, 250, "Serves 8  ·  Prep 20 min  ·  Bake 45 min", 30, rgb=(0.4, 0.4, 0.42))
    # ilustrace: talir s dortem a citrony
    g = cairo.LinearGradient(110, 300, 1130, 760)
    g.add_color_stop_rgb(0, 1.0, 0.93, 0.62)
    g.add_color_stop_rgb(1, 0.99, 0.80, 0.42)
    cr.rectangle(110, 300, 1020, 460)
    cr.set_source(g)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.save()
    cr.translate(620, 600)
    cr.scale(1, 0.35)
    cr.arc(0, 0, 330, 0, 2 * math.pi)
    cr.restore()
    cr.fill()
    cr.set_source_rgb(0.93, 0.76, 0.45)
    cr.rectangle(420, 430, 400, 160)
    cr.fill()
    cr.set_source_rgb(0.99, 0.96, 0.85)
    cr.rectangle(420, 415, 400, 34)
    cr.fill()
    for cx, cy, r in ((250, 420, 70), (980, 450, 62), (900, 660, 50)):
        cr.set_source_rgb(0.98, 0.84, 0.10)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(0.40, 0.66, 0.25)
        cr.save()
        cr.translate(cx + r * 0.6, cy - r * 0.9)
        cr.rotate(-0.6)
        cr.scale(1, 0.45)
        cr.arc(0, 0, r * 0.45, 0, 2 * math.pi)
        cr.restore()
        cr.fill()
    _text(cr, 110, 860, "Ingredients", 44, True)
    y = 930
    for line in ("225 g butter, softened", "225 g caster sugar", "4 eggs", "225 g self-raising flour",
                 "Zest of 2 lemons", "Juice of 1½ lemons and 85 g icing sugar for the drizzle"):
        cr.set_source_rgb(0.98, 0.75, 0.10)
        cr.arc(126, y - 11, 8, 0, 2 * math.pi)
        cr.fill()
        _text(cr, 150, y, line, 30)
        y += 52
    _text(cr, 110, y + 50, "Method", 44, True)
    y += 120
    for i, line in enumerate(("Heat the oven to 180 °C and line a loaf tin.",
                              "Beat the butter and sugar until pale, then add the eggs.",
                              "Fold in the flour and lemon zest, pour into the tin.",
                              "Bake for 45 minutes, until a skewer comes out clean.",
                              "Mix the lemon juice with icing sugar and pour over the warm cake.")):
        _text(cr, 110, y, "%d." % (i + 1), 30, True)
        _text(cr, 160, y, line, 30)
        y += 56
    _text(cr, 110, 1680, "From Grandma's recipe box", 26, rgb=(0.5, 0.5, 0.52))


def letter_page(cr):
    """Strana 2: dopis / potvrzeni."""
    _paper(cr)
    cr.set_source_rgb(0.24, 0.48, 1.0)
    cr.rectangle(110, 130, 90, 90)
    cr.fill()
    _text(cr, 230, 195, "Riverside Community Garden", 46, True)
    _text(cr, 110, 330, "Dear member,", 32)
    y = 400
    for line in ("Thank you for joining the Riverside Community Garden this season!",
                 "Your plot number is 14, next to the herb beds by the east gate.",
                 "", "Spring work day: Saturday, 10 am to 2 pm. Tools, seeds and",
                 "lemonade are provided - just bring gloves and good spirits.",
                 "", "Watering rota and compost tips are on the notice board.",
                 "", "See you in the garden,", "", "The Garden Committee"):
        if line:
            _text(cr, 110, y, line, 30)
        y += 52
    cr.set_source_rgb(0.85, 0.85, 0.86)
    cr.rectangle(110, 1110, 1020, 3)
    cr.fill()
    _text(cr, 110, 1180, "Membership", 34, True)
    y = 1250
    for k, v in (("Plot", "14 (east gate)"), ("Season", "March - October"), ("Fee", "Paid")):
        _text(cr, 110, y, k, 30, rgb=(0.4, 0.4, 0.42))
        _text(cr, 420, y, v, 30)
        y += 54


def write_pnm(path, draw, gray=False):
    """Vykresli stranku a ulozi ji jako PNM (P6, nebo P5 sede) jako scanimage."""
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(surf)
    draw(cr)
    surf.flush()
    data = surf.get_data()
    stride = surf.get_stride()
    out = bytearray()
    for y in range(H):
        row = data[y * stride:y * stride + W * 4]
        if gray:
            out += bytes((row[i] * 11 + row[i + 1] * 59 + row[i + 2] * 30) // 100 for i in range(0, W * 4, 4))
        else:
            r = bytearray(W * 3)
            r[0::3] = row[2::4]
            r[1::3] = row[1::4]
            r[2::3] = row[0::4]
            out += r
    with open(path, "wb") as f:
        f.write((b"P5" if gray else b"P6") + b"\n%d %d\n255\n" % (W, H) + bytes(out))


def fake_bin(s):
    """Slozka s falesnymi prikazy (na zacatek PATH) a stranky pro scanimage -> env."""
    d = os.path.join(s.tmp, "fake-bin")
    os.makedirs(d, exist_ok=True)
    scripts = {
        "scanimage": FAKE_SCANIMAGE,
        "lpq": "#!/bin/sh\nexit 0\n",
        "avahi-browse": "#!/bin/sh\nexit 0\n",
        "ipptool": "#!/bin/sh\nexit 1\n",
        "pkexec": "#!/bin/sh\nexit 126\n",
        "xdg-open": "#!/bin/sh\nexit 0\n",
    }
    for name, text in scripts.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(os.path.join(d, name), 0o755)
    pages = []
    for name, draw in (("recipe", recipe_page), ("letter", letter_page)):
        p = os.path.join(s.tmp, name + ".pnm")
        write_pnm(p, draw)
        pages.append(p)
    return {"PATH": d + os.pathsep + s.env.get("PATH", "/usr/bin"),
            "DEMO_SCAN_PAGES": ",".join(pages), "DEMO_SCAN_COUNTER": os.path.join(s.tmp, "scan-counter")}
