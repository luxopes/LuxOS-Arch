"""Protokoly shellu v luxwm pres harness scripts/wl-test (headless pixman): Dock obnovi minimalizovane
okno i z jine plochy, zamek obrazovky (nova okna pod nim skryta, zamykac zabity -> stale zakryto),
allowlist privilegovanych protokolu (wp-security-context, program mimo allowlist, program v nem)
a XWayland na pozadani (xeyes ze sysrootu: umisteni, zamereni, pamet bez a s XWayland).

  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
  cd packages/luxwm/tests && env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY \\
    DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent systemd-run --user --scope -p TasksMax=300 -- \\
    timeout 900 python3 -m unittest -v test_luxwm_protocols

XWayland si dela svuj X soket v /tmp/.X11-unix (wlroots; volne cislo displeje, ne :0 skutecne relace).
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from test_luxwm import BUILD, ROOT, SYSROOT, Session, children, pss_kb, wlt

HERE = os.path.dirname(os.path.abspath(__file__))
LSLC = shutil.which("lslc")
GRIM = os.path.join(SYSROOT, "usr/bin/grim")
XEYES = os.path.join(SYSROOT, "usr/bin/xeyes")
PRIVILEGED = ["zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1",
              "ext_output_image_capture_source_manager_v1",
              "ext_foreign_toplevel_image_capture_source_manager_v1", "ext_data_control_manager_v1",
              "zwlr_data_control_manager_v1", "zwlr_foreign_toplevel_manager_v1", "ext_foreign_toplevel_list_v1",
              "zwlr_output_manager_v1", "ext_session_lock_manager_v1", "zwp_virtual_keyboard_manager_v1",
              "zwlr_virtual_pointer_manager_v1"]
SANDBOX_DENIED = ["zwlr_layer_shell_v1", "ext_idle_notifier_v1", "wp_security_context_manager_v1"]
LOCK = (0x19, 0x33, 0x99)     # zamykaci plocha luxos-wl-test


def xwayland_pid(display):
    """Xwayland teto relace (wlroots ho spousti dvojitym forkem, neni to potomek luxwm)."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if argv[0].endswith(b"Xwayland") and len(argv) > 1 and argv[1].decode() == display:
            return int(pid)
    return None


def globals_of(out, prefix):
    return {line.split()[1]: int(line.split()[2]) for line in out.splitlines() if line.startswith(prefix + " ")}


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and LSLC and os.path.exists(GRIM),
                     "build first: packages/luxwm/tests/build-host.sh (and lslc, sysroot)")
