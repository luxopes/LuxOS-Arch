#!/usr/bin/env python3
"""LuxOS - snimky cele plochy pro web (uvodni notebook, galerie). Spoustet jen pres site-screenshots.sh.

Kazda varianta (jazyk x svetly/tmavy vzhled) ma vlastni docasny koren v out/site-screenshots/run-*:
HOME sezeni, soukromy XDG_RUNTIME_DIR (0700), XDG_CONFIG_HOME/DATA/CACHE/STATE pod nim, vlastni D-Bus
(dbus-run-session) - xfconfd, dconf ani aplikace tak nikdy nesahnou na skutecne ~/.config nebo ~/.local.
guard_env() pred spustenim cehokoli overi, ze HOME a vsechny XDG_* vedou do korene behu, jinak skonci.

Plocha jako v LuxOS: tapeta (okno typu plocha, jako xfdesktop), xfwm4 s kompozitorem (stiny, pruhledna
lista), horni lista xfce4-panel s nastavenim z luxos-desktop/files/xdg a vzhledem z luxos-appearance,
Dock Plank (polozky ze skel, tema WhiteSur-Light/-Dark). Sceny (SCENES) spousti aplikace pres
Session ze scripts/store-screenshots/shoot.py - postupy apps/<id>.py se pouziji znovu, jen snimek je
cela obrazovka misto okna. Procesy se ukoncuji jen podle vlastnich PID/skupin procesu, nikdy podle nazvu.

Vystup v site/assets/shots/: <scena>-<light|dark>.webp (1920x1080, prohlizec galerie), -960.webp (notebook
na uvodni strance, galerie na hustych displejich) a -small.webp (640x360, dlazdice galerie); cestina
v podslozce cs/. Docasne PNG zustanou jen s --keep.
"""
import argparse
import json
import os
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PACKAGES = os.path.join(REPO, "packages")
STORE = os.path.join(REPO, "scripts", "store-screenshots")
sys.path.insert(0, STORE)
sys.path.insert(0, HERE)
import shoot  # noqa: E402

W, H = 1920, 1080
shoot.SCREEN = (W, H)              # Session.center() a park_mouse() pocitaji s celou obrazovkou
OUT_DEFAULT = os.path.join(REPO, "site", "assets", "shots")
XDG = os.path.join(PACKAGES, "luxos-desktop", "files", "xdg")
XFCONF = os.path.join(XDG, "xfce4", "xfconf", "xfce-perchannel-xml")
WALLPAPERS = os.path.join(PACKAGES, "luxos-branding", "files", "wallpapers")
# vychozi tapety LuxOS (luxos-light.jpg / luxos-dark.jpg v PKGBUILD luxos-branding)
WALLPAPER = {False: "luxos-flow-light.jpg", True: "luxos-flow-dark.jpg"}
SIZES = (("", 1920, 1080, 260), ("-960", 960, 540, 90), ("-small", 640, 360, 50))   # pripona, sirka, vyska, max. KB
LANGS = {"en": ("en_US.UTF-8", "en"), "cs": ("cs_CZ.UTF-8", "cs")}
WORK = os.path.join(REPO, "out", "site-screenshots")
RUN_PREFIX = "luxos-site-shots-"


# tichy vystup "Speakers" jako vychozi zarizeni (bez spravce relace nastavi metadata "default" PipeWire sam)
PIPEWIRE_DEMO = """context.objects = [
    { factory = adapter
      args = { factory.name = support.null-audio-sink node.name = luxos-demo node.description = Speakers
               media.class = Audio/Sink audio.position = [ FL FR ] monitor.channel-volumes = true } }
    { factory = metadata
      args = { metadata.name = default
               metadata.values = [ { key = default.audio.sink value = { name = luxos-demo } }
                                   { key = default.configured.audio.sink value = { name = luxos-demo } } ] } }
]
"""


def die(msg):
    print("site-screenshots: " + msg, file=sys.stderr)
    sys.exit(2)


def log(msg):
    print(msg, flush=True)


