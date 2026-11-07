#!/usr/bin/env python3
"""LuxOS - snimky aplikaci pro Obchod: spolecne nastroje a spousteni postupu apps/<desktop-id>.py.

Spoustet jen pres store-screenshots.sh (xvfb-run, nikdy skutecna obrazovka). Postup aplikace je modul
s funkci shots(s), kde s je Session:

    def shots(s):
        s.launch_python("luxos-desktop/files/bin/luxos-calculator")
        win = s.window(name="Calculator")          # nebo pid=..., cls=...
        s.capture("1", win)                         # -> screens/luxos-calculator/1.webp
        s.key("ctrl+2", win)
        s.capture("2", win)

Kazda aplikace ma vlastni docasny HOME (s.home, s.tmp) a XDG slozky; spolecny je jen virtualni displej,
xfwm4 a soukromy XDG_RUNTIME_DIR (0700) sezeni. Procesy spustene pres s.launch se ukonci po postupu
(jen vlastni skupina procesu, nikdy podle nazvu). Postup muze spustit falesny server ve vlakne
(s.serve_http) - aplikace nesmi chodit na skutecne sluzby tretich stran.
"""
import argparse
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PACKAGES = os.path.join(REPO, "packages")
APPS_DIR = os.path.join(HERE, "apps")
OUT_DEFAULT = os.path.join(PACKAGES, "luxos-store", "screens")
SCREEN = (1280, 800)
MAX_WIDTH = 1280
MAX_BYTES = 150 * 1024
# Spolecne moduly LuxOS pro programy v Pythonu spoustene ze zdroju (jinak /usr/lib/luxos/python)
PYTHON_PATHS = [os.path.join(PACKAGES, "luxos-i18n", "files"), os.path.join(PACKAGES, "luxos-desktop", "files", "python")]


def die(msg):
    print("store-screenshots: " + msg, file=sys.stderr)
    sys.exit(2)


# ---- prostredi --------------------------------------------------------------
def guard_display():
    """Jen virtualni displej xvfb-run (wrapper), nikdy :0 ani skutecne sezeni."""
    d = os.environ.get("DISPLAY", "")
    if os.environ.get("LUXOS_SHOTS_XVFB") != "1" or not d or d in (":0", ":0.0") or \
            "xvfb-run" not in os.environ.get("XAUTHORITY", ""):
        die("run me through scripts/store-screenshots/store-screenshots.sh (xvfb only)")


def prepare_session(dark):
    """Docasny HOME sezeni, soukromy XDG_RUNTIME_DIR a nastaveni vzhledu (GTK, xfwm4) jako v LuxOS."""
    # docasna data (HOME aplikaci, preklady LSL) na disku v out/, ne v /tmp (tmpfs = pamet RAM)
    base = os.path.join(REPO, "out", "store-screenshots")
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix="run-", dir=base)
    run_dir = os.path.join(root, "run")
    os.makedirs(run_dir, mode=0o700)
    os.chmod(run_dir, 0o700)
    home = os.path.join(root, "session-home")
    cfg = os.path.join(home, ".config")
    theme = "WhiteSur-Dark" if dark else "WhiteSur-Light"
    icons = "WhiteSur-dark" if dark else "WhiteSur-light"
    xdg = os.path.join(PACKAGES, "luxos-desktop", "files", "xdg")
    for v in ("gtk-3.0", "gtk-4.0"):
        os.makedirs(os.path.join(cfg, v), exist_ok=True)
        src = os.path.join(xdg, v, "settings.ini")
        text = open(src, encoding="utf-8").read() if os.path.exists(src) else "[Settings]\n"
        text = text.replace("WhiteSur-Light", theme).replace("WhiteSur-light", icons)
        if dark:
            text += "gtk-application-prefer-dark-theme=1\n"
        with open(os.path.join(cfg, v, "settings.ini"), "w", encoding="utf-8") as f:
            f.write(text)
    xf = os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml")
    os.makedirs(xf, exist_ok=True)
    for name in ("xfwm4.xml", "xsettings.xml"):
        src = os.path.join(xdg, "xfce4", "xfconf", "xfce-perchannel-xml", name)
        if os.path.exists(src):
            text = open(src, encoding="utf-8").read().replace("WhiteSur-Light", theme).replace("WhiteSur-light", icons)
            # xvfb nema kompozitor (stin okna by byl cerny)
            text = text.replace('name="use_compositing" type="bool" value="true"',
                                'name="use_compositing" type="bool" value="false"')
            with open(os.path.join(xf, name), "w", encoding="utf-8") as f:
                f.write(text)
    env = dict(os.environ)
    env.update({"HOME": home, "XDG_CONFIG_HOME": cfg, "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
                "XDG_CACHE_HOME": os.path.join(home, ".cache"), "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
                "XDG_RUNTIME_DIR": run_dir, "LUXOS_SHOTS_ROOT": root, "GTK_THEME": theme,
                "LANG": "en_US.UTF-8", "LANGUAGE": "en", "LC_ALL": "", "NO_AT_BRIDGE": "1",
                "XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11", "GDK_BACKEND": "x11",
                # bez portalu a gvfs (jejich FUSE pripojeni v XDG_RUNTIME_DIR by zustala po behu)
                "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local"})
    for k in ("LC_MESSAGES", "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL", "DBUS_SESSION_BUS_ADDRESS",
              "WAYLAND_DISPLAY", "XDG_DATA_DIRS"):
        env.pop(k, None)
    return root, env


