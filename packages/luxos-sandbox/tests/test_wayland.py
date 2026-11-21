#!/usr/bin/env python3
"""LuxOS Sandbox na Waylandu: okna aplikaci pres vlastni soket wp-security-context (headless luxwm).

    scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY \\
      DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent systemd-run --user --scope -p TasksMax=300 \\
      -p MemoryMax=1G -p MemorySwapMax=0 -- timeout 900 python3 -m unittest -v packages/luxos-sandbox/tests/test_wayland.py

luxwm bezi headless (scripts/wl-test, pixman), luxos-sandbox ze zdrojoveho stromu v testovacim
rezimu nad malym korenem (busybox + testovaci aplikace wl-sandbox-app.c a x11-sandbox-app.c s jejich
knihovnami). Overuje, ze aplikace v sandboxu:
  - nevidi ani nebindne snimani obrazovky, data-control, seznam cizich oken, layer-shell, virtualni
    vstup, spravu vystupu, zamek ani security-context (globaly skryte, bind podle cisla = chyba protokolu);
  - nema soket Waylandu plochy, soket luxwm IPC, X11 hostitele ani D-Bus (cesty v jejim namespace
    nejsou, abstraktni sokety hostitele nedosahne);
  - schranku dostane jen se zamerenim; aktivaci (kradez zamereni) luxwm odmitne, i kdyz si
    aplikace nastavi app_id zamereneho okna;
  - jeji okno se zobrazi se zahlavim se znackou "Sandbox · prikaz" a vstup do nej funguje;
  - X11 aplikace se zobrazi pres vlastni Xwayland sandboxu (jeho okno je take klient sandboxu);
  - po skonceni behu kompozitor soket zavre a adresar behu zmizi.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
CLI = os.path.join(HERE, "..", "files", "luxos-sandbox")
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "packages", "luxwm", "tests"))
import luxos_testguard  # noqa: E402,F401  - pojistka: nikdy skutecna obrazovka ani relace
from test_luxwm import BUILD, SYSROOT, Session, wlt  # noqa: E402

PROTOCOLS = os.path.join(SYSROOT, "usr/share/wayland-protocols")
# Globaly, ktere klient sandboxu nikdy nedostane (luxcomp security.c)
DENIED = ["zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1",
          "ext_output_image_capture_source_manager_v1", "ext_foreign_toplevel_image_capture_source_manager_v1",
          "ext_data_control_manager_v1", "zwlr_data_control_manager_v1", "zwlr_foreign_toplevel_manager_v1",
          "ext_foreign_toplevel_list_v1", "zwlr_output_manager_v1", "ext_session_lock_manager_v1",
          "zwp_virtual_keyboard_manager_v1", "zwlr_virtual_pointer_manager_v1", "zwlr_layer_shell_v1",
          "ext_idle_notifier_v1", "wp_security_context_manager_v1"]
TOOLS = ("bwrap", "busybox", "gcc", "wayland-scanner")
MISSING = [t for t in TOOLS if not shutil.which(t)]
if not os.path.exists(os.path.join(BUILD, "luxwm")):
    MISSING.append("luxwm build (packages/luxwm/tests/build-host.sh)")


def copy_with_libs(binary, root, env=None):
    """Program do korene sandboxu i s knihovnami (ldd)."""
    shutil.copy(binary, os.path.join(root, "usr/bin"))
    out = subprocess.run(["ldd", binary], capture_output=True, text=True, env=env).stdout   # staticky: nic
    for lib in re.findall(r"(/\S+)", out):
        dest = os.path.join(root, "usr/lib", os.path.basename(lib))
        if not os.path.exists(dest):
            shutil.copy(lib, dest)


def sandbox_xwayland(pid):
    """PID Xwayland sandboxu mezi potomky procesu pid (ne XWayland kompozitoru ani cizi relace)."""
    parent = {}
    for d in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{d}/stat") as f:
                parent[int(d)] = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            pass
    found = []
    for q in parent:
        a = q
        while a > 1 and a != pid:
            a = parent.get(a, 0)
        if a != pid:
            continue
        try:
            with open(f"/proc/{q}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if argv[0].endswith(b"/Xwayland"):
            found.append(q)
    return found


@unittest.skipIf(MISSING, "missing: %s" % ", ".join(MISSING))
class WaylandSandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="sbx-wl-", dir=os.path.join(REPO, "out"))
        os.chmod(cls.t, 0o700)
        t = cls.t
        code = []
        for xml in ("staging/security-context/security-context-v1.xml", "stable/xdg-shell/xdg-shell.xml",
                    "unstable/xdg-decoration/xdg-decoration-unstable-v1.xml",
                    "staging/xdg-activation/xdg-activation-v1.xml"):
            base = os.path.basename(xml)[:-4]
            subprocess.run(["wayland-scanner", "client-header", os.path.join(PROTOCOLS, xml),
                            os.path.join(t, base + "-client-protocol.h")], check=True)
            code.append(os.path.join(t, base + ".c"))
            subprocess.run(["wayland-scanner", "private-code", os.path.join(PROTOCOLS, xml), code[-1]], check=True)
        cc = ["gcc", "-O1", "-Wall", "-Wno-unused-parameter", "-I", t]
        cls.helper = os.path.join(t, "luxos-sandbox-wayland")
        subprocess.run(cc + ["-o", cls.helper, os.path.join(HERE, "..", "files", "luxos-sandbox-wayland.c"), code[0],
                             "-lwayland-client"], check=True)
        cls.app = os.path.join(t, "wl-sandbox-app")
        subprocess.run(cc + ["-o", cls.app, os.path.join(HERE, "wl-sandbox-app.c"), *code[1:], "-lwayland-client"],
                       check=True)
        xapp = os.path.join(t, "x11-sandbox-app")
        cls.has_x11 = subprocess.run(cc + ["-o", xapp, os.path.join(HERE, "x11-sandbox-app.c"), "-lX11"]).returncode == 0
        # koren sandboxu (jako isolation-test.sh)
        user = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        base = os.path.join(t, "base")
        r = os.path.join(base, user)
        for d in ("usr/bin", "usr/lib", "etc", "var/tmp", "opt", "srv", "root", "mnt", "home/sandbox"):
            os.makedirs(os.path.join(r, d))
        os.chmod(base, 0o755)
        os.chmod(r, 0o700)
        copy_with_libs(shutil.which("busybox"), r)
        for a in ("sh", "ls", "cat", "env", "test", "echo", "sleep", "tr"):
            os.symlink("busybox", os.path.join(r, "usr/bin", a))
        copy_with_libs(cls.app, r)
        if cls.has_x11:
            copy_with_libs(xapp, r)
        with open(os.path.join(r, "etc/passwd"), "w") as f:
            f.write(f"root:x:0:0:root:/root:/bin/sh\nsandbox:x:{os.getuid()}:{os.getgid()}:Sandbox:/home/sandbox:/bin/sh\n")
        cls.env = {"PATH": "/usr/bin", "HOME": os.path.join(t, "home"), "LANG": "C.UTF-8",
                   "LUXOS_SANDBOX_TESTING": "1", "LUXOS_SANDBOX_BASE": base,
                   "LUXOS_SANDBOX_SHARED": os.path.join(t, "shared"), "XDG_DATA_HOME": os.path.join(t, "data"),
                   "XDG_CONFIG_HOME": os.path.join(t, "config"), "LUXOS_SANDBOX_NO_SCOPE": "1",
                   "LUXOS_SANDBOX_WL_HELPER": cls.helper, "LUXOS_SANDBOX_XWAYLAND_ROOT": SYSROOT,
                   "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent"}
        os.makedirs(cls.env["HOME"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, ignore_errors=True)

    # ---- pomocne ----

    def session(self):
        s = Session(size="1600x1000")
        self.addCleanup(s.stop)
        self.run_dir = os.path.join(s.dir, "run")
        return s

    def sandbox_env(self, s):
        debug = {"LUXOS_SANDBOX_DEBUG": "1"} if os.environ.get("LUXOS_SANDBOX_DEBUG") == "1" else {}
        return {**self.env, **debug, "XDG_RUNTIME_DIR": os.path.join(s.dir, "run"), "WAYLAND_DISPLAY": "wayland-0"}

    def sandbox(self, s, *argv):
        """Beh v sandboxu s oknem (--gui), ceka na konec -> stdout."""
        r = subprocess.run([sys.executable, "-I", CLI, "run", "--gui", "--", *argv], capture_output=True, text=True,
                           env=self.sandbox_env(s), timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def spawn(self, s, *argv):
        p = subprocess.Popen([sys.executable, "-I", CLI, "run", "--gui", "--", *argv], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=self.sandbox_env(s))
        return self.track(p)

    def track(self, p):
        """Vystup procesu cte vlakno do p.lines (radky), p.seen = kolik uz test precetl."""
        p.lines, p.seen = [], 0

        def reader():
            for line in p.stdout:
                p.lines.append(line.strip())
        p.reader = threading.Thread(target=reader, daemon=True)
        p.reader.start()
        self.addCleanup(self.stop_proc, p)
        return p

    @staticmethod
    def stop_proc(p):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        p.reader.join(5)
        p.stdout.close()

    def wait_line(self, p, want, timeout=15):
        """Ceka na radek want ve vystupu procesu; vraci nove prectene radky."""
        end = time.time() + timeout
        while time.time() < end:
            if want in p.lines[p.seen:]:
                i = p.lines.index(want, p.seen) + 1
                got, p.seen = p.lines[p.seen:i], i
                return got
            time.sleep(0.05)
        self.fail(f"no '{want}' in output: {p.lines}")

    def read_available(self, p, seconds):
        time.sleep(seconds)
        got, p.seen = p.lines[p.seen:], len(p.lines)
        return got

    def host(self, s, *argv):
        return subprocess.run([os.path.join(REPO, "scripts/wl-test/wlt"), "run", s.dir, self.app, *argv],
                              capture_output=True, text=True, timeout=60).stdout

    def host_bg(self, s, *argv):
        p = subprocess.Popen([os.path.join(REPO, "scripts/wl-test/wlt"), "run", s.dir, self.app, *argv],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return self.track(p)

    def view(self, s, title):
        for _ in range(30):
            v = s.state()["views"].get(title)
            if v:
                return v
            time.sleep(0.2)
        self.fail(f"no window {title}: {s.state()['views']}")

    def xroot(self, s, pred, timeout=10):
        """Okno X obrazovky sandboxu, az splni pred."""
        end = time.time() + timeout
        while True:
            xw = [v for v in s.state()["views"].values() if v["sandbox"] == "x11-sandbox-app"]
            if xw and pred(xw[0]):
                return xw[0]
            if time.time() > end:
                self.fail(f"sandbox X window: {xw}")
            time.sleep(0.2)

    # ---- testy ----

    def test_privileged_globals_hidden_and_unbindable(self):
        s = self.session()
        host = {ln.split()[1]: ln.split()[2] for ln in self.host(s, "--globals").splitlines()
                if ln.startswith("global ")}
        inside = {ln.split()[1] for ln in self.sandbox(s, "/usr/bin/wl-sandbox-app", "--globals").splitlines()
                  if ln.startswith("global ")}
        for name in ("wl_compositor", "xdg_wm_base", "wl_seat", "wl_data_device_manager", "xdg_activation_v1"):
            self.assertIn(name, inside)
        leaked = [name for name in DENIED if name in inside]
        self.assertEqual(leaked, [], "sandboxed client sees privileged globals")
        # schovany global podle cisla z neomezeneho spojeni: chyba protokolu, nikdy bind
        tried = 0
        for name in ("zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1",
                     "zwlr_foreign_toplevel_manager_v1", "ext_foreign_toplevel_list_v1",
                     "zwlr_data_control_manager_v1", "ext_data_control_manager_v1", "zwlr_layer_shell_v1",
                     "zwp_virtual_keyboard_manager_v1", "zwlr_virtual_pointer_manager_v1"):
            num = host.get(name)
            if num is None:
                # kompozitor ho neprivilegovanemu klientovi neukaze; cislo je pak neznamy global
                continue
            out = self.sandbox(s, "/usr/bin/wl-sandbox-app", "--bind", name, num)
            self.assertIn("refused", out, name)
            tried += 1
        # LUXCOMP_VIRTUAL_INPUT=1 v testech: aspon virtualni vstup a layer-shell vidi hostitel
        self.assertGreaterEqual(tried, 3)

    def test_namespace_has_no_host_sockets(self):
        s = self.session()
        wl = os.path.join(self.run_dir, "wayland-0")
        ipc = os.path.join(self.run_dir, "luxwm-wayland-0.sock")
        self.assertTrue(os.path.exists(wl) and os.path.exists(ipc), os.listdir(self.run_dir))
        script = ('for p in "$@"; do test -e "$p" && echo "LEAK:$p"; done; echo "rt=$(ls /run/luxos/runtime | tr "\\n" " ")";'
                  ' echo "x11=$(ls /tmp/.X11-unix | tr "\\n" " ")"; env | grep -E "^(WAYLAND_DISPLAY|DISPLAY|DBUS_SESSION|LUXWM)="')
        out = self.sandbox(s, "/bin/sh", "-c", script, "sh", wl, ipc, self.run_dir, "/run/user", "/run/dbus")
        self.assertNotIn("LEAK", out)
        self.assertIn("rt=wayland-0 ", out)
        self.assertIn("x11=X0 ", out)
        self.assertIn("WAYLAND_DISPLAY=wayland-0", out)
        self.assertIn("DISPLAY=:0", out)
        self.assertNotIn("DBUS_SESSION", out)
        self.assertNotIn("LUXWM", out)
        # ani soket plochy a luxwm podle cesty, ani abstraktni soket hostitele (vlastni net namespace)
        for path in (wl, ipc):
            self.assertIn("refused", self.sandbox(s, "/usr/bin/wl-sandbox-app", "--connect", path))
        name = f"luxos-sbx-test-{os.getpid()}"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind("\0" + name)
        srv.listen(4)
        self.addCleanup(srv.close)
        self.assertIn("connected", self.host(s, "--connect", "@" + name))
        self.assertIn("refused", self.sandbox(s, "/usr/bin/wl-sandbox-app", "--connect", "@" + name))
        # po skonceni behu: zadne sokety sandboxu v XDG_RUNTIME_DIR
        self.assertEqual(os.listdir(os.path.join(self.run_dir, "luxos-sandbox")), [])

    def test_window_marker_input_clipboard_and_activation(self):
        s = self.session()
        a = self.spawn(s, "/usr/bin/wl-sandbox-app", "--window", "sbx.fake", "Fake", "--stay", "40000")
        self.wait_line(a, "mapped")
        va = self.view(s, "Fake")
        self.assertEqual(va["sandbox"], "wl-sandbox-app")
        self.assertGreater(va["top"], 0, "sandboxed window must have the server-side title bar")
        listener = [d for d in os.listdir(os.path.join(self.run_dir, "luxos-sandbox")) if d.startswith("wl-")]
        self.assertEqual(len(listener), 1)
        # hostitelska aplikace se zamerenim nastavi schranku
        b = self.host_bg(s, "--window", "org.host.app", "Host", "--copy", "secret-123", "--stay", "40000")
        self.wait_line(b, "copied")
        vb = self.view(s, "Host")
        self.assertEqual(vb["sandbox"], "-")
        self.assertEqual(s.focused(), ["Host"])
        time.sleep(1)
        before = self.read_available(a, 0.5)
        self.assertFalse([ln for ln in before if ln.startswith(("clip", "selection"))],
                         f"unfocused sandboxed client got the clipboard: {before}")

        # znacka: vpravo v zahlavi okna sandboxu jsou pixely znacky, u hostitelskeho okna jen pozadi
        va, vb = self.view(s, "Fake"), self.view(s, "Host")
        shot = s.shot("sandbox-marker.ppm")
        self.assertGreater(self.title_detail(shot, va), 20, "no badge in the sandboxed title bar")
        self.assertEqual(self.title_detail(shot, vb), 0, "badge in a normal title bar")

        # kradez zamereni: aplikace v sandboxu s app_id zamereneho okna, aktivace vlastnim tokenem
        c = self.spawn(s, "/usr/bin/wl-sandbox-app", "--window", "org.host.app", "Spoof", "--activate-ms", "2500",
                       "--stay", "40000")
        self.wait_line(c, "mapped")
        vb = self.view(s, "Host")
        s.input(f"move {vb['x'] + 100} {vb['y'] + 100}", "click")
        self.assertEqual(s.focused(), ["Host"])
        self.wait_line(c, "activate")
        time.sleep(0.8)
        self.assertEqual(s.focused(), ["Host"], "sandboxed window stole the focus")
        vc = self.view(s, "Spoof")
        self.assertIn(f"activate refused {vc['id']}", s.log())

        # vstup do okna sandboxu: klik zameri, pak schranka (az ted) a klavesy
        va = self.view(s, "Fake")
        s.input(f"move {va['x'] + 100} {va['y'] + 100}", "click", "type ab")
        got = self.read_available(a, 2)
        self.assertIn("button", got)
        self.assertIn("focus-in", got)
        self.assertIn("clip secret-123", got)
        self.assertEqual([ln for ln in got if ln.startswith("key ")], ["key 30", "key 48"])
        self.assertEqual(s.focused(), ["Fake"])
        # se zamerenim smi sandbox aktivovat sve okno (Spoof je jina instance: dal odmitnuto)
        self.stop_proc(a)
        self.stop_proc(c)
        time.sleep(0.5)
        self.assertEqual(os.listdir(os.path.join(self.run_dir, "luxos-sandbox")), [])

    def title_detail(self, path, view):
        """Pocet pixelu v prave tretine zahlavi okna, ktere se lisi od barvy pozadi zahlavi."""
        with open(path, "rb") as f:
            data = f.read()
        parts = data.split(maxsplit=4)
        width = int(parts[1])
        off = len(data) - width * int(parts[2]) * 3

        def px(x, y):
            i = off + (y * width + x) * 3
            return data[i:i + 3]
        top = view["y"] - view["top"]
        bg = px(view["x"] + view["w"] // 2, top + 2)
        count = 0
        for y in range(top + 3, view["y"] - 3):
            for x in range(view["x"] + view["w"] * 2 // 3, view["x"] + view["w"] - 20):   # bez zaobleneho rohu
                if max(abs(p - q) for p, q in zip(px(x, y), bg)) > 24:
                    count += 1
        return count

    def test_x11_app_through_sandbox_xwayland(self):
        if not self.has_x11:
            self.skipTest("libX11 headers missing")
        s = self.session()
        p = self.spawn(s, "/usr/bin/x11-sandbox-app")
        self.wait_line(p, "mapped", timeout=30)
        views = s.state()["views"]
        xw = [v for v in views.values() if v["sandbox"] == "x11-sandbox-app"]
        self.assertEqual(len(xw), 1, views)
        v = xw[0]
        self.assertEqual(v["x11"], 0, "must be the sandbox's own Xwayland, not the compositor's XWayland")
        self.assertGreater(v["top"], 0)
        xwayland = sandbox_xwayland(p.pid)
        self.assertEqual(len(xwayland), 1, xwayland)
        pid = xwayland[0]
        with open(f"/proc/{pid}/smaps_rollup") as f:
            pss = int(re.search(r"^Pss:\s+(\d+)", f.read(), re.M).group(1))
        print(f"\nsandbox Xwayland pss_kb={pss}", file=sys.stderr)
        # okno X obrazovky ma velikost a nazev hlavniho okna aplikace (XWatch -> luxwm sandbox_window), lista
        # a Dock vidi aplikaci ze sandboxu, ne "Xwayland"; hlavni okno je v rohu korene
        v = self.xroot(s, lambda v: (v["w"], v["h"]) == (360, 220))
        self.assertEqual((v["app"], v["title"]), ("x11-sandbox-app", "X11_Sandbox_App"))
        self.assertGreaterEqual(v["y"] - v["top"], 0)
        s.input(f"move {v['x'] + 60} {v['y'] + 60}", "click", "type a")
        got = self.read_available(p, 2)
        self.assertIn("button", got)
        self.assertIn("key 38", got)     # X keycode of 'a' (evdev 30 + 8)
        # aplikace sama zmeni velikost okna: okno X obrazovky ji nasleduje
        s.input("type r")
        v = self.xroot(s, lambda v: (v["w"], v["h"]) == (420, 260))
        # uzivatel okno maximalizuje: hlavni okno aplikace se roztahne na celou X obrazovku
        s.input("key super+Up")
        v = self.xroot(s, lambda v: v["maximized"] == 1 and v["w"] == 1600)
        self.wait_line(p, f"size {v['w']} {v['h']}")
        s.shot("sandbox-x11-maximized.png")
        s.input("key super+Up")
        v = self.xroot(s, lambda v: (v["w"], v["h"]) == (420, 260))
        self.wait_line(p, "size 420 260")
        s.shot("sandbox-x11-window.png")
        self.stop_proc(p)
        time.sleep(0.5)
        self.assertFalse(os.path.exists(f"/proc/{pid}"), "Xwayland outlived the sandbox")
        self.assertEqual(os.listdir(os.path.join(self.run_dir, "luxos-sandbox")), [])

    def test_wayland_only_app_starts_no_xwayland(self):
        s = self.session()
        p = self.spawn(s, "/usr/bin/wl-sandbox-app", "--window", "sbx.fake", "Lazy", "--stay", "5000")
        self.wait_line(p, "mapped")
        self.assertEqual(sandbox_xwayland(p.pid), [])


if __name__ == "__main__":
    unittest.main()
