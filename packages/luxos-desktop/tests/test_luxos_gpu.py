#!/usr/bin/env python3
"""LuxOS - testy luxos-gpu (files/lsl/luxos-gpu.lsl): grafika podle rezimu napajeni.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_gpu.py -v

Nic skutecneho se nemeni: falesny power-profiles-daemon na soukrome sbernici D-Bus (Gio.TestDBus jako
systemova sbernice), falesne sysfs/pci.ids/run (LUXOS_SYSROOT, LUXOS_PCI_IDS), docasny HOME s prepisy
Flatpaku, falesne nvidia-settings, notify-send, systemctl a flatpak v PATH. DISPLAY je jen jmeno pro
falesne nvidia-settings (zadny X server se nepouzije). LUXOS_LSLC: prekladac lslc (jinak se testy preskoci).
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
LSL = os.path.join(FILES, "lsl")
SYNC = os.path.join(FILES, "apps", "luxos-apps-sync")
I18N_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
TMP = tempfile.mkdtemp(prefix="luxos-gpu-test-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
sys.path.insert(0, HERE)

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from test_luxos_power import ServiceThread  # noqa: E402

PPD_XML = """<node><interface name="org.freedesktop.UPower.PowerProfiles">
  <property name="ActiveProfile" type="s" access="readwrite"/>
