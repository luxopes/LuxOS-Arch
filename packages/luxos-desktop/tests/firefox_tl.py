"""LuxOS - Firefox s tlacitky okna LuxOS v testovacim displeji (jen pod Xvfb, nikdy na skutecne obrazovce).

Firefox bezi z "kopie" instalace pod out/: skutecny spustitelny soubor firefox (zbytek jsou odkazy na
/usr/lib/firefox), aby autoconfig nasel luxos.cfg, defaults/pref a luxos/titlebar.css z repozitare (nebo
z rozbaleneho balicku) bez instalace do systemu. Ovladani a cteni stylu pres Marionette (chrome kontext),
snimky obrazovky pres GDK z korenoveho okna Xvfb, spravce oken xfwm4 s tematem WhiteSur.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.environ.get("LUXOS_FIREFOX_TL_OUT") or os.path.join(REPO, "out", "firefox-tl")
FIREFOX_DIR = "/usr/lib/firefox"

# malo procesu (jeden obsahovy, bez fission): testy bezi ve scope s TasksMax=300 a pocita se kazde vlakno
PREFS = """user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("dom.ipc.processCount", 1);
user_pref("fission.autostart", false);
user_pref("dom.ipc.processPrelaunch.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("app.update.disabledForTesting", true);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.warnOnQuit", false);
user_pref("browser.tabs.inTitlebar", 1);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
user_pref("sidebar.revamp", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("marionette.port", %d);
"""


def firefox_available():
    return os.access(os.path.join(FIREFOX_DIR, "firefox"), os.X_OK) and bool(shutil.which("xfwm4"))


def on_test_display():
    """Jen virtualni displej xvfb-run (nebo vyslovne LUXOS_TEST_X=1)."""
    return bool(os.environ.get("DISPLAY")) and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                or os.environ.get("LUXOS_TEST_X") == "1")


def build_root(dest, cfg_dir=None, extensions=()):
    """Instalace Firefoxu pod dest: firefox zkopirovany, ostatni odkazy; LuxOS soubory z cfg_dir
    (koren rozbaleneho balicku) nebo z files/ repozitare. extensions: soubory .xpi do
    browser/extensions (doplnky v adresari aplikace jako z balicku firefox-ublock-origin)."""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.join(dest, "defaults", "pref"))
    for name in os.listdir(FIREFOX_DIR):
        src = os.path.join(FIREFOX_DIR, name)
        if name in ("defaults", "luxos", "luxos.cfg"):
            continue
        if name == "firefox":
            shutil.copy2(src, os.path.join(dest, name))
        elif name == "browser":
            # vlastni browser/extensions (skutecny adresar Firefoxu se nemeni), zbytek odkazy
            os.makedirs(os.path.join(dest, "browser", "extensions"))
            for sub in os.listdir(src):
                if sub != "extensions":
                    os.symlink(os.path.realpath(os.path.join(src, sub)), os.path.join(dest, "browser", sub))
            for xpi in extensions:
                shutil.copy2(xpi, os.path.join(dest, "browser", "extensions", os.path.basename(xpi)))
        else:
            os.symlink(os.path.realpath(src), os.path.join(dest, name))
    for name in os.listdir(os.path.join(FIREFOX_DIR, "defaults", "pref")):
        if not name.startswith("luxos"):
            os.symlink(os.path.join(FIREFOX_DIR, "defaults", "pref", name), os.path.join(dest, "defaults", "pref", name))
    if cfg_dir:
        lib = os.path.join(cfg_dir, "usr", "lib", "firefox")
        for name in os.listdir(os.path.join(lib, "defaults", "pref")):
            shutil.copy2(os.path.join(lib, "defaults", "pref", name), os.path.join(dest, "defaults", "pref", name))
        shutil.copy2(os.path.join(lib, "luxos.cfg"), os.path.join(dest, "luxos.cfg"))
        shutil.copytree(os.path.join(lib, "luxos"), os.path.join(dest, "luxos"))
    else:
        ff = os.path.join(FILES, "firefox")
        for name in ("luxos.js", "luxos-autoconfig.js"):
            shutil.copy2(os.path.join(ff, name), os.path.join(dest, "defaults", "pref", name))
        shutil.copy2(os.path.join(ff, "luxos.cfg"), os.path.join(dest, "luxos.cfg"))
        os.makedirs(os.path.join(dest, "luxos"))
        shutil.copy2(os.path.join(ff, "titlebar.css"), os.path.join(dest, "luxos", "titlebar.css"))
        shutil.copytree(os.path.join(ff, "welcome"), os.path.join(dest, "luxos", "welcome"))
    return dest


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Marionette:
    def __init__(self, port, timeout=60):
        end = time.time() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.3)
        self.sock.settimeout(60)
        self.buf = b""
        self.id = 0
        self.recv()                                    # uvitani {"applicationType":"gecko",...}
        self.cmd("WebDriver:NewSession", {"capabilities": {}})
        self.cmd("Marionette:SetContext", {"value": "chrome"})

    def recv(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        n, rest = self.buf.split(b":", 1)
        n = int(n)
        while len(rest) < n:
            rest += self.sock.recv(65536)
        self.buf = rest[n:]
        return json.loads(rest[:n])

    def cmd(self, name, params=None):
        self.id += 1
        data = json.dumps([0, self.id, name, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self.recv()
            if msg[0] == 1 and msg[1] == self.id:
                if msg[2]:
                    raise RuntimeError("%s: %s" % (name, msg[2]))
                return msg[3]

    def js(self, script, *args):
        r = self.cmd("WebDriver:ExecuteScript", {"script": script, "args": list(args)})
        return r.get("value") if isinstance(r, dict) else r

    def windows(self):
        return self.cmd("WebDriver:GetWindowHandles")

    def switch(self, handle):
        self.cmd("WebDriver:SwitchToWindow", {"handle": handle, "focus": False})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# stav tlacitek v chrome okne: viditelna tlacitka (poradi na obrazovce), jejich ikona a vypocteny styl
BUTTONS_JS = r"""
const out = [];
for (const b of document.querySelectorAll('.titlebar-button')) {
  const r = b.getBoundingClientRect();
  if (!r.width || !r.height) continue;
  const icon = b.querySelector('.toolbarbutton-icon');
  const ir = icon ? icon.getBoundingClientRect() : null;
  const cs = icon ? getComputedStyle(icon) : null;
  out.push({cls: b.className, toolbar: b.closest('toolbar') ? b.closest('toolbar').id : '',
            x: r.x, y: r.y, w: r.width, h: r.height,
            icon: ir && {x: ir.x, y: ir.y, w: ir.width, h: ir.height},
            bg: cs && cs.backgroundColor, img: cs && cs.backgroundImage, radius: cs && cs.borderRadius,
            shadow: cs && cs.boxShadow});
}
out.sort((a, b) => a.x - b.x);
return {buttons: out, scale: window.devicePixelRatio, mozInnerScreenX: window.mozInnerScreenX,
        mozInnerScreenY: window.mozInnerScreenY, sizemode: document.documentElement.getAttribute('sizemode'),
        width: window.outerWidth, height: window.outerHeight};
"""


class Session:
    """Xvfb uz bezi (xvfb-run); vlastni HOME/XDG_* pod out/, vlastni D-Bus, xfwm4, GTK nastaveni LuxOS."""

    def __init__(self, dark=False, scale=1, name="run", compositor="on"):
        if not on_test_display():
            raise RuntimeError("Run under xvfb-run - never on a real display.")
        os.makedirs(OUT, exist_ok=True)
        self.home = tempfile.mkdtemp(prefix=name + "-", dir=OUT)
        real_home = os.path.realpath(os.path.expanduser("~"))
        run = os.path.join(self.home, "run")
        os.makedirs(run, mode=0o700)
        os.chmod(run, 0o700)
        xdg = os.path.join(self.home, "xdg")
        shutil.copytree(os.path.join(FILES, "xdg"), xdg, symlinks=True)
        theme = "WhiteSur-Dark" if dark else "WhiteSur-Light"
        cfg = os.path.join(self.home, ".config")
        os.makedirs(os.path.join(cfg, "gtk-3.0"))
        with open(os.path.join(xdg, "gtk-3.0", "settings.ini")) as f:
            ini = f.read().replace("WhiteSur-Light", theme)
        if dark:
            ini += "gtk-application-prefer-dark-theme=1\n"
        with open(os.path.join(cfg, "gtk-3.0", "settings.ini"), "w") as f:
            f.write(ini)
        xml = os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml")
        os.makedirs(xml)
        with open(os.path.join(xdg, "xfce4", "xfconf", "xfce-perchannel-xml", "xfwm4.xml")) as f:
            wm = f.read().replace("WhiteSur-Light", theme)
        with open(os.path.join(xml, "xfwm4.xml"), "w") as f:
            f.write(wm)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "DBUS_", "SESSION_MANAGER", "MOZ_"))}
        env.update(HOME=self.home, XDG_RUNTIME_DIR=run, XDG_CONFIG_HOME=cfg,
                   XDG_CACHE_HOME=os.path.join(self.home, ".cache"),
                   XDG_DATA_HOME=os.path.join(self.home, ".local", "share"),
                   XDG_STATE_HOME=os.path.join(self.home, ".local", "state"),
                   XDG_CONFIG_DIRS=xdg + ":/etc/xdg", XDG_DATA_DIRS="/usr/local/share:/usr/share",
                   # relace Xfce jako v LuxOS (bez toho Firefox na X11 nekresli vlastni listu: -moz-gtk-csd-available)
                   XDG_CURRENT_DESKTOP="XFCE", XDG_SESSION_TYPE="x11",
                   GTK_A11Y="none", NO_AT_BRIDGE="1", LANG="C.UTF-8", GTK_USE_PORTAL="0", GIO_USE_VFS="local",
                   MOZ_CRASHREPORTER_DISABLE="1", MOZ_USE_XINPUT2="1",
                   MOZ_REMOTE_ALLOW_SYSTEM_ACCESS="1")
        if scale != 1:
            env["GDK_SCALE"] = str(scale)
        for k, v in env.items():
            if k.endswith(("_HOME", "_DIR")) and k.startswith("XDG_"):
                p = os.path.realpath(v)
                if p == real_home or not p.startswith(os.path.realpath(OUT)):
                    raise RuntimeError("refusing %s=%s outside the test dir" % (k, v))
        self.env = env
        self.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                    env=env, stdout=subprocess.PIPE, text=True)
        env["DBUS_SESSION_BUS_ADDRESS"] = self.bus.stdout.readline().strip()
        self.wm_log = open(os.path.join(self.home, "xfwm4.log"), "w")
        self.wm = subprocess.Popen(["xfwm4", "--compositor=" + compositor, "--sm-client-disable"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=self.wm_log)
        for _ in range(100):
            if "window id" in subprocess.run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], env=env,
                                             capture_output=True, text=True).stdout:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("xfwm4 did not start")
        time.sleep(0.8)
        self.procs = []
        self.ff = None
        self.mn = None

    # -- Firefox --
    def start_firefox(self, root, extra_prefs="", args=(), url="about:blank", user_chrome=None, first_run=False,
                      env=None, size=(900, 600)):
        """first_run: jako skutecne prvni spusteni - bez potlaceni uvodnich stranek v testovacich volbach
        a bez "doporucenych" voleb Marionette (ty by prvni spusteni samy schovaly), bez adresy."""
        port = free_port()
        self.profile = os.path.join(self.home, "profile")
        os.makedirs(self.profile, exist_ok=True)
        prefs = PREFS % port
        if first_run:
            prefs = "".join(line + "\n" for line in prefs.splitlines() if not any(
                k in line for k in ("homepage_override.mstone", "reportingpolicy.firstRun", "dataSubmissionEnabled",
                                    "aboutwelcome")))
            prefs += 'user_pref("remote.prefs.recommended", false);\n'
        with open(os.path.join(self.profile, "user.js"), "w") as f:
            f.write(prefs + extra_prefs)
        if user_chrome is not None:
            os.makedirs(os.path.join(self.profile, "chrome"), exist_ok=True)
            with open(os.path.join(self.profile, "chrome", "userChrome.css"), "w") as f:
                f.write(user_chrome)
        if self.ff:
            self.ff_log.close()
        self.ff_log = open(os.path.join(self.home, "firefox.log"), "a")
        cmd = [os.path.join(root, "firefox"), "--marionette", "--no-remote", "--new-instance", "--profile", self.profile,
               "--width", str(size[0]), "--height", str(size[1]), *args]
        if url and not first_run:
            cmd.append(url)
        self.ff = subprocess.Popen(cmd, env=dict(self.env, **(env or {})), stdout=self.ff_log, stderr=subprocess.STDOUT)
        self.mn = Marionette(port)
        self.wait_window()
        return self.mn

    def quit_firefox(self):
        """Radne ukonceni (profil si zapamatuje, ze uz prvni spusteni probehlo)."""
        try:
            self.mn.js("Services.startup.quit(Ci.nsIAppStartup.eForceQuit)")
        except Exception:
            pass
        self.mn.close()
        self.mn = None
        try:
            self.ff.wait(30)
        except subprocess.TimeoutExpired:
            self.ff.kill()
            self.ff.wait()

    def tab_urls(self):
        return self.mn.js("return gBrowser.tabs.map(t => t.linkedBrowser.currentURI.spec)")

    def wait_window(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                st = self.mn.js("return document.readyState == 'complete' && !!window.gBrowserInit && "
                                "gBrowserInit.delayedStartupFinished")
                if st:
                    time.sleep(1.0)
                    return
            except RuntimeError:
                pass
            time.sleep(0.3)
        raise RuntimeError("Firefox window did not finish starting")

    def buttons(self):
        return self.mn.js(BUTTONS_JS)

    def xid(self, name_re="Mozilla Firefox"):
        r = subprocess.run(["xdotool", "search", "--sync", "--onlyvisible", "--name", name_re], env=self.env,
                           capture_output=True, text=True, timeout=20)
        return [int(x) for x in r.stdout.split()]

    def xdo(self, *args):
        return subprocess.run(["xdotool", *map(str, args)], env=self.env, capture_output=True, text=True,
                              timeout=20).stdout

    def screen_xy(self, info, b):
        """Stred ikony tlacitka v souradnicich obrazovky (fyzicke pixely)."""
        s = info["scale"]
        return (round((info["mozInnerScreenX"] + b["icon"]["x"] + b["icon"]["w"] / 2) * s),
                round((info["mozInnerScreenY"] + b["icon"]["y"] + b["icon"]["h"] / 2) * s))

    def open_gtk_window(self, title="LuxOS xfwm4 reference", w=420, h=200, x=40, y=700):
        code = ("import gi,sys; gi.require_version('Gtk','3.0'); from gi.repository import Gtk;"
                "w=Gtk.Window(title=sys.argv[1]); w.set_default_size(%d,%d); w.move(%d,%d);"
                "w.connect('destroy',Gtk.main_quit); w.show_all(); Gtk.main()" % (w, h, x, y))
        p = subprocess.Popen([sys.executable, "-c", code, title], env=self.env)
        self.procs.append(p)
        wid = self.xid("^%s$" % title)[0]
        time.sleep(0.8)
        return wid

    def grab(self, path=None, rect=None):
        """Snimek korenoveho okna (nebo vyrezu x, y, w, h) -> (sirka, vyska, rowstride, bajty RGB)."""
        out = os.path.join(self.home, "grab.raw")
        code = ("import gi,sys,struct; gi.require_version('Gdk','3.0'); from gi.repository import Gdk;"
                "r=Gdk.get_default_root_window(); a=[int(v) for v in sys.argv[2].split(',')] if sys.argv[2] else "
                "[0,0,r.get_width(),r.get_height()]; pb=Gdk.pixbuf_get_from_window(r,*a);"
                "sys.argv[3] and pb.savev(sys.argv[3],'png',[],[]);"
                "open(sys.argv[1],'wb').write(struct.pack('<4i',pb.get_width(),pb.get_height(),pb.get_rowstride(),"
                "pb.get_n_channels())+pb.get_pixels())")
        env = dict(self.env, GDK_SCALE="1")
        subprocess.run([sys.executable, "-c", code, out, ",".join(map(str, rect)) if rect else "", path or ""],
                       env=env, check=True, timeout=30)
        import struct
        with open(out, "rb") as f:
            data = f.read()
        w, h, rs, n = struct.unpack("<4i", data[:16])
        return Image(w, h, rs, n, data[16:])

    def stop(self):
        if self.mn:
            self.mn.close()
        for p in self.procs + ([self.ff] if self.ff else []):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        for p in (self.wm, self.bus):
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        # sluzby, ktere sbernice relace aktivovala (xfconfd, portaly, klicenka, a11y): podle adresy sbernice
        # v prostredi, jinak zustanou bezet a kazda dalsi relace modulu pridava dalsi (pamet, limit procesu)
        mark = ("DBUS_SESSION_BUS_ADDRESS=" + self.env["DBUS_SESSION_BUS_ADDRESS"]).encode()
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                with open("/proc/%s/environ" % pid, "rb") as f:
                    if mark in f.read().split(b"\0"):
                        os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass
        self.bus.stdout.close()
        self.wm_log.close()
        if self.ff:
            self.ff_log.close()


class Image:
    def __init__(self, w, h, rs, n, data):
        self.w, self.h, self.rs, self.n, self.data = w, h, rs, n, data

    def px(self, x, y):
        o = y * self.rs + x * self.n
        return tuple(self.data[o:o + 3])


def hexrgb(c):
    return "#%02x%02x%02x" % c


def close(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def rgb(css):
    """'rgb(242, 80, 86)' -> (242, 80, 86)."""
    v = css[css.index("(") + 1:css.index(")")].split(",")
    return tuple(int(float(x)) for x in v[:3])
