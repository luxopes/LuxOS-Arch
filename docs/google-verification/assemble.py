#!/usr/bin/env python3
"""LuxOS Mail - slozeni ukazkoveho videa pro overeni aplikace OAuth u Googlu (ffmpeg, nic nenahrava).

  assemble.py PARTS_DIR [--consent KLIP] [--out VYSTUP.mp4]

PARTS_DIR obsahuje part-a.mp4, part-g.mp4, part-b.mp4 (z record_demo.py). Bez --consent vznikne nahled se
zastupnou kartou (a zastupnou strankou v prohlizeci); s --consent se misto nich vlozi klip vlastnika se
skutecnym souhlasem Google (libovolne rozliseni a fps -> 1920x1080, 30 fps, okraje doplnene).

Poradi: uvodni karta, 1. pridani uctu (A), 2. souhlas Google (klip / nahled), 3. pouziti rozsahu (B), zaver.
Vysledek: MP4 H.264 (yuv420p, +faststart), 1920x1080, 30 fps, tichy zvuk AAC (YouTube), nejvys 3 minuty.

Interni rezim pro record_demo.py: --wallpaper-window OBRAZEK (tapeta LuxOS jako okno plochy v xvfb).
"""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ICON = os.path.join(REPO, "packages", "apps", "luxos-mail", "files", "luxos-mail.svg")
W, H, FPS = 1920, 1080, 30
MAX_SECONDS = 180
CLIENT_ID = "167842547008-kl3g01rd4b424v6q8msuj7ue47eodm52.apps.googleusercontent.com"
FONT = "Inter, Noto Sans, DejaVu Sans, sans-serif"
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.stderr.write(r.stderr[-3000:])
        raise RuntimeError("command failed: " + " ".join(cmd[:6]) + " ...")
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def svg_png(svg, path):
    src = path + ".svg"
    with open(src, "w", encoding="utf-8") as f:
        f.write(svg)
    run(["rsvg-convert", "-w", str(W), "-h", str(H), src, "-o", path])
    os.unlink(src)
    return path


def esc(s):
    return html.escape(s, quote=True)


def icon_data():
    with open(ICON, encoding="utf-8") as f:
        svg = f.read()
    # vnorene SVG bez XML hlavicky
    start = svg.find("<svg")
    return svg[start:].replace('width="512" height="512" ', "", 1)


# ---- karty ------------------------------------------------------------------------------------------------
def card_svg(title, lines=(), kicker="", warn=False, icon=False):
    bg = "#3a2f0b" if warn else "#0d1430"
    accent = "#ffd34d" if warn else "#8fa0ff"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
             f'<stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="#1b2a6b"/></linearGradient></defs>',
             f'<rect width="{W}" height="{H}" fill="url(#g)"/>']
    y = 330
    if icon:
        inner = icon_data().replace("<svg ", '<svg x="860" y="150" width="200" height="200" ', 1)
        parts.append(inner)
        y = 470
    if kicker:
        parts.append(f'<text x="{W // 2}" y="{y}" text-anchor="middle" font-family="{FONT}" font-size="34" '
                     f'font-weight="600" fill="{accent}" letter-spacing="2">{esc(kicker)}</text>')
        y += 90
    parts.append(f'<text x="{W // 2}" y="{y}" text-anchor="middle" font-family="{FONT}" font-size="72" '
                 f'font-weight="800" fill="#ffffff">{esc(title)}</text>')
    y += 80
    for line in lines:
        mono = line.startswith("`")
        text = line.strip("`")
        fam = "JetBrains Mono, DejaVu Sans Mono, monospace" if mono else FONT
        size = 30 if mono else 36
        parts.append(f'<text x="{W // 2}" y="{y}" text-anchor="middle" font-family="{fam}" font-size="{size}" '
                     f'fill="#d9defc">{esc(text)}</text>')
        y += 58
    parts.append(f'<text x="{W // 2}" y="{H - 50}" text-anchor="middle" font-family="{FONT}" font-size="24" '
                 'fill="#8d96c4">LuxOS Mail · luxos.lux-ai.cz/mail</text>')
    parts.append("</svg>")
    return "".join(parts)


