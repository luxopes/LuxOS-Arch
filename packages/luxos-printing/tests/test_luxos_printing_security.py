"""Tiskarny z neovereneho mDNS a opravneni pomocnika (luxos_printing, luxos-printing-helper, polkit).

- ohlaseni ze site: UUID jen ve tvaru UUID (nic dalsiho se nedostane do dnssd:// URI), nazvy DNS-SD,
  jen domena local, zname typy sluzeb, porty; text pro CUPS bez ridicich znaku
- sync sam pridava jen IPP Everywhere a nejvys AUTO_PER_HOUR / AUTO_MAX front, ovladace nikdy kvuli siti
- odebrani fronty a zruseni cizi ulohy pres pkexec jen s heslem spravce (luxos-printing-admin)
- luxos-printing-watch: nejvys jeden sync za LUXOS_PRINTING_WATCH_MIN_GAP s i pri zaplave ohlaseni

Spusteni: python3 -m unittest discover -s packages/luxos-printing/tests -v
Skutecneho CUPS, avahi ani polkitu se testy nedotknou; docasne soubory jsou v out/ repozitare.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
import luxos_printing as lp  # noqa: E402

GOOD_UUID = "3cf9787f-057b-317d-4660-aa66ee44b2b8"


def tmpdir():
    base = os.path.join(ROOT, "out", "test-printing")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(dir=base)


def avahi_line(name, txt, stype="_ipp._tcp", domain="local", port="631", iface="wlan0"):
    esc = name.replace(";", "\\059").replace(" ", "\\032")       # \NNN uz v nazvu nechat (escapovani avahi)
    return f"=;{iface};IPv4;{esc};{stype};{domain};p.local;10.0.0.9;{port};{txt}"


DRIVERLESS = '"pdl=application/pdf,image/urf" "URF=W8" "ty=Test Printer"'


class MdnsValidation(unittest.TestCase):
    def test_clean_uuid(self):
        self.assertEqual(lp.clean_uuid(GOOD_UUID.upper()), GOOD_UUID)
        self.assertEqual(lp.clean_uuid("urn:uuid:" + GOOD_UUID), GOOD_UUID)
        for bad in ("", None, GOOD_UUID + "&contimeout=1", GOOD_UUID + "/x", "x" * 36, GOOD_UUID[:-1],
                    "../../" + GOOD_UUID, GOOD_UUID + "\nx", "{" + GOOD_UUID + "}"):
            self.assertIsNone(lp.clean_uuid(bad), bad)
        self.assertEqual(lp.clean_uuid(f" {GOOD_UUID}\n"), GOOD_UUID)        # okolni mezery nevadi

    def test_uuid_injection_does_not_reach_uri(self):
        txt = f'"UUID={GOOD_UUID}&contimeout=1&x=/../" {DRIVERLESS}'
        g = lp.group_printers(lp.parse_avahi(avahi_line("Evil", txt)))
        (p,) = g.values()
        self.assertIsNone(p["uuid"])
        self.assertEqual(p["key"], "dnssd:Evil")
        self.assertEqual(p["uri"], "dnssd://Evil._ipp._tcp.local/")
        self.assertTrue(lp.valid_dnssd_uri(p["uri"]))

    def test_valid_uuid_in_uri(self):
        g = lp.group_printers(lp.parse_avahi(avahi_line("Good One", f'"UUID={GOOD_UUID.upper()}" {DRIVERLESS}')))
        (p,) = g.values()
        self.assertEqual(p["uri"], f"dnssd://Good%20One._ipp._tcp.local/?uuid={GOOD_UUID}")
        self.assertTrue(lp.valid_dnssd_uri(p["uri"]))
        self.assertEqual(lp.uri_uuid(p["uri"]), GOOD_UUID)

    def test_name_is_fully_encoded(self):
        name = "a/b?c#d&e=f%g'h\"i`j$(k)"
        uri = lp.dnssd_uri(name, "_ipp._tcp", GOOD_UUID)
        self.assertTrue(lp.valid_dnssd_uri(uri))
        self.assertEqual(lp.uri_service_name(uri), name)
        with self.assertRaises(ValueError):
            lp.dnssd_uri("x", "_ipp._tcp.example.com/../_ipp._tcp")
        with self.assertRaises(ValueError):
            lp.dnssd_uri("x", "_ipp._tcp", domain="evil.example")

    def test_valid_dnssd_uri_rejects_other_shapes(self):
        for bad in (f"dnssd://x._ipp._tcp.local/?uuid={GOOD_UUID}&contimeout=1", "dnssd://x._ipp._tcp.example/",
                    "ipp://10.0.0.1/ipp/print", "dnssd://x y._ipp._tcp.local/", "dnssd://x._ipp._tcp.local/\n",
                    "socket://10.0.0.1:9100", "", None, "dnssd://x._smb._tcp.local/"):
            self.assertFalse(lp.valid_dnssd_uri(bad), bad)

    def test_bad_records_are_dropped(self):
        lines = [
            avahi_line("ok", DRIVERLESS),
            avahi_line("x" * 64, DRIVERLESS),                       # nazev delsi nez 63 bajtu
            avahi_line("č" * 32, DRIVERLESS),                       # 64 bajtu UTF-8
            avahi_line("bad\\010name", DRIVERLESS),                 # ridici znak (\010 = backspace)
            avahi_line("wide", DRIVERLESS, domain="example.com"),
            avahi_line("smb", DRIVERLESS, stype="_smb._tcp"),
            avahi_line("port0", DRIVERLESS, port="0"),
            avahi_line("port70000", DRIVERLESS, port="70000"),
        ]
        names = [s["name"] for s in lp.parse_avahi("\n".join(lines))]
        self.assertEqual(names, ["ok"])
        self.assertEqual([s["name"] for s in lp.parse_avahi(avahi_line("č" * 31, DRIVERLESS))], ["č" * 31])

    def test_text_for_cups_is_clean(self):
        self.assertEqual(lp.friendly_name("HP\nInfo Evil\r\n<Printer x>"), "HP Info Evil <Printer x>")
        self.assertEqual(lp.clean_text("a\x00b‮c d"), "a b c d")
        self.assertEqual(len(lp.clean_text("x" * 500)), 127)
        g = lp.group_printers(lp.parse_avahi(avahi_line("m", '"ty=Model\\010X" "pdl=application/pdf"')))
        self.assertEqual(next(iter(g.values()))["model"], "Model X")

    def test_rp(self):
        self.assertEqual(lp.clean_rp("ipp/print"), "ipp/print")
        self.assertEqual(lp.clean_rp("/ipp/print"), "ipp/print")
        for bad in ("../../etc", "ipp/print?x=1", "a b", "ipp/print\n", "x" * 200):
            self.assertEqual(lp.clean_rp(bad), "ipp/print", bad)


def load_helper(tmp):
    os.environ["LUXOS_PRINTING_NOTIFY_LOG"] = os.path.join(tmp, "notify")
    os.environ["LUXOS_PRINTING_STATE"] = os.path.join(tmp, "state.json")
    os.environ["LUXOS_PRINTING_LOCK"] = os.path.join(tmp, "lock")
    path = os.path.join(FILES, "luxos-printing-helper")
    loader = importlib.machinery.SourceFileLoader("luxos_printing_helper_sec", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    h = importlib.util.module_from_spec(spec)
    loader.exec_module(h)
    return h


class HelperBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir()
        self.h = h = load_helper(self.tmp)
        self.services = []
        self.cmds, self.installs = [], []
        self.queues = {}
        h.cups_queues = lambda: dict(self.queues)
        h.cups_default = lambda: "x"
        h.usb_printers = lambda: []
        h.usb_scanners = lambda: {}
        h.browse = lambda types: [s for s in self.services if s["type"] in types]
        h.models = lambda: []
        h.installed = lambda pkg: False
        h.available = lambda pkg: True
        h.drivers_index = lambda: {}
        h.auto_resume = lambda st, event=False, services=None: []

        def install(pkg):
            self.installs.append(pkg)
            return True
        h.install_driver = install

        def run(cmd, timeout=60):
            self.cmds.append(cmd)
            if cmd[:2] == ["lpadmin", "-p"]:
                self.queues[cmd[2]] = cmd[cmd.index("-v") + 1]
            return 0, "", ""
        h.run = run

    def tearDown(self):
        for k in ("LUXOS_PRINTING_NOTIFY_LOG", "LUXOS_PRINTING_STATE", "LUXOS_PRINTING_LOCK", "PKEXEC_UID"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def announce(self, n, driverless=True, prefix="Net Printer"):
        for i in range(n):
            uuid = f"00000000-0000-4000-8000-{i:012d}"
            txt = f'"UUID={uuid}" ' + (DRIVERLESS if driverless else '"pdl=application/vnd.hp-PCL" "ty=Old"')
            self.services += lp.parse_avahi(avahi_line(f"{prefix} {i}", txt))

    def added(self):
        return [c for c in self.cmds if c[:2] == ["lpadmin", "-p"]]


class AutoAdd(HelperBase):
    def test_flood_is_rate_limited(self):
        self.announce(30)
        st = self.h.load_state()
        self.h.cmd_sync(st)
        self.assertEqual(len(self.added()), self.h.AUTO_PER_HOUR)
        self.h.cmd_sync(st)                                  # stejna hodina: nic dalsiho
        self.assertEqual(len(self.added()), self.h.AUTO_PER_HOUR)
        # po hodine dalsi davka, celkem ale nejvys AUTO_MAX
        for _ in range(10):
            st["auto_net"] = [t - 3601 for t in st["auto_net"]]
            self.h.cmd_sync(st)
        self.assertEqual(len(self.added()), self.h.AUTO_MAX)
        for c in self.added():
            self.assertIn("everywhere", c)
            self.assertTrue(lp.valid_dnssd_uri(c[c.index("-v") + 1]))

    def test_user_can_still_add_beyond_limit(self):
        self.announce(self.h.AUTO_PER_HOUR + 1)
        st = self.h.load_state()
        self.h.cmd_sync(st)
        last = f"uuid:00000000-0000-4000-8000-{self.h.AUTO_PER_HOUR:012d}"
        self.assertEqual(self.h.cmd_sync(st, only_key=last), [f"Net_Printer_{self.h.AUTO_PER_HOUR}"])

    def test_network_printer_never_installs_drivers(self):
        self.announce(3, driverless=False)
        st = self.h.load_state()
        self.assertEqual(self.h.cmd_sync(st), [])
        self.assertEqual(self.added(), [])
        self.assertEqual(self.installs, [])
        # ani rucni pridani sitove tiskarny bez IPP Everywhere ovladac neinstaluje
        self.h.cmd_sync(st, only_key="uuid:00000000-0000-4000-8000-000000000000")
        self.assertEqual(self.installs, [])

    def test_unexpected_uri_is_not_added(self):
        dev = {"key": "k", "name": "X", "model": "X", "usb": False, "driverless": True,
               "uri": f"dnssd://X._ipp._tcp.local/?uuid={GOOD_UUID}&contimeout=1"}
        self.assertEqual(self.h.create_queue(dev, {}), (None, "manual"))
        # "classic" z ohlaseni (ne z backendu usb) nic neodemkne
        dev2 = dict(dev, classic=True, device_id="MFG:HP;MDL:X;", uri="socket://10.0.0.1:9100")
        self.assertEqual(self.h.create_queue(dev2, {}), (None, "manual"))
        self.assertEqual(self.added(), [])
        self.assertEqual(self.installs, [])

    def test_control_chars_never_reach_lpadmin(self):
        self.services += lp.parse_avahi(avahi_line("Nice\\013Printer", DRIVERLESS))   # \013 = CR: zahozeno
        self.services += lp.parse_avahi(avahi_line("Fine (A1B2C3)", '"ty=T\\010" "pdl=application/pdf"'))
        st = self.h.load_state()
        self.h.cmd_sync(st)
        (c,) = self.added()
        self.assertEqual(c[c.index("-D") + 1], "Fine")
        for arg in c:
            self.assertFalse(any(ord(ch) < 32 for ch in arg), arg)


class Privileges(HelperBase):
    def main(self, argv, pkexec=False, admin=False):
        if pkexec:
            os.environ["PKEXEC_UID"] = "1000"
        self.h.ADMIN_ENTRY = admin
        geteuid, os.geteuid = os.geteuid, lambda: 0
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = self.h.main(argv)
        finally:
            os.geteuid = geteuid
            os.environ.pop("PKEXEC_UID", None)
        return rc, err.getvalue()

    def test_remove_and_cancel_need_admin_via_pkexec(self):
        self.queues["Office"] = "dnssd://Office._ipp._tcp.local/"
        for argv in (["remove", "Office"], ["cancel", "42"]):
            rc, err = self.main(argv, pkexec=True)
            self.assertEqual(rc, 4, argv)
            self.assertIn("administrator", err)
        self.assertEqual(self.cmds, [])                       # nic se nespustilo
        self.assertEqual(self.main(["remove", "Office"], pkexec=True, admin=True)[0], 0)
        self.assertIn(["lpadmin", "-x", "Office"], self.cmds)
        self.assertEqual(self.main(["cancel", "42"], pkexec=True, admin=True)[0], 0)
        self.assertIn(["cancel", "42"], self.cmds)

    def test_root_services_keep_full_access(self):
        self.queues["Office"] = "dnssd://Office._ipp._tcp.local/"
        self.assertEqual(self.main(["remove", "Office"])[0], 0)
        self.assertEqual(self.main(["cancel", "7"])[0], 0)

    def test_common_actions_stay_password_free(self):
        self.queues["Office"] = "dnssd://Office._ipp._tcp.local/"
        for argv in (["default", "Office"], ["resume", "Office"], ["discover"], ["sync"]):
            self.assertEqual(self.main(argv, pkexec=True)[0], 0, argv)

    def test_queue_argument_validated(self):
        for bad in ("-x", "a b", "a/b", "", "x" * 200, "a#b"):
            rc, _err = self.main(["remove", bad], pkexec=True, admin=True)
            self.assertEqual(rc, 2, bad)
            rc, _err = self.main(["default", bad], pkexec=True)
            self.assertEqual(rc, 2, bad)
        self.assertEqual(self.cmds, [])
        self.assertEqual(self.main(["cancel", "1;2"], pkexec=True, admin=True)[0], 2)

    def test_admin_entry_sets_flag_only_through_runpy(self):
        """luxos-printing-admin spusti pomocnika s LUXOS_PRINTING_ADMIN (ne z prostredi)."""
        stub = os.path.join(self.tmp, "stub-helper")
        with open(stub, "w") as f:
            f.write("import sys\nprint(globals().get('LUXOS_PRINTING_ADMIN'), sys.argv[1:])\n")
        with open(os.path.join(FILES, "luxos-printing-admin")) as f:
            src = f.read()
        self.assertIn('HELPER = "/usr/lib/luxos/printing/luxos-printing-helper"', src)
        admin = os.path.join(self.tmp, "admin")
        with open(admin, "w") as f:
            f.write(src.replace("/usr/lib/luxos/printing/luxos-printing-helper", stub))
        out = subprocess.run([sys.executable, "-I", admin, "remove", "Q"], capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "True ['remove', 'Q']")
        # prostredi priznak nenastavi
        env = dict(os.environ, LUXOS_PRINTING_ADMIN="True")
        out = subprocess.run([sys.executable, "-I", stub, "x"], capture_output=True, text=True, env=env).stdout
        self.assertEqual(out.strip(), "None ['x']")
        self.assertFalse(load_helper(self.tmp).ADMIN_ENTRY)


class Polkit(unittest.TestCase):
    def setUp(self):
        self.actions = {}
        for a in ET.parse(os.path.join(FILES, "org.luxos.printing.policy")).getroot().iter("action"):
            d = a.find("defaults")
            ann = {x.get("key"): x.text for x in a.iter("annotate")}
            self.actions[a.get("id")] = ({c.tag: c.text for c in d}, ann.get("org.freedesktop.policykit.exec.path"))

    def test_manage_is_password_free_for_active_user(self):
        defaults, path = self.actions["org.luxos.printing.manage"]
        self.assertEqual(defaults, {"allow_any": "auth_admin", "allow_inactive": "auth_admin", "allow_active": "yes"})
        self.assertEqual(path, "/usr/lib/luxos/printing/luxos-printing-helper")

    def test_admin_requires_admin_auth(self):
        defaults, path = self.actions["org.luxos.printing.admin"]
        self.assertEqual(defaults, {"allow_any": "auth_admin", "allow_inactive": "auth_admin",
                                    "allow_active": "auth_admin_keep"})
        self.assertEqual(path, "/usr/lib/luxos/printing/luxos-printing-admin")

    def test_package_installs_admin_entry_and_app_uses_it(self):
        with open(os.path.join(HERE, "..", "PKGBUILD")) as f:
            pkgbuild = f.read()
        self.assertIn('"$f/luxos-printing-admin"', pkgbuild)
        self.assertIn("install -Dm755 -t \"$d\"", pkgbuild)
        with open(os.path.join(FILES, "luxos-printers")) as f:
            app = f.read()
        self.assertIn('run_helper(["remove", name], lambda rc, o, e: self.after_admin(rc, e), admin=True)', app)
        self.assertIn('run_helper(["cancel", str(jid)], lambda rc, o, e: self.after_admin(rc, e), admin=True)', app)


class WatchFlood(unittest.TestCase):
    """Zaplava ohlaseni mDNS: nejvys jeden sync za LUXOS_PRINTING_WATCH_MIN_GAP s."""

    def setUp(self):
        self.tmp = tmpdir()
        b = os.path.join(self.tmp, "bin")
        os.makedirs(b)
        self.calls = os.path.join(self.tmp, "helper.log")
        scripts = {
            "helper": f"#!/bin/sh\necho \"$@\" >> {self.calls}\n",
            "systemctl": "#!/bin/sh\nexit 1\n",
            # nova sluzba kazdych 0,1 s po celou dobu testu
            "avahi-browse": "#!/bin/bash\ncase \"$*\" in *_ipp._tcp*) i=0; while :; do i=$((i+1)); "
                            "echo \"+;wlan0;IPv4;P$i;_ipp._tcp;local\"; sleep 0.1; done;; esac\nexec sleep 30\n",
        }
        for n, text in scripts.items():
            p = os.path.join(b, n)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, 0o755)
        self.env = {"PATH": b + os.pathsep + "/usr/bin:/bin", "LUXOS_PRINTING_HELPER": os.path.join(b, "helper"),
                    "LUXOS_PRINTING_CUPS_CONF": os.path.join(self.tmp, "printers.conf"),
                    "LUXOS_PRINTING_WATCH_INTERVAL": "100", "LUXOS_PRINTING_WATCH_FIRST": "100",
                    "LUXOS_PRINTING_WATCH_MIN_GAP": "5"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flood_syncs_at_most_once_per_gap(self):
        p = subprocess.Popen(["bash", os.path.join(FILES, "luxos-printing-watch")], env=self.env,
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(11.5)
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=10)
        try:
            with open(self.calls) as f:
                n = f.read().split().count("sync")
        except OSError:
            n = 0
        # ~110 ohlaseni za 11,5 s: prvni sync po 3 s, pak nejvys jednou za 5 s. Drive se pri zaplave
        # sync nespustil vubec (kazde dalsi ohlaseni prodlouzilo cekani o 3 s).
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