# ---- bezpecnost: jen xvfb, jen docasne slozky ------------------------------------------------------
def real_home():
    return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)


XDG_VARS = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")


def guard_env(env, root):
    """Konec, pokud HOME nebo nektera XDG_* promenna nevede do korene behu (nebo vede do skutecneho
    ~/.config, ~/.local, ~/.cache), nebo pokud displej neni xvfb-run."""
    root = os.path.realpath(root)
    home = real_home()
    forbidden = [os.path.join(home, d) for d in (".config", ".local", ".cache")]
    for k in XDG_VARS:
        v = env.get(k)
        if not v:
            die("refusing to run: %s is not set" % k)
        rv = os.path.realpath(v)
        if any(rv == f or rv.startswith(f + os.sep) for f in forbidden) or rv == home:
            die("refusing to run: %s=%s points into the real home" % (k, v))
        short_run = k == "XDG_RUNTIME_DIR" and os.path.dirname(rv) == "/run/user/%d" % os.getuid() and \
            os.path.basename(rv).startswith(RUN_PREFIX)
        if not (rv == root or rv.startswith(root + os.sep) or short_run):
            die("refusing to run: %s=%s is outside the run folder %s" % (k, v, root))
    for k in ("XDG_CONFIG_DIRS", "XDG_DATA_DIRS"):
        for part in (env.get(k) or "").split(":"):
            rp = os.path.realpath(part) if part else ""
            if part and (rp == home or rp.startswith(home + os.sep)) and not rp.startswith(root + os.sep):
                die("refusing to run: %s contains %s (real home)" % (k, part))
    d = env.get("DISPLAY", "")
    if env.get("LUXOS_SITE_SHOTS_XVFB") != "1" or not d or d in (":0", ":0.0") or \
            "xvfb-run" not in env.get("XAUTHORITY", ""):
        die("run me through scripts/site-screenshots/site-screenshots.sh (xvfb only)")


def write_xml(src_name, dst_dir, replace=()):
    text = open(os.path.join(XFCONF, src_name), encoding="utf-8").read()
    for a, b in replace:
        text = text.replace(a, b)
    with open(os.path.join(dst_dir, src_name), "w", encoding="utf-8") as f:
        f.write(text)


def panel_css(dark):
    """Blok gtk.css horni listy jako luxos-appearance panel_css()."""
    fg = "#ffffff" if dark else "#1d1d1f"
    lines = ["/* LuxOS appearance begin */"]
    if not dark:
        lines.append(".xfce4-panel, .xfce4-panel label, .xfce4-panel button, .xfce4-panel image { color: %s; }" % fg)
    lines += [
        ".xfce4-panel grid > button { min-width: 20px; min-height: 0; padding: 0 4px; margin: 4px 1px; border-radius: 6px; "
        "background: transparent; box-shadow: none; border: none; }",
        ".xfce4-panel grid > button label { color: alpha(%s, 0.55); font-weight: 600; }" % fg,
        "/* LuxOS appearance end */", ""]
    return "\n".join(lines)


def build_locale(lang):
    """Cesky locale pro glibc bez roota (LOCPATH): vyvojovy pocitac nemusi mit cs_CZ vygenerovany."""
    name = LANGS[lang][0]
    if subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.lower().replace("-", "").count(
            name.lower().replace("-", "")):
        return None
    locpath = os.path.join(WORK, "locale")
    if not os.path.isdir(os.path.join(locpath, name)):
        os.makedirs(locpath, exist_ok=True)
        subprocess.run(["localedef", "-i", name.split(".")[0], "-f", "UTF-8", os.path.join(locpath, name)],
                       check=False, capture_output=True, timeout=120)
        if not os.path.isdir(os.path.join(locpath, name)):
            die("cannot build locale %s (localedef)" % name)
    return locpath