</interface></node>"""
PPD = "org.freedesktop.UPower.PowerProfiles"
NV_ENV = {"__NV_PRIME_RENDER_OFFLOAD": "1", "__GLX_VENDOR_LIBRARY_NAME": "nvidia", "__VK_LAYER_NV_optimus": "NVIDIA_only"}
PCI_IDS = """# test
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t164c  Lucienne
\t73ff  Navi 23 [Radeon RX 6600/6600 XT/6600M]
10de  NVIDIA Corporation
\t1f9d  TU117M [GeForce GTX 1650 Mobile / Max-Q]
\t\t1043 1f9d  subsystem
8086  Intel Corporation
\t9a49  TigerLake-LP GT2 [Iris Xe Graphics]
\t1f9e  Not NVIDIA
"""


def build():
    if not LSLC:
        return None
    src = os.path.join(TMP, "src")
    os.makedirs(src, exist_ok=True)
    for f in glob.glob(os.path.join(LSL, "*.lsl")):
        shutil.copy(f, src)
    out = os.path.join(TMP, "luxos-gpu")
    r = subprocess.run(["nice", "-n", "10", LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, "luxos-gpu.lsl"), out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return None
    return out


BIN = build()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class FakePPD:
    """power-profiles-daemon: vlastnost ActiveProfile (cteni pres Properties.Get)."""

    def __init__(self, svc, address, profile):
        self.svc, self.profile = svc, profile
        svc.run(self._init, address)

    def _init(self, address):
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        node = Gio.DBusNodeInfo.new_for_xml(PPD_XML)
        self.conn.register_object("/org/freedesktop/UPower/PowerProfiles", node.interfaces[0], None,
                                  lambda *_a: GLib.Variant("s", self.profile), None)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", (PPD, 4)), None, 0, 2000, None)

    def close(self):
        self.svc.run(self.conn.close_sync, None)


@unittest.skipUnless(BIN, "chybi lslc (LSL >= 0.10.6, LUXOS_LSLC)")
class Gpu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tdbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        cls.tdbus.up()
        cls.address = cls.tdbus.get_bus_address()
        cls.svc = ServiceThread()

    @classmethod
    def tearDownClass(cls):
        cls.svc.stop()
        cls.tdbus.down()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="case-", dir=TMP)
        self.home = os.path.join(self.tmp, "home")
        self.root = os.path.join(self.tmp, "root")
        self.runtime = os.path.join(self.tmp, "run-user")
        self.fake = os.path.join(self.tmp, "fake")
        self.log = os.path.join(self.tmp, "calls.log")
        for d in (self.home, self.root, self.runtime, self.fake):
            os.makedirs(d)
        write(os.path.join(self.tmp, "pci.ids"), PCI_IDS)
        # nvidia-settings: -q vrati FAKE_PM (vychozi 0 = adaptivni), -a zapise do logu
        self.script("nvidia-settings", 'echo "nvidia-settings $*" >>"$FAKE_LOG"\n'
                    'case "$*" in *" -q "*) echo "${FAKE_PM:-0}";; esac\n')
        for name in ("notify-send", "systemctl", "flatpak"):
            self.script(name, 'echo "$(basename "$0") $*" >>"$FAKE_LOG"\n')
        self.ppd = None
        self.hybrid_nvidia()

    def tearDown(self):
        if self.ppd:
            self.ppd.close()

    def script(self, name, body):
        path = os.path.join(self.fake, name)
        write(path, "#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def card(self, name, pci, slot, driver, boot):
        dev = os.path.join(self.root, "sys", "class", "drm", name, "device")
        write(os.path.join(dev, "uevent"), f"DRIVER={driver}\nPCI_CLASS=30000\nPCI_ID={pci}\nPCI_SLOT_NAME={slot}\n")
        if boot is not None:
            write(os.path.join(dev, "boot_vga"), "1\n" if boot else "0\n")
        return dev

    def hybrid_nvidia(self):
        self.card("card0", "10DE:1F9D", "0000:01:00.0", "nvidia", False)
        self.card("card1", "1002:164C", "0000:05:00.0", "amdgpu", True)
        os.makedirs(os.path.join(self.root, "sys", "class", "drm", "card1-eDP-1"))

    def set_profile(self, profile):
        if self.ppd is None:
            self.ppd = FakePPD(self.svc, self.address, profile)
        self.ppd.profile = profile

    def env(self, **extra):
        env = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.home, "XDG_RUNTIME_DIR": self.runtime,
               "LUXOS_SYSROOT": self.root, "LUXOS_PCI_IDS": os.path.join(self.tmp, "pci.ids"),
               "DBUS_SYSTEM_BUS_ADDRESS": self.address, "DISPLAY": ":97", "FAKE_LOG": self.log,
               "LUXOS_I18N_DIR": I18N_DIR, "LANG": "C.UTF-8"}
        env.update(extra)
        return env

    def gpu(self, *args, **extra):
        r = subprocess.run([BIN, *args], env=self.env(**extra), capture_output=True, text=True, timeout=30)
        return r

    def calls(self):
        return read(self.log).splitlines() if os.path.exists(self.log) else []

    def clear(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def override(self, app):
        return os.path.join(self.home, ".local", "share", "flatpak", "overrides", app)

    def status(self, **extra):
        r = self.gpu("status", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(line.split("=", 1) for line in r.stdout.splitlines())

    def run_env(self, **extra):
        r = self.gpu("run", "env", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)

    # ---- zjisteni grafiky a profilu ------------------------------------------------------------------
    def test_status_hybrid_nvidia(self):
        self.set_profile("performance")
        st = self.status()
        self.assertEqual(st, {"gpu": "nvidia", "name": "NVIDIA GeForce GTX 1650 Mobile / Max-Q",
                              "profile": "performance", "offload": "yes"})
        # nazev z mezipameti (pci.ids uz neni potreba)
        os.unlink(os.path.join(self.tmp, "pci.ids"))
        self.assertEqual(self.status()["name"], "NVIDIA GeForce GTX 1650 Mobile / Max-Q")
        self.set_profile("balanced")
        self.assertEqual(self.status()["offload"], "no")

    def test_status_amd_dgpu_and_device_of_other_vendor(self):
        shutil.rmtree(os.path.join(self.root, "sys"))
        self.card("card0", "8086:9A49", "0000:00:02.0", "i915", True)
        self.card("card1", "1002:73FF", "0000:03:00.0", "amdgpu", None)
        self.set_profile("performance")
        st = self.status()
        self.assertEqual((st["gpu"], st["name"]), ("dri", "AMD Radeon RX 6600/6600 XT/6600M"))
        # zarizeni 1f9e je v pci.ids jen u Intelu: u NVIDIA se nesmi najit
        shutil.rmtree(os.path.join(self.root, "sys"))
        self.card("card0", "1002:164C", "0000:05:00.0", "amdgpu", True)
        self.card("card1", "10DE:1F9E", "0000:01:00.0", "nvidia", False)
        self.assertEqual(self.status(XDG_CACHE_HOME=os.path.join(self.tmp, "c2"))["name"], "NVIDIA")

    def test_no_discrete_gpu(self):
        self.set_profile("performance")
        shutil.rmtree(os.path.join(self.root, "sys"))
        self.card("card0", "1002:164C", "0000:05:00.0", "amdgpu", True)
        self.assertEqual(self.status()["gpu"], "none")
        # NVIDIA bez ovladace (nic nenavazano) se nepocita
        self.card("card1", "10DE:1F9D", "0000:01:00.0", "", False)
        self.assertEqual(self.status()["gpu"], "none")
        env = self.run_env()
        self.assertFalse(set(NV_ENV) & set(env))

    # ---- luxos-gpu run ------------------------------------------------------------------------------------
    def test_run_follows_profile(self):
        self.set_profile("performance")
        env = self.run_env()
        for k, v in NV_ENV.items():
            self.assertEqual(env.get(k), v)
        self.set_profile("power-saver")
        self.assertFalse(set(NV_ENV) & set(self.run_env()))
        self.set_profile("balanced")
        self.assertFalse(set(NV_ENV) & set(self.run_env()))
        # argumenty beze zmeny (zadny shell)
        self.set_profile("performance")
        r = self.gpu("run", "printf", "%s|", "a b", "$HOME", "*")
        self.assertEqual(r.stdout, "a b|$HOME|*|")
        self.assertEqual(self.gpu("env").stdout.split(), [f"{k}={v}" for k, v in NV_ENV.items()])

    def test_run_without_ppd_and_errors(self):
        # power-profiles-daemon nebezi: spusti normalne, bez samostatne grafiky
        env = self.run_env()
        self.assertFalse(set(NV_ENV) & set(env))
        r = self.gpu("run", "/nonexistent/game")
        self.assertEqual(r.returncode, 127)
        self.assertIn("/nonexistent/game", r.stderr)
        self.assertEqual(self.gpu("run").returncode, 2)
        self.assertEqual(self.gpu("bogus").returncode, 2)
        self.assertEqual(self.gpu("--help").returncode, 0)

    def test_run_dri_keeps_user_choice(self):
        shutil.rmtree(os.path.join(self.root, "sys"))
        self.card("card0", "8086:9A49", "0000:00:02.0", "i915", True)
        self.card("card1", "1002:73FF", "0000:03:00.0", "amdgpu", False)
        self.set_profile("performance")
        self.assertEqual(self.run_env().get("DRI_PRIME"), "1")
        self.assertEqual(self.run_env(DRI_PRIME="0").get("DRI_PRIME"), "0")

    # ---- Flatpak --------------------------------------------------------------------------------------------
    def flatpak_game(self, app, name, categories="Game;", user=False):
        base = (os.path.join(self.home, ".local", "share", "flatpak") if user
                else os.path.join(self.root, "var", "lib", "flatpak"))
        write(os.path.join(base, "exports", "share", "applications", app + ".desktop"),
              f"[Desktop Entry]\nName={name}\nExec=/usr/bin/flatpak run {app}\nCategories={categories}\nX-Flatpak={app}\n")

    def test_flatpak_overrides_apply_revert_idempotent(self):
        self.flatpak_game("com.valvesoftware.Steam", "Steam", "Network;FileTransfer;Game;")
        self.flatpak_game("org.example.Racer", "Racer", "Game;ArcadeGame;", user=True)
        self.flatpak_game("org.example.Editor", "Editor", "Utility;")
        # vlastni prepis uzivatele: jine skupiny a vlastni hodnota jedne z promennych zustanou
        user_steam = "[Context]\nfilesystems=/mnt/games;\n\n[Environment]\n__GLX_VENDOR_LIBRARY_NAME=mesa\nFOO=bar\n"
        write(self.override("com.valvesoftware.Steam"), user_steam)
        self.set_profile("performance")
        self.assertEqual(self.gpu("apply").returncode, 0)
        kf = GLib.KeyFile()
        kf.load_from_file(self.override("com.valvesoftware.Steam"), GLib.KeyFileFlags.NONE)
        self.assertEqual(kf.get_string("Context", "filesystems"), "/mnt/games;")
        self.assertEqual(kf.get_string("Environment", "FOO"), "bar")
        self.assertEqual(kf.get_string("Environment", "__GLX_VENDOR_LIBRARY_NAME"), "mesa")   # nastaveni uzivatele
        self.assertEqual(kf.get_string("Environment", "__NV_PRIME_RENDER_OFFLOAD"), "1")
        self.assertEqual(kf.get_string("Environment", "__VK_LAYER_NV_optimus"), "NVIDIA_only")
        for app in ("org.example.Racer", "net.lutris.Lutris", "com.heroicgameslauncher.hgl"):
            kf = GLib.KeyFile()
            kf.load_from_file(self.override(app), GLib.KeyFileFlags.NONE)
            self.assertEqual(dict((k, kf.get_string("Environment", k)) for k in kf.get_keys("Environment")[0]), NV_ENV, app)
        self.assertFalse(os.path.exists(self.override("org.example.Editor")))
        snapshot = {f: read(f) for f in glob.glob(self.override("*"))}
        records = read(os.path.join(self.home, ".local", "state", "luxos", "gpu-flatpak"))
        self.assertNotIn("__GLX_VENDOR_LIBRARY_NAME\tnvidia\ncom.valvesoftware.Steam", records)
        self.assertNotIn("com.valvesoftware.Steam\t__GLX_VENDOR_LIBRARY_NAME", records)
        # znovu (prihlaseni, dalsi zmena): nic se nemeni
        self.assertEqual(self.gpu("apply").returncode, 0)
        self.assertEqual({f: read(f) for f in glob.glob(self.override("*"))}, snapshot)
        # zpet na Vyrovnany: puvodni prepis uzivatele beze zmeny, vlastni soubory pryc
        self.set_profile("balanced")
        self.assertEqual(self.gpu("apply").returncode, 0)
        self.assertEqual(read(self.override("com.valvesoftware.Steam")), user_steam)
        self.assertEqual(os.listdir(os.path.dirname(self.override("x"))), ["com.valvesoftware.Steam"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "state", "luxos", "gpu-flatpak")))
        self.assertEqual(self.gpu("apply").returncode, 0)
        self.assertEqual(read(self.override("com.valvesoftware.Steam")), user_steam)

    def test_flatpak_user_change_wins(self):
        self.set_profile("performance")
        self.gpu("apply")
        path = self.override("net.lutris.Lutris")
        # uzivatel si mezitim zmenil jednu promennou a pridal vlastni
        write(path, read(path).replace("__VK_LAYER_NV_optimus=NVIDIA_only", "__VK_LAYER_NV_optimus=NVIDIA_any") + "MINE=1\n")
        self.gpu("apply")
        self.assertIn("__VK_LAYER_NV_optimus=NVIDIA_any", read(path))
        self.set_profile("power-saver")
        self.gpu("apply")
        kf = GLib.KeyFile()
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
        self.assertEqual(sorted(kf.get_keys("Environment")[0]), ["MINE", "__VK_LAYER_NV_optimus"])
        self.assertEqual(kf.get_string("Environment", "__VK_LAYER_NV_optimus"), "NVIDIA_any")

    def test_crash_leftovers_reverted_when_gpu_gone(self):
        """Prepisy z rezimu Vykon zustanou i po padu/odhlaseni; dalsi apply je srovna i bez grafiky."""
        self.set_profile("performance")
        self.gpu("apply")
        self.assertTrue(os.path.exists(self.override("com.valvesoftware.Steam")))
        shutil.rmtree(os.path.join(self.root, "sys"))          # napr. grafika vypnuta v BIOSu
        self.gpu("apply")
        self.assertFalse(os.path.exists(self.override("com.valvesoftware.Steam")))

    def test_running_steam_notified_once(self):
        self.flatpak_game("com.valvesoftware.Steam", "Steam", "Game;")
        write(os.path.join(self.runtime, ".flatpak", "1234", "info"),
              "[Application]\nname=com.valvesoftware.Steam\nruntime=runtime/x\n\n[Instance]\ninstance-id=1234\n")
        self.set_profile("performance")
        self.gpu("apply")
        notes = [c for c in self.calls() if c.startswith("notify-send")]
        self.assertEqual(len(notes), 1, self.calls())
        self.assertIn("Restart Steam to run its games on NVIDIA GeForce GTX 1650 Mobile / Max-Q.", notes[0])
        self.assertIn("-i com.valvesoftware.Steam", notes[0])
        self.clear()
        self.gpu("apply")
        self.assertEqual([c for c in self.calls() if c.startswith("notify-send")], [])
        self.set_profile("balanced")
        r = self.gpu("apply", LANG="cs_CZ.UTF-8")
        notes = [c for c in self.calls() if c.startswith("notify-send")]
        self.assertEqual(len(notes), 1)
        self.assertIn("Restartujte Steam, aby hry znovu používaly integrovanou grafiku", notes[0])

    # ---- NVIDIA PowerMizer ------------------------------------------------------------------------------
    def test_powermizer(self):
        self.set_profile("performance")
        self.gpu("apply")
        ns = [c for c in self.calls() if c.startswith("nvidia-settings")]
        self.assertEqual(ns, ["nvidia-settings --no-write-config -t -q [gpu:0]/GpuPowerMizerMode",
                              "nvidia-settings --no-write-config -a [gpu:0]/GpuPowerMizerMode=1"])
        self.assertEqual(read(os.path.join(self.runtime, "luxos", "gpu-powermizer")).strip(), "0")
        self.clear()
        self.gpu("apply")              # uz nastaveno: grafiku znovu nebudit
        self.assertEqual([c for c in self.calls() if c.startswith("nvidia-settings")], [])
        self.set_profile("balanced")
        self.gpu("apply")
        self.assertEqual([c for c in self.calls() if c.startswith("nvidia-settings")],
                         ["nvidia-settings --no-write-config -a [gpu:0]/GpuPowerMizerMode=0"])
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "luxos", "gpu-powermizer")))
        self.clear()
        self.gpu("apply")              # Vyrovnany bez zaznamu: nvidia-settings vubec nespoustet
        self.assertEqual([c for c in self.calls() if c.startswith("nvidia-settings")], [])

    def test_powermizer_already_max_or_no_display(self):
        self.set_profile("performance")
        self.gpu("apply", FAKE_PM="1")
        self.assertEqual([c for c in self.calls() if "-a" in c.split()], [])
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "luxos", "gpu-powermizer")))
        self.clear()
        self.gpu("apply", DISPLAY="")
        self.assertEqual([c for c in self.calls() if c.startswith("nvidia-settings")], [])
        # nvidia-settings nic nevrati (bez NV-CONTROL): nic nezapisovat
        self.script("nvidia-settings", 'echo "nvidia-settings $*" >>"$FAKE_LOG"\nexit 1\n')
        self.gpu("apply")
        self.assertEqual([c for c in self.calls() if "-a" in c.split()], [])

    # ---- samostatna AMD (root cast) -------------------------------------------------------------------------
    def amd_dgpu(self):
        shutil.rmtree(os.path.join(self.root, "sys"))
        self.card("card0", "8086:9A49", "0000:00:02.0", "i915", True)
        dev = self.card("card1", "1002:73FF", "0000:03:00.0", "amdgpu", False)
        write(os.path.join(dev, "power_dpm_force_performance_level"), "auto\n")
        return dev

    def test_amd_system_part(self):
        dev = self.amd_dgpu()
        self.set_profile("performance")
        self.gpu("apply")
        self.assertIn("systemctl --no-ask-password --no-block start luxos-gpu-performance.service", self.calls())
        self.assertFalse([c for c in self.calls() if c.startswith("nvidia-settings")])
        # root cast (spousti ji jednotka)
        self.assertEqual(self.gpu("system", "on").returncode, 0)
        self.assertEqual(read(os.path.join(dev, "power_dpm_force_performance_level")).strip(), "high")
        self.assertTrue(os.path.exists(os.path.join(self.root, "run", "luxos", "gpu-performance")))
        self.gpu("system", "on")       # podruhe: puvodni hodnota se neprepise
        self.clear()
        self.gpu("apply")              # jednotka uz bezi
        self.assertEqual([c for c in self.calls() if c.startswith("systemctl")], [])
        self.set_profile("balanced")
        self.gpu("apply")
        self.assertIn("systemctl --no-ask-password --no-block stop luxos-gpu-performance.service", self.calls())
        self.assertEqual(self.gpu("system", "off").returncode, 0)
        self.assertEqual(read(os.path.join(dev, "power_dpm_force_performance_level")).strip(), "auto")
        self.assertEqual(os.listdir(os.path.join(self.root, "run", "luxos")), [])
        self.clear()
        self.gpu("apply")
        self.assertEqual([c for c in self.calls() if c.startswith("systemctl")], [])

    def test_nvidia_never_touches_system_unit(self):
        for profile in ("performance", "balanced"):
            self.set_profile(profile)
            self.gpu("apply")
        self.assertEqual([c for c in self.calls() if c.startswith("systemctl")], [])

    # ---- .desktop: hry pres luxos-gpu run (luxos-apps-sync) --------------------------------------------------
    def test_apps_sync_wraps_games(self):
        apps = os.path.join(self.tmp, "applications")
        base = os.path.join(self.tmp, "luxos-apps")
        exports = os.path.join(self.tmp, "flatpak", "exports", "share")
        write(os.path.join(apps, "supertux.desktop"),
              "[Desktop Entry]\nType=Application\nName=SuperTux\nExec=supertux2 %f\nCategories=Game;ArcadeGame;\n"
              "Actions=Win;\n\n[Desktop Action Win]\nName=Windowed\nExec=supertux2 --window\n")
        write(os.path.join(apps, "blender.desktop"),
              "[Desktop Entry]\nType=Application\nName=Blender\nExec=blender %f\nCategories=Graphics;\nPrefersNonDefaultGPU=true\n")
        write(os.path.join(apps, "gedit.desktop"), "[Desktop Entry]\nType=Application\nName=Text\nExec=gedit\nCategories=Utility;\n")
        write(os.path.join(apps, "dbusgame.desktop"),
              "[Desktop Entry]\nType=Application\nName=D\nExec=dgame\nCategories=Game;\nDBusActivatable=true\n")
        write(os.path.join(apps, "hiddengame.desktop"), "[Desktop Entry]\nType=Application\nName=H\nExec=h\nCategories=Game;\nHidden=true\n")
        # hra v rename.conf: kratky nazev i Exec pres luxos-gpu
        write(os.path.join(apps, "steam.desktop"),
              "[Desktop Entry]\nType=Application\nName=Steam (Runtime)\nExec=/usr/bin/steam %U\nCategories=Network;Game;\nPrefersNonDefaultGPU=true\n")
        conf = os.path.join(self.tmp, "rename.conf")
        write(conf, "steam|Steam||\n")
        # aplikace z Flathubu se stejnym desktop-id: odkaz zustane odkazem (resi ho prepis Flatpaku)
        exp = os.path.join(self.tmp, "flatpak", "app", "x", "export")
        write(os.path.join(exp, "net.lutris.Lutris.desktop"),
              "[Desktop Entry]\nType=Application\nName=Lutris\nExec=flatpak run net.lutris.Lutris\nCategories=Game;\nX-Flatpak=net.lutris.Lutris\n")
        os.makedirs(os.path.join(exports, "applications"))
        os.symlink(os.path.join(exp, "net.lutris.Lutris.desktop"), os.path.join(exports, "applications", "net.lutris.Lutris.desktop"))
        write(os.path.join(apps, "net.lutris.Lutris.desktop"),
              "[Desktop Entry]\nType=Application\nName=Lutris native\nExec=lutris\nCategories=Game;\n")
        env = dict(os.environ, LUXOS_APPS_RENAME_CONF=conf, LUXOS_APPS_SOURCE=apps, LUXOS_APPS_DIR=base,
                   LUXOS_APPS_FLATPAK_EXPORTS=exports, LUXOS_APPS_GPU=BIN)

        def sync():
            r = subprocess.run(["bash", SYNC], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            out = os.path.join(base, "applications")
            return {f: (os.readlink(os.path.join(out, f)) if os.path.islink(os.path.join(out, f)) else read(os.path.join(out, f)))
                    for f in os.listdir(out) if f.endswith(".desktop")}

        first = sync()
        self.assertEqual(sorted(first), ["blender.desktop", "net.lutris.Lutris.desktop", "steam.desktop", "supertux.desktop"])
        tux = first["supertux.desktop"]
        self.assertIn("Exec=luxos-gpu run supertux2 %f\n", tux)
        self.assertIn("Exec=luxos-gpu run supertux2 --window", tux)
        self.assertEqual(tux.count("X-LuxOS-GPU=true"), 1)
        self.assertIn("Exec=luxos-gpu run blender %f", first["blender.desktop"])
        self.assertIn("Name=Steam\n", first["steam.desktop"])
        self.assertNotIn("Name=Steam (Runtime)", first["steam.desktop"])
        self.assertIn("Exec=luxos-gpu run /usr/bin/steam %U", first["steam.desktop"])
        self.assertEqual(first["net.lutris.Lutris.desktop"], os.path.join(exports, "applications", "net.lutris.Lutris.desktop"))
        # opakovane: stejny vysledek, bez dvojiteho obaleni; soubor jen kvuli grafice se neprepisuje
        out = os.path.join(base, "applications")
        mtime = os.stat(os.path.join(out, "supertux.desktop")).st_mtime_ns
        self.assertEqual(sync(), first)
        self.assertEqual(os.stat(os.path.join(out, "supertux.desktop")).st_mtime_ns, mtime)
        # hra odinstalovana: prepis zmizi
        os.unlink(os.path.join(apps, "supertux.desktop"))
        self.assertNotIn("supertux.desktop", sync())
        # spousteni obaleneho prikazu: luxos-gpu run predava argumenty dal
        self.set_profile("performance")
        r = self.gpu("run", "sh", "-c", 'echo "$__NV_PRIME_RENDER_OFFLOAD $1"', "x", "arg")
        self.assertEqual(r.stdout.strip(), "1 arg")


class PowerAppGpuLine(unittest.TestCase):
    """Baterie a napajeni: radek "Grafika: ..." z `luxos-gpu status` a Vykon vypne Sporic baterie."""

    @classmethod
    def setUpClass(cls):
        from test_luxos_power import load_power
        cls.mod = load_power()

    def test_gpu_info(self):
        mod = self.mod
        orig = mod.run
        try:
            mod.run = lambda *a: "gpu=nvidia\nname=NVIDIA GeForce GTX 1650\nprofile=balanced\noffload=no"
            self.assertEqual(mod.gpu_info(), {"kind": "nvidia", "name": "NVIDIA GeForce GTX 1650"})
            mod.run = lambda *a: "gpu=none\nname=\nprofile=performance\noffload=no"
            self.assertIsNone(mod.gpu_info())
            mod.run = lambda *a: ""                 # luxos-gpu chybi
            self.assertIsNone(mod.gpu_info())
        finally:
            mod.run = orig

    def test_texts_and_saver(self):
        mod = self.mod
        labels, calls, sets = [], [], []

        class Label:
            def set_text(self, t):
                labels.append(t)

        class Switch:
            def handler_block(self, h):
                calls.append(("block", h))

            def handler_unblock(self, h):
                calls.append(("unblock", h))

            def set_active(self, v):
                calls.append(("active", v))

        win = mod.PowerWindow.__new__(mod.PowerWindow)
        win.gpu = {"kind": "nvidia", "name": "NVIDIA X"}
        win.gpu_label, win.saver, win.saver_handler = Label(), Switch(), 7
        win.bat = type("B", (), {"bus": None})()
        orig = (mod.run, mod.ppd_set, mod.SAVER_STATE)
        tmp = tempfile.mkdtemp(dir=TMP)
        try:
            mod.run = lambda *a: calls.append(a) or ""
            mod.ppd_set = lambda bus, k: sets.append(k) or True
            mod.SAVER_STATE = os.path.join(tmp, "powersaver")
            win.set_mode("balanced")
            self.assertEqual(labels[-1], mod._("Graphics: integrated (Performance mode uses %s for games)") % "NVIDIA X")
            self.assertEqual(calls, [])
            open(mod.SAVER_STATE, "w").close()          # Sporic baterie zapnuty
            win.set_mode("performance")
            self.assertEqual(calls, [("luxos-powersaver", "off"), ("block", 7), ("active", False), ("unblock", 7)])
            self.assertEqual(sets, ["balanced", "performance"])
            self.assertEqual(labels[-1], mod._("Graphics: %s for games and demanding apps") % "NVIDIA X")
            win.gpu = None
            n = len(labels)
            win.update_gpu("performance")
            self.assertEqual(len(labels), n)
        finally:
            mod.run, mod.ppd_set, mod.SAVER_STATE = orig


if __name__ == "__main__":
    unittest.main()
