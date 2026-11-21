#!/usr/bin/env python3
"""LuxOS - testy Sporice baterie (neuspavani pri prehravani a hudbu v Ovladacim centru testuje test_luxos_awake.py).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_power.py -v

Nic nemeni na skutecnem systemu: sysfs je falesny strom (LUXOS_SYSROOT), prikazy gdbus,
gsettings, xfconf-query, systemctl, brightnessctl a xrandr jsou falesne (PATH / LUXOS_XRANDR).
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PYDIR = os.path.join(ROOT, "luxos-desktop", "files", "python")
BIN = os.path.join(ROOT, "luxos-desktop", "files", "bin")
HELPER = os.path.join(ROOT, "luxos-tweaks", "files", "power", "luxos-powersaver-helper")
UNMETERED = os.path.join(ROOT, "luxos-tweaks", "files", "power", "luxos-unmetered")
FAKE_XRANDR = os.path.join(HERE, "fake-displays", "xrandr")
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.join(ROOT, "luxos-i18n", "files"))

import luxos_displays as ld  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read().strip()


# =====================================================================================
# 1. Systemova cast Sporice baterie (root helper) nad falesnym sysfs
# =====================================================================================
class Helper(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-ps-root-")
        r = self.root
        write(f"{r}/sys/devices/system/cpu/intel_pstate/no_turbo", "0\n")
        write(f"{r}/sys/devices/system/cpu/cpufreq/policy0/boost", "1\n")
        write(f"{r}/sys/module/snd_hda_intel/parameters/power_save", "0\n")
        write(f"{r}/proc/sys/vm/dirty_writeback_centisecs", "500\n")
        usb = f"{r}/sys/bus/usb/devices"
        drivers = f"{r}/sys/bus/usb/drivers"

        def dev(name, cls, ifaces):
            write(f"{usb}/{name}/power/control", "on\n")
            write(f"{usb}/{name}/bDeviceClass", cls + "\n")
            for i, drv in enumerate(ifaces):
                d = f"{usb}/{name}/{name}:1.{i}"
                os.makedirs(d)
                if drv:
                    os.makedirs(f"{drivers}/{drv}", exist_ok=True)
                    os.symlink(f"{drivers}/{drv}", f"{d}/driver")
        dev("1-1", "ef", ["uvcvideo", "uvcvideo"])      # kamera -> auto
        dev("1-2", "00", ["usbhid"])                     # mys -> beze zmeny
        dev("1-3", "e0", ["btusb", "btusb"])             # Bluetooth -> beze zmeny
        dev("1-4", "ff", [None])                         # nepouzivane (bez ovladace) -> auto
        dev("1-5", "00", ["uvcvideo", "snd-usb-audio"])  # kamera s mikrofonem -> beze zmeny
        dev("usb1", "09", ["hub"])                       # hub -> beze zmeny
        self.usb = usb

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def helper(self, arg):
        r = subprocess.run(["bash", HELPER, arg], env=dict(os.environ, LUXOS_SYSROOT=self.root),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def values(self):
        r = self.root
        return {"turbo": read(f"{r}/sys/devices/system/cpu/intel_pstate/no_turbo"),
                "boost": read(f"{r}/sys/devices/system/cpu/cpufreq/policy0/boost"),
                "hda": read(f"{r}/sys/module/snd_hda_intel/parameters/power_save"),
                "wb": read(f"{r}/proc/sys/vm/dirty_writeback_centisecs"),
                **{d: read(f"{self.usb}/{d}/power/control") for d in ("1-1", "1-2", "1-3", "1-4", "1-5", "usb1")}}

    def test_on_off_restores_everything(self):
        before = self.values()
        self.helper("on")
        on = self.values()
        self.assertEqual((on["turbo"], on["boost"], on["hda"], on["wb"]), ("1", "0", "1", "1500"))
        self.assertEqual((on["1-1"], on["1-4"]), ("auto", "auto"))
        self.assertEqual((on["1-2"], on["1-3"], on["1-5"], on["usb1"]), ("on",) * 4)
        self.assertTrue(os.path.exists(f"{self.root}/run/luxos/powersaver"))
        # druhe "on" nesmi prepsat puvodni hodnoty
        self.helper("on")
        self.helper("off")
        self.assertEqual(self.values(), before)
        self.assertFalse(os.path.exists(f"{self.root}/run/luxos/powersaver"))
        self.assertFalse(os.path.exists(f"{self.root}/run/luxos/powersaver.saved"))

    def test_hda_already_saving_untouched(self):
        write(f"{self.root}/sys/module/snd_hda_intel/parameters/power_save", "10\n")
        self.helper("on")
        self.assertEqual(self.values()["hda"], "10")
        self.helper("off")
        self.assertEqual(self.values()["hda"], "10")

    def test_missing_files_and_off_without_on(self):
        shutil.rmtree(f"{self.root}/sys/devices")
        self.helper("off")          # nic ulozeno -> nic se nedeje
        self.helper("on")
        self.assertEqual(read(f"{self.root}/proc/sys/vm/dirty_writeback_centisecs"), "1500")
        self.helper("off")
        self.assertEqual(read(f"{self.root}/proc/sys/vm/dirty_writeback_centisecs"), "500")


class Unmetered(unittest.TestCase):
    def run_with(self, out, rc=0):
        d = tempfile.mkdtemp()
        try:
            write(f"{d}/busctl", f"#!/bin/sh\necho '{out}'\nexit {rc}\n")
            os.chmod(f"{d}/busctl", 0o755)
            return subprocess.run(["bash", UNMETERED], env=dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"]),
                                  capture_output=True, timeout=10).returncode
        finally:
            shutil.rmtree(d)

    def test_values(self):
        self.assertEqual(self.run_with("u 1"), 1)      # merene (Sporic dat)
        self.assertEqual(self.run_with("u 3"), 1)      # odhadem merene (telefon)
        self.assertEqual(self.run_with("u 2"), 0)
        self.assertEqual(self.run_with("u 4"), 0)
        self.assertEqual(self.run_with("u 0"), 0)
        self.assertEqual(self.run_with("", rc=1), 0)   # bez NetworkManageru se nepreskakuje


# =====================================================================================
# 2. Uzivatelska cast luxos-powersaver s falesnymi prikazy
# =====================================================================================
FAKES = {
    # stav v souborech v $FAKE_STATE; volani do $FAKE_STATE/log
    "gdbus": r'''#!/bin/bash
echo "gdbus $*" >>"$FAKE_STATE/log"
if [[ $* == *Properties.Get* ]]; then echo "(<'$(cat "$FAKE_STATE/profile")'>,)"; exit 0; fi
if [[ $* == *Properties.Set* ]]; then p=${*: -1}; p=${p#<\'}; echo "${p%\'>}" >"$FAKE_STATE/profile"; fi
''',
    "gsettings": r'''#!/bin/bash
f="$FAKE_STATE/gs-$3"
case $1 in get) cat "$f" 2>/dev/null || echo true ;; set) echo "$4" >"$f" ;; esac
''',
    "xfconf-query": r'''#!/bin/bash
ch= p= v= reset=
while (($#)); do case $1 in -c) ch=$2; shift ;; -p) p=$2; shift ;; -s) v=$2; shift ;; -r) reset=1 ;; esac; shift; done
f="$FAKE_STATE/xf-$ch${p//\//_}"
if [[ -n $reset ]]; then rm -f "$f"; elif [[ -n $v ]]; then echo "$v" >"$f"; else cat "$f" 2>/dev/null || exit 1; fi
''',
    "systemctl": '#!/bin/bash\necho "systemctl $*" >>"$FAKE_STATE/log"\n',
    "brightnessctl": r'''#!/bin/bash
b="$LUXOS_BACKLIGHT/bl"; v=${*: -1}; v=${v%\%}
echo $(( v * $(cat "$b/max_brightness") / 100 )) >"$b/brightness"
''',
}


class PowersaverScript(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="luxos-ps-user-")
        self.bin = os.path.join(self.d, "bin")
        os.makedirs(self.bin)
        for name, text in FAKES.items():
            write(os.path.join(self.bin, name), text)
            os.chmod(os.path.join(self.bin, name), 0o755)
        self.state = os.path.join(self.d, "state")
        os.makedirs(self.state)
        write(f"{self.state}/profile", "performance")
        self.bl = os.path.join(self.d, "backlight")
        write(f"{self.bl}/bl/max_brightness", "1000")
        write(f"{self.bl}/bl/brightness", "900")
        self.xr = os.path.join(self.d, "xrandr.json")
        with open(self.xr, "w") as f:
            json.dump({"outputs": [
                {"name": "eDP-1", "connected": True, "edid": "", "mm": [344, 194], "primary": True,
                 "modes": [["2560x1600", ["165.00", "120.00", "60.00"]], ["1920x1200", ["165.00", "60.00"]]],
                 "preferred": ["2560x1600", "165.00"], "current": ["2560x1600", "165.00"],
                 "rotation": "normal", "pos": [0, 0]}]}, f)
        self.cfg = os.path.join(self.d, "config")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], FAKE_STATE=self.state,
                        XDG_CONFIG_HOME=self.cfg, LUXOS_BACKLIGHT=self.bl, LUXOS_XRANDR=FAKE_XRANDR,
                        FAKE_XRANDR_STATE=self.xr, LUXOS_DISPLAYS_PY=os.path.join(PYDIR, "luxos_displays.py"),
                        DISPLAY=":luxos-test-fake", LUXOS_SYSROOT=self.d)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def ps(self, *args):
        r = subprocess.run(["bash", os.path.join(BIN, "luxos-powersaver"), *args], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def rate(self):
        with open(self.xr) as f:
            return json.load(f)["outputs"][0]["current"]

    def log(self):
        try:
            return read(f"{self.state}/log")
        except OSError:
            return ""

    def test_on_off_roundtrip(self):
        self.assertEqual(self.ps("status").strip(), "off")
        self.ps("on")
        self.assertEqual(self.ps("status").strip(), "on")
        self.assertEqual(read(f"{self.state}/profile"), "power-saver")
        # zvetsovani v Docku zustava (sporic na nem nic neusetri; Dock se "nekdy" nezvetsoval)
        self.assertFalse(os.path.exists(f"{self.state}/gs-zoom-enabled"))
        # animace GTK zustavaji (jinak stoji i kolecka prubehu v aplikacich)
        self.assertFalse(os.path.exists(f"{self.state}/xf-xsettings_Gtk_EnableAnimations"))
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])   # 60 Hz jen na prani (displej zcerna)
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "720")         # 90 % -> 72 %
        self.assertIn("systemctl --no-ask-password --no-block start luxos-powersaver.service", self.log())
        # druhe zapnuti (napr. automaticke) nesmi ztlumit znovu ani prepsat puvodni hodnoty
        self.ps("on")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "720")
        self.ps("off")
        self.assertEqual(self.ps("status").strip(), "off")
        self.assertEqual(read(f"{self.state}/profile"), "performance")   # puvodni profil, ne "balanced"
        self.assertFalse(os.path.exists(f"{self.state}/gs-zoom-enabled"))
        self.assertFalse(os.path.exists(f"{self.state}/xf-xsettings_Gtk_EnableAnimations"))   # vychozi
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "900")
        self.assertIn("stop luxos-powersaver.service", self.log())
        self.assertFalse(os.path.exists(f"{self.cfg}/luxos/powersaver.saved"))

    def test_animations_from_old_version_restored(self):
        """Sporic z 0.9.11 vypnul animace GTK: pri dalsim zapnuti (reapply) se vrati puvodni hodnota."""
        write(f"{self.cfg}/luxos/powersaver", "")
        write(f"{self.cfg}/luxos/powersaver.saved", "profile=balanced\nanimations=unset\n")
        write(f"{self.state}/xf-xsettings_Gtk_EnableAnimations", "false")
        self.ps("reapply")
        self.assertFalse(os.path.exists(f"{self.state}/xf-xsettings_Gtk_EnableAnimations"))
        self.assertNotIn("animations=", read(f"{self.cfg}/luxos/powersaver.saved"))

    def test_zoom_from_old_version_restored_while_on(self):
        """Sporic do 1.0.x vypnul zvetsovani v Docku: pri reapply (prihlaseni) se vrati hned, i kdyz
        sporic zustava zapnuty; pri dalsim zapnuti/vypnuti uz se zvetsovani nemeni."""
        write(f"{self.cfg}/luxos/powersaver", "")
        write(f"{self.cfg}/luxos/powersaver.saved", "profile=balanced\ndock-zoom=true\n")
        write(f"{self.state}/gs-zoom-enabled", "false")
        self.ps("reapply")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "true")
        self.assertNotIn("dock-zoom=", read(f"{self.cfg}/luxos/powersaver.saved"))
        self.assertIn("profile=balanced", read(f"{self.cfg}/luxos/powersaver.saved"))
        self.ps("on")
        self.ps("off")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "true")
        self.assertEqual(read(f"{self.state}/profile"), "balanced")

    def test_zoom_restore_after_update_and_user_choice_kept(self):
        """restore-zoom (po aktualizaci v bezici relaci): puvodni hodnotu "false" uzivatele zachova,
        bez ulozene hodnoty nic nemeni, starsi soubor dock-zoom take obnovi."""
        write(f"{self.cfg}/luxos/powersaver", "")
        write(f"{self.cfg}/luxos/powersaver.saved", "dock-zoom=false\n")
        write(f"{self.state}/gs-zoom-enabled", "false")
        self.ps("restore-zoom")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "false")
        self.assertNotIn("dock-zoom=", read(f"{self.cfg}/luxos/powersaver.saved"))
        # uzivatel si zvetseni pak zapne sam - nic ho uz nevypne
        write(f"{self.state}/gs-zoom-enabled", "true")
        self.ps("restore-zoom")
        self.ps("reapply")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "true")
        # nejstarsi verze: ~/.config/luxos/dock-zoom, sporic uz vypnuty
        os.unlink(f"{self.cfg}/luxos/powersaver")
        write(f"{self.cfg}/luxos/dock-zoom", "true")
        write(f"{self.state}/gs-zoom-enabled", "false")
        self.ps("reapply")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "true")
        self.assertFalse(os.path.exists(f"{self.cfg}/luxos/dock-zoom"))

    def test_no_backlight_no_error(self):
        """Stolni pocitac bez podsviceni: zapnuti/vypnuti bez chyby "/max_brightness" na stderr."""
        self.env["LUXOS_BACKLIGHT"] = os.path.join(self.d, "no-backlight")
        for cmd in ("on", "off"):
            r = subprocess.run(["bash", os.path.join(BIN, "luxos-powersaver"), cmd], env=self.env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")

    def test_zoom_kept_for_retry_when_gsettings_fails(self):
        """Bez D-Bus (gsettings selze) se ulozena hodnota nesmaze - zkusi se znovu pri prihlaseni."""
        write(f"{self.cfg}/luxos/powersaver.saved", "dock-zoom=true\n")
        write(os.path.join(self.bin, "gsettings"), "#!/bin/bash\nexit 1\n")
        self.ps("restore-zoom")
        self.assertIn("dock-zoom=true", read(f"{self.cfg}/luxos/powersaver.saved"))

    def test_60hz_opt_in(self):
        write(f"{self.cfg}/luxos/powersaver-60hz", "")
        self.ps("on")
        self.assertEqual(self.rate(), ["2560x1600", "60.00"])
        self.ps("off")
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])

    def test_user_brightness_change_kept(self):
        self.ps("on")
        write(f"{self.bl}/bl/brightness", "300")       # uzivatel si jas zmenil sam
        self.ps("off")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "300")

    def test_low_brightness_not_dimmed(self):
        write(f"{self.bl}/bl/brightness", "350")
        self.ps("on")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "350")
        self.ps("off")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "350")

    def test_reapply_after_reboot(self):
        write(f"{self.cfg}/luxos/powersaver-60hz", "")
        self.ps("on")
        # restart: 165 Hz z ulozenych Monitoru, systemova cast pryc
        with open(self.xr) as f:
            st = json.load(f)
        st["outputs"][0]["current"] = ["2560x1600", "165.00"]
        with open(self.xr, "w") as f:
            json.dump(st, f)
        os.unlink(f"{self.state}/log")
        self.ps("reapply")
        self.assertEqual(self.rate(), ["2560x1600", "60.00"])
        self.assertIn("start luxos-powersaver.service", self.log())
        self.ps("off")
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])

    def displays_auto(self):
        """luxos-displays auto jako po prihlaseni (luxos-session): skutecny skript s falesnym xrandr."""
        fake = os.path.join(HERE, "fake-displays")
        write(os.path.join(self.bin, "luxos-powersaver"), f'#!/bin/sh\nexec bash "{BIN}/luxos-powersaver" "$@"\n')
        os.chmod(os.path.join(self.bin, "luxos-powersaver"), 0o755)
        write(f"{self.cfg}/luxos/displays-mode", "extend\n")
        env = dict(self.env, PATH=self.bin + os.pathsep + fake + os.pathsep + os.environ["PATH"],
                   FAKE_XFCONF=os.path.join(self.d, "xfconf.json"), LUXOS_PYDIR=PYDIR)
        r = subprocess.run(["bash", os.path.join(BIN, "luxos-displays"), "auto"], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_login_keeps_rate_without_60hz_opt_in(self):
        """Prihlaseni se zapnutym sporicem bez volby 60 Hz: frekvence displeje se nemeni - zmena by
        uprostred nacitani relace obrazovku na okamzik zcernala (hlaseni 1.0.3, panel 144 Hz)."""
        write(f"{self.cfg}/luxos/powersaver", "")
        self.displays_auto()
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])
        self.ps("reapply")
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])

    def test_login_with_60hz_opt_in_saves_rate_for_off(self):
        """S volbou 60 Hz omezi luxos-displays auto frekvenci jako sporic a vypnuti ji vrati."""
        write(f"{self.cfg}/luxos/powersaver-60hz", "")
        write(f"{self.cfg}/luxos/powersaver", "")
        self.displays_auto()
        self.assertEqual(self.rate(), ["2560x1600", "60.00"])
        self.assertIn("rate-eDP-1=2560x1600 165.00", read(f"{self.cfg}/luxos/powersaver.saved"))
        self.ps("off")
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])

    def test_reapply_off_stops_leftover(self):
        write(f"{self.d}/run/luxos/powersaver", "")
        self.ps("reapply")
        self.assertIn("stop luxos-powersaver.service", self.log())
        os.unlink(f"{self.d}/run/luxos/powersaver")
        os.unlink(f"{self.state}/log")
        self.ps("reapply")
        self.assertEqual(self.log(), "")


class InstallDockZoom(unittest.TestCase):
    """luxos-desktop.install: po aktualizaci se bezicim relacim vrati zvetsovani v Docku, ktere
    vypnul Sporic baterie do 1.0.x - jen tam, kde je ulozena puvodni hodnota."""

    def test_running_sessions(self):
        import socket
        d = tempfile.mkdtemp(prefix="luxos-ps-inst-")
        self.addCleanup(shutil.rmtree, d, True)
        fb, st = os.path.join(d, "bin"), os.path.join(d, "state")
        os.makedirs(st)
        users = {"1000": "anna", "1001": "bob", "1002": "cyril"}
        socks = []
        for uid, name in users.items():
            os.makedirs(f"{d}/run/user/{uid}")
            s = socket.socket(socket.AF_UNIX)
            s.bind(f"{d}/run/user/{uid}/bus")
            socks.append(s)
            os.makedirs(f"{d}/home/{name}/.config/luxos")
            write(f"{st}/gs-{name}", "false")
        self.addCleanup(lambda: [s.close() for s in socks])
        write(f"{d}/home/anna/.config/luxos/powersaver.saved", "profile=balanced\ndock-zoom=true\n")
        write(f"{d}/home/anna/.config/luxos/powersaver", "")           # sporic porad zapnuty
        write(f"{d}/home/bob/.config/luxos/dock-zoom", "true")          # nejstarsi verze
        # cyril: nic ulozeno -> vlastni volba "false" zustava
        fakes = {
            "getent": f'#!/bin/bash\ncase $2 in 1000) n=anna;; 1001) n=bob;; 1002) n=cyril;; *) exit 2;; esac\n'
                      f'echo "$n:x:$2:$2::{d}/home/$n:/bin/bash"\n',
            "runuser": '#!/bin/bash\n[[ $1 == -u && $3 == -- ]] || exit 9\nexport FAKE_USER=$2\nshift 3\nexec "$@"\n',
            "gsettings": f'#!/bin/bash\n[[ $DBUS_SESSION_BUS_ADDRESS == unix:path={d}/run/user/*/bus ]] || exit 1\n'
                         f'[[ $1 == set ]] && echo "$4" >"{st}/gs-$FAKE_USER"\n',
        }
        os.makedirs(fb)
        for name, text in fakes.items():
            write(os.path.join(fb, name), text)
            os.chmod(os.path.join(fb, name), 0o755)
        # v repozitari neni spustitelny (PKGBUILD instaluje s pravy 755)
        write(os.path.join(fb, "luxos-powersaver"),
              f'#!/bin/bash\nexec bash "{os.path.join(BIN, "luxos-powersaver")}" "$@"\n')
        os.chmod(os.path.join(fb, "luxos-powersaver"), 0o755)
        inst = os.path.join(HERE, "..", "luxos-desktop.install")
        env = dict(os.environ, PATH=fb + os.pathsep + os.environ["PATH"], LUXOS_SYSROOT=d,
                   XDG_CONFIG_HOME=os.path.join(d, "root-config"))
        r = subprocess.run(["bash", "-c", f'. "{inst}"; _luxos_dock_zoom'], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(f"{st}/gs-anna"), "true")
        self.assertEqual(read(f"{st}/gs-bob"), "true")
        self.assertEqual(read(f"{st}/gs-cyril"), "false")
        self.assertNotIn("dock-zoom", read(f"{d}/home/anna/.config/luxos/powersaver.saved"))
        self.assertFalse(os.path.exists(f"{d}/home/bob/.config/luxos/dock-zoom"))
        self.assertFalse(os.path.exists(os.path.join(d, "root-config")))
        with open(inst) as f:
            self.assertIn("_luxos_dock_zoom", f.read().split("post_upgrade()")[1].splitlines()[0])


class RateCap(unittest.TestCase):
    def out(self, name, rates, cur, active=True):
        return {"name": name, "connected": True, "active": active,
                "modes": [{"name": "1920x1080", "rates": rates, "current": cur, "preferred": rates[0]}]}

    def test_targets(self):
        self.assertEqual(ld.rate_cap_target(self.out("eDP-1", ["144.00", "120.00", "60.01", "59.95"], "144.00")),
                         ("1920x1080", "144.00", "60.01"))
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["60.02", "48.01"], "60.02")))
        self.assertIsNone(ld.rate_cap_target(self.out("HDMI-1", ["144.00", "60.00"], "144.00")))   # externi ne
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["144.00", "60.00"], "144.00", active=False)))
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["165.00", "120.00"], "165.00")))   # bez 60 Hz


# =====================================================================================
# 3. Soukroma sbernice D-Bus: falesny prehravac MPRIS a xfconfd
# =====================================================================================


if __name__ == "__main__":
    unittest.main()
