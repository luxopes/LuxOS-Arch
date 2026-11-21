"""LuxOS - spolecne pomucky testu aplikaci Nastaveni prepsanych do LSL (luxos-settings, luxos-power,
luxos-lock-settings, luxos-whats-new, luxos-tour).

  build(name)                         prelozi files/lsl/<name>.lsl (lslc 0.11, --system-bindings), cesta k binarce
  X11App(binary, env, script)         aplikace ve vlastnim Xvfb (luxos_testguard), skript LUXOS_UI_TEST,
                                      .dump() / .wait_dump(), .window() (xdotool), .hints(), .shot(png), .pss()
  WaylandApp(binary, env, script)     totez v luxwm headless (scripts/wl-test/wlt), snimek pres grim
  fake_bin(folder, programs)          falesne programy v PATH: zapisuji argv do $FAKE_LOG, vystup z FAKE_OUT_<nazev>

Testy GUI bezi jen ve virtualni obrazovce nebo v headless kompozitoru, nikdy na skutecne obrazovce.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import luxos_testguard  # noqa: E402
import lsl_app  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
LSL_DIR = Path(os.environ.get("LUXOS_LSL_DIR") or PKG / "files" / "lsl")
I18N = REPO / "packages" / "luxos-i18n" / "files"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
WLT = REPO / "scripts/wl-test/wlt"
WLT_OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or WLT_OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
HAVE_X11 = bool(shutil.which("Xvfb") and shutil.which("xdotool") and shutil.which("dbus-run-session"))
HAVE_WAYLAND = (LUXWM_BUILD / "luxwm").exists() and (SYSROOT / "usr/bin/grim").exists()

_built = {}


def private_dir():
    return luxos_testguard._private_dir()


def lslc_ok():
    """lslc 0.11+ (system bindings); host muze mit starsi 0.10."""
    if not LSLC:
        return False
    lsl = Path(LSLC).resolve().parent / "lsl"
    if not lsl.exists():
        return False
    r = subprocess.run([str(lsl), "version"], capture_output=True, text=True)
    parts = (r.stdout.strip().split() or ["0"])[-1].split(".")
    return len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() and (int(parts[0]), int(parts[1])) >= (0, 11)


def build(name):
    if name in _built:
        return _built[name]
    out = Path(tempfile.mkdtemp(prefix="lslbuild-", dir=private_dir())) / name
    if not (LSL_DIR / f"{name}.lsl").exists() and name in lsl_app.SETTINGS_ALIASES:
        # stary program nastaveni je odkaz na luxos-settings (stranka podle jmena)
        out.symlink_to(build("luxos-settings"))
        _built[name] = out
        return out
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(LSL_DIR),
                        str(LSL_DIR / f"{name}.lsl"), str(out)], capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError(f"lslc {name}: {r.stdout[-2000:]}{r.stderr[-3000:]}")
    _built[name] = out
    return out


FAKE = """#!/bin/sh
printf '%s' "$(basename "$0")" >>"$FAKE_LOG"
for a in "$@"; do printf ' %s' "$a" >>"$FAKE_LOG"; done
printf '\\n' >>"$FAKE_LOG"
var="FAKE_OUT_$(basename "$0" | tr -c 'a-zA-Z0-9\\n' _)"
eval "out=\\${$var-}"
[ -n "$out" ] && printf '%s\\n' "$out"
var="FAKE_RC_$(basename "$0" | tr -c 'a-zA-Z0-9\\n' _)"
eval "rc=\\${$var-0}"
exit "$rc"
"""


def fake_bin(folder, programs, scripts=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in programs:
        (folder / name).write_text((scripts or {}).get(name, FAKE))
        (folder / name).chmod(0o755)
    return folder


def base_env(tmp, lang="C.UTF-8"):
    tmp = Path(tmp)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG", "WAYLAND", "DISPLAY", "XDG_",
                                                                      "DBUS_SESSION"))}
    env.update(HOME=str(tmp / "home"), XDG_CONFIG_HOME=str(tmp / "config"), XDG_CACHE_HOME=str(tmp / "cache"),
               XDG_DATA_HOME=str(tmp / "data"), XDG_RUNTIME_DIR=str(tmp / "run"), LANG=lang,
               LUXOS_I18N_DIR=str(I18N), GTK_THEME="WhiteSur-Light", NO_AT_BRIDGE="1", GTK_A11Y="none",
               GSETTINGS_BACKEND="keyfile", GIO_USE_VFS="local", GTK_USE_PORTAL="0",
               DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent", FAKE_LOG=str(tmp / "fake.log"))
    for d in ("home", "config", "cache", "data"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "run").mkdir(mode=0o700, parents=True, exist_ok=True)
    return env


def free_display():
    for n in range(600, 700):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    raise RuntimeError("no free display")


def pss_kb(pid):
    """PSS procesu a jeho potomku (kB) z /proc/PID/smaps_rollup."""
    total = 0
    pids = [pid]
    try:
        for line in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
            pids.append(int(line))
    except OSError:
        pass
    for p in pids:
        try:
            for line in Path(f"/proc/{p}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except OSError:
            pass
    return total


class _App:
    def __init__(self, argv, env, script, tmp):
        self.tmp = Path(tmp)
        self.script = self.tmp / "ui-test"
        self.script.write_text("\n".join(script or ["wait 600000"]) + "\n")
        self.out = Path(str(self.script) + ".out")
        env = dict(env, LUXOS_UI_TEST=str(self.script))
        self.env = env
        self.argv = argv

    def dumps(self):
        if not self.out.exists():
            return []
        parts = self.out.read_text().split("----\n")
        return [p.splitlines() for p in parts if p.strip()]

    def wait_dump(self, count=1, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self.dumps()
            if len(d) >= count:
                return d[count - 1]
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        raise AssertionError(f"no dump {count} (rc {self.proc.poll()}): {self.stderr()}")

    def wait_exit(self, timeout=20):
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            raise AssertionError("app did not quit: " + self.stderr())

    def stderr(self):
        p = self.tmp / "stderr"
        return p.read_text()[-3000:] if p.exists() else ""

    def app_pid(self):
        """Proces aplikace pod dbus-run-session (podle argv[-1] v prikazove radce)."""
        want = os.path.basename(self.argv[-1])
        for _ in range(50):
            try:
                kids = Path(f"/proc/{self.proc.pid}/task/{self.proc.pid}/children").read_text().split()
            except OSError:
                kids = []
            for k in kids:
                try:
                    cmd = Path(f"/proc/{k}/cmdline").read_bytes().split(b"\0")
                except OSError:
                    continue
                if any(os.path.basename(c.decode()) == want for c in cmd if c):
                    return int(k)
            time.sleep(0.1)
        raise AssertionError("app process not found")

    def pss(self):
        return pss_kb(self.app_pid())


class X11App(_App):
    def __init__(self, argv, env, script=None, size=(1366, 768), tmp=None):
        tmp = tmp or tempfile.mkdtemp(prefix="x11app-", dir=private_dir())
        super().__init__(argv, env, script, tmp)
        self.n = free_display()
        self.display = ":%d" % self.n
        self.xvfb = subprocess.Popen(["Xvfb", self.display, "-screen", "0", "%dx%dx24" % size, "-nolisten", "tcp"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if os.path.exists("/tmp/.X11-unix/X%d" % self.n):
                break
            time.sleep(0.05)
        self.env = dict(self.env, DISPLAY=self.display)
        luxos_testguard.check_env(self.env)
        with open(self.tmp / "stderr", "w") as err:
            self.proc = subprocess.Popen(["dbus-run-session", "--", *argv], env=self.env, stdout=err, stderr=err)

    def xdotool(self, *args):
        return subprocess.run(["xdotool", *args], env={"DISPLAY": self.display, "PATH": os.environ["PATH"]},
                              capture_output=True, text=True, timeout=10).stdout

    def window(self, name):
        """[sirka, vyska] X okna (vcetne HeaderBar) podle titulku."""
        for _ in range(100):
            ids = self.xdotool("search", "--onlyvisible", "--name", "^" + name + "$").split()
            if ids:
                geo = self.xdotool("getwindowgeometry", "--shell", ids[0])
                vals = dict(line.split("=", 1) for line in geo.splitlines() if "=" in line)
                return {"id": ids[0], "width": int(vals["WIDTH"]), "height": int(vals["HEIGHT"])}
            time.sleep(0.1)
        raise AssertionError(f"no window {name!r}: {self.stderr()}")

    def hints(self, wid):
        """Nejmensi velikost z WM_NORMAL_HINTS (program specified minimum size)."""
        out = subprocess.run(["xprop", "-id", wid, "WM_NORMAL_HINTS"], env={"DISPLAY": self.display,
                             "PATH": os.environ["PATH"]}, capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "minimum size" in line:
                w, h = line.split(":")[1].strip().split(" by ")
                return int(w), int(h)
        return None

    def shot(self, path):
        code = ("import gi,sys; gi.require_version('Gdk','3.0'); from gi.repository import Gdk; "
                "w=Gdk.get_default_root_window(); "
                "Gdk.pixbuf_get_from_window(w,0,0,w.get_width(),w.get_height()).savev(sys.argv[1],'png',[],[])")
        subprocess.run([sys.executable, "-c", code, str(path)], env={"DISPLAY": self.display, "PATH": os.environ["PATH"],
                       "HOME": self.env["HOME"]}, check=True, timeout=20, capture_output=True)

    def close(self):
        for p in (self.proc, self.xvfb):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


class WaylandApp(_App):
    """Aplikace v luxwm headless (xwayland = no), snimek obrazovky pres grim."""

    def __init__(self, argv, env, script=None, size="1366x768", tmp=None):
        tmp = tmp or tempfile.mkdtemp(prefix="wlapp-", dir=private_dir())
        super().__init__(argv, env, script, tmp)
        conf = self.tmp / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        wenv = dict(os.environ, WLT_COMPOSITOR_ENV=f"LUXWM_SYSTEM_CONFIG={conf} "
                                                   f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        name = f"a{os.getpid() % 10000}-{int(time.monotonic() * 1000) % 100000}"
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", size, "--timeout", "600", "--name", name,
                            "--", str(LUXWM_BUILD / "luxwm")], env=wenv, capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise AssertionError("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        wl = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            wl[key] = value
        self.env = dict(self.env, WAYLAND_DISPLAY=wl["WAYLAND_DISPLAY"], XDG_RUNTIME_DIR=wl["XDG_RUNTIME_DIR"],
                        GDK_BACKEND="wayland")
        # runtime adresar relace wlt (soukromy, pod out/wl-test/sessions), zadny DISPLAY
        assert self.env["XDG_RUNTIME_DIR"].startswith(str(self.session)) and "DISPLAY" not in self.env
        with open(self.tmp / "stderr", "w") as err:
            self.proc = subprocess.Popen(["dbus-run-session", "--", *argv], env=self.env, stdout=err, stderr=err)

    def shot(self, path):
        r = subprocess.run([str(WLT), "shot", str(self.session), str(path)], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError("wlt shot: " + r.stdout + r.stderr)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)