class Protocols(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxwm-proto-", dir=os.path.join(ROOT, "out"))
        desktop = os.path.join(ROOT, "packages", "luxos-desktop")
        subprocess.run(["make", "-s", "-C", os.path.join(desktop, "files/src/luxos-wl"), f"OUT={cls.tmp}"],
                       check=True, capture_output=True)
        cls.lib = os.path.join(cls.tmp, "libluxos-wl.so.0")
        src = os.path.join(cls.tmp, "lsl")
        os.mkdir(src)
        for name in os.listdir(os.path.join(desktop, "files/lsl")):
            shutil.copy(os.path.join(desktop, "files/lsl", name), src)
        shutil.copy(os.path.join(desktop, "tests/lsl/luxos-wl-test.lsl"), src)
        cls.wltest = os.path.join(cls.tmp, "luxos-wl-test")
        subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", src,
                        os.path.join(src, "luxos-wl-test.lsl"), cls.wltest],
                       check=True, capture_output=True)
        # wl-probe ve dvou kopiich: jedna v allowlistu, druha ne (allowlist rozlisuje cestu programu)
        protocols = os.path.join(SYSROOT, "usr/share/wayland-protocols")
        scanner = os.path.join(SYSROOT, "usr/bin/wayland-scanner")
        env = {**os.environ, "LD_LIBRARY_PATH": os.path.join(SYSROOT, "usr/lib")}
        code = []
        for xml in ("staging/security-context/security-context-v1.xml", "stable/xdg-shell/xdg-shell.xml",
                    "staging/xdg-activation/xdg-activation-v1.xml"):
            base = os.path.basename(xml)[:-4]
            subprocess.run([scanner, "client-header", os.path.join(protocols, xml),
                            os.path.join(cls.tmp, base + "-client-protocol.h")], check=True, env=env)
            code.append(os.path.join(cls.tmp, base + ".c"))
            subprocess.run([scanner, "private-code", os.path.join(protocols, xml), code[-1]], check=True, env=env)
        cls.probe = os.path.join(cls.tmp, "wl-probe")
        subprocess.run(["gcc", "-O1", "-Wall", "-I", cls.tmp, "-o", cls.probe, os.path.join(HERE, "wl-probe.c"),
                        *code, "-lwayland-client"], check=True)
        cls.trusted = os.path.join(cls.tmp, "trusted", "wl-probe")
        os.mkdir(os.path.dirname(cls.trusted))
        shutil.copy(cls.probe, cls.trusted)
        cls.allow = os.path.join(cls.tmp, "privileged.conf")
        tools = [os.path.realpath(os.path.join(SYSROOT, "usr/bin", t)) for t in ("wlr-randr", "grim")]
        tools.append(os.path.realpath(os.path.join(ROOT, "out", "wl-test", "bin", "wlt-input")))
        with open(cls.allow, "w") as f:
            f.write("# testy luxwm\n" + "\n".join(tools + [cls.trusted, cls.wltest]) + "\nrelative/ignored\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def session(self, env=""):
        # LUXCOMP_VIRTUAL_INPUT=0: virtualni vstup jen pro allowlist (wlt-input v nem je)
        wrapper = os.path.join(ROOT, "packages/luxcomp/xwayland-sw")
        s = Session(env=f"LUXWM_PRIVILEGED={self.allow} LUXCOMP_VIRTUAL_INPUT=0 LUXCOMP_XWAYLAND_WRAPPER={wrapper} {env}")
        self.addCleanup(s.stop)
        return s

    def run_in(self, s, *cmd, check=True):
        r = subprocess.run([os.path.join(ROOT, "scripts/wl-test/wlt"), "run", s.dir, "env",
                            f"LUXOS_WL_LIB={self.lib}", *cmd], capture_output=True, text=True, timeout=60)
        if check:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def spawn_in(self, s, *cmd):
        return subprocess.Popen([os.path.join(ROOT, "scripts/wl-test/wlt"), "run", s.dir, "env",
                                 f"LUXOS_WL_LIB={self.lib}", *cmd], stdout=subprocess.PIPE, text=True)

    # ---- allowlist ----

    def test_privileged_globals_allowlist(self):
        s = self.session()
        trusted = globals_of(self.run_in(s, self.trusted), "global")
        plain = globals_of(self.run_in(s, self.probe), "global")
        sandboxed = globals_of(self.run_in(s, self.trusted, "--sandbox"), "sandbox")
        for name in PRIVILEGED:
            self.assertIn(name, trusted)
            self.assertNotIn(name, plain)
            self.assertNotIn(name, sandboxed)
        for name in SANDBOX_DENIED:
            self.assertIn(name, plain)
            self.assertNotIn(name, sandboxed)
        for name in ("wl_compositor", "xdg_wm_base", "wl_seat", "xdg_activation_v1", "zwp_idle_inhibit_manager_v1"):
            self.assertIn(name, sandboxed)
        # bind skryteho globalu podle cisla (z duveryhodneho spojeni) knihovna odmitne chybou protokolu
        for name in ("zwlr_screencopy_manager_v1", "ext_data_control_manager_v1", "zwlr_foreign_toplevel_manager_v1"):
            out = self.run_in(s, self.probe, "--bind", name, str(trusted[name]), check=False)
            self.assertIn("refused", out, name)
            self.assertIn("bound", self.run_in(s, self.trusted, "--bind", name, str(trusted[name]), check=False))
        self.assertIn("ignored relative path", s.log())
        self.assertIsNotNone(s.state())     # kompozitor zije

    # ---- Dock ----

    def test_dock_restores_minimized_window_from_other_workspace(self):
        s = self.session()
        s.client("Prvni", app="one")
        s.input("key ctrl+super+Right", wait=0.8)
        s.client("Druhe", app="two")
        st = s.state()
        self.assertEqual(st["workspace"], 2)
        self.assertEqual(st["views"]["Prvni"]["ws"], 1)
        out = self.run_in(s, self.wltest, "restore", "one")
        self.assertIn("minimized", out.splitlines())
        self.assertIn("restored", out.splitlines())
        st = s.state()
        # aktivace z Docku prepne na plochu okna a zameri ho
        self.assertEqual(st["workspace"], 1)
        self.assertEqual(st["views"]["Prvni"]["visible"], 1)
        self.assertEqual(st["views"]["Prvni"]["focused"], 1)
        self.assertIn("origin 3", s.log())

    # ---- wlr-output-management ----

    def test_output_reenabled_while_client_holds_output_manager(self):
        # wlroots 0.20.2 padal (assert v head_send_state), kdyz se vystup bez rezimu znovu zapnul a
        # jeden klient drzel zwlr_output_manager_v1 uz pred vypnutim (lista pres libluxos-wl)
        s = self.session()
        holder = self.spawn_in(s, self.wltest, "clip-set", "drzi")
        for line in holder.stdout:
            if line.startswith("set "):
                self.assertEqual(line.strip(), "set True")
                break
        self.assertEqual(self.run_in(s, "wlr-randr", "--output", "HEADLESS-1", "--off"), "")
        time.sleep(0.3)
        self.assertEqual(self.run_in(s, "wlr-randr", "--output", "HEADLESS-1", "--on"), "")
        time.sleep(0.3)
        out = self.run_in(s, "wlr-randr")
        self.assertIn("Enabled: yes", out)
        self.assertIn("Position: 0,0", out)
        self.assertEqual(s.state()["usable"][2:], (1280, 800))
        self.assertIsNone(holder.poll())
        out = self.run_in(s, self.wltest, "heads")
        self.assertIn("result 1", out)
        holder.terminate()
        holder.wait(5)
        holder.stdout.close()

    # ---- xdg-activation ----

    def wait_view(self, s, title, timeout=5):
        for _ in range(timeout * 10):
            st = s.state()
            if title in st["views"]:
                return st["views"][title]
            time.sleep(0.1)
        self.fail(f"{title} se neobjevilo")

    def test_activation_needs_token_from_focus_or_shell(self):
        s = self.session()
        s.client("Prace", app="work", size="300x200")
        # okno jine aplikace s vlastnim tokenem bez vstupu uzivatele: zamereni neukradne
        wlt("run", s.dir, "--bg", self.probe, "--window", "cizi", "1500")
        v = self.wait_view(s, "cizi")
        work = s.state()["views"]["Prace"]
        s.input(f"move {work['x'] + 20} {work['y'] + 20}", "click", wait=0.3)
        self.assertEqual(s.focused(), ["Prace"])
        time.sleep(1.8)
        self.assertEqual(s.focused(), ["Prace"])
        self.assertIn(f"activate refused {v['id']} origin 0", s.log())
        # program spusteny luxwm (zkratka exec) ma token shellu: aktivace projde
        os.makedirs(os.path.join(s.dir, "config", "luxwm"), exist_ok=True)
        with open(os.path.join(s.dir, "config", "luxwm", "luxwm.conf"), "w") as f:
            f.write(f"[keys]\n<Super>p = exec {self.probe} --window spusteny 1500\n")
        os.kill(s.pid, signal.SIGHUP)
        time.sleep(0.3)
        s.input("key super+p", wait=0.2)
        v = self.wait_view(s, "spusteny")
        s.input(f"move {work['x'] + 20} {work['y'] + 20}", "click", wait=0.3)
        self.assertEqual(s.focused(), ["Prace"])
        time.sleep(1.8)
        self.assertEqual(s.focused(), ["spusteny"])
        self.assertIn(f"activate {v['id']} origin 2", s.log())

    # ---- zamek ----

    def test_lock_new_window_hidden_and_killed_locker_keeps_cover(self):
        s = self.session()
        desktop = s.pixel(5, 795)
        locker = self.spawn_in(s, self.wltest, "lock")
        lines = []
        for line in locker.stdout:
            lines.append(line.strip())
            if line.strip() == "locked":
                break
        # zamykac (nejhlubsi potomek wlt run -> env -> timeout) zabit pred odemcenim, zadny unlock
        pid = locker.pid
        while children(pid):
            pid = children(pid)[0]
        os.kill(pid, 9)
        locker.wait(10)
        self.assertIn("locked", lines)
        time.sleep(0.5)
        self.assertIn("lock 1 (locker gone)", s.log())
        cover = s.pixel(640, 400)
        self.assertNotEqual(cover, LOCK)
        self.assertEqual(cover, desktop)     # nepruhledna plocha v barve pozadi LuxOS
        # nove okno pod zamkem: namapovane, ale neni videt a nema klavesnici
        s.client("Zamceno", color="ff00ff", wait=1.0)
        self.assertEqual(s.pixel(640, 400), desktop)
        self.assertEqual(s.state()["views"]["Zamceno"]["visible"], 1)
        with open(os.path.join(s.dir, "clients.log")) as f:
            self.assertNotIn("focus ", f.read())
        # zkratky jsou pod zamkem vypnute
        s.input("key ctrl+super+Right", wait=0.5)
        self.assertEqual(s.state()["workspace"], 1)
        # novy zamykac prevezme zamek, odemkne, okno je videt a dostane klavesnici
        out = self.run_in(s, self.wltest, "lock")
        self.assertIn("unlock True", out.splitlines())
        time.sleep(0.4)
        window = s.pixel(640, 400)
        self.assertNotIn(window, (desktop, LOCK))
        self.assertEqual(window[1], 0)          # fialove okno (pruhovany obsah wlt-client)
        with open(os.path.join(s.dir, "clients.log")) as f:
            self.assertIn("focus ", f.read())

    # ---- XWayland ----

    @unittest.skipUnless(os.path.exists(XEYES) and os.path.exists(os.path.join(SYSROOT, "usr/bin/Xwayland")),
                         "xeyes/Xwayland not in the sysroot")
    def test_xwayland_on_demand(self):
        s = self.session()
        s.client("Wayland", app="wl", size="300x200", color="00ff00")
        time.sleep(4)
        idle = pss_kb(s.pid)
        st = s.state()
        log = s.log()
        display = log.split("xwayland ")[1].split()[0]
        self.assertIn("xwayland=0", log.rsplit("luxwm: workspace", 1)[1])     # lazy: zatim nebezi
        wlt("run", s.dir, "--bg", "env", f"DISPLAY={display}", XEYES)
        for _ in range(100):
            st = s.state()
            if "xeyes" in st["views"]:
                break
            time.sleep(0.1)
        x = st["views"]["xeyes"]
        self.assertEqual(x["x11"], 1)
        self.assertEqual(x["app"], "XEyes")
        self.assertEqual(x["focused"], 1)
        self.assertGreater(x["top"], 0)                     # zahlavi LuxOS
        # umisteni jako u Wayland okna (xfwm4 luxos: nejlevejsi volne misto), cele v plose, zahlavi na obrazovce
        self.assertGreaterEqual(x["x"], 0)
        self.assertGreaterEqual(x["y"] - x["top"], 0)
        self.assertLessEqual(x["x"] + x["w"], 1280)
        self.assertLessEqual(x["y"] + x["h"], 800)
        wl = st["views"]["Wayland"]
        self.assertFalse(x["x"] < wl["x"] + wl["w"] and wl["x"] < x["x"] + x["w"]
                         and x["y"] < wl["y"] + wl["h"] and wl["y"] < x["y"] + x["h"])
        # zamereni klikem tam a zpet
        s.input(f"move {wl['x'] + 20} {wl['y'] + 20}", "click", wait=0.4)
        self.assertEqual(s.focused(), ["Wayland"])
        s.input(f"move {x['x'] + 10} {x['y'] + 10}", "click", wait=0.4)
        self.assertEqual(s.focused(), ["xeyes"])
        self.assertIn("xwayland=1", s.log().rsplit("luxwm: workspace", 1)[1])
        xpid = xwayland_pid(display)
        self.assertIsNotNone(xpid)
        time.sleep(3)
        comp = pss_kb(s.pid)
        xwayland = pss_kb(xpid)
        print(f"\n  PSS kB: luxwm idle bez XWayland {idle}, s XWayland luxwm {comp} + Xwayland {xwayland}")
        # zavreni pres Alt+F4 / view_close (WM_DELETE_WINDOW), XWayland skonci 10 s po poslednim klientovi
        s.input("key alt+F4", wait=1.0)
        self.assertNotIn("xeyes", s.state()["views"])
        for _ in range(30):
            if "xwayland=0" in s.log().rsplit("luxwm: workspace", 1)[1] and not os.path.exists(f"/proc/{xpid}"):
                break
            time.sleep(0.5)
            s.state()
        self.assertFalse(os.path.exists(f"/proc/{xpid}"))
        time.sleep(1)
        print(f"  PSS kB: luxwm po skonceni XWayland {pss_kb(s.pid)}")


if __name__ == "__main__":
    unittest.main()
