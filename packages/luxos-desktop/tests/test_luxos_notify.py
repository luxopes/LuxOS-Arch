#!/usr/bin/env python3
"""luxos-notify (server oznameni pro Wayland) proti labwc headless (pixman) a soukrome sbernici relace.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -- timeout 900 \\
      dbus-run-session --config-file packages/luxos-desktop/tests/dbus-private.conf -- \
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_notify.py -v

Sbernice: jen soukroma z dbus-run-session (skutecna sbernice relace = test se preskoci). Kompozitor: scripts/wl-test/wlt
(sysroot z fetch-sysroot.sh), jeden vystup 1280x800. Kazdy test spousti vlastni luxos-notify s prazdnym HOME, takze historie
a nastaveni jsou cista; mezi testy zustava jen kompozitor. Klienti: notify-send (matice voleb) a GDBus (image-data, Activate,
signaly). Klikani pres wlt input (virtualni ukazatel), snimky pres wlt shot (grim).
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

try:
    import gi
    from gi.repository import Gio, GLib
except ImportError:
    gi = None

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
BUS = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
REAL_BUS = "unix:path=" + os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()) + "/bus"
PRIVATE_BUS = BUS != "" and BUS != REAL_BUS and "/nonexistent" not in BUS

FDO = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications")
HISTORY = ("org.freedesktop.Notifications", "/cz/luxos/NotificationHistory", "cz.luxos.NotificationHistory")
LOG = ("org.xfce.Notifyd", "/org/xfce/Notifyd", "org.xfce.Notifyd.Log")

W, H = 1280, 800
# karta: vrstva 4 px od praveho a horniho okraje, karta ma okraj 4 px, sirka 344 (navrh 1.1.0)
CARD_LEFT, CARD_RIGHT, CARD_TOP = W - 8 - 344, W - 8, 8
PROBE_X = CARD_LEFT + 200          # pruh karty bez textu (vpravo od kratkeho nadpisu)
# material toast bez rozmazani (labwc): tonovani s kryti BLUR fallback_opacity 0,96 na cerne
LIGHT_CARD = (236, 237, 242)       # rgba(246, 247, 252, 0.96)
DARK_CARD = (29, 30, 40)           # rgba(30, 31, 42, 0.96)


def near(rgb, want, tol=8):
    return all(abs(a - b) <= tol for a, b in zip(rgb, want))


@unittest.skipUnless(gi and LSLC and PRIVATE_BUS and shutil.which("notify-send") and os.access(WLT, os.X_OK),
                     "chybi gi/lslc/notify-send/wlt nebo soukroma sbernice (spustit pod dbus-run-session)")
class Notify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-notify-", dir=REPO / "out" if (REPO / "out").is_dir() else None))
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        shutil.copy(HERE / "lsl/luxos-layer-test.lsl", src)
        for name in ("luxos-notify", "luxos-layer-test"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"), str(cls.tmp / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        outer = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")}
        cls.outer = outer
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", f"{W}x{H}", "--name",
                            f"notify-{os.getpid()}", "--timeout", "1500"], env=outer, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("wlt start: " + r.stderr)
        cls.session = r.stdout.strip().splitlines()[-1]
        r = subprocess.run([str(WLT), "env", cls.session], env=outer, capture_output=True, text=True, check=True)
        cls.wl_env = {}
        for line in r.stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            cls.wl_env[key] = value.strip("'\"")
        cls.bus = Gio.DBusConnection.new_for_address_sync(
            BUS, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        cls.signals = []
        cls.owner = None
        for iface in (FDO[2], HISTORY[2], LOG[2]):
            cls.bus.signal_subscribe(None, iface, None, None, None, 0, cls.on_signal)

    @classmethod
    def on_signal(cls, conn, sender, path, iface, name, params):
        # jen signaly prave beziciho serveru (cisla oznameni zacinaji v kazdem testu znovu)
        if sender == cls.owner:
            cls.signals.append((time.monotonic(), name, params.unpack()))

    @classmethod
    def tearDownClass(cls):
        subprocess.run([str(WLT), "stop", cls.session], env=cls.outer, capture_output=True)
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="home-", dir=self.tmp))
        self.env = dict(self.wl_env)
        self.env.pop("LD_LIBRARY_PATH", None)      # sysroot je jen pro labwc/grim
        self.env.update(HOME=str(self.home), XDG_DATA_HOME=str(self.home / ".local/share"),
                        XDG_CONFIG_HOME=str(self.home / ".config"), XDG_CACHE_HOME=str(self.home / ".cache"),
                        DBUS_SESSION_BUS_ADDRESS=BUS, GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GIO_USE_VFS="local")
        self.procs = []
        self.server = None
        type(self).signals = []
        self.pointer(10, H - 10)
        self.start_server()

    def tearDown(self):
        for p in self.procs + [self.server]:
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        if self.server:
            err = self.server.stderr.read().decode(errors="replace")
            self.server.stderr.close()
            self.assertNotIn("LSL callback error", err)

    # ---- pomocnici ----

    def start_server(self, dark=False):
        if dark:
            (self.home / ".config/luxos").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/luxos/appearance").write_text("dark\n")
        self.server = subprocess.Popen([str(self.tmp / "luxos-notify")], env=self.env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE)
        self.wait_for(lambda: self.has_owner(FDO[0]), 10, "luxos-notify nevlastni jmeno")
        type(self).owner = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                              "GetNameOwner", GLib.Variant("(s)", (FDO[0],)), None, 0, 2000, None).unpack()[0]

    def stop_server(self):
        self.server.send_signal(signal.SIGTERM)
        self.server.wait(5)
        self.server.stderr.close()
        self.server = None
        self.wait_for(lambda: not self.has_owner(FDO[0]), 5, "jmeno zustalo")

    def pump(self, seconds=0.0):
        end = time.monotonic() + seconds
        ctx = GLib.MainContext.default()
        while True:
            while ctx.iteration(False):
                pass
            if time.monotonic() >= end:
                return
            time.sleep(0.01)

    def wait_for(self, cond, timeout, message):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if cond():
                return
            time.sleep(0.02)
        self.fail(message)

    def call(self, target, method, args=None, sig=None, reply=None):
        params = GLib.Variant(sig, args) if sig else None
        result = self.bus.call_sync(target[0], target[1], target[2], method, params,
                                    GLib.VariantType(reply) if reply else None, 0, 5000, None)
        self.pump()
        return result.unpack() if result else None

    def has_owner(self, name):
        return self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                  GLib.Variant("(s)", (name,)), None, 0, 2000, None).unpack()[0]

    def notify(self, summary, body="", actions=(), hints=None, timeout=-1, replaces=0, app="Test"):
        return self.call(FDO, "Notify", (app, replaces, "", summary, body, list(actions), hints or {}, timeout),
                         "(susssasa{sv}i)", "(u)")[0]

    def send(self, *args):
        r = subprocess.run(["notify-send", "-p", *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.pump(0.05)
        return int(r.stdout.split()[0])

    def send_async(self, *args):
        p = subprocess.Popen(["notify-send", "-p", *args], env=self.env, stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def closed(self, nid):
        return [s for s in self.signals if s[1] == "NotificationClosed" and s[2][0] == nid]

    def wait_closed(self, nid, timeout=10):
        self.wait_for(lambda: self.closed(nid), timeout, f"oznameni {nid} se nezavrelo")
        return self.closed(nid)[0]

    def history(self):
        return self.call(LOG, "List", ("", 0, False), "(sub)", "(a(sxssssssa(ss)ib))")[0]

    def wlt(self, *args):
        subprocess.run([str(WLT), *args], env=self.outer, check=True, capture_output=True, timeout=30)

    def pointer(self, x, y):
        self.wlt("input", self.session, f"move {x} {y}")

    def click(self, x, y, button="left"):
        self.wlt("input", self.session, f"move {x} {y}", "sleep 0.15", f"click {button}")
        self.pump(0.2)

    def shot(self):
        path = self.home / "shot.ppm"
        self.pump(0.4)
        self.wlt("shot", self.session, str(path))
        data = path.read_bytes()
        magic, size, depth, pixels = data.split(b"\n", 3)
        width, height = map(int, size.split())
        self.assertEqual((width, height), (W, H))
        return lambda x, y: tuple(pixels[(y * width + x) * 3:(y * width + x) * 3 + 3])

    def card_bottom(self, pixel, x=PROBE_X, top=CARD_TOP + 2):
        """Prvni cerny radek pod kartou ve sloupci x."""
        y = top
        while y < H and pixel(x, y) != (0, 0, 0):
            y += 1
        return y

    def pss(self, pid):
        rollup = Path(f"/proc/{pid}/smaps_rollup").read_text()
        return int(next(l for l in rollup.splitlines() if l.startswith("Pss:")).split()[1])

    # ---- server ----

    def test_server_information_and_capabilities(self):
        info = self.call(FDO, "GetServerInformation", reply="(ssss)")
        self.assertEqual(info, ("luxos-notify", "LuxOS", "1.1.0", "1.2"))
        caps = self.call(FDO, "GetCapabilities", reply="(as)")[0]
        for cap in ("actions", "body", "body-markup", "persistence"):
            self.assertIn(cap, caps)
        self.assertNotIn("daemon", " ".join(info).lower())

    def test_second_server_refuses(self):
        p = subprocess.run([str(self.tmp / "luxos-notify")], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 1)
        self.assertIn("another notification server", p.stderr)
        self.assertIsNone(self.server.poll())

    # ---- matice notify-send ----

    def test_matrix_actions_replace_urgency_transient_keep(self):
        plain = self.send("Jen bublina")
        kept = self.send("-a", "Zálohy", "-h", "boolean:x-luxos-keep:true", "-h", "string:desktop-entry:luxos-backup",
                         "Záloha dokončena", "Uloženo 12 GB")
        transient = self.send("-e", "-h", "boolean:x-luxos-keep:true", "Hlasitost 40 %")
        kept_byte = self.send("-h", "byte:x-luxos-keep:1", "Bajtovy hint")
        rows = self.history()
        summaries = [r[6] for r in rows]
        self.assertEqual(summaries, ["Bajtovy hint", "Záloha dokončena"])   # nejnovejsi prvni
        self.assertNotIn("Hlasitost 40 %", summaries)
        self.assertNotIn("Jen bublina", summaries)
        self.assertEqual(rows[1][3:5], ("luxos-backup", "Zálohy"))
        self.assertEqual(len({plain, kept, transient, kept_byte}), 4)
        # nahrazeni: stejne cislo, jedna bublina i jeden zaznam v historii
        again = self.send("-r", str(kept), "-h", "boolean:x-luxos-keep:true", "Záloha dokončena", "Uloženo 13 GB")
        self.assertEqual(again, kept)
        self.assertEqual([r[7] for r in self.history() if r[6] == "Záloha dokončena"], ["Uloženo 13 GB"])
        self.assertEqual(self.closed(kept), [])
        # akce: notify-send -A ceka na vysledek; zavreni aplikaci ho ukonci
        p = self.send_async("-A", "default=Otevřít", "-A", "later=Později", "S akcemi")
        nid = int(p.stdout.readline())
        self.call(FDO, "CloseNotification", (nid,), "(u)")
        p.wait(5)
        self.assertEqual(self.wait_closed(nid)[2], (nid, 3))
        # kriticka zustava i s kratkym casem, normalni vyprsi
        critical = self.send("-u", "critical", "-t", "800", "Kritické")
        normal = self.send("-t", "800", "Normální")
        self.wait_closed(normal, 10)      # ceka ve fronte, dokud nevyprsi prvni ctyri (6 s)
        self.pump(1.5)
        self.assertEqual(self.closed(critical), [])
        self.assertIsNone(self.server.poll())

    def test_expire_timeout(self):
        t0 = time.monotonic()
        short = self.send("-t", "1500", "Krátká")
        default = self.send("Výchozí")
        never = self.send("-t", "0", "Navždy")
        when, _, args = self.wait_closed(short, 5)
        self.assertEqual(args, (short, 1))
        self.assertGreater(when - t0, 1.35)
        self.assertLess(when - t0, 2.2)
        when, _, args = self.wait_closed(default, 9)
        self.assertEqual(args, (default, 1))
        self.assertGreater(when - t0, 5.8)
        self.assertLess(when - t0, 6.8)
        self.pump(1.0)
        self.assertEqual(self.closed(never), [])
        print(f"\n  vyprseni: -t 1500 -> {self.closed(short)[0][0] - t0:.2f} s, -1 -> {when - t0:.2f} s")

    def test_hover_pauses_expiry(self):
        nid = self.send("-t", "1200", "Pod mysi")
        self.pointer(PROBE_X, CARD_TOP + 20)
        self.pump(2.5)
        self.assertEqual(self.closed(nid), [], "vyprselo pod mysi")
        t0 = time.monotonic()
        self.pointer(10, H - 10)
        when = self.wait_closed(nid, 5)[0]
        # po odjeti nejmene 1,5 s, at bublina nezmizi pod rukou
        self.assertGreater(when - t0, 1.3)
        self.assertLess(when - t0, 2.5)

    # ---- vzhled ----

    def check_look(self, want, name):
        bar = subprocess.Popen([str(self.tmp / "luxos-layer-test"), "32", "#ff0000"], env=self.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(bar)
        self.pump(1.0)
        p = self.send_async("-a", "Pošta", "-A", "default=Otevřít", "-t", "0", "Nová zpráva", "Krátký text")
        p.stdout.readline()
        self.send("-i", "dialog-information", "-t", "0", "Druhé oznámení", "Starší je pod novějším")
        pixel = self.shot()
        shutil.copy(self.home / "shot.ppm", self.tmp.parent / f"luxos-notify-{name}.ppm") if os.environ.get(
            "LUXOS_NOTIFY_SHOTS") else None
        # lista nahore cela cervena, karta az pod ni (vyhradni zona listy)
        self.assertEqual(pixel(PROBE_X, 10), (255, 0, 0))
        self.assertEqual(pixel(PROBE_X, 33), (0, 0, 0))
        top = 32 + CARD_TOP + 2
        self.assertTrue(near(pixel(PROBE_X, top + 4), want), pixel(PROBE_X, top + 4))
        # vlevo od karty nic
        self.assertEqual(pixel(CARD_LEFT - 10, top + 20), (0, 0, 0))
        # dve karty pod sebou: mezi nimi cerna mezera
        first = self.card_bottom(pixel, top=top)
        self.assertTrue(near(pixel(PROBE_X, first + 12), want), "druha karta chybi")
        second = self.card_bottom(pixel, top=first + 12)
        self.assertEqual(pixel(PROBE_X, second + 3), (0, 0, 0))

    def test_screenshot_light(self):
        self.check_look(LIGHT_CARD, "light")

    def test_screenshot_dark(self):
        self.stop_server()
        self.start_server(dark=True)
        self.check_look(DARK_CARD, "dark")

    def test_image_data(self):
        size = 48
        pixels = bytes([255, 0, 0, 255]) * size * size
        image = GLib.Variant("(iiibiiay)", (size, size, size * 4, True, 8, 4, pixels))
        self.notify("Obrázek", "image-data", hints={"image-data": image, "x-luxos-keep": GLib.Variant("b", True)},
                    timeout=0)
        pixel = self.shot()
        # ikona 40 px vlevo v karte: cervena
        reds = sum(1 for x in range(CARD_LEFT, CARD_LEFT + 80) for y in range(CARD_TOP, CARD_TOP + 70)
                   if pixel(x, y) == (255, 0, 0))
        self.assertGreater(reds, 30 * 30)
        icon = self.history()[0][5]
        self.assertTrue(icon.endswith(".png") and Path(icon).is_file(), icon)
        # spatne rozmery (data kratsi nez sirka x vyska) se odmitnou bez padu
        bad = GLib.Variant("(iiibiiay)", (4000, 4000, 16000, True, 8, 4, b"\0" * 64))
        self.notify("Spatny obrazek", hints={"image-data": bad})
        self.notify("<b>Znacky</b>", "<a href='x'>odkaz</a> <b>tučně</b> <i>a</i> &amp; <u>neuzavrene", timeout=0)
        self.assertIsNone(self.server.poll())

    def test_sound_hints(self):
        # zvuk jako xfce4-notifyd (libcanberra): jen s hintem sound-name/sound-file, bez suppress-sound a bez Nerusit
        fake = self.home / "bin"
        fake.mkdir()
        played = self.home / "played"
        (fake / "canberra-gtk-play").write_text(f"#!/bin/sh\necho \"$*\" >> {played}\n")
        (fake / "canberra-gtk-play").chmod(0o755)
        self.stop_server()
        self.env["PATH"] = f"{fake}:" + self.env["PATH"]
        self.start_server()
        self.assertIn("sound", self.call(FDO, "GetCapabilities", reply="(as)")[0])
        self.notify("Bez zvuku", timeout=300)
        self.notify("Zvuk", hints={"sound-name": GLib.Variant("s", "message-new-instant")}, timeout=300)
        self.notify("Soubor", hints={"sound-file": GLib.Variant("s", "/usr/share/sounds/x.oga")}, timeout=300)
        self.notify("Potlaceny", hints={"sound-name": GLib.Variant("s", "bell"), "suppress-sound": GLib.Variant("b", True)},
                    timeout=300)
        self.call(HISTORY, "SetDoNotDisturb", (True,), "(b)")
        self.notify("Nerusit", hints={"sound-name": GLib.Variant("s", "bell")}, timeout=300)
        self.wait_for(lambda: played.exists() and len(played.read_text().splitlines()) >= 2, 3, "zvuk nehral")
        self.pump(0.5)
        self.assertEqual(played.read_text().splitlines(),
                         ["-i message-new-instant -d luxos-notify", "-f /usr/share/sounds/x.oga -d luxos-notify"])

    # ---- klikani ----

    def test_click_invokes_default_action(self):
        p = self.send_async("-A", "default=Otevřít", "-t", "0", "Klikni", "Krátký text")
        nid = int(p.stdout.readline())
        self.pump(0.5)
        self.click(PROBE_X, CARD_TOP + 30)
        out, _ = p.communicate(timeout=5)
        self.assertEqual(out.strip(), "default")
        self.wait_for(lambda: self.closed(nid), 3, "nezavreno")
        invoked = [s[2] for s in self.signals if s[1] == "ActionInvoked" and s[2][0] == nid]
        self.assertEqual(invoked, [(nid, "default")])
        self.assertEqual(self.closed(nid)[0][2], (nid, 2))

    def test_click_expands_long_text_first(self):
        body = "Dlouhý text oznámení, který se do tří řádků nevejde. " * 6
        nid = self.notify("Dlouhé", body, actions=["default", ""], timeout=0)
        pixel = self.shot()
        short = self.card_bottom(pixel)
        self.click(PROBE_X, CARD_TOP + 30)
        pixel = self.shot()
        tall = self.card_bottom(pixel)
        self.assertGreater(tall, short + 30)
        self.assertEqual([s for s in self.signals if s[1] == "ActionInvoked" and s[2][0] == nid], [])
        self.click(PROBE_X, CARD_TOP + 30)
        self.wait_for(lambda: self.closed(nid), 3, "druhy klik nezavrel")
        self.assertEqual([s[2] for s in self.signals if s[1] == "ActionInvoked" and s[2][0] == nid], [(nid, "default")])

    def test_close_button_and_right_click(self):
        a = self.notify("Křížek", actions=["default", "Otevřít"], timeout=0)
        self.pointer(PROBE_X, CARD_TOP + 20)
        self.pump(0.3)
        self.click(CARD_LEFT + 13, CARD_TOP + 13)
        self.assertEqual(self.wait_closed(a, 3)[2], (a, 2))
        self.assertEqual([s for s in self.signals if s[1] == "ActionInvoked" and s[2][0] == a], [])
        b = self.notify("Pravý klik", actions=["default", "Otevřít"], timeout=0)
        self.pump(0.3)
        self.click(PROBE_X, CARD_TOP + 30, "right")
        self.assertEqual(self.wait_closed(b, 3)[2], (b, 2))
        self.assertEqual([s for s in self.signals if s[1] == "ActionInvoked" and s[2][0] == b], [])

    # ---- Nerusit ----

    def test_do_not_disturb(self):
        self.call(HISTORY, "SetDoNotDisturb", (True,), "(b)")
        self.assertEqual(self.call(HISTORY, "GetDoNotDisturb", reply="(b)"), (True,))
        self.wait_for(lambda: any(s[1] == "DoNotDisturbChanged" and s[2] == (True,) for s in self.signals), 2, "signal")
        nid = self.notify("Potichu", actions=["default", "Otevřít"], hints={"x-luxos-keep": GLib.Variant("b", True)})
        quiet = self.notify("Potichu bez historie")
        self.assertEqual(self.wait_closed(nid, 2)[2], (nid, 4))
        self.assertEqual(self.wait_closed(quiet, 2)[2], (quiet, 4))
        pixel = self.shot()
        self.assertEqual(pixel(PROBE_X, CARD_TOP + 10), (0, 0, 0))
        self.assertEqual([r[6] for r in self.history()], ["Potichu"])
        # kriticke projde i v rezimu Nerusit
        crit = self.notify("Baterie 3 %", hints={"urgency": GLib.Variant("y", 2)})
        pixel = self.shot()
        self.assertTrue(near(pixel(PROBE_X, CARD_TOP + 6), LIGHT_CARD))
        self.assertEqual(self.closed(crit), [])
        # akce z historie dorazi, i kdyz bublina nebyla (aplikace = tento test, bezi)
        log_id = self.history()[0][0]
        self.assertEqual(self.call(HISTORY, "Activate", (log_id,), "(s)", "(b)"), (True,))
        self.wait_for(lambda: any(s[1] == "ActionInvoked" and s[2] == (nid, "default") for s in self.signals), 2, "akce")
        self.assertEqual(self.history(), [])
        # nastaveni prezije restart
        self.stop_server()
        self.start_server()
        self.assertEqual(self.call(HISTORY, "GetDoNotDisturb", reply="(b)"), (True,))
        self.assertIn("DO_NOT_DISTURB=true", (self.home / ".config/luxos/notifications.conf").read_text())

    # ---- historie ----

    def test_history_survives_restart(self):
        keep = {"x-luxos-keep": GLib.Variant("b", True), "desktop-entry": GLib.Variant("s", "luxos-mail")}
        first = self.notify("První", "a", actions=["default", "Otevřít"], hints=keep, timeout=300)
        second = self.notify("Druhé", "b", hints=keep, timeout=300)
        self.wait_closed(second, 3)
        self.call(LOG, "MarkRead", ([self.history()[0][0]],), "(as)")
        before = self.history()
        path = self.home / ".local/share/luxos/notifications.json"
        self.wait_for(path.exists, 3, "historie neulozena")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.stop_server()
        self.start_server()
        after = self.history()
        self.assertEqual(after, before)
        self.assertEqual([(r[6], r[10]) for r in after], [("Druhé", True), ("První", False)])
        self.assertEqual(self.call(LOG, "HasUnread", reply="(b)"), (True,))
        # cislovani pokracuje, takze stara cisla aplikaci se nepletou s novymi
        third = self.notify("Třetí")
        self.assertGreater(third, second)
        # po restartu stale funguje vazba na aplikaci: Activate i CloseNotification
        self.assertEqual(self.call(HISTORY, "Activate", (after[1][0],), "(s)", "(b)"), (True,))
        self.wait_for(lambda: any(s[1] == "ActionInvoked" and s[2] == (first, "default") for s in self.signals), 2,
                      "akce po restartu")
        self.call(FDO, "CloseNotification", (second,), "(u)")
        self.assertEqual(self.history(), [])
        # Activate bez vychozi akce nebo neznameho zaznamu = False (okno pak otevre aplikaci samo)
        self.assertEqual(self.call(HISTORY, "Activate", ("nic",), "(s)", "(b)"), (False,))

    def test_history_api(self):
        keep = {"x-luxos-keep": GLib.Variant("b", True)}
        ids = [self.notify(f"Zaznam {i}", hints=keep, timeout=0) for i in range(5)]
        rows = self.history()
        self.assertEqual(len(rows), 5)
        self.assertEqual(self.call(LOG, "List", ("", 2, False), "(sub)", "(a(sxssssssa(ss)ib))")[0], rows[:2])
        self.assertEqual(self.call(LOG, "List", (rows[1][0], 2, False), "(sub)", "(a(sxssssssa(ss)ib))")[0], rows[2:4])
        self.assertEqual(self.call(LOG, "Get", (rows[3][0],), "(s)", "((sxssssssa(ss)ib))")[0], rows[3])
        self.call(LOG, "Delete", ([rows[0][0]],), "(as)")
        self.call(LOG, "MarkAllRead")
        self.assertEqual(self.call(LOG, "HasUnread", reply="(b)"), (False,))
        self.assertEqual(self.call(LOG, "List", ("", 0, True), "(sub)", "(a(sxssssssa(ss)ib))")[0], [])
        self.call(LOG, "Truncate", (2,), "(u)")
        self.assertEqual(len(self.history()), 2)
        self.call(LOG, "Clear")
        self.assertEqual(self.history(), [])
        names = [s[1] for s in self.signals]
        for name in ("RowAdded", "RowDeleted", "RowChanged", "Truncated", "Cleared"):
            self.assertIn(name, names)
        for n in ids:
            self.call(FDO, "CloseNotification", (n,), "(u)")
        # bubliny pod vyskakovacim oknem listy: skryte a odpocet stoji
        nid = self.notify("Skryté", timeout=1000)
        self.call(HISTORY, "SetPopupsHidden", (True,), "(b)")
        pixel = self.shot()
        self.assertEqual(pixel(PROBE_X, CARD_TOP + 10), (0, 0, 0))
        self.pump(1.5)
        self.assertEqual(self.closed(nid), [])
        self.call(HISTORY, "SetPopupsHidden", (False,), "(b)")
        self.wait_closed(nid, 3)
        self.assertEqual(len(ids), 5)

    # ---- zatez a pamet ----

    def test_burst_and_memory(self):
        pid = self.server.pid
        self.pump(1.0)
        idle = self.pss(pid)
        nids = [self.notify(f"Dávka {i}", "text " * 20, timeout=300) for i in range(50)]
        self.assertEqual(len(set(nids)), 50)
        self.wait_for(lambda: all(self.closed(n) for n in nids), 30, "davka se nezavrela")
        reasons = {self.closed(n)[0][2][1] for n in nids}
        self.assertEqual(reasons, {1})
        self.pump(0.5)
        after_one = self.pss(pid)
        # dalsich 6 x 50 do historie: po druhem kole je plna (100), pak uz pamet nema kam rust
        rounds = []
        for round_ in range(6):
            more = [self.notify(f"Kolo {round_} {i}", "text " * 20, timeout=200,
                                hints={"x-luxos-keep": GLib.Variant("b", True)}) for i in range(50)]
            self.wait_for(lambda: all(self.closed(n) for n in more), 30, "kolo se nezavrelo")
            self.pump(0.3)
            rounds.append(self.pss(pid))
        print(f"\n  PSS luxos-notify (kB): necinny {idle}, po 50 {after_one}, po kolech 50 do historie {rounds}")
        self.assertLess(idle, 25 * 1024)
        self.assertLess(min(rounds[-2:]) - rounds[1], 2 * 1024)
        self.assertLess(max(rounds), idle + 8 * 1024)
        self.assertLessEqual(len(self.history()), 100)
        self.assertIsNone(self.server.poll())


if __name__ == "__main__":
    unittest.main()