CARDS = {
    "title": (dict(title="LuxOS Mail", kicker="GOOGLE OAUTH VERIFICATION · DEMO VIDEO", icon=True,
                   lines=["Desktop mail client of LuxOS (IMAP) · OAuth client type: Desktop app",
                          "Scopes: https://mail.google.com/ · openid · userinfo.email",
                          "`client_id " + CLIENT_ID,
                          "Mail data stays on the user’s computer – never sent to LuxOS servers"]), 7.0),
    "card1": (dict(title="1. Add a Gmail account", kicker="STEP 1",
                   lines=["LuxOS Mail → Add Account → Gmail address → “Sign in with Google”"]), 3.5),
    "card2": (dict(title="2. Google sign-in and consent", kicker="STEP 2",
                   lines=["Google’s consent screen for “LuxOS Mail” (English)",
                          "with the OAuth client ID in the browser address bar"]), 3.5),
    "placeholder": (dict(title="Real consent recording goes here", kicker="PLACEHOLDER – PREVIEW ONLY", warn=True,
                         lines=["docs/google-verification/record-consent.sh records the real Google consent",
                                "screen on the owner’s computer and replaces this card"]), 4.0),
    "card3": (dict(title="3. Mail uses the scope to read mail", kicker="STEP 3",
                   lines=["https://mail.google.com/ = IMAP access: list, read, folders, mark read, move to Trash",
                          "Shown with a demo mailbox (sample messages) – the same app and the same steps",
                          "Removing the account deletes local data and revokes access at Google"]), 5.0),
    "end": (dict(title="Your mail stays on your computer", kicker="LUXOS MAIL",
                 lines=["Google user data is stored only locally (mail cache + token in the keyring)",
                        "Never transferred to LuxOS servers or third parties · no ads · no AI training",
                        "Homepage: https://luxos.lux-ai.cz/mail/",
                        "Privacy Policy: https://luxos.lux-ai.cz/privacy/#google-user-data"]), 6.0),
}


def card_video(name, work):
    spec, seconds = CARDS[name]
    png = svg_png(card_svg(**spec), os.path.join(work, name + ".png"))
    out = os.path.join(work, name + ".mp4")
    run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", str(seconds), "-i", png,
         "-vf", "fade=t=in:st=0:d=0.4,fade=t=out:st=%.2f:d=0.4" % (seconds - 0.4)] + ENC + [out])
    return out


