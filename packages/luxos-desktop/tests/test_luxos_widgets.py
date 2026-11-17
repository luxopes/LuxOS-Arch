#!/usr/bin/env python3
"""LuxOS - widgety na plose (files/lsl/luxos-widgets.lsl).

    xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_widgets.py -v

Vlastni domov a vlastni sbernice D-Bus (dbus-run-session); okna jen pod Xvfb (xvfb-run), nikdy
na skutecnem displeji. luxos-weather, luxos-calendar-toggle a luxos-monitor jsou napodoby v PATH.
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
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "lsl", "luxos-widgets.lsl")
PLAYER = os.path.join(HERE, "fake_mpris_player.py")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
BIN = tempfile.mkdtemp(prefix="luxos-widgets-bin-")


def build():
    if not LSLC:
        return False
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", SRC, os.path.join(BIN, "luxos-widgets")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    return True


BUILT = build()

# stara aplikace Pocasi bez datoveho rozhrani: kazde spusteni = otevrene okno (zaznam do logu)
OLD_WEATHER = '#!/bin/sh\necho "weather $*" >> "$FAKE_LOG"\n'
# nova aplikace s "--json"
NEW_WEATHER = r'''#!/bin/sh
# datove rozhrani "--json"
echo "weather $*" >> "$FAKE_LOG"
[ "$1" = "--json" ] || exit 9
echo '{"ok": true, "location": {"name": "Brno"}, "data": {"current": {"temp": -2.6, "code": 71, "is_day": false, "condition": "Snow"}}, "fetched": 4000000000}'
'''


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class Widgets(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-widgets-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home = os.path.join(self.t, "home")
        self.fake = os.path.join(self.t, "fake")
        self.run_dir = os.path.join(self.t, "run")
        for d in (os.path.join(self.home, ".config", "luxos"), self.fake, self.run_dir):
            os.makedirs(d)
        os.chmod(self.run_dir, 0o700)
        self.log = os.path.join(self.t, "calls")
        shutil.copy(os.path.join(BIN, "luxos-widgets"), self.fake)
        self.weather(OLD_WEATHER)
        self.env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        XDG_CACHE_HOME=os.path.join(self.home, ".cache"), XDG_RUNTIME_DIR=self.run_dir,
                        PATH=self.fake + ":" + os.environ["PATH"], FAKE_LOG=self.log, LANG="C",
                        # bez gvfs: v docasne sbernici by zustal bezet gvfsd-fuse s pripojenim v $XDG_RUNTIME_DIR
                        GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1")
        self.procs = []

    def tearDown(self):
        # cela skupina: dbus-run-session, sbernice i widgety pod ni
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            p.wait(timeout=10)

    def weather(self, body):
        p = os.path.join(self.fake, "luxos-weather")
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    def conf(self, text):
        with open(os.path.join(self.home, ".config", "luxos", "widgets.conf"), "w") as f:
            f.write(text)

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def start(self, *args):
        p = subprocess.Popen(["dbus-run-session", "--", os.path.join(self.fake, "luxos-widgets"), *args],
                             env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        self.procs.append(p)
        return p

    def visible(self):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-widgets"],
                           capture_output=True, text=True)
        return r.stdout.split()[0] if r.stdout.strip() else None

    def window(self):
        """Okno widgetu (az 5 s), None kdyz se neukaze."""
        for _ in range(50):
            w = self.visible()
            if w:
                return w
            time.sleep(0.1)
        return None

    def test_disabled_by_default(self):
        p = self.start()
        self.assertEqual(p.wait(timeout=20), 0)
        self.assertIsNone(self.window())

    def test_on_off(self):
        # "on" zapise ENABLED=1 a spusti luxos-widgets z PATH - tady napodoba, ktera spusteni zapise
        real = os.path.join(self.t, "luxos-widgets")
        shutil.move(os.path.join(self.fake, "luxos-widgets"), real)
        with open(os.path.join(self.fake, "luxos-widgets"), "w") as f:
            f.write('#!/bin/sh\necho "spawned $*" >> "$FAKE_LOG"\n')
        os.chmod(os.path.join(self.fake, "luxos-widgets"), 0o755)
        self.assertEqual(subprocess.run([real, "on"], env=self.env, timeout=20).returncode, 0)
        self.assertIn("ENABLED=1", self.read(os.path.join(self.home, ".config", "luxos", "widgets.conf")))
        for _ in range(30):
            if "spawned" in self.read(self.log):
                break
            time.sleep(0.1)
        self.assertIn("spawned \n", self.read(self.log))
        self.assertEqual(subprocess.run([real, "off"], env=self.env, timeout=20).returncode, 0)
        conf = self.read(os.path.join(self.home, ".config", "luxos", "widgets.conf"))
        self.assertIn("ENABLED=0", conf)
        self.assertNotIn("ENABLED=1", conf)

    def test_window_single_instance_and_off_quits(self):
        self.conf("ENABLED=1\nWIDGETS=system,calendar\n")
        p = self.start()
        self.assertIsNotNone(self.window(), "okno widgetu")
        second = self.start()
        self.assertEqual(second.wait(timeout=20), 0, "druha instance hned skonci")
        self.conf("ENABLED=0\n")
        self.assertEqual(p.wait(timeout=20), 0, "vypnuti v nastaveni ukonci bezici widgety")

    def test_old_weather_app_never_started(self):
        """Starsi Pocasi bez --json by s neznamym prepinacem otevrelo okno aplikace."""
        self.conf("ENABLED=1\nWIDGETS=today\n")
        self.start()
        self.assertIsNotNone(self.window())
        time.sleep(1.5)
        self.assertNotIn("weather", self.read(self.log))

    def test_weather_from_json_interface(self):
        self.weather(NEW_WEATHER)
        self.conf("ENABLED=1\nWIDGETS=today\n")
        self.start()
        self.assertIsNotNone(self.window())
        out = os.path.join(self.run_dir, "luxos-widgets-weather.json")
        for _ in range(50):
            if os.path.exists(out):
                break
            time.sleep(0.1)
        self.assertIn("weather --json forecast --days 1 --hours 0", self.read(self.log))
        with open(out) as f:
            self.assertEqual(json.load(f)["location"]["name"], "Brno")

    def windows(self):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "^luxos-widgets$"],
                           capture_output=True, text=True)
        return r.stdout.split()

    def geometry(self, win):
        out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win], capture_output=True, text=True).stdout
        g = dict(line.split("=", 1) for line in out.split() if "=" in line)
        return int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"])

    def wait_for(self, check, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def test_each_widget_own_window_and_remove_closes_it(self):
        self.conf("ENABLED=1\nWIDGETS=system,calendar\n")
        self.start()
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == 2), "jedno okno na widget")
        self.conf("ENABLED=1\nWIDGETS=calendar\n")
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == 1), "odebrany widget zavre sve okno")

    def test_drag_moves_and_remembers_position(self):
        self.conf("ENABLED=1\nWIDGETS=calendar\n")
        self.start()
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == 1))
        time.sleep(0.5)
        x, y, w, h = self.geometry(self.windows()[0])
        sx, sy = x + w // 2, y + h // 2
        subprocess.run(["xdotool", "mousemove", str(sx), str(sy), "mousedown", "1"])
        for i in range(1, 11):
            subprocess.run(["xdotool", "mousemove", str(sx - i * 30), str(sy + i * 20)])
            time.sleep(0.03)
        subprocess.run(["xdotool", "mouseup", "1"])
        path = os.path.join(self.home, ".config", "luxos", "widgets.conf")
        self.assertTrue(self.wait_for(lambda: "POS_calendar=" in self.read(path)), self.read(path))
        pos = [l for l in self.read(path).splitlines() if l.startswith("POS_calendar=")][0][13:].split(",")
        self.assertEqual([int(v) % 8 for v in pos], [0, 0], "pozice na mrizce 8 px")
        # po pusteni se karta jeste dorovna na mrizku: pockat, az se poloha ustali
        last = None
        for _ in range(30):
            cur = self.geometry(self.windows()[0])
            if cur == last:
                break
            last = cur
            time.sleep(0.2)
        nx, ny, _w, _h = last
        self.assertLess(nx, x - 200)
        self.assertGreater(ny, y + 150)
        # klik bez pohybu karta nepresune a spusti akci (Kalendar)
        self.script("luxos-calendar-toggle", '#!/bin/sh\necho calendar >> "$FAKE_LOG"\n')
        subprocess.run(["xdotool", "mousemove", str(nx + w // 2), str(ny + h // 2), "click", "1"])
        self.assertTrue(self.wait_for(lambda: "calendar" in self.read(self.log)))
        self.assertEqual(self.geometry(self.windows()[0])[:2], (nx, ny))

    def test_gallery_add_and_remove(self):
        self.conf("ENABLED=1\nWIDGETS=system\n")
        self.start("settings")
        r = None
        for _ in range(50):
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-widgets-settings"],
                               capture_output=True, text=True).stdout.split()
            if r:
                break
            time.sleep(0.1)
        self.assertTrue(r, "okno galerie")
        path = os.path.join(self.home, ".config", "luxos", "widgets.conf")
        self.assertIn("WIDGETS=system", self.read(path), "galerie sama nic nemeni")

    # ---- karta Hudba (napodoba prehravace MPRIS, jako Firefox) --------------------------------

    def start_music(self, widgets="today,music,system"):
        """Napodoba prehravace a widgety na stejne docasne sbernici; vraci PID napodoby."""
        self.conf("ENABLED=1\nWIDGETS=%s\n" % widgets)
        self.env["LUXOS_WIDGETS_MUSIC_GRACE"] = "2"
        pidfile = os.path.join(self.t, "player.pid")
        script = ('python3 %s & echo $! > %s; sleep 0.5; exec %s'
                  % (shlex.quote(PLAYER), shlex.quote(pidfile), shlex.quote(os.path.join(self.fake, "luxos-widgets"))))
        p = subprocess.Popen(["dbus-run-session", "--", "sh", "-c", script], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        self.assertTrue(self.wait_for(lambda: self.read(pidfile).strip() != ""))
        n = len(widgets.split(","))
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == n, 10), "karta Hudba se ukaze")
        time.sleep(0.6)
        return int(self.read(pidfile))

    def positions(self):
        """{vyska okna: (x, y)} - karty se lisi vyskou (Hudba je nejnizsi)."""
        out = {}
        for w in self.windows():
            x, y, _w, h = self.geometry(w)
            out[h] = (x, y)
        return out

    def music_window(self):
        wins = sorted(self.windows(), key=lambda w: self.geometry(w)[3])
        return wins[0] if wins else None

    def calls(self):
        return [l.split(" call ", 1)[1] for l in self.read(self.log).splitlines() if " call " in l]

    def click_play(self):
        x, y, _w, h = self.geometry(self.music_window())
        # Prehrat/Pozastavit: druhe tlacitko zprava (okraj okna 24, karta 18, Dalsi 32, mezera 12)
        subprocess.run(["xdotool", "mousemove", str(x + 238), str(y + (h - 26) // 2), "click", "1"])

    def test_music_card_appearing_never_moves_other_cards(self):
        pid = self.start_music()
        before = self.positions()
        self.assertEqual(len(before), 3)
        music_h = min(before)
        others = {h: xy for h, xy in before.items() if h != music_h}
        # prehravac odejde (Firefox zavrel stranku): karta Hudba zmizi po chvili, ostatni stoji
        os.kill(pid, signal.SIGUSR1)
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == 2, 8), "karta Hudba zmizi")
        time.sleep(0.5)
        self.assertEqual(self.positions(), others, "ostatni karty se po skryti Hudby nehnou")
        # prehravac se vrati: Hudba na svem puvodnim miste, ostatni porad stoji
        os.kill(pid, signal.SIGUSR2)
        self.assertTrue(self.wait_for(lambda: len(self.windows()) == 3, 8), "karta Hudba se vrati")
        time.sleep(0.8)
        self.assertEqual(self.positions(), before)

    def test_player_reregistering_keeps_music_card(self):
        """Firefox odhlasi a hned znovu prihlasi nazev MPRIS (nova stranka/media) - karta nemrka."""
        pid = self.start_music()
        os.kill(pid, signal.SIGUSR1)
        for _ in range(8):
            self.assertEqual(len(self.windows()), 3, "karta Hudba zustava videt i bez prehravace")
            time.sleep(0.1)
        os.kill(pid, signal.SIGUSR2)
        for _ in range(25):
            self.assertEqual(len(self.windows()), 3, "karta Hudba zustava videt")
            time.sleep(0.1)

    def test_play_button_sends_what_it_shows(self):
        pid = self.start_music()
        self.click_play()            # hraje -> ikona Pozastavit
        self.assertTrue(self.wait_for(lambda: self.calls() == ["Player Pause"]), self.calls())
        time.sleep(0.5)
        self.click_play()            # pozastaveno -> ikona Prehrat
        self.assertTrue(self.wait_for(lambda: self.calls() == ["Player Pause", "Player Play"]), self.calls())
        # prehravac se pozastavi sam (stranka, jine ovladani): klik na Prehrat ho pusti, nikdy nezastavi
        time.sleep(0.5)
        os.kill(pid, signal.SIGHUP)
        time.sleep(0.8)
        self.click_play()
        self.assertTrue(self.wait_for(lambda: len(self.calls()) == 3), self.calls())
        self.assertEqual(self.calls()[2], "Player Play")
        self.assertNotIn("Player PlayPause", self.calls())

    def test_card_moved_by_someone_else_returns(self):
        """Spravce oken (umisteni pri namapovani, restart) kartu presune - vrati se na sve misto."""
        self.start_music()
        before = self.positions()
        tallest = max(before)
        win = [w for w in self.windows() if self.geometry(w)[3] == tallest][0]
        subprocess.run(["xdotool", "windowmove", win, "300", "500"])
        self.assertTrue(self.wait_for(lambda: self.geometry(win)[:2] == (300, 500), 3))
        self.assertTrue(self.wait_for(lambda: self.positions() == before, 8), self.positions())
        path = os.path.join(self.home, ".config", "luxos", "widgets.conf")
        self.assertNotIn("POS_", self.read(path), "nic se neulozi")

    def script(self, name, body):
        p = os.path.join(self.fake, name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)


if __name__ == "__main__":
    unittest.main()