# ---- sezeni jedne aplikace ------------------------------------------------------
class Session:
    def __init__(self, app_id, base_env, out_dir, work, dark, shell):
        self.app_id, self.dark, self.shell = app_id, dark, shell
        self.repo, self.packages = REPO, PACKAGES
        self.tmp = os.path.join(work, app_id + ("-dark" if dark else ""))
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        for d in (".config", ".local/share", ".cache", ".local/state", "Documents", "Pictures", "Downloads",
                  "Desktop", "Music", "Videos"):
            os.makedirs(os.path.join(self.home, d), exist_ok=True)
        # nastaveni vzhledu GTK jako v sezeni
        shutil.copytree(os.path.join(base_env["XDG_CONFIG_HOME"], "gtk-3.0"), os.path.join(self.home, ".config", "gtk-3.0"))
        shutil.copytree(os.path.join(base_env["XDG_CONFIG_HOME"], "gtk-4.0"), os.path.join(self.home, ".config", "gtk-4.0"))
        self.env = dict(base_env)
        self.env.update({"HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                         "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                         "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
                         "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
                         "LUXOS_I18N_DIR": os.path.join(PACKAGES, "luxos-i18n", "files"),
                         "PYTHONDONTWRITEBYTECODE": "1"})
        self.out_dir = os.path.join(out_dir, app_id)
        self.shots = []
        self.procs = []
        self._servers = []

    # -- cesty a sestaveni --
    def src(self, rel):
        """Cesta ve zdrojich: packages/<rel>."""
        return os.path.join(PACKAGES, rel)

    def lslc(self, main, extra_dirs=(), name=None):
        """Prelozi program v LSL (packages/<main>) do docasne slozky; extra_dirs = slozky s moduly (packages/...),
        ktere se zkopiruji vedle (jako build() v PKGBUILD). Vysledek se pamatuje podle obsahu zdroju."""
        main_path = self.src(main)
        dirs = [os.path.dirname(main_path)] + [self.src(d) for d in extra_dirs]
        h = hashlib.sha256()
        for d in dirs:
            for f in sorted(os.listdir(d)):
                if f.endswith(".lsl"):
                    h.update(f.encode())
                    with open(os.path.join(d, f), "rb") as fh:
                        h.update(fh.read())
        cache = os.path.join(os.path.dirname(self.tmp), "lsl-cache", h.hexdigest()[:16])
        out = os.path.join(cache, name or os.path.basename(main_path)[:-4])
        if os.path.exists(out):
            return out
        build = os.path.join(cache, "src")
        os.makedirs(build, exist_ok=True)
        for d in reversed(dirs):          # soubory programu maji prednost pred spolecnymi moduly
            for f in os.listdir(d):
                if f.endswith(".lsl"):
                    shutil.copy(os.path.join(d, f), build)
        subprocess.run(["lslc", "--target", "linux-x86_64-gnu", os.path.basename(main_path), out], cwd=build,
                       check=True, timeout=900)
        return out

    def python_env(self, *extra):
        """PYTHONPATH pro program v Pythonu ze zdroju (moduly z pracovni kopie maji prednost)."""
        paths = [self.src(p) for p in extra] + PYTHON_PATHS
        self.env["PYTHONPATH"] = ":".join(paths + ([self.env["PYTHONPATH"]] if self.env.get("PYTHONPATH") else []))
        return self.env

    def write(self, rel, text, mode=0o644):
        """Soubor v docasnem HOME (rel vuci HOME)."""
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    # -- procesy --
    def launch(self, cmd, env=None, cwd=None, log=None):
        e = dict(self.env)
        e.update(env or {})
        logf = open(log or os.path.join(self.tmp, "app-%d.log" % len(self.procs)), "ab")
        p = subprocess.Popen(cmd, env=e, cwd=cwd or self.home, stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        return p

    def launch_python(self, rel, *args, env=None, paths=()):
        """Program v Pythonu ze zdroju (packages/<rel>) s moduly z pracovni kopie."""
        self.python_env(*paths)
        return self.launch([sys.executable, self.src(rel), *args], env=env)

    def stop(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.time() + 5
        for p in self.procs:
            try:
                p.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.procs = []
        for srv in self._servers:
            srv.shutdown()
            srv.server_close()
        self._servers = []

    def serve_http(self, handler_cls):
        """Falesny HTTP server na 127.0.0.1 (nahodny port) ve vlakne -> port."""
        class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True
        srv = Srv(("127.0.0.1", 0), handler_cls)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self._servers.append(srv)
        return srv.server_address[1]

    def sleep(self, sec):
        self.shell.pump(sec)

    # -- okna a vstup --
    def xdo(self, *args, check=False):
        r = subprocess.run(["xdotool", *[str(a) for a in args]], env=self.env, capture_output=True, text=True,
                           timeout=30)
        if check and r.returncode:
            raise RuntimeError("xdotool %s: %s" % (" ".join(map(str, args)), r.stderr.strip()))
        return r.stdout.strip()

    def window(self, name=None, pid=None, cls=None, timeout=25, size=(1040, 700), place=True):
        """Pocka na viditelne okno (podle titulku, pid nebo tridy WM_CLASS) a nastavi mu velikost a stred.
        size=None nechava velikost, place=False i polohu (napr. dialogy)."""
        args = ["search", "--onlyvisible"]
        if pid:
            args += ["--pid", pid]
        if name:
            args += ["--name", name]
        if cls:
            args += ["--class", cls]
        if not (pid or name or cls):
            raise ValueError("window(): name, pid or cls")
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = self.xdo(*args)
            ids = [int(x) for x in out.split()] if out else []
            if ids:
                win = ids[-1]
                self.shell.pump(0.5)
                if size:
                    self.xdo("windowsize", win, size[0], size[1])
                    self.shell.pump(0.3)
                if place:
                    self.center(win)
                self.xdo("windowactivate", win)
                self.shell.pump(0.8)
                return win
            self.shell.pump(0.3)
        for i, _p in enumerate(self.procs):
            log = os.path.join(self.tmp, "app-%d.log" % i)
            if os.path.exists(log):
                sys.stderr.write(open(log, errors="replace").read()[-3000:])
        raise RuntimeError("window did not appear (name=%r pid=%r cls=%r)" % (name, pid, cls))

    def center(self, win):
        x, y, w, h = self.shell.frame(win)
        self.xdo("windowmove", win, max(0, (SCREEN[0] - w) // 2), max(0, (SCREEN[1] - h) // 2))
        self.shell.pump(0.3)

    def activate(self, win):
        self.xdo("windowactivate", win)
        self.shell.pump(0.3)

    def key(self, keys, win=None, delay=0.4):
        """Klavesy pro xdotool (napr. "ctrl+f", "Return", "Down Down")."""
        if win:
            self.xdo("windowactivate", "--sync", win)
        self.xdo("key", "--clearmodifiers", *keys.split())
        self.shell.pump(delay)

    def type(self, text, win=None, delay=0.4):
        if win:
            self.xdo("windowactivate", "--sync", win)
        self.xdo("type", "--delay", 25, text)
        self.shell.pump(delay)

    def click(self, x, y, win=None, button=1, delay=0.5):
        """Kliknuti na x, y vuci obsahu okna win (jinak vuci obrazovce)."""
        if win:
            self.xdo("mousemove", "--window", win, x, y)
        else:
            self.xdo("mousemove", x, y)
        self.xdo("click", button)
        self.shell.pump(delay)

    def park_mouse(self):
        self.xdo("mousemove", SCREEN[0] - 2, SCREEN[1] - 2)

    # -- snimky --
    def capture(self, name, win, pad=0):
        """Snimek okna vcetne ramecku xfwm4 -> <out>/<app-id>/<name>.webp (tmavy: <name>-dark.webp)."""
        self.park_mouse()
        self.shell.pump(0.6)
        x, y, w, h = self.shell.frame(win)
        x, y = max(0, x - pad), max(0, y - pad)
        w, h = min(SCREEN[0] - x, w + 2 * pad), min(SCREEN[1] - y, h + 2 * pad)
        pix = self.shell.grab(x, y, w, h)
        fname = name + ("-dark" if self.dark else "")
        os.makedirs(self.out_dir, exist_ok=True)
        raw = os.path.join(self.tmp, fname + ".png")
        pix.savev(raw, "png", [], [])
        path = os.path.join(self.out_dir, fname + ".webp")
        width, height, size = save_webp(pix, path)
        self.shots.append({"name": name, "file": fname + ".webp", "width": width, "height": height, "bytes": size})
        print("  %s/%s %dx%d %d KB" % (self.app_id, fname + ".webp", width, height, size // 1024))
        return path


def save_webp(pix, path):
    """WebP do MAX_BYTES: nejvys MAX_WIDTH px, kvalita postupne nizsi."""
    from gi.repository import GdkPixbuf
    if pix.get_width() > MAX_WIDTH:
        h = round(pix.get_height() * MAX_WIDTH / pix.get_width())
        pix = pix.scale_simple(MAX_WIDTH, h, GdkPixbuf.InterpType.HYPER)
    tmp = path + ".tmp"
    for q in (90, 85, 80, 74, 68, 60, 52, 45):
        pix.savev(tmp, "webp", ["quality"], [str(q)])
        if os.path.getsize(tmp) <= MAX_BYTES:
            break
    else:
        # porad velky: zmensit
        w = int(pix.get_width() * 0.85)
        pix = pix.scale_simple(w, round(pix.get_height() * w / pix.get_width()), GdkPixbuf.InterpType.HYPER)
        pix.savev(tmp, "webp", ["quality"], ["70"])
    os.replace(tmp, path)
    return pix.get_width(), pix.get_height(), os.path.getsize(path)


# ---- displej: pozadi plochy, snimani --------------------------------------------
class Shell:
    def __init__(self, dark):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkX11", "3.0")
        from gi.repository import Gdk, GdkX11, Gtk
        self.Gtk, self.Gdk, self.GdkX11 = Gtk, Gdk, GdkX11
        # plocha: jednobarevne pozadi (rohy ramecku oken nejsou cerne)
        self.desk = Gtk.Window()
        self.desk.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.desk.set_decorated(False)
        self.desk.move(0, 0)
        self.desk.set_default_size(*SCREEN)
        css = Gtk.CssProvider()
        css.load_from_data(b"window.desk { background: %s; }" % (b"#2a2c38" if dark else b"#e8eaf1"))
        self.desk.get_style_context().add_class("desk")
        self.desk.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.desk.show_all()
        self.pump(0.5)

    def pump(self, sec):
        end = time.time() + sec
        while True:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if time.time() >= end:
                break
            time.sleep(0.02)

    def frame(self, xid):
        """Obdelnik okna vcetne ramecku ve sradnicich obrazovky."""
        disp = self.Gdk.Display.get_default()
        w = self.GdkX11.X11Window.foreign_new_for_display(disp, xid)
        r = w.get_frame_extents()
        x, y = max(0, r.x), max(0, r.y)
        return x, y, min(SCREEN[0] - x, r.width), min(SCREEN[1] - y, r.height)

    def grab(self, x, y, w, h):
        root = self.Gdk.get_default_root_window()
        return self.Gdk.pixbuf_get_from_window(root, x, y, w, h)


# ---- spusteni -----------------------------------------------------------------
def recipes():
    return sorted(f[:-3] for f in os.listdir(APPS_DIR) if f.endswith(".py") and not f.startswith("_"))


def load_recipe(app_id):
    spec = importlib.util.spec_from_file_location("shots_" + app_id.replace("-", "_"), os.path.join(APPS_DIR, app_id + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_manifest(out_dir, results, dark):
    path = os.path.join(out_dir, "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {}
    for app_id, shots in results.items():
        entries = {e["file"].rsplit(".", 1)[0].replace("-dark", ""): e for e in manifest.get(app_id, [])}
        if not dark:
            # svetle snimky urcuji seznam (stare jmena pryc), tmave jen doplni
            old = entries
            entries = {}
            for s in shots:
                e = {"file": s["file"], "width": s["width"], "height": s["height"]}
                if s["name"] in old and old[s["name"]].get("dark"):
                    dark_file = os.path.join(out_dir, app_id, old[s["name"]]["dark"])
                    if os.path.exists(dark_file):
                        e["dark"] = old[s["name"]]["dark"]
                entries[s["name"]] = e
        else:
            for s in shots:
                if s["name"] in entries:
                    entries[s["name"]]["dark"] = s["file"]
        manifest[app_id] = [entries[k] for k in sorted(entries)]
        # soubory, ktere uz manifest nezna
        keep = {e["file"] for e in manifest[app_id]} | {e["dark"] for e in manifest[app_id] if e.get("dark")}
        d = os.path.join(out_dir, app_id)
        for f in os.listdir(d) if os.path.isdir(d) else []:
            if f.endswith(".webp") and f not in keep:
                os.unlink(os.path.join(d, f))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: manifest[k] for k in sorted(manifest)}, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def start_wm(env):
    wm = subprocess.Popen(["xfwm4", "--compositor=off"], env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(1.5)
    return wm


def main():
    ap = argparse.ArgumentParser(description="LuxOS Store screenshots (run via store-screenshots.sh)")
    ap.add_argument("apps", nargs="*")
    ap.add_argument("--dark", action="store_true", help="also dark variant")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = ap.parse_args()
    if args.list:
        print("\n".join(recipes()))
        return 0
    guard_display()
    apps = args.apps or recipes()
    unknown = [a for a in apps if a not in recipes()]
    if unknown:
        die("no recipe for: " + ", ".join(unknown))
    if os.environ.get("LUXOS_SHOTS_INNER") != "1":
        # prvni beh: pripravit HOME a XDG_RUNTIME_DIR, pak znovu pod vlastnim D-Bus (xfconfd zdedi docasny HOME)
        failed = 0
        for dark in ((False, True) if args.dark else (False,)):
            root, env = prepare_session(dark)
            env["LUXOS_SHOTS_INNER"] = "1"
            env["LUXOS_SHOTS_VARIANT"] = "dark" if dark else "light"
            cmd = ["dbus-run-session", "--", sys.executable, os.path.abspath(__file__), "--out", args.out] + apps
            rc = subprocess.call(cmd, env=env)
            failed |= rc
            if args.keep:
                print("kept: " + root)
            else:
                shutil.rmtree(root, ignore_errors=True)
        return 1 if failed else 0

    dark = os.environ.get("LUXOS_SHOTS_VARIANT") == "dark"
    base_env = dict(os.environ)
    base_env.pop("LUXOS_SHOTS_INNER", None)
    shell = Shell(dark)
    wm = start_wm(base_env)
    work = os.path.join(os.environ["LUXOS_SHOTS_ROOT"], "apps")
    os.makedirs(work, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    results, failed = {}, []
    try:
        for app_id in apps:
            print("== %s (%s)" % (app_id, "dark" if dark else "light"), flush=True)
            s = Session(app_id, base_env, args.out, work, dark, shell)
            try:
                load_recipe(app_id).shots(s)
                if s.shots:
                    results[app_id] = s.shots
                else:
                    failed.append(app_id)
            except Exception:
                traceback.print_exc()
                failed.append(app_id)
            finally:
                s.stop()
                shell.pump(0.5)
    finally:
        try:
            os.killpg(wm.pid, signal.SIGTERM)
        except OSError:
            pass
    write_manifest(args.out, results, dark)
    if failed:
        print("FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
