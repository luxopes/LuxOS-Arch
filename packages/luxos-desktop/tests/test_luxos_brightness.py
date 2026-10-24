#!/usr/bin/env python3
"""LuxOS - jas kolecko mysi nad baterii v horni liste: luxos-brightness a patch xfce4-genmon-plugin.

  python3 -m unittest packages/luxos-desktop/tests/test_luxos_brightness.py -v
  env -u DISPLAY xvfb-run -a -s "-screen 0 1024x600x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_brightness.py -v

luxos-brightness bezi nad falesnym podsvicenim (LUXOS_BACKLIGHT) s falesnym brightnessctl,
notify-send a luxos-displays v PATH - na skutecny jas ani oznameni nesahne.

Cast pod Xvfb spusti skutecny xfce4-panel (soukroma sbernice D-Bus, HOME v docasne slozce)
s pluginem genmon v procesu panelu jako v LuxOS (/usr/lib/luxos/panel) a s vystupem baterie
s <iconclick>/<txtclick> (ikona a text jsou tlacitka) a <scroll>luxos-brightness</scroll>,
a kolecko mysi pres xdotool nad ikonou i textem musi zmenit falesny jas. Potrebuje xfce4-panel,
dbus-daemon, xdotool a libgenmon.so s patchem LuxOS: LUXOS_GENMON_SO=/cesta/libgenmon.so
(napr. z packages/xfce4-genmon-plugin/pkg), jinak /usr/lib/xfce4/panel/plugins/libgenmon.so,
pokud obsahuje <scroll>. Nikdy na skutecne obrazovce.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
BIN = os.path.join(FILES, "bin")
BRIGHTNESS = os.path.join(BIN, "luxos-brightness")
GENMON_DESKTOP = os.path.join(FILES, "panel-plugins", "genmon.desktop")

UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")

FAKES = {
    # brightnessctl nad falesnym podsvicenim: get / max / -q set N%
    "brightnessctl": r'''#!/bin/bash
b=$(ls -d "$LUXOS_BACKLIGHT"/* | head -n1)
echo "$*" >> "$LOG/brightnessctl"
case $1 in
    get) cat "$b/brightness" ;;
    max) cat "$b/max_brightness" ;;
    -q) v=${3%\%}; echo $(( v * $(cat "$b/max_brightness") / 100 )) > "$b/brightness" ;;
    *) exit 1 ;;
esac
''',
    "notify-send": '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG/notify-send"\n',
    "luxos-displays": '#!/bin/bash\necho "$*" >> "$LOG/luxos-displays"\n',
}


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read().strip()


class FakeSystem:
    """Docasna slozka s falesnym podsvicenim, prikazy v PATH a protokolem volani."""

    def __init__(self, backlight=True):
        self.dir = tempfile.mkdtemp(prefix="luxos-brightness-test-")
        self.bl = os.path.join(self.dir, "backlight")
        self.log = os.path.join(self.dir, "log")
        self.fake = os.path.join(self.dir, "bin")
        os.makedirs(self.bl)
        os.makedirs(self.log)
        if backlight:
            write(os.path.join(self.bl, "intel_backlight", "max_brightness"), "1000")
            write(os.path.join(self.bl, "intel_backlight", "brightness"), "500")
        for name, body in FAKES.items():
            write(os.path.join(self.fake, name), body, 0o755)
        os.symlink(os.path.abspath(BRIGHTNESS), os.path.join(self.fake, "luxos-brightness"))
        self.env = dict(os.environ, LUXOS_BACKLIGHT=self.bl, LOG=self.log, HOME=self.dir,
                        XDG_CONFIG_HOME=os.path.join(self.dir, "config"),
                        PATH=self.fake + ":" + os.environ.get("PATH", "/usr/bin"))

    @property
    def raw(self):
        return int(read(os.path.join(self.bl, "intel_backlight", "brightness")))

    @raw.setter
    def raw(self, value):
        write(os.path.join(self.bl, "intel_backlight", "brightness"), str(value))

    def logged(self, name):
        try:
            with open(os.path.join(self.log, name)) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestBrightnessScript(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSystem()
        self.addCleanup(self.fs.cleanup)

    def run_b(self, *args, fs=None):
        fs = fs or self.fs
        return subprocess.run(["bash", BRIGHTNESS, *args], env=fs.env, capture_output=True, text=True, timeout=20)

    def test_up_and_down_by_5_percent(self):
        self.assertEqual(self.run_b("up").returncode, 0)
        self.assertEqual(self.fs.raw, 550)
        self.run_b("down")
        self.run_b("down")
        self.assertEqual(self.fs.raw, 450)

    def test_limits(self):
        self.fs.raw = 120                       # 12 % -> nejmene 10 %
        self.run_b("down")
        self.assertEqual(self.fs.raw, 100)
        self.run_b("down")
        self.assertEqual(self.fs.raw, 100)
        self.fs.raw = 980                       # 98 % -> 100 %
        self.run_b("up")
        self.assertEqual(self.fs.raw, 1000)
        self.run_b("up")
        self.assertEqual(self.fs.raw, 1000)

    def test_bad_argument(self):
        r = self.run_b("sideways")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.fs.logged("brightnessctl"), [])
        self.assertEqual(self.run_b().returncode, 2)

    def test_osd_notification_is_transient(self):
        """Ukazatel jasu nahrazuje predchozi a neuklada se do historie oznameni (-e)."""
        self.run_b("up")
        n = self.fs.logged("notify-send")
        self.assertEqual(len(n), 1)
        self.assertIn("-e", n[0].split())
        self.assertIn("int:value:55", n[0])
        self.assertIn("string:x-canonical-private-synchronous:luxos-brightness", n[0])

    def test_brightnessctl_failure(self):
        write(os.path.join(self.fs.fake, "brightnessctl"), "#!/bin/sh\nexit 1\n", 0o755)
        self.assertEqual(self.run_b("up").returncode, 1)
        self.assertEqual(self.fs.logged("notify-send"), [])

    def test_without_backlight_software_brightness(self):
        fs = FakeSystem(backlight=False)
        self.addCleanup(fs.cleanup)
        self.assertEqual(self.run_b("down", fs=fs).returncode, 0)
        self.assertEqual(read(os.path.join(fs.dir, "config", "luxos", "brightness")), "95")
        self.assertEqual(fs.logged("luxos-displays"), ["brightness 95"])
        self.assertEqual(fs.logged("brightnessctl"), [])


def patched_genmon():
    so = os.environ.get("LUXOS_GENMON_SO") or "/usr/lib/xfce4/panel/plugins/libgenmon.so"
    try:
        with open(so, "rb") as f:
            return os.path.abspath(so) if b"<scroll>" in f.read() else None
    except OSError:
        return None


GENMON = patched_genmon()


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
@unittest.skipUnless(shutil.which("xfce4-panel") and shutil.which("dbus-daemon") and shutil.which("xdotool"),
                     "needs xfce4-panel, dbus-daemon and xdotool")
@unittest.skipUnless(GENMON, "needs libgenmon.so with the LuxOS <scroll> patch (LUXOS_GENMON_SO)")
class TestGenmonScroll(unittest.TestCase):
    """Kolecko nad baterii v horni liste (genmon v procesu panelu) zmeni jas."""

    BATTERY = ("<icon>battery-good-symbolic</icon><txt> 85 %%</txt><tool>85 %%</tool>"
               "<iconclick>%s</iconclick><txtclick>%s</txtclick><scroll>luxos-brightness</scroll>")

    def setUp(self):
        self.fs = FakeSystem()
        self.addCleanup(self.fs.cleanup)
        d = self.fs.dir
        # Plugin genmon v procesu panelu jako v LuxOS: <prefix>/share/xfce4/panel/plugins/*.desktop
        # z XDG_DATA_DIRS a modul z <prefix>/lib/... (Arch /usr/lib, Debian /usr/lib/<multiarch>)
        prefix = os.path.join(d, "panel")
        os.makedirs(os.path.join(prefix, "share", "xfce4", "panel", "plugins"))
        shutil.copy(GENMON_DESKTOP, os.path.join(prefix, "share", "xfce4", "panel", "plugins"))
        for lib in ("lib", os.path.join("lib", "x86_64-linux-gnu")):
            p = os.path.join(prefix, lib, "xfce4", "panel", "plugins")
            os.makedirs(p)
            os.symlink(GENMON, os.path.join(p, "libgenmon.so"))
        self.clicked = os.path.join(d, "clicked")
        write(os.path.join(self.fs.fake, "luxos-battery"),
              "#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % (self.BATTERY % (("touch " + self.clicked,) * 2)), 0o755)
        write(os.path.join(d, "config", "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-panel.xml"), """\
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=6;x=0;y=0"/>
      <property name="length" type="uint" value="100"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="30"/>
      <property name="plugin-ids" type="array"><value type="int" value="10"/></property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-10" type="string" value="genmon">
      <property name="command" type="string" value="luxos-battery"/>
      <property name="update-period" type="int" value="20000"/>
      <property name="use-label" type="bool" value="false"/>
      <property name="enable-single-row" type="bool" value="true"/>
    </property>
  </property>
