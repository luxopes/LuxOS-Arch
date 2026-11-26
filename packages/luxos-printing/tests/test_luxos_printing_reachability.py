"""Sitova tiskarna mimo sit: aplikace nesmi hodiny ukazovat zelene "Pripravena".

Skutecny pripad (1.0.3): Kyocera ECOSYS MA4000cix (IPP Everywhere, dnssd://) pridana rano v jine siti,
aplikace otevrena cely den - po odchodu z te site porad "Pripravena". CUPS u fronty bez ovladace hlasi
idle, dokud uloha neselze, a avahi muze mit ohlaseni jeste v mezipameti. Dostupnost se proto urcuje
z ohlaseni mDNS a kratkeho spojeni na adresu tiskarny, pravidelne, dokud je okno otevrene.

Testy nikdy nesahaji na skutecny CUPS, avahi ani sit: avahi-browse, zkouska spojeni a CUPS jsou
nahrazene v procesu, ipptool/avahi-browse/scanimage na PATH jsou falesne skripty a adresy jsou
z dokumentacniho rozsahu 192.0.2.0/24. Jen tcp_reachable() se zkousi na 127.0.0.1 (vlastni soket).
GUI jen pod Xvfb (scripts/luxos_testguard.py).

Spusteni: python3 -m unittest discover -s packages/luxos-printing/tests -v
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
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")
sys.path.insert(0, FILES)
import luxos_printing as lp  # noqa: E402

KYO = "Kyocera ECOSYS MA4000cix"
KYO_UUID = "4509a320-00a0-008f-00b6-002507510eca"
KYO_URI = lp.dnssd_uri(KYO, "_ipp._tcp", KYO_UUID)
CANON_URI = "usb://Canon/MF4100%20Series?serial=0000A1B2C3D4&interface=1"


def avahi_line(name, addr, port=631, iface="wlan0", stype="_ipp._tcp", uuid=KYO_UUID):
    """Radek `avahi-browse -p -r -k` (vyresena sluzba)."""
    txt = f'"rp=ipp/print" "UUID={uuid}" "pdl=application/pdf,image/pwg-raster" "ty={name}"'
    proto = "IPv6" if ":" in addr else "IPv4"
    return f"=;{iface};{proto};{name};{stype};local;printer.local;{addr};{port};{txt}\n"


class PureLogic(unittest.TestCase):
    def test_probe_target(self):
        self.assertEqual(lp.probe_target("ipp://192.0.2.10/ipp/print"), ("192.0.2.10", 631))
        self.assertEqual(lp.probe_target("ipps://kyocera.local:443/ipp/print"), ("kyocera.local", 443))
        self.assertEqual(lp.probe_target("socket://192.0.2.11"), ("192.0.2.11", 9100))
        self.assertEqual(lp.probe_target("socket://192.0.2.11:9101"), ("192.0.2.11", 9101))
        self.assertEqual(lp.probe_target("lpd://192.0.2.12/queue"), ("192.0.2.12", 515))
        self.assertEqual(lp.probe_target("ipp://[2001:db8::5]:631/ipp/print"), ("2001:db8::5", 631))
        self.assertEqual(lp.probe_target("ipp://user@192.0.2.10/ipp/print"), ("192.0.2.10", 631))

    def test_probe_target_none(self):
        for uri in (KYO_URI, CANON_URI, "hp:/usb/LaserJet?serial=1", "smb://srv/q", "", None,
                    "ipp:///ipp/print", "ipp://192.0.2.1:99999/x", "ipp://-oProxy/x", "cnusbufr2:/dev/usb/lp0"):
            self.assertIsNone(lp.probe_target(uri), uri)

    def test_mdns_find_by_uuid_and_name(self):
        groups = list(lp.group_printers(lp.parse_avahi(avahi_line(KYO, "192.0.2.50"))).values())
        self.assertEqual(lp.mdns_find(groups, KYO_URI)["name"], KYO)
        self.assertEqual(lp.mdns_find(groups, lp.dnssd_uri(KYO, "_ipp._tcp"))["name"], KYO)
        # tiskarna se prejmenovala, UUID zustalo
        self.assertIsNotNone(lp.mdns_find(groups, lp.dnssd_uri("Old name", "_ipp._tcp", KYO_UUID)))
        self.assertIsNone(lp.mdns_find(groups, lp.dnssd_uri("Other", "_ipp._tcp")))

    def test_link_local_not_probed(self):
        g = list(lp.group_printers(lp.parse_avahi(avahi_line(KYO, "fe80::1") +
                                                  avahi_line(KYO, "192.0.2.50"))).values())[0]
        self.assertEqual([a[1] for a in lp.mdns_probe_addrs(g)], ["192.0.2.50"])


# Ovladac v podprocesu: nacte aplikaci, nahradi avahi, zkousku spojeni a CUPS, vypise JSON
DRIVER = r"""
import importlib.machinery as m, importlib.util as u, json, os, sys, threading
l = m.SourceFileLoader('lp_app', sys.argv[1]); s = u.spec_from_loader('lp_app', l)
a = u.module_from_spec(s); l.exec_module(a)
cfg = json.loads(sys.argv[2])
calls = {"probe": [], "browse": 0, "threads": set()}
state = {"avahi": cfg.get("avahi", ""), "reach": set(map(tuple, cfg.get("reach", [])))}
probe_started = threading.Event()
allow_probe = threading.Event()
if not cfg.get("hold_probe"):
    allow_probe.set()