def prepare(dark, lang):
    """Docasny koren behu, HOME sezeni s nastavenim LuxOS (svetly/tmavy vzhled) a prostredi."""
    os.makedirs(WORK, exist_ok=True)
    root = tempfile.mkdtemp(prefix="run-", dir=WORK)
    run_dir = os.path.join(root, "run")
    if len(run_dir) > 70:
        # sokety v XDG_RUNTIME_DIR (PipeWire, klicenka) maji limit 108 bajtu cele cesty; dlouha cesta
        # pracovni kopie -> vlastni prazdna slozka 0700 ve /run/user/<uid> (jen sokety, smaze se po behu)
        base = "/run/user/%d" % os.getuid()
        run_dir = tempfile.mkdtemp(prefix=RUN_PREFIX, dir=base) if os.path.isdir(base) else run_dir
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    os.chmod(run_dir, 0o700)
    home = os.path.join(root, "session-home")
    cfg = os.path.join(home, ".config")
    theme = "WhiteSur-Dark" if dark else "WhiteSur-Light"
    icons = "WhiteSur-dark" if dark else "WhiteSur-light"
    for v in ("gtk-3.0", "gtk-4.0"):
        os.makedirs(os.path.join(cfg, v), exist_ok=True)
        text = open(os.path.join(XDG, v, "settings.ini"), encoding="utf-8").read()
        text = text.replace("WhiteSur-Light", theme).replace("WhiteSur-light", icons)
        if dark:
            text += "gtk-application-prefer-dark-theme=1\n"
        with open(os.path.join(cfg, v, "settings.ini"), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(cfg, "gtk-3.0", "gtk.css"), "w", encoding="utf-8") as f:
        f.write(panel_css(dark))
    xf = os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml")
    os.makedirs(xf, exist_ok=True)
    themes = (("WhiteSur-Light", theme), ("WhiteSur-light", icons))
    for name in ("xfwm4.xml", "xsettings.xml", "xfce4-notifyd.xml", "thunar.xml", "xfce4-desktop.xml"):
        write_xml(name, xf, themes)
    rgba = ("0.09", "0.09", "0.12") if dark else ("0.96", "0.96", "0.97")
    panel = open(os.path.join(XFCONF, "xfce4-panel.xml"), encoding="utf-8").read()
    panel = panel.replace('<property name="dark-mode" type="bool" value="false"/>',
                          '<property name="dark-mode" type="bool" value="%s"/>' % ("true" if dark else "false"))
    old = ('<value type="double" value="0.96"/>\n        <value type="double" value="0.96"/>\n'
           '        <value type="double" value="0.97"/>')
    if old not in panel:
        die("xfce4-panel.xml: background-rgba not found (update panel colours in shoot_site.py)")
    panel = panel.replace(old, '<value type="double" value="%s"/>\n        <value type="double" value="%s"/>\n'
                          '        <value type="double" value="%s"/>' % rgba)
    with open(os.path.join(xf, "xfce4-panel.xml"), "w", encoding="utf-8") as f:
        f.write(panel)
    pw = os.path.join(cfg, "pipewire", "pipewire.conf.d")
    os.makedirs(pw, exist_ok=True)
    with open(os.path.join(pw, "luxos-site-shots.conf"), "w", encoding="utf-8") as f:
        f.write(PIPEWIRE_DEMO)
    # Dock: polozky ze skel (tema a poradi dconf: systemove vychozi LuxOS + nize gsettings v sezeni)
    shutil.copytree(os.path.join(PACKAGES, "luxos-desktop", "files", "skel", ".config", "plank"),
                    os.path.join(cfg, "plank"))
    for d in (".local/share", ".cache", ".local/state", "Desktop", "Documents", "Downloads", "Pictures", "Music"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    locale, language = LANGS[lang]
    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and k not in (
        "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL", "SESSION_MANAGER",
        "LC_ALL", "LC_MESSAGES", "LC_TIME", "GTK_MODULES", "GTK_THEME", "LOCPATH")}
    env.update({"HOME": home, "XDG_CONFIG_HOME": cfg, "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
                "XDG_CACHE_HOME": os.path.join(home, ".cache"), "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
                "XDG_RUNTIME_DIR": run_dir,
                # jako /etc/profile.d/luxos.sh: vychozi nastaveni LuxOS, kratke nazvy aplikaci, skryte technicke
                # polozky (Launchpad, Nastaveni) a lehke pluginy listy; bez exportu Flathubu vyvojoveho pocitace
                "XDG_CONFIG_DIRS": "/etc/xdg/luxos:/etc/xdg",
                "XDG_DATA_DIRS": "/usr/lib/luxos/panel/share:/var/lib/luxos/apps:/usr/share/luxos/xdg:/usr/local/share:/usr/share",
                "PATH": "/usr/lib/luxos/override-bin:" + os.environ.get("PATH", "/usr/bin:/bin"),
                "XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11", "XDG_SESSION_DESKTOP": "luxos",
                "GDK_BACKEND": "x11", "LANG": locale, "LANGUAGE": language, "NO_AT_BRIDGE": "1",
                "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local",
                # gvfsd (D-Bus aktivace pro Kos v Docku) bez pripojeni FUSE v XDG_RUNTIME_DIR
                "GVFS_DISABLE_FUSE": "1", "TMPDIR": os.path.join(root, "tmp"),
                "LUXOS_SHOTS_ROOT": root, "LUXOS_SITE_VARIANT": "dark" if dark else "light", "LUXOS_SITE_LANG": lang,
                "GIT_CEILING_DIRECTORIES": root, "PYTHONDONTWRITEBYTECODE": "1",
                "USER": pwd.getpwuid(os.getuid()).pw_name})
    if dark:
        env["GTK_THEME"] = theme
    locpath = build_locale(lang) if lang != "en" else None
    if locpath:
        env["LOCPATH"] = locpath
    os.makedirs(env["TMPDIR"])
    return root, env