</channel>
""")
        run = os.path.join(d, "run")
        os.makedirs(run, mode=0o700)
        env = dict(self.fs.env, XDG_DATA_DIRS=os.path.join(prefix, "share") + ":/usr/share",
                   XDG_CACHE_HOME=os.path.join(d, "cache"), XDG_DATA_HOME=os.path.join(d, "data"),
                   XDG_RUNTIME_DIR=run, NO_AT_BRIDGE="1", GTK_A11Y="none")
        env.pop("SESSION_MANAGER", None)
        # Soukroma sbernice: xfconfd se aktivuje s timto prostredim (HOME/XDG_CONFIG_HOME v TMP)
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        out = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
                             env=env, capture_output=True, text=True, timeout=20).stdout.split()
        self.bus_pid = int(out[1])
        self.addCleanup(self.kill_bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = out[0]
        self.panel = subprocess.Popen(["xfce4-panel", "--disable-wm-check"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_panel)
        for _ in range(100):
            if subprocess.run(["xdotool", "search", "--class", "xfce4-panel"], capture_output=True).stdout:
                break
            time.sleep(0.1)
        time.sleep(2)
        with open("/proc/%d/maps" % self.panel.pid) as f:
            maps = f.read()
        # genmon v procesu panelu (ne externi wrapper-2.0 s jinym modulem)
        self.assertIn(os.path.realpath(GENMON), maps, "genmon is not loaded inside the panel")

    def kill_bus(self):
        try:
            os.kill(self.bus_pid, 15)
        except OSError:
            pass

    def stop_panel(self):
        if self.panel.poll() is None:
            self.panel.terminate()
            try:
                self.panel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.panel.kill()

    def move(self, x):
        # Xvfb: prvni presun ukazatele po startu serveru se nekdy ztrati - opakovat do potvrzeni
        for _ in range(20):
            subprocess.run(["xdotool", "mousemove", str(x), "15"], timeout=10)
            time.sleep(0.1)
            loc = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
            if loc.startswith("x:%d y:15 " % x):
                return
            subprocess.run(["xdotool", "mousemove", str(x + 1), "16"], timeout=10)
        self.fail("pointer did not move")

    def scroll(self, x, button, times=1):
        self.move(x)
        time.sleep(0.2)
        for _ in range(times):
            subprocess.run(["xdotool", "click", str(button)], timeout=10)
            time.sleep(0.3)
        time.sleep(0.5)

    def test_scroll_over_icon(self):
        self.scroll(14, 4)                      # kolecko nahoru nad ikonou (tlacitko <iconclick>)
        self.assertEqual(self.fs.raw, 550)
        self.scroll(14, 5, 2)
        self.assertEqual(self.fs.raw, 450)

    def test_scroll_over_percentage(self):
        self.scroll(48, 5)                      # nad textem "85 %" (tlacitko <txtclick>)
        self.assertEqual(self.fs.raw, 450)

    def test_click_still_works(self):
        self.move(14)
        subprocess.run(["xdotool", "click", "1"], timeout=10)
        for _ in range(30):
            if os.path.exists(self.clicked):
                break
            time.sleep(0.1)
        self.assertTrue(os.path.exists(self.clicked))
        self.assertEqual(self.fs.raw, 500)


if __name__ == "__main__":
    unittest.main()