def browse():
    calls["browse"] += 1
    calls["threads"].add(threading.current_thread() is threading.main_thread())
    probe_started.set()
    if not allow_probe.wait(10):
        raise RuntimeError("Test did not release the network probe")
    return state["avahi"]

def reach(host, port, timeout=3):
    calls["probe"].append([host, port])
    calls["threads"].add(threading.current_thread() is threading.main_thread())
    return (host, port) in state["reach"]

a.browse_printers = browse
a.tcp_reachable = reach
printers = cfg["printers"]

def info(live_all, name, jobs=()):
    return a.printer_info(printers[name], live_all.get(name), list(jobs))

if cfg["mode"] == "live":
    live = a.Cups.live(printers)
    out = {n: info(live, n, [{"job-id": 1}] * cfg.get("jobs", {}).get(n, 0))[:2] for n in printers
           if not a.lp.is_local_uri(printers[n].get("device-uri"))}
    print(json.dumps({"out": out, "live": live, "probe": sorted(calls["probe"]), "browse": calls["browse"],
                      "main_thread": True in calls["threads"]}))
    sys.exit(0)

# mode gui: okno otevrene, stav se meni "za behu"
from gi.repository import GLib, Gtk
from types import SimpleNamespace
a.Gio = SimpleNamespace(NetworkMonitor=SimpleNamespace(
    get_default=lambda: SimpleNamespace(connect=lambda *_: None)))
data = {"printers": printers, "default": None, "jobs": {}, "markers": {}, "usb_online": {"Canon": False}}
a.Cups.snapshot = lambda self: data
a.list_scanners = lambda: []
a.cups = a.cups or object()
win = a.Window()
win.select_key = "p:Kyocera"
win.show_all()

def subtitles():
    return {r.key: r.sub.get_text() for r in win.side.get_children()}

def wait(pred, secs):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + secs * 1000000
    while GLib.get_monotonic_time() < end:
        ctx.iteration(False)
        if pred():
            return True
        GLib.usleep(20000)
    return False

