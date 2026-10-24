"""Testy programu horni listy v LSL (files/lsl): luxos-clock, luxos-battery, luxos-netcheck,
luxos-cc-toggle, luxos-calendar-toggle, luxos-appname. Vystup musi byt stejny jako u puvodnich
skriptu v bashi (tests/lsl-reference), vcetne prekladu z luxos-i18n (TSV) a vedlejsich ucinku
(Sporic baterie, signaly bezicimu luxos-hub, spusteni nahradniho programu).

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_lsl_tools.py -v
LUXOS_LSLC: cesta k prekladaci lslc (jinak lslc z PATH). Potrebuje LSL >= 0.10.4 (cil linux-x86_64-gnu,
moduly glib/gio); bez nej se testy preskoci. Test luxos-netcheck potrebuje dbus-daemon a python3-gi.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
REF = os.path.join(HERE, "lsl-reference")
I18N_SH = os.path.join(HERE, "..", "..", "luxos-i18n", "files", "i18n.sh")
I18N_DIR = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
PROGRAMS = ["luxos-clock", "luxos-battery", "luxos-netcheck", "luxos-cc-toggle", "luxos-calendar-toggle",
            "luxos-appname"]
TMP = tempfile.mkdtemp(prefix="luxos-lsl-test-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")


def compile_lsl(source, out):
    res = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", source, out], capture_output=True, text=True)
    return res.returncode == 0, res.stderr + res.stdout


def have_gnu_target():
    """Prekladac s moduly glib/gio (LSL 0.10.4): starsi lslc je nema."""
    if not LSLC:
        return False
    src = os.path.join(TMP, "probe.lsl")
    with open(src, "w") as f:
        f.write('load glib, gio\nprint "ok"\n')
    ok, _ = compile_lsl(src, os.path.join(TMP, "probe"))
    return ok


def translation(key):
    with open(os.path.join(I18N_DIR, "cs.tsv"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.rstrip("\n").partition("\t")
            if k == key:
                return v
    raise KeyError(key)


@unittest.skipUnless(have_gnu_target(), "chybi lslc s cilem linux-x86_64-gnu (LSL >= 0.10.4), viz LUXOS_LSLC")
class LslTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = os.path.join(TMP, "bin")
        cls.ref = os.path.join(TMP, "ref")
        cls.fake = os.path.join(TMP, "fake")
        for d in (cls.bin, cls.ref, cls.fake):
            os.makedirs(d, exist_ok=True)
        for p in PROGRAMS:
            ok, log = compile_lsl(os.path.join(LSL, p + ".lsl"), os.path.join(cls.bin, p))
            assert ok, f"{p}: {log}"
            # puvodni skript: preklady z repozitare misto /usr/lib/luxos/i18n.sh
            with open(os.path.join(REF, p)) as f:
                text = f.read().replace("/usr/lib/luxos/i18n.sh", I18N_SH)
            with open(os.path.join(cls.ref, p), "w") as f:
                f.write(text)
            os.chmod(os.path.join(cls.ref, p), 0o755)
        # falesne programy: zapisuji volani do $FAKE_LOG
        for name in ("luxos-powersaver", "notify-send", "luxos-control-center", "luxos-calendar", "xdg-open",
                     "luxos-cc-toggle"):
            path = os.path.join(cls.fake, name)
            with open(path, "w") as f:
                f.write('#!/bin/sh\nprintf "%s\\n" "$0 $*" >>"$FAKE_LOG"\n')
            os.chmod(path, 0o755)

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        self.runtime = os.path.join(self.home, "run")
        self.cfg = os.path.join(self.home, ".config", "luxos")
        os.makedirs(self.runtime)
        os.makedirs(self.cfg)
        self.log = os.path.join(self.home, "calls.log")

    def env(self, lang="cs_CZ.UTF-8", **extra):
        env = {"PATH": self.fake + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home,
               "XDG_RUNTIME_DIR": self.runtime, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
               "LUXOS_I18N_DIR": I18N_DIR, "LANG": lang, "FAKE_LOG": self.log}
        env.update(extra)
        return env

    def run_prog(self, where, prog, *args, lang="cs_CZ.UTF-8", **extra):
        return subprocess.run([os.path.join(where, prog), *args], capture_output=True, text=True,
                              env=self.env(lang, **extra), timeout=10)

    def both(self, prog, *args, **kw):
        """Vystup noveho programu a puvodniho skriptu (musi byt stejny)."""
        new = self.run_prog(self.bin, prog, *args, **kw)
        old = self.run_prog(self.ref, prog, *args, **kw)
        self.assertEqual(new.stdout, old.stdout, f"{prog} {args}: stderr new={new.stderr!r} old={old.stderr!r}")
        self.assertEqual(new.returncode, old.returncode)
        return new.stdout

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [line.split(" ", 1)[1] if " " in line else "" for line in f.read().splitlines()]

    # ---- hodiny ---------------------------------------------------------------------------------
    def test_clock_same_as_bash(self):
        for lang in ("cs_CZ.UTF-8", "en_US.UTF-8", "C"):
            for _ in range(3):   # zmena minuty mezi obema behy
                new = self.run_prog(self.bin, "luxos-clock", lang=lang).stdout
                old = self.run_prog(self.ref, "luxos-clock", lang=lang).stdout
                if new == old:
                    break
            self.assertEqual(new, old, lang)
            self.assertTrue(new.startswith('<txt><span weight="600">'), new)
            self.assertIn("</tool><txtclick>luxos-calendar-toggle</txtclick>\n", new)

    # ---- baterie --------------------------------------------------------------------------------
    def battery(self, name="BAT0", **files):
        supply = tempfile.mkdtemp(prefix="supply-", dir=self.home)
        if name:
            os.makedirs(os.path.join(supply, name))
            for key, value in files.items():
                with open(os.path.join(supply, name, key), "w") as f:
                    f.write(f"{value}\n")
        # puvodni skript ma cestu /sys/class/power_supply napevno
        with open(os.path.join(REF, "luxos-battery")) as f:
            text = f.read().replace("/usr/lib/luxos/i18n.sh", I18N_SH).replace("/sys/class/power_supply", supply)
        with open(os.path.join(self.ref, "luxos-battery"), "w") as f:
            f.write(text)
        return {"LUXOS_POWER_SUPPLY": supply}

    def test_battery_no_battery(self):
        env = self.battery(name=None)
        self.assertEqual(self.both("luxos-battery", **env), "<txt></txt>\n")

    def test_battery_discharging_estimate(self):
        env = self.battery(capacity=57, status="Discharging", energy_now=30000000, energy_full=50000000,
                           power_now=10000000)
        out = self.both("luxos-battery", **env)
        self.assertEqual(out, "<icon>battery-level-60-symbolic</icon><txt> 57 %</txt><tool>57 % · "
                         + translation("On battery") + " · " + translation("%s remaining").replace("%s", "3 h 0 min")
                         + "</tool><iconclick>luxos-cc-toggle</iconclick><txtclick>luxos-cc-toggle</txtclick>"
                         "<scroll>luxos-brightness</scroll>\n")

    def test_battery_charging_minutes(self):
        env = self.battery(capacity=80, status="Charging", energy_now=40000000, energy_full=50000000,
                           power_now=20000000)
        out = self.both("luxos-battery", **env)
        self.assertIn("<icon>battery-level-80-charging-symbolic</icon>", out)
        self.assertIn("30 min", out)
        self.assertIn(translation("Charging"), out)

    def test_battery_full_and_not_charging(self):
        out = self.both("luxos-battery", **self.battery(capacity=100, status="Full"))
        self.assertIn("<icon>battery-level-100-charged-symbolic</icon>", out)
        self.assertIn(translation("Fully charged"), out)
        out = self.both("luxos-battery", **self.battery(capacity=97, status="Not charging"))
        self.assertIn("battery-level-100-charged-symbolic", out)
        out = self.both("luxos-battery", **self.battery(capacity=50, status="Not charging"))
        self.assertIn("<icon>battery-level-50-symbolic</icon>", out)

    def test_battery_charge_units_negative_current(self):
        env = self.battery(capacity=3, status="Discharging", charge_now=500000, charge_full=4000000,
                           current_now=-1000000)
        out = self.both("luxos-battery", **env)
        self.assertIn("<icon>battery-level-0-symbolic</icon><txt> 3 %</txt>", out)
        self.assertIn("30 min", out)

    def test_battery_no_estimate(self):
        # nulovy odber, prilis dlouhy odhad (>= 6000 min) a chybejici soubory: bez casu
        for files in (dict(energy_now=1, energy_full=2, power_now=0),
                      dict(energy_now=90000000, energy_full=90000000, power_now=100),
                      dict(energy_now=1, energy_full=2), {}):
            env = self.battery(capacity=42, status="Discharging", **files)
            out = self.both("luxos-battery", **env)
            self.assertIn("<tool>42 % · " + translation("On battery") + "</tool>", out)

    def test_battery_english_and_unknown_language(self):
        env = self.battery(capacity=42, status="Discharging", energy_now=1000, energy_full=2000, power_now=1000)
        out = self.both("luxos-battery", lang="en_US.UTF-8", **env)
        self.assertIn("42 % · On battery · 1 h 0 min remaining", out)
        out = self.both("luxos-battery", lang="xx_YY.UTF-8", **env)
        self.assertIn("On battery · 1 h 0 min remaining", out)

    def test_battery_saver_flag(self):
        open(os.path.join(self.cfg, "powersaver"), "w").close()
        out = self.both("luxos-battery", **self.battery(capacity=42, status="Discharging"))
        self.assertTrue(out.rstrip("\n").split("</tool>")[0].endswith(" · " + translation("Battery Saver")), out)
        self.assertEqual(self.calls(), [])

    def test_battery_auto_saver(self):
        open(os.path.join(self.cfg, "powersaver-auto"), "w").close()
        mark = os.path.join(self.runtime, "luxos-powersaver-auto-on")
        for where in (self.bin, self.ref):
            env = self.battery(capacity=15, status="Discharging")
            self.run_prog(where, "luxos-battery", **env)
            self.assertTrue(os.path.exists(mark))
            self.assertEqual(self.calls()[:2], ["on", "-i battery-caution -a LuxOS " + translation("Battery Saver is on")
                                                + " " + translation("Battery is at %s %%. Connect the charger.")
                                                .replace("%s", "15").replace("%%", "%")])
            # podruhe uz nic (priznak), po pripojeni nabijecky vypnout a priznak smazat
            self.run_prog(where, "luxos-battery", **env)
            self.assertEqual(len(self.calls()), 2)
            self.run_prog(where, "luxos-battery", **self.battery(capacity=16, status="Charging"))
            self.assertEqual(self.calls(), ["on", self.calls()[1], "off"])
            self.assertFalse(os.path.exists(mark))
            # zapnuty rucne (stav powersaver): automatika nezasahuje
            open(os.path.join(self.cfg, "powersaver"), "w").close()
            self.run_prog(where, "luxos-battery", **self.battery(capacity=10, status="Discharging"))
            self.assertEqual(len(self.calls()), 3)
            os.remove(os.path.join(self.cfg, "powersaver"))
            os.remove(self.log)

    # ---- nazev aplikace -------------------------------------------------------------------------
    def test_appname_print(self):
        self.assertEqual(self.both("luxos-appname", "print"),
                         "<txt></txt><tool>" + translation("Active app: %s").replace("%s", "") + "</tool>\n")
        with open(os.path.join(self.runtime, "luxos-appname"), "w") as f:
            f.write("A&B <x>")
        # Jen novy program: puvodni skript v bashi >= 5.2 vracel "<lt;x>gt;" (& v nahrade ${s//</&lt;}
        # je nalezeny text, patsub_replacement) - neplatny markup, v LSL opraveno
        out = self.run_prog(self.bin, "luxos-appname", "print").stdout
        self.assertEqual(out, "<txt>A&amp;B &lt;x&gt;</txt><tool>"
                         + translation("Active app: %s").replace("%s", "A&amp;B &lt;x&gt;") + "</tool>\n")
        self.assertEqual(self.run_prog(self.bin, "luxos-appname").stdout, out)      # bez argumentu = print
        self.assertIn("<tool>Active app: A&amp;B &lt;x&gt;</tool>",
                      self.run_prog(self.bin, "luxos-appname", lang="C").stdout)
        with open(os.path.join(self.runtime, "luxos-appname"), "w") as f:
            f.write("Soubory")
        self.assertEqual(self.both("luxos-appname", "print"),
                         "<txt>Soubory</txt><tool>" + translation("Active app: %s").replace("%s", "Soubory") + "</tool>\n")

    # ---- prepinace ------------------------------------------------------------------------------
    def fake_process(self, name):
        """Proces, jehoz cmdline obsahuje name (jako python3 /usr/bin/luxos-hub); signaly zapisuje do souboru."""
        path = os.path.join(self.home, name)
        got = os.path.join(self.home, name + ".signals")
        with open(path, "w") as f:
            f.write(f'#!/bin/bash\ntrap "echo USR1 >>{got}" USR1\ntrap "echo USR2 >>{got}" USR2\n'
                    'while :; do sleep 0.05; done\n')
        proc = subprocess.Popen(["bash", path])
        self.addCleanup(proc.kill)
        time.sleep(0.2)
        return proc, got

    def signals(self, path):
        time.sleep(0.3)
        return open(path).read().split() if os.path.exists(path) else []

    def pidfile(self, name, content):
        with open(os.path.join(self.runtime, name), "w") as f:
            f.write(content)

    def test_cc_toggle_signals_hub(self):
        hub, got = self.fake_process("luxos-hub")
        self.pidfile("luxos-control-center.pid", f"{hub.pid}\n")
        for where in (self.bin, self.ref):
            self.assertEqual(self.run_prog(where, "luxos-cc-toggle").returncode, 0)
            time.sleep(0.3)      # bash by dva signaly tesne za sebou spojil do jednoho
        self.assertEqual(self.signals(got), ["USR1", "USR1"])
        self.assertEqual(self.calls(), [])

    def test_cc_toggle_standalone_control_center(self):
        cc, got = self.fake_process("luxos-control-center")
        self.pidfile("luxos-control-center.pid", str(cc.pid))
        self.assertEqual(self.run_prog(self.bin, "luxos-cc-toggle").returncode, 0)
        self.assertEqual(self.signals(got), ["USR1"])

    def test_cc_toggle_starts_control_center(self):
        # bez pid souboru, s neplatnym obsahem, s mrtvym procesem a s cizim procesem: spusti program
        dead = subprocess.Popen(["sleep", "0"])
        dead.wait()
        other, got = self.fake_process("something-else")
        for content in (None, "abc", str(dead.pid), str(other.pid)):
            if content is not None:
                self.pidfile("luxos-control-center.pid", content)
            for where in (self.bin, self.ref):
                self.assertEqual(self.run_prog(where, "luxos-cc-toggle").returncode, 0)
        self.assertEqual(self.calls(), [""] * 8)
        self.assertEqual(self.signals(got), [])

    def test_calendar_toggle(self):
        hub, hub_got = self.fake_process("luxos-hub")
        cal, cal_got = self.fake_process("luxos-calendar")
        for where in (self.bin, self.ref):
            self.pidfile("luxos-calendar.pid", str(hub.pid))
            self.assertEqual(self.run_prog(where, "luxos-calendar-toggle").returncode, 0)
            time.sleep(0.3)
            self.pidfile("luxos-calendar.pid", str(cal.pid))
            self.assertEqual(self.run_prog(where, "luxos-calendar-toggle").returncode, 0)
            time.sleep(0.3)
        self.assertEqual(self.signals(hub_got), ["USR2", "USR2"])
        self.assertEqual(self.signals(cal_got), ["USR1", "USR1"])
        os.remove(os.path.join(self.runtime, "luxos-calendar.pid"))
        for where in (self.bin, self.ref):
            self.assertEqual(self.run_prog(where, "luxos-calendar-toggle").returncode, 0)
        self.assertEqual(self.calls(), ["", ""])     # 2x luxos-calendar

    # ---- internet -------------------------------------------------------------------------------
    def test_netcheck_usage(self):
        res = self.run_prog(self.bin, "luxos-netcheck", "bogus")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stderr, "usage: luxos-netcheck [panel|click]\n")
        self.assertEqual(res.stdout, "")

    @unittest.skipUnless(shutil.which("dbus-daemon"), "chybi dbus-daemon")
    def test_netcheck_states(self):
        try:
            subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Gio', '2.0')"], check=True,
                           capture_output=True)
        except subprocess.CalledProcessError:
            self.skipTest("chybi python3-gi")
        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                               stdout=subprocess.PIPE, text=True)
        self.addCleanup(bus.kill)
        address = bus.stdout.readline().strip()
        self.assertTrue(address, "dbus-daemon bez adresy")
        fake = os.path.join(HERE, "fake-netcheck", "fake-networkmanager.py")
        portal = translation("Sign in to the network to use the internet (click to open the sign-in page)")
        limited = translation("Connected to the network, but the internet is not available")
        icon = "<icon>luxos-network-no-internet-symbolic</icon><tool>%s</tool><iconclick>luxos-netcheck click</iconclick>\n"
        cases = [((70, 4), "<txt></txt>\n"), ((70, 2), icon % portal), ((70, 3), icon % limited),
                 ((60, 1), icon % limited), ((70, 0), "<txt></txt>\n"), ((20, 2), "<txt></txt>\n")]
        env = dict(DBUS_SYSTEM_BUS_ADDRESS=address, DBUS_SESSION_BUS_ADDRESS=address)
        for (state, conn), expected in cases:
            nm = subprocess.Popen([sys.executable, fake, str(state), str(conn)], stdout=subprocess.PIPE, text=True,
                                  env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address))
            self.assertEqual(nm.stdout.readline().strip(), "ready")
            try:
                res = self.run_prog(self.bin, "luxos-netcheck", **env)
                self.assertEqual(res.stdout, expected, (state, conn, res.stderr))
                self.assertEqual(res.returncode, 0)
                res = self.run_prog(self.bin, "luxos-netcheck", "click", **env)
                self.assertEqual(res.returncode, 0)
            finally:
                nm.kill()
                nm.wait()
        # klik: prihlasovaci stranka jen pro portal, jinak Ovladaci centrum
        self.assertEqual(self.calls(), ["", "http://ping.archlinux.org/", "", "", "", ""])
        # anglicky text a NetworkManager, ktery nebezi
        self.assertEqual(self.run_prog(self.bin, "luxos-netcheck", **env).stdout, "<txt></txt>\n")
        nm = subprocess.Popen([sys.executable, fake, "70", "2"], stdout=subprocess.PIPE, text=True,
                              env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address))
        self.addCleanup(nm.kill)
        nm.stdout.readline()
        self.assertEqual(self.run_prog(self.bin, "luxos-netcheck", lang="C", **env).stdout,
                         icon % "Sign in to the network to use the internet (click to open the sign-in page)")

    # ---- preklady -------------------------------------------------------------------------------
    def test_i18n_tsv_rules(self):
        # komentar se preskoci, prazdny preklad = anglicky text, koncove tabulatory pryc, %% je %
        d = tempfile.mkdtemp(prefix="i18n-", dir=self.home)
        with open(os.path.join(d, "cs.tsv"), "w", encoding="utf-8") as f:
            f.write("# komentar\tKOMENTAR\nCharging\tNabíjení!\t\t\nOn battery\t\n"
                    "Battery Saver is on\tŠetřič\nBattery is at %s %%. Connect the charger.\t%s %% baterie\n")
        env = self.battery(capacity=50, status="Charging")
        env["LUXOS_I18N_DIR"] = d
        self.assertIn("<tool>50 % · Nabíjení!</tool>", self.both("luxos-battery", **env))
        env = self.battery(capacity=50, status="Discharging")
        env["LUXOS_I18N_DIR"] = d
        self.assertIn("<tool>50 % · On battery</tool>", self.both("luxos-battery", **env))
        open(os.path.join(self.cfg, "powersaver-auto"), "w").close()
        env = self.battery(capacity=20, status="Discharging")
        env["LUXOS_I18N_DIR"] = d
        self.run_prog(self.bin, "luxos-battery", **env)
        self.assertEqual(self.calls()[1], "-i battery-caution -a LuxOS Šetřič 20 % baterie")


if __name__ == "__main__":
    unittest.main()