# ---- titulky v usecich -------------------------------------------------------------------------------------
def caption_svg(text, sub):
    mono = text.startswith("client_id=")
    fam = "JetBrains Mono, DejaVu Sans Mono, monospace" if mono else FONT
    size = 34 if mono else 40
    h = 150 if sub else 104
    y0 = H - h - 18
    width = min(W - 120, max(900, int(len(max(text, sub, key=len)) * (21 if mono else 19)) + 120))
    x0 = (W - width) // 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect x="{x0}" y="{y0}" width="{width}" height="{h}" rx="22" fill="#0b1130" fill-opacity="0.86"/>',
             f'<text x="{W // 2}" y="{y0 + 64}" text-anchor="middle" font-family="{fam}" font-size="{size}" '
             f'font-weight="700" fill="#ffffff">{esc(text)}</text>']
    if sub:
        parts.append(f'<text x="{W // 2}" y="{y0 + 114}" text-anchor="middle" font-family="{FONT}" font-size="30" '
                     f'fill="#c9d0f5">{esc(sub)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def cut_parts(raw, markers_path, parts_dir):
    """Surovy zaznam -> part-a/g/b.mp4 s titulky podle znacek z record_demo.py."""
    with open(markers_path) as f:
        data = json.load(f)
    marks = data["markers"]
    os.makedirs(parts_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cut-", dir=parts_dir)
    total = duration(raw)
    out_files = []
    for name in ("a", "g", "b"):
        start = next(m["t"] for m in marks if m["kind"] == "segment" and m["name"] == name and m["edge"] == "start")
        end = next(m["t"] for m in marks if m["kind"] == "segment" and m["name"] == name and m["edge"] == "end")
        end = min(end, total)
        caps = [m for m in marks if m["kind"] == "caption" and start - 0.01 <= m["t"] < end]
        inputs = ["-ss", "%.2f" % start, "-to", "%.2f" % end, "-i", raw]
        chain = []
        last = "0:v"
        for i, c in enumerate(caps):
            png = svg_png(caption_svg(c["text"], c.get("sub", "")), os.path.join(work, "%s-%02d.png" % (name, i)))
            inputs += ["-i", png]
            a = c["t"] - start
            b = (caps[i + 1]["t"] - start) if i + 1 < len(caps) else (end - start)
            label = "v%d" % i
            chain.append("[%s][%d:v]overlay=0:0:enable='between(t,%.2f,%.2f)'[%s]" % (last, i + 1, a, b - 0.05, label))
            last = label
        out = os.path.join(parts_dir, "part-%s.mp4" % name)
        cmd = ["nice", "-n", "10", "ffmpeg", "-loglevel", "error", "-y"] + inputs
        if chain:
            cmd += ["-filter_complex", ";".join(chain), "-map", "[%s]" % last]
        cmd += ENC + ["-an", out]
        run(cmd)
        out_files.append(out)
    shutil.rmtree(work, ignore_errors=True)
    with open(os.path.join(parts_dir, "markers.json"), "w") as f:
        json.dump(data, f, indent=2)
    return out_files


def normalize(src, out, max_seconds=None):
    """Libovolny klip -> 1920x1080 (zachovany pomer, okraje), 30 fps, H.264, bez zvuku."""
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x0d1430,"
          "setsar=1,fps=%d" % (W, H, W, H, FPS))
    cmd = ["nice", "-n", "10", "ffmpeg", "-loglevel", "error", "-y", "-i", src]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    run(cmd + ["-vf", vf] + ENC + ["-an", out])
    return out


def assemble(parts_dir, consent, out):
    work = tempfile.mkdtemp(prefix="assemble-", dir=parts_dir)
    try:
        seq = [card_video("title", work), card_video("card1", work), os.path.join(parts_dir, "part-a.mp4"),
               card_video("card2", work)]
        if consent:
            seq.append(normalize(consent, os.path.join(work, "consent.mp4")))
        else:
            seq += [os.path.join(parts_dir, "part-g.mp4"), card_video("placeholder", work)]
        seq += [card_video("card3", work), os.path.join(parts_dir, "part-b.mp4"), card_video("end", work)]
        for p in seq:
            if not os.path.exists(p):
                raise RuntimeError("missing part: " + p)
        total = sum(duration(p) for p in seq)
        if total > MAX_SECONDS:
            raise RuntimeError("video would be %.0f s, Google allows at most %d s - record a shorter consent clip"
                               % (total, MAX_SECONDS))
        inputs = []
        for p in seq:
            inputs += ["-i", p]
        n = len(seq)
        filt = "".join("[%d:v]" % i for i in range(n)) + "concat=n=%d:v=1:a=0[v]" % n
        tmp = out + ".tmp.mp4"
        run(["nice", "-n", "10", "ffmpeg", "-loglevel", "error", "-y"] + inputs +
            ["-f", "lavfi", "-t", "%.2f" % total, "-i", "anullsrc=r=48000:cl=stereo",
             "-filter_complex", filt, "-map", "[v]", "-map", "%d:a" % n] + ENC +
            ["-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", tmp])
        os.replace(tmp, out)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- tapeta (interni, jen v xvfb z record_demo.py) ------------------------------------------------------------
def wallpaper_window(path):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GdkPixbuf, Gtk
    scr = Gdk.Screen.get_default()
    w, h = scr.get_width(), scr.get_height()
    pix = GdkPixbuf.Pixbuf.new_from_file(path)
    scale = max(w / pix.get_width(), h / pix.get_height())
    pix = pix.scale_simple(int(pix.get_width() * scale) + 1, int(pix.get_height() * scale) + 1, GdkPixbuf.InterpType.HYPER)
    pix = pix.new_subpixbuf((pix.get_width() - w) // 2, (pix.get_height() - h) // 2, w, h)
    win = Gtk.Window()
    win.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
    win.set_decorated(False)
    win.move(0, 0)
    win.set_default_size(w, h)
    win.add(Gtk.Image.new_from_pixbuf(pix))
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--wallpaper-window":
        if "xvfb-run" not in os.environ.get("XAUTHORITY", ""):
            sys.exit("assemble: --wallpaper-window only under xvfb")
        wallpaper_window(sys.argv[2])
        return
    ap = argparse.ArgumentParser(description="Assemble the LuxOS Mail OAuth verification video (never uploads anything).")
    ap.add_argument("parts_dir")
    ap.add_argument("--consent", default="", help="owner's recording of the real Google consent screen")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.parts_dir)),
                                "luxos-mail-demo-final.mp4" if a.consent else "luxos-mail-demo-preview.mp4")
    path = assemble(os.path.abspath(a.parts_dir), a.consent or None, out)
    print("%s (%.1f s)" % (path, duration(path)))


if __name__ == "__main__":
    main()