# ---- snimky ---------------------------------------------------------------------------------------
def save_sizes(pix, out_dir, name, dark, keep_png=None):
    """Ulozi snimek obrazovky ve trech velikostech WebP (kvalita podle limitu velikosti)."""
    from gi.repository import GdkPixbuf
    os.makedirs(out_dir, exist_ok=True)
    variant = "dark" if dark else "light"
    if keep_png:
        pix.savev(os.path.join(keep_png, "%s-%s.png" % (name, variant)), "png", [], [])
    result = []
    for suffix, w, h, max_kb in SIZES:
        p = pix if pix.get_width() == w else pix.scale_simple(w, h, GdkPixbuf.InterpType.HYPER)
        path = os.path.join(out_dir, "%s-%s%s.webp" % (name, variant, suffix))
        tmp = path + ".tmp"
        for q in (88, 84, 80, 76, 72, 66, 60):
            p.savev(tmp, "webp", ["quality"], [str(q)])
            if os.path.getsize(tmp) <= max_kb * 1024:
                break
        os.replace(tmp, path)
        result.append((os.path.basename(path), os.path.getsize(path)))
    log("  %s" % ", ".join("%s %d KB" % (n, s // 1024) for n, s in result))
    return result


def save_og_image(pix, path):
    """Nahled odkazu (og:image) 1200x630 JPEG z tmave plochy: vyrez 1920x1008 s Dockem (bez horni listy)."""
    from gi.repository import GdkPixbuf
    crop = pix.new_subpixbuf(0, H - 1008, W, 1008).scale_simple(1200, 630, GdkPixbuf.InterpType.HYPER)
    crop.savev(path, "jpeg", ["quality"], ["84"])
    log("  %s %d KB" % (os.path.basename(path), os.path.getsize(path) // 1024))


class SiteSession(shoot.Session):
    """Session ze store-screenshots: capture() bere celou obrazovku (s listou a Dockem), ne jen okno."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.frames = {}
        # HOME ukazkoveho uzivatele "alex" (v Souborech a Terminalu je videt jmeno slozky)
        alex = os.path.join(self.tmp, "alex")
        os.rename(self.home, alex)
        for k, v in list(self.env.items()):
            if k in XDG_VARS and v.startswith(self.home):
                self.env[k] = alex + v[len(self.home):]
        self.home = alex
        # nahledy obrazku dela tumblerd sezeni (D-Bus aktivace s prostredim sezeni) do jeho XDG_CACHE_HOME
        self.env["XDG_CACHE_HOME"] = cache = os.path.join(self.env.get("LUXOS_SHOTS_ROOT", self.tmp),
                                                               "session-home", ".cache")
        os.makedirs(cache, exist_ok=True)
        # Dock se pri prekryti oknem schova (window-dodge): okna aplikaci nechat nad nim
        self.max_h = H - 28 - 96

    def window(self, name=None, pid=None, cls=None, timeout=25, size=(1180, 760), place=True):
        if size:
            size = (min(size[0], W - 120), min(size[1], self.max_h - 40))
        return super().window(name=name, pid=pid, cls=cls, timeout=timeout, size=size, place=place)

    def center(self, win):
        x, y, w, h = self.shell.frame(win)
        # stred plochy mezi horni listou (28 px) a Dockem
        top = 28 + max(0, (self.max_h - h) // 2)
        self.xdo("windowmove", win, max(0, (W - w) // 2), top)
        self.shell.pump(0.3)

    def capture(self, name, win=None, pad=0):
        self.park_mouse()
        self.shell.pump(1.0)
        self.frames[name] = self.shell.grab(0, 0, W, H)
        log("  frame %s" % name)
        return name

    def park_mouse(self):
        # kurzor neni ve snimku (xvfb), ale najeti mysi by zvyraznilo polozky - mimo okna i Dock
        self.xdo("mousemove", W - 3, H // 2)


class Desktop:
    """Displej se vsim, co patri k plose LuxOS: tapeta, xfwm4, horni lista, Dock."""

    def __init__(self, env, dark):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkX11", "3.0")
        from gi.repository import Gdk, GdkPixbuf, GdkX11, Gtk
        self.Gtk, self.Gdk, self.GdkX11 = Gtk, Gdk, GdkX11
        self.env, self.dark = env, dark
        self.procs = []
        root = env["LUXOS_SHOTS_ROOT"]
        self.logdir = os.path.join(root, "logs")
        os.makedirs(self.logdir, exist_ok=True)
        # tapeta jako xfdesktop: okno typu plocha pres celou obrazovku (vyplneni se zachovanim pomeru)
        pix = GdkPixbuf.Pixbuf.new_from_file(os.path.join(WALLPAPERS, WALLPAPER[dark]))
        scale = max(W / pix.get_width(), H / pix.get_height())
        pix = pix.scale_simple(int(pix.get_width() * scale + 0.999), int(pix.get_height() * scale + 0.999),
                               GdkPixbuf.InterpType.HYPER)
        pix = pix.new_subpixbuf((pix.get_width() - W) // 2, (pix.get_height() - H) // 2, W, H)
        self.desk = Gtk.Window()
        self.desk.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.desk.set_decorated(False)
        # jako xfdesktop: lista ukaze "Plocha", kdyz neni aktivni zadne okno (luxos-appname-watch)
        self.desk.set_wmclass("xfdesktop", "Xfdesktop")
        self.desk.move(0, 0)
        self.desk.set_default_size(W, H)
        self.desk.add(Gtk.Image.new_from_pixbuf(pix))
        self.desk.show_all()
        self.pump(0.5)

    def _log(self, name):
        return open(os.path.join(self.logdir, name + ".log"), "ab")

    def spawn(self, name, cmd, env=None):
        logf = self._log(name)
        p = subprocess.Popen(cmd, env=env or self.env, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=self.env["HOME"])
        self.procs.append(p)
        return p

    def start(self):
        env = self.env
        # nastaveni xsettings (pismo, vyhlazovani, kurzor) z xfconf sezeni jako v LuxOS
        self.spawn("xfsettingsd", ["xfsettingsd", "--no-daemon", "--replace"])
        self.pump(1.0)
        # rozlozeni klavesnice v liste (vlajka) podle jazyka - jen na virtualnim displeji xvfb
        if env.get("LUXOS_SITE_LANG") == "cs":
            subprocess.run(["setxkbmap", "-layout", "cz,us"], env=env, timeout=15, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        self.spawn("xfwm4", ["xfwm4", "--replace", "--compositor=on"])
        self.pump(2.0)
        if self.dark:
            dock = "net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/"
            subprocess.run(["gsettings", "set", dock, "theme", "WhiteSur-Dark"], env=env, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for scheme in (("org.gnome.desktop.interface", "color-scheme", "prefer-dark" if self.dark else "prefer-light"),):
            subprocess.run(["gsettings", "set", *scheme], env=env, timeout=20, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        # zvuk: soukromy PipeWire jen s tichym vystupem (bez wireplumber zadna skutecna zarizeni), aby ikona
        # v liste ukazovala hlasitost jako v LuxOS, ne "bez zvuku"; vystup a vychozi vystup (metadata) jsou
        # v $XDG_CONFIG_HOME/pipewire/pipewire.conf.d sezeni (prepare)
        if shutil.which("pipewire") and shutil.which("pipewire-pulse"):
            self.spawn("pipewire", ["pipewire"])
            self.pump(1.0)
            self.spawn("pipewire-pulse", ["pipewire-pulse"])
            self.pump(1.5)
            for cmd in (["pactl", "set-sink-volume", "luxos-demo", "60%"],):
                subprocess.run(cmd, env=env, timeout=15, stdout=self._log("pactl"), stderr=subprocess.STDOUT)
        # lista jako v LuxOS (override-bin pridava modul luxos-panel-menus)
        panel = "/usr/lib/luxos/override-bin/xfce4-panel"
        self.spawn("panel", [panel if os.path.exists(panel) else "xfce4-panel", "--disable-wm-check"])
        # primo plank: luxos-dock konci, pokud uz bezi plank skutecneho sezeni (pgrep -u uzivatel)
        # Kos v Docku potrebuje GIO trash:// (gvfs); bez pripojeni FUSE v XDG_RUNTIME_DIR
        plank_env = dict(env, GVFS_DISABLE_FUSE="1")
        plank_env.pop("GIO_USE_VFS", None)
        self.spawn("plank", ["plank"], env=plank_env)
        # nazev aktivni aplikace v liste (genmon "luxos-appname print" cte stav ze XDG_RUNTIME_DIR)
        self.spawn("appname", ["luxos-appname", "watch"])
        self.pump(8.0)

    def stop(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        end = time.time() + 6
        for p in self.procs:
            try:
                p.wait(max(0.1, end - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass

    # rozhrani Shell ze shoot.py (Session ho pouziva)
    def pump(self, sec):
        end = time.time() + sec
        while True:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if time.time() >= end:
                break
            time.sleep(0.02)

    def frame(self, xid):
        disp = self.Gdk.Display.get_default()
        w = self.GdkX11.X11Window.foreign_new_for_display(disp, xid)
        r = w.get_frame_extents()
        x, y = max(0, r.x), max(0, r.y)
        return x, y, min(W - x, r.width), min(H - y, r.height)

    def grab(self, x, y, w, h):
        return self.Gdk.pixbuf_get_from_window(self.Gdk.get_default_root_window(), x, y, w, h)


# ---- spusteni -------------------------------------------------------------------------------------
def run_inner(args):
    import scenes
    dark = os.environ.get("LUXOS_SITE_VARIANT") == "dark"
    lang = os.environ.get("LUXOS_SITE_LANG", "en")
    root = os.environ["LUXOS_SHOTS_ROOT"]
    guard_env(os.environ, root)
    base_env = dict(os.environ)
    desk = Desktop(base_env, dark)
    work = os.path.join(root, "apps")
    os.makedirs(work, exist_ok=True)
    out_dir = args.out if lang == "en" else os.path.join(args.out, lang)
    keep_png = os.path.join(root, "png") if args.keep else None
    if keep_png:
        os.makedirs(keep_png, exist_ok=True)
    failed = []
    try:
        desk.start()
        for name in args.scenes:
            log("== %s (%s, %s)" % (name, lang, "dark" if dark else "light"))
            s = SiteSession(name, base_env, os.path.join(root, "unused-out"), work, dark, desk)
            s.lang = lang
            s.desktop = desk
            try:
                pix = scenes.SCENES[name](s)
                if pix is None:
                    raise RuntimeError("scene returned no frame")
                save_sizes(pix, out_dir, name, dark, keep_png)
                if name == "desktop" and dark and lang == "en":
                    save_og_image(pix, os.path.join(os.path.dirname(args.out.rstrip("/")), "og-image.jpg"))
            except Exception:
                traceback.print_exc()
                failed.append(name)
            finally:
                s.stop()
                desk.pump(1.0)
    finally:
        desk.stop()
    if failed:
        print("FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def cleanup_root(root):
    """Po behu: zbyle procesy behu (podle LUXOS_SHOTS_ROOT v prostredi, jen vlastni PID) a pripojeni pod
    korenem behu (napr. FUSE) pryc - teprve pak se koren smaze."""
    root = os.path.realpath(root)
    me = os.getpid()
    for pid in [p for p in os.listdir("/proc") if p.isdigit() and int(p) != me]:
        try:
            with open("/proc/%s/environ" % pid, "rb") as f:
                envb = f.read()
        except OSError:
            continue
        if ("LUXOS_SHOTS_ROOT=" + root).encode() + b"\0" in envb + b"\0":
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass
    time.sleep(0.5)
    try:
        mounts = [line.split()[1] for line in open("/proc/mounts", encoding="utf-8")]
    except OSError:
        mounts = []
    for m in mounts:
        m = m.replace("\\040", " ")
        if m == root or m.startswith(root + os.sep):
            for tool in ("fusermount3", "fusermount"):
                if shutil.which(tool) and subprocess.run([tool, "-u", "-z", m], capture_output=True).returncode == 0:
                    break


def main():
    import scenes
    ap = argparse.ArgumentParser(description="LuxOS website screenshots (run via site-screenshots.sh)")
    ap.add_argument("scenes", nargs="*")
    ap.add_argument("--light", action="store_true", help="only the light variant")
    ap.add_argument("--dark", action="store_true", help="only the dark variant")
    ap.add_argument("--lang", choices=sorted(LANGS), action="append", help="only this language (repeatable)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the temporary run folder (with PNG masters)")
    args = ap.parse_args()
    if args.list:
        print("\n".join(scenes.SCENES))
        return 0
    args.scenes = args.scenes or list(scenes.SCENES)
    unknown = [n for n in args.scenes if n not in scenes.SCENES]
    if unknown:
        die("unknown scene: " + ", ".join(unknown))
    if os.environ.get("LUXOS_SITE_INNER") == "1":
        return run_inner(args)
    d = os.environ.get("DISPLAY", "")
    if os.environ.get("LUXOS_SITE_SHOTS_XVFB") != "1" or not d or d in (":0", ":0.0") or \
            "xvfb-run" not in os.environ.get("XAUTHORITY", ""):
        die("run me through scripts/site-screenshots/site-screenshots.sh (xvfb only)")
    variants = [False, True]
    if args.light and not args.dark:
        variants = [False]
    elif args.dark and not args.light:
        variants = [True]
    failed = 0
    for lang in args.lang or list(LANGS):
        for dark in variants:
            root, env = prepare(dark, lang)
            guard_env(env, root)
            env["LUXOS_SITE_INNER"] = "1"
            cmd = ["dbus-run-session", "--", sys.executable, os.path.abspath(__file__), "--out", args.out] + \
                (["--keep"] if args.keep else []) + args.scenes
            rc = subprocess.call(cmd, env=env, cwd=env["HOME"])
            failed |= rc
            cleanup_root(root)
            if os.path.basename(env["XDG_RUNTIME_DIR"]).startswith(RUN_PREFIX):
                cleanup_root(env["XDG_RUNTIME_DIR"])
                shutil.rmtree(env["XDG_RUNTIME_DIR"], ignore_errors=True)
            if args.keep:
                log("kept: " + root)
            else:
                shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