steps = []
for step in cfg["steps"]:
    state["reach"] = set(map(tuple, step.get("reach", [])))
    state["avahi"] = step.get("avahi", state["avahi"])
    if step.get("network_changed"):
        win.on_network_changed(None, True)
    if step.get("release_probe"):
        allow_probe.set()
    def expected_status():
        return (step["expect"] in subtitles().get("p:Kyocera", "")
                and (not step.get("verify_detail") or step["expect"] == win.ppage.status.get_text()))
    ok = wait(expected_status, step.get("within", 10))
    if step.get("expect_probe"):
        ok = wait(probe_started.is_set, 1) and ok
    steps.append([ok, subtitles().get("p:Kyocera"), subtitles().get("p:Canon")])
print(json.dumps({"steps": steps, "main_thread": True in calls["threads"], "browse": calls["browse"]}))
"""


class AppReachability(unittest.TestCase):
    def setUp(self):
        base = os.path.join(ROOT, "out", "test-printing")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=base)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "calls.log")
        # zadny skutecny ipptool/avahi-browse/scanimage/lpq: jen zapis volani
        for tool in ("ipptool", "avahi-browse", "scanimage", "lpq", "lpstat"):
            p = os.path.join(self.bin, tool)
            with open(p, "w") as f:
                f.write(f"#!/bin/sh\necho \"{tool} $*\" >> {self.log}\nexit 1\n")
            os.chmod(p, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self):
        if not os.path.exists(self.log):
            return ""
        with open(self.log) as f:
            return f.read()

    def run_app(self, cfg, timeout=60, lang="C.UTF-8"):
        env = {**os.environ, "LANG": lang, "LC_ALL": lang, "LUXOS_I18N_DIR": I18N,
               "PYTHONPATH": FILES + os.pathsep + I18N, "PATH": self.bin + os.pathsep + os.environ["PATH"],
               "LUXOS_PRINTERS_LIVE_INTERVAL": str(cfg.get("interval", 1))}
        if "luxos_testguard" in globals():
            luxos_testguard.check_env(env)
        r = subprocess.run([sys.executable, "-c", DRIVER, os.path.join(FILES, "luxos-printers"), json.dumps(cfg)],
                           capture_output=True, text=True, env=env, timeout=timeout)
        if r.returncode and "Gtk" in r.stderr and "display" in r.stderr.lower():
            self.skipTest("Gtk needs a display (run under xvfb-run)")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    @staticmethod
    def printers(**extra):
        p = {"Kyocera": {"device-uri": KYO_URI, "printer-state": 3, "printer-is-accepting-jobs": True,
                         "printer-info": KYO, "printer-make-and-model": "Kyocera ECOSYS MA4000cix, driverless"},
             "Canon": {"device-uri": CANON_URI, "printer-state": 3, "printer-is-accepting-jobs": True,
                       "printer-info": "Canon MF4100", "printer-location": "jupiter"}}
        p.update(extra)
        return p

    def live(self, **cfg):
        cfg.setdefault("printers", self.printers())
        return self.run_app({"mode": "live", **cfg})

    def test_real_case_cached_advertisement_but_unreachable(self):
        """avahi ma ohlaseni jeste v mezipameti, tiskarna ale neodpovida -> Nepripojeno (ne Pripravena)."""
        r = self.live(avahi=avahi_line(KYO, "192.0.2.50"), reach=[])
        self.assertEqual(r["out"]["Kyocera"], ["Not connected", "warn"])
        self.assertEqual(r["probe"], [["192.0.2.50", 631]])
        self.assertNotIn("ipptool", self.calls())     # na neodpovidajici adresu se nic dalsiho neposila

    def test_not_advertised(self):
        r = self.live(avahi="", reach=[["192.0.2.50", 631]])
        self.assertEqual(r["out"]["Kyocera"], ["Not connected", "warn"])
        self.assertEqual(r["probe"], [])

    def test_reachable_stays_ready(self):
        r = self.live(avahi=avahi_line(KYO, "192.0.2.50"), reach=[["192.0.2.50", 631]])
        self.assertEqual(r["out"]["Kyocera"], ["Ready", "ok"])
        self.assertTrue(r["live"]["Kyocera"]["online"])
        # stav naplni se zkousi jen na dostupnou adresu (falesny ipptool)
        self.assertIn("ipptool -T 5 -tv ipp://192.0.2.50:631/ipp/print", self.calls())

    def test_one_of_several_addresses_reachable(self):
        avahi = avahi_line(KYO, "192.0.2.50") + avahi_line(KYO, "2001:db8::50") + avahi_line(KYO, "fe80::50")
        r = self.live(avahi=avahi, reach=[["2001:db8::50", 631]])
        self.assertEqual(r["out"]["Kyocera"], ["Ready", "ok"])
        self.assertNotIn(["fe80::50", 631], r["probe"])

    def test_only_link_local_trusts_mdns(self):
        r = self.live(avahi=avahi_line(KYO, "fe80::50"), reach=[])
        self.assertEqual(r["out"]["Kyocera"], ["Ready", "ok"])
        self.assertEqual(r["probe"], [])

    def test_waiting_document(self):
        r = self.live(avahi="", reach=[], jobs={"Kyocera": 1})
        self.assertEqual(r["out"]["Kyocera"], ["Not connected · 1 document waiting", "warn"])
        r = self.live(avahi="", reach=[], jobs={"Kyocera": 3})
        self.assertEqual(r["out"]["Kyocera"], ["Not connected · 3 documents waiting", "warn"])

    def test_direct_ipp_and_socket_queues(self):
        pr = self.printers(Office={"device-uri": "ipp://192.0.2.20/ipp/print", "printer-state": 3,
                                   "printer-is-accepting-jobs": True},
                           Laser={"device-uri": "socket://192.0.2.21", "printer-state": 3,
                                  "printer-is-accepting-jobs": True})
        r = self.live(printers=pr, avahi=avahi_line(KYO, "192.0.2.50"), reach=[["192.0.2.21", 9100]])
        self.assertEqual(r["out"]["Office"], ["Not connected", "warn"])
        self.assertEqual(r["out"]["Laser"], ["Ready", "ok"])
        self.assertEqual(r["probe"], [["192.0.2.20", 631], ["192.0.2.21", 9100], ["192.0.2.50", 631]])

    def test_usb_never_probed_and_no_browse_without_dnssd(self):
        pr = {"Canon": self.printers()["Canon"],
              "Office": {"device-uri": "ipp://192.0.2.20/ipp/print", "printer-state": 3}}
        r = self.live(printers=pr, avahi=avahi_line(KYO, "192.0.2.50"), reach=[["192.0.2.20", 631]])
        self.assertEqual(r["probe"], [["192.0.2.20", 631]])
        self.assertEqual(r["browse"], 0)
        self.assertNotIn("Canon", r["live"])

    def test_ipp_usb_on_loopback_not_marked_offline(self):
        """ipp-usb (dnssd na lo): o pripojeni rozhoduje ohlaseni, ne zkouska spojeni."""
        uri = lp.dnssd_uri("Canon USB", "_ipp._tcp", "11111111-2222-3333-4444-555555555555")
        pr = {"CanonUSB": {"device-uri": uri, "printer-state": 3, "printer-is-accepting-jobs": True,
                           "printer-location": "USB"}}
        avahi = avahi_line("Canon USB", "127.0.0.1", 60000, "lo", uuid="11111111-2222-3333-4444-555555555555")
        r = self.live(printers=pr, avahi=avahi, reach=[])
        self.assertTrue(r["live"]["CanonUSB"]["online"])

    def test_czech(self):
        cfg = {"mode": "live", "printers": self.printers(), "avahi": "", "reach": []}
        r = self.run_app(cfg, lang="cs_CZ.UTF-8")
        self.assertEqual(r["out"]["Kyocera"], ["Nepřipojeno", "warn"])

    def test_startup_has_neutral_status_while_probe_is_pending(self):
        """CUPS hlasi idle pred sitovou kontrolou. Seznam ani detail nesmi ukazat Ready."""
        adv = avahi_line(KYO, "192.0.2.50")
        steps = [{"expect": "Checking the connection…", "verify_detail": True, "expect_probe": True},
                 {"expect": "Not connected", "verify_detail": True, "release_probe": True}]
        r = self.run_app({"mode": "gui", "printers": self.printers(), "avahi": adv, "steps": steps,
                          "interval": 60, "hold_probe": True})
        self.assertTrue(all(s[0] for s in r["steps"]), r["steps"])

    def test_window_refreshes_while_open(self):
        """Okno otevrene: tiskarna dostupna -> mimo sit -> zpet; radek se meni sam, USB Canon zustava odpojeny."""
        adv = avahi_line(KYO, "192.0.2.50")
        steps = [{"avahi": adv, "reach": [["192.0.2.50", 631]], "expect": "Ready"},
                 {"avahi": adv, "reach": [], "expect": "Not connected"},        # mezipamet avahi, neodpovida
                 {"avahi": "", "reach": [], "expect": "Not connected"},
                 {"avahi": adv, "reach": [["192.0.2.50", 631]], "expect": "Ready"}]
        r = self.run_app({"mode": "gui", "printers": self.printers(), "avahi": adv, "steps": steps, "interval": 1})
        for ok, kyo, canon in r["steps"]:
            self.assertTrue(ok, r["steps"])
            self.assertTrue(canon.startswith("Not connected – connect the USB cable"), canon)
        self.assertFalse(r["main_thread"])

    def test_network_change_refreshes_immediately(self):
        """Pravidelne obnoveni jednou za 60 s, zmena site (NetworkMonitor) ho spusti hned."""
        adv = avahi_line(KYO, "192.0.2.50")
        steps = [{"reach": [["192.0.2.50", 631]], "expect": "Ready", "within": 10},
                 {"reach": [], "network_changed": True, "expect": "Checking the connection…", "within": 1},
                 {"expect": "Not connected", "within": 8}]
        r = self.run_app({"mode": "gui", "printers": self.printers(), "avahi": adv, "steps": steps,
                          "interval": 60})
        self.assertTrue(all(s[0] for s in r["steps"]), r["steps"])


class TcpReachable(unittest.TestCase):
    """Skutecna zkouska spojeni jen na vlastni soket na 127.0.0.1 (zadna sit, zadna tiskarna)."""

    def load(self):
        code = (r"import importlib.machinery as m, importlib.util as u, json, socket, sys, time;"
                r"l = m.SourceFileLoader('lp_app', sys.argv[1]); s = u.spec_from_loader('lp_app', l);"
                r"a = u.module_from_spec(s); l.exec_module(a);"
                r"srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1); port = srv.getsockname()[1];"
                r"c = socket.socket(); c.bind(('127.0.0.1', 0)); closed = c.getsockname()[1]; c.close();"
                r"t = time.monotonic();"
                r"res = a.probe_all({'a': [('127.0.0.1', port)], 'b': [('127.0.0.1', closed)]}, 1);"
                r"print(json.dumps([res[('127.0.0.1', port)], res[('127.0.0.1', closed)], time.monotonic() - t]))")
        env = {**os.environ, "PYTHONPATH": FILES + os.pathsep + I18N, "LUXOS_I18N_DIR": I18N}
        r = subprocess.run([sys.executable, "-c", code, os.path.join(FILES, "luxos-printers")],
                           capture_output=True, text=True, env=env, timeout=60)
        if r.returncode and "Gtk" in r.stderr and "display" in r.stderr.lower():
            self.skipTest("Gtk needs a display (run under xvfb-run)")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_open_and_closed_port(self):
        up, down, took = self.load()
        self.assertTrue(up)
        self.assertFalse(down)
        self.assertLess(took, 4)


if __name__ == "__main__":
    unittest.main()
