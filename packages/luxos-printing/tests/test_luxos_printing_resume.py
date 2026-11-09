"""Odpojena / vypnuta tiskarna: politika chyb front, samo-obnoveni pozastavenych front, upozorneni.

Skutecny pripad: fronta Canon MF4100 (USB, UFR II) "disabled since 2026-11-06 - Unplugged or turned off"
(udev-configure-printer ji pri odpojeni pozastavil). CUPS ani nikdo jiny ji po pripojeni nepovolil,
ulohy cekaly a aplikace ukazovala "odpojeno".

Testy pouzivaji falesny CUPS (tests/fake/cups: lpstat, lpadmin, cupsenable... v docasnem PATH),
falesny sysfs (USB zarizeni) a falesne udalosti - skutecneho cupsd ani tiskaren se nedotknou.
Docasne soubory jsou v out/ repozitare (ne v /tmp).

Spusteni: python3 -m unittest discover -s packages/luxos-printing/tests -v
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")
sys.path.insert(0, FILES)
import luxos_printing as lp  # noqa: E402

CANON_URI = "usb://Canon/MF4100%20Series?serial=0000A1B2C3D4&interface=1"
CANON_SERIAL = "0000A1B2C3D4"
TOOLS = ("lpstat", "lpadmin", "cupsenable", "cupsdisable", "cupsaccept", "lp", "lpinfo", "systemctl",
         "fake-cupsd-save")


def tmpdir():
    base = os.path.join(ROOT, "out", "test-printing")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(dir=base)


def add_usb_device(sysfs, port, serial, manufacturer="Canon", product="MF4100 Series", cls="07"):
    """Falesne USB zarizeni v sysfs: /sys/bus/usb/devices/1-2 a rozhrani 1-2:1.0 (trida 07 = tiskarna)."""
    dev = os.path.join(sysfs, port)
    os.makedirs(os.path.join(sysfs, port + ":1.0"), exist_ok=True)
    os.makedirs(dev, exist_ok=True)
    for k, v in (("serial", serial), ("manufacturer", manufacturer), ("product", product)):
        if v is not None:
            with open(os.path.join(dev, k), "w") as f:
                f.write(v + "\n")
    with open(os.path.join(sysfs, port + ":1.0", "bInterfaceClass"), "w") as f:
        f.write(cls + "\n")


def remove_usb_device(sysfs, port):
    shutil.rmtree(os.path.join(sysfs, port), ignore_errors=True)
    shutil.rmtree(os.path.join(sysfs, port + ":1.0"), ignore_errors=True)


# ---------------------------------------------------------------- cista logika

LPSTAT_P = """printer Canon disabled since Fri Nov  6 10:00:00 2026 -
\tUnplugged or turned off
\tForm mounted:
\tContent types: any
\tPrinter types: unknown
\tDescription: Canon MF4100 Series
\tAlerts: paused
\tLocation: jupiter
\tConnection: direct
printer HP is idle.  enabled since Mon Nov  9 20:27:04 2026
\tForm mounted:
\tDescription: HP LaserJet
\tAlerts: none
printer Busy now printing Busy-12.  enabled since Mon Nov  9 20:27:04 2026
\tWaiting for printer to become available.
\tForm mounted:
\tDescription: Brother
\tAlerts: none
printer Mine disabled since Mon Nov  9 20:27:04 2026 -
\tParty: no printing: sorry
\tDescription:
\tAlerts: paused
printer Silent disabled since Mon Nov  9 20:27:04 2026 -
\treason unknown
\tForm mounted:
\tDescription: X
\tAlerts: paused
"""


class Parsing(unittest.TestCase):
    def test_lpstat_p(self):
        q = lp.parse_lpstat_p(LPSTAT_P)
        self.assertEqual(q["Canon"], {"state": "stopped", "message": "Unplugged or turned off",
                                      "reasons": ["paused"], "info": "Canon MF4100 Series"})
        self.assertEqual((q["HP"]["state"], q["HP"]["message"], q["HP"]["reasons"]), ("idle", "", []))
        self.assertEqual((q["Busy"]["state"], q["Busy"]["message"]),
                         ("printing", "Waiting for printer to become available."))
        self.assertEqual(q["Mine"]["message"], "Party: no printing: sorry")    # dvojtecka ve zprave
        self.assertEqual(q["Silent"]["message"], "")

    def test_lpstat_p_real_host_format(self):
        """Tvar ze skutecneho `LC_ALL=C lpstat -l -p` (CUPS 2.4, fronta Canon MF4100 po cupsenable)."""
        text = ("printer MF4100-Series is idle.  enabled since Mon Nov  9 20:27:04 2026\n\tForm mounted:\n"
                "\tContent types: any\n\tPrinter types: unknown\n\tDescription: Canon MF4100 Series\n"
                "\tAlerts: none\n\tLocation: jupiter\n\tConnection: direct\n"
                "\tInterface: /etc/cups/ppd/MF4100-Series.ppd\n\tOn fault: no alert\n\tAfter fault: continue\n"
                "\tUsers allowed:\n\t\t(all)\n\tForms allowed:\n\t\t(none)\n\tBanner required\n")
        self.assertEqual(lp.parse_lpstat_p(text), {"MF4100-Series": {
            "state": "idle", "message": "", "reasons": [], "info": "Canon MF4100 Series"}})

    def test_lpstat_a(self):
        self.assertEqual(lp.parse_lpstat_a("A accepting requests since X\nB not accepting requests since X -\n"
                                           "\tRejecting Jobs\nC/inst accepting requests since X\n"),
                         {"A": True, "B": False})

    def test_lpstat_jobs(self):
        text = ("Canon-12               antonin           1024   Fri Nov  6 10:00:00 2026\n"
                "\tStatus: Waiting for printer to become available.\n\tAlerts: job-printing\n\tqueued for Canon\n"
                "HP_M110-3               bob           2048   Fri Nov  6 10:00:00 2026\n"
                "\tAlerts: job-hold-until-specified\n\tqueued for HP_M110\n")
        jobs = lp.parse_lpstat_jobs(text)
        self.assertEqual([(j["queue"], j["id"], j["user"]) for j in jobs], [("Canon", 12, "antonin"), ("HP_M110", 3, "bob")])
        self.assertEqual(jobs[0]["status"], "Waiting for printer to become available.")
        self.assertFalse(lp.job_held_by_user(jobs[0]))
        self.assertTrue(lp.job_held_by_user(jobs[1]))
        self.assertFalse(lp.job_held_by_user({"reasons": ["job-hold-until-specified", "resources-are-not-ready"]}))

    def test_printers_conf(self):
        text = ("# Printer configuration file for CUPS v2.4.14\n<DefaultPrinter MF4100-Series>\n"
                "Info Canon MF4100 Series\nDeviceURI " + CANON_URI + "\nState Stopped\n"
                "StateMessage Unplugged or turned off\nAccepting Yes\nErrorPolicy stop-printer\n</DefaultPrinter>\n"
                "<Printer HP>\nDeviceURI dnssd://HP._ipp._tcp.local/\nState Idle\nErrorPolicy retry-job\n</Printer>\n")
        c = lp.parse_printers_conf(text)
        self.assertEqual(c["MF4100-Series"], {"uri": CANON_URI, "stopped": True, "message": "Unplugged or turned off",
                                              "accepting": True, "policy": "stop-printer"})
        self.assertEqual((c["HP"]["stopped"], c["HP"]["policy"]), (False, "retry-job"))


class Policy(unittest.TestCase):
    def test_error_policy(self):
        self.assertEqual(lp.error_policy(CANON_URI), "retry-current-job")
        self.assertEqual(lp.error_policy("hp:/usb/LaserJet_1020?serial=X"), "retry-current-job")
        self.assertEqual(lp.error_policy("cnusbufr2:/dev/usb/lp0"), "retry-current-job")
        self.assertEqual(lp.error_policy("gutenprint53+usb://canon-pixma/1"), "retry-current-job")
        # ipp-usb: dnssd na lo, ale tiskarna je na USB
        self.assertEqual(lp.error_policy("dnssd://Canon%20USB._ipp._tcp.local/?uuid=1", usb=True), "retry-current-job")
        self.assertEqual(lp.error_policy("dnssd://HP._ipp._tcp.local/?uuid=1"), "retry-job")
        self.assertEqual(lp.error_policy("socket://10.0.0.5"), "retry-job")
        self.assertEqual(lp.error_policy("hp:/net/LaserJet?ip=10.0.0.5"), "retry-job")

    def test_paused_for_device(self):
        for m in ("Unplugged or turned off", "Printer stopped due to backend errors; please consult the "
                  "/var/log/cups/error_log file for details.", "Waiting for printer to become available.",
                  "There was an unrecoverable USB error.", "Unable to locate printer."):
            self.assertTrue(lp.paused_for_device(m, ["paused"]), m)
        # pozastaveno uzivatelem nebo spravcem - nepovolovat samo
        for m in ("Paused", "Maintenance - toner replacement", "reason unknown"):
            self.assertFalse(lp.paused_for_device(m, ["paused"]), m)
        self.assertFalse(lp.paused_for_device("", ["paused"]))
        self.assertTrue(lp.paused_for_device("", ["paused", "offline-report"]))


class UsbPresence(unittest.TestCase):
    def setUp(self):
        self.sysfs = tmpdir()

    def tearDown(self):
        shutil.rmtree(self.sysfs, ignore_errors=True)

    def test_serial(self):
        self.assertEqual(lp.usb_printer_devices(self.sysfs), [])
        self.assertFalse(lp.usb_present(CANON_URI, lp.usb_printer_devices(self.sysfs)))
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        add_usb_device(self.sysfs, "1-3", "MOUSE", "Logitech", "Mouse", cls="03")   # neni tiskarna
        devs = lp.usb_printer_devices(self.sysfs)
        self.assertEqual(devs, [{"serial": CANON_SERIAL, "manufacturer": "Canon", "product": "MF4100 Series"}])
        self.assertTrue(lp.usb_present(CANON_URI, devs))
        self.assertFalse(lp.usb_present("usb://Canon/MF4100%20Series?serial=OTHER", devs))

    def test_without_serial(self):
        add_usb_device(self.sysfs, "1-2", None, "Canon", "MF4100 Series")
        devs = lp.usb_printer_devices(self.sysfs)
        self.assertTrue(lp.usb_present("usb://Canon/MF4100%20Series", devs))
        self.assertIsNone(lp.usb_present("usb://HP/LaserJet%201020", devs))     # jen CUPS vi jiste
        self.assertFalse(lp.usb_present("usb://HP/LaserJet%201020", []))
        self.assertEqual(lp.usb_printer_devices(os.path.join(self.sysfs, "missing")), [])


class Condition(unittest.TestCase):
    def test_unplugged_paused(self):
        """Skutecny pripad: zastaveno "Unplugged or turned off" a tiskarna neni pripojena."""
        self.assertEqual(lp.printer_condition("stopped", "Unplugged or turned off", ["paused"], True, True, False, 0),
                         ("unplugged_auto", False))
        # nevime (URI bez serioveho cisla), ale zprava rika odpojeno
        self.assertEqual(lp.printer_condition(5, "Unplugged or turned off", ["paused"], True, True, None, 1),
                         ("unplugged_auto", False))

    def test_waiting_job(self):
        self.assertEqual(lp.printer_condition("printing", "Waiting for printer to become available.", [], True,
                                              True, None, 1), ("unplugged_auto", False))
        self.assertEqual(lp.printer_condition("idle", "", [], True, True, False, 0), ("unplugged", False))
        self.assertEqual(lp.printer_condition("idle", "", [], True, False, False, 2), ("offline_auto", False))
        self.assertEqual(lp.printer_condition("idle", "", [], True, False, False, 0), ("offline", False))

    def test_paused_other_reason_offers_resume(self):
        self.assertEqual(lp.printer_condition("stopped", "Paused", ["paused"], True, True, True, 0), ("paused", True))
        self.assertEqual(lp.printer_condition("idle", "", [], False, True, True, 0), ("paused", True))
        # odpojena a zaroven pozastavena uzivatelem: Obnovit ano
        self.assertEqual(lp.printer_condition("stopped", "Paused", ["paused"], True, True, False, 0),
                         ("unplugged", True))
        # pozastaveno kvuli odpojeni, tiskarna uz je pripojena (hlidac ji za chvili povoli): Obnovit muze
        self.assertEqual(lp.printer_condition("stopped", "Unplugged or turned off", [], True, True, True, 0),
                         ("paused", True))

    def test_ready(self):
        self.assertEqual(lp.printer_condition("idle", "", [], True, True, True, 0), (None, False))
        self.assertEqual(lp.printer_condition(4, "", [], True, False, None, 1), (None, False))


# ---------------------------------------------------------------- pomocnik s falesnym CUPS

class FakeCups(unittest.TestCase):
    """luxos-printing-helper proti falesnemu CUPS (tests/fake/cups v docasnem PATH)."""

    def setUp(self):
        self.tmp = tmpdir()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for t in TOOLS:
            os.symlink(os.path.join(HERE, "fake", "cups"), os.path.join(self.bin, t))
        self.sysfs = os.path.join(self.tmp, "sys")
        os.makedirs(self.sysfs)
        self.env = {
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin"),
            "FAKE_CUPS_STATE": os.path.join(self.tmp, "cups.json"),
            "FAKE_CUPS_LOG": os.path.join(self.tmp, "cups.log"),
            "LUXOS_PRINTING_CUPS_CONF": os.path.join(self.tmp, "printers.conf"),
            "LUXOS_PRINTING_SYSFS": self.sysfs,
            "LUXOS_PRINTING_STATE": os.path.join(self.tmp, "state.json"),
            "LUXOS_PRINTING_LOCK": os.path.join(self.tmp, "lock"),
            "LUXOS_PRINTING_NOTIFY_LOG": os.path.join(self.tmp, "notify"),
        }
        self.old_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.cups({"active": True, "queues": {}, "jobs": []})
        loader = importlib.machinery.SourceFileLoader("luxos_printing_helper_t",
                                                      os.path.join(FILES, "luxos-printing-helper"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.h = importlib.util.module_from_spec(spec)
        loader.exec_module(self.h)
        self.h.browse = lambda types: self.services       # zadny skutecny avahi-browse
        self.services = []
        self.now = time.time()
        self.h.time = type("T", (), {"time": staticmethod(lambda: self.now)})

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- falesny CUPS
    def cups(self, data=None):
        path = self.env["FAKE_CUPS_STATE"]
        if data is not None:
            with open(path, "w") as f:
                json.dump(data, f)
        with open(path) as f:
            return json.load(f)

    def edit(self, fn):
        d = self.cups()
        fn(d)
        self.cups(d)

    def calls(self):
        try:
            with open(self.env["FAKE_CUPS_LOG"]) as f:
                return [json.loads(x) for x in f]
        except OSError:
            return []

    def notes(self):
        try:
            with open(self.env["LUXOS_PRINTING_NOTIFY_LOG"]) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def simulate_cupsd(self):
        """Chovani CUPS 2.4 podle zdroju: povolena fronta posle ulohu backendu; backend usb na
        nepripojenou tiskarnu ceka ("Waiting for printer to become available.", usb-libusb.c),
        pripojena tiskarna ulohu vytiskne. Zastavena fronta ani pozdrzena uloha se nehnou."""
        d = self.cups()
        devs = lp.usb_printer_devices(self.sysfs)
        for name, q in d["queues"].items():
            if q["state"] == "stopped":
                continue
            mine = [j for j in d["jobs"] if j["queue"] == name and j["state"] in ("pending", "processing")]
            if not mine:
                q["state"], q["message"] = "idle", ""
                continue
            if lp.usb_present(q["uri"], devs):
                d.setdefault("printed", []).extend(j["id"] for j in mine)
                d["jobs"] = [j for j in d["jobs"] if j not in mine]
                q["state"], q["message"] = "idle", ""
            else:
                mine[0]["state"] = "processing"
                mine[0]["status"] = q["message"] = "Waiting for printer to become available."
                q["state"] = "printing"
        self.cups(d)
        return d

    def canon_paused(self, jobs=1, own=False, policy="stop-printer"):
        """Stav ze skutecneho hlaseni: fronta pozastavena udev-configure-printer pri odpojeni."""
        self.cups({"active": True, "queues": {"MF4100-Series": {
            "uri": CANON_URI, "state": "stopped", "message": "Unplugged or turned off", "reasons": ["paused"],
            "accepting": True, "policy": policy, "info": "Canon MF4100 Series"}},
            "jobs": [{"id": 40 + i, "queue": "MF4100-Series", "user": "antonin", "state": "pending",
                      "reasons": []} for i in range(jobs)]})
        if own:
            st = self.h.load_state()
            st["queues"]["MF4100-Series"] = {"key": CANON_URI, "uri": CANON_URI, "usb": True, "added": 1, "seen": 1}
            self.h.save_state(st)

    def autoresume(self):
        return self.h.main(["autoresume"])

    def run_main(self, *args):
        geteuid = os.geteuid
        os.geteuid = lambda: 0
        try:
            return self.h.main(list(args))
        finally:
            os.geteuid = geteuid


class AutoResume(FakeCups):
    def setUp(self):
        super().setUp()
        self._geteuid = os.geteuid
        os.geteuid = lambda: 0

    def tearDown(self):
        os.geteuid = self._geteuid
        super().tearDown()

    def test_real_case_paused_queue_resumes_when_printer_is_plugged_in(self):
        """Pozastavena fronta + zarizeni pripojeno (udev add -> luxos-printing-sync) -> povolena, uloha vytistena."""
        self.canon_paused(jobs=1)
        self.h.usb_printers = lambda: []
        self.h.usb_scanners = lambda: {}
        # tiskarna stale odpojena: fronta zustane, uzivatel dostane upozorneni (kratke)
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "stopped")
        self.assertEqual(self.notes(), ["waiting\tCanon MF4100 Series\tusb"])
        self.assertFalse(any(c[0] == "cupsenable" for c in self.calls()))
        # pripojeni USB kabelu: udev add spusti luxos-printing-helper sync
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.assertEqual(self.run_main("sync"), 0)
        q = self.cups()["queues"]["MF4100-Series"]
        self.assertEqual((q["state"], q["message"]), ("idle", ""))
        self.assertIn(["cupsenable", "MF4100-Series"], self.calls())
        self.assertEqual(self.notes()[-1], "resumed\tCanon MF4100 Series")
        # CUPS ulohu posle tiskarne
        self.assertEqual(self.simulate_cupsd()["printed"], [40])
        # vse vytisteno: zadne dalsi upozorneni, zaznam o cekani smazan
        self.autoresume()
        self.assertEqual(len(self.notes()), 2)
        self.assertEqual(self.h.load_state()["waiting"], {})

    def test_periodic_check_resumes_without_event(self):
        """Udalost zmeskana (tiskarna zapnuta behem spanku): pravidelna kontrola frontu povoli taky."""
        self.canon_paused(jobs=0)
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "idle")
        self.assertEqual(self.notes(), [])          # zadna uloha necekala - zadne upozorneni

    def test_user_paused_queue_is_left_alone(self):
        self.canon_paused(jobs=1)
        self.edit(lambda d: d["queues"]["MF4100-Series"].update(message="Paused"))
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "stopped")
        self.assertFalse(any(c[0] == "cupsenable" for c in self.calls()))
        self.assertEqual(self.notes(), [])

    def test_other_printer_plugged_in_does_not_resume(self):
        self.canon_paused(jobs=0)
        add_usb_device(self.sysfs, "1-2", "OTHERSERIAL")
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "stopped")

    def test_not_accepting_is_accepted_again(self):
        self.canon_paused(jobs=0)
        self.edit(lambda d: d["queues"]["MF4100-Series"].update(accepting=False))
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.autoresume()
        q = self.cups()["queues"]["MF4100-Series"]
        self.assertEqual((q["state"], q["accepting"]), ("idle", True))

    def test_backend_stop_queue_without_serial_uses_lpinfo(self):
        """Fronta zastavena CUPS (backend STOP), URI bez serioveho cisla: pritomnost potvrdi lpinfo."""
        self.cups({"active": True, "queues": {"LJ": {
            "uri": "usb://HP/LaserJet%201020", "state": "stopped", "reasons": ["paused"], "accepting": True,
            "message": "Printer stopped due to backend errors; please consult the /var/log/cups/error_log file "
                       "for details.", "policy": "stop-printer", "info": "HP LaserJet 1020"}}, "jobs": [],
            "lpinfo": ["direct usb://HP/LaserJet%201020"]})
        add_usb_device(self.sysfs, "1-4", None, "Hewlett-Packard", "HP LaserJet 1020")
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["LJ"]["state"], "idle")
        self.assertIn(["lpinfo", "--include-schemes", "usb", "-v"], self.calls())

    def test_serial_from_device_id_differs_from_usb_serial(self):
        """Seriove cislo v URI z IEEE 1284 (SERN) jine nez v USB popisu: rozhodne lpinfo (CUPS)."""
        self.canon_paused(jobs=0)
        self.edit(lambda d: d.update(lpinfo=["direct " + CANON_URI]))
        add_usb_device(self.sysfs, "1-2", "USB-SERIAL-OTHER")
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "idle")
        # pravidelna kontrola s odpojenou tiskarnou a cizim zarizenim: lpinfo nejvys jednou za 5 min
        self.edit(lambda d: d.update(lpinfo=[]))
        self.edit(lambda d: d["queues"]["MF4100-Series"].update(state="stopped", message="Unplugged or turned off"))
        for minute in range(1, 11):
            self.now += 60
            self.autoresume()
        self.assertEqual(len([c for c in self.calls() if c[0] == "lpinfo"]), 3)    # 0, 5, 10 min
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "stopped")

    def test_backoff_when_queue_keeps_stopping(self):
        """Tiskarna pripojena, ale CUPS frontu hned zase zastavi (vadny ovladac): ne kazdych 30 s."""
        self.canon_paused(jobs=0)
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        stop = {"state": "stopped", "message": "Printer stopped due to backend errors."}
        enables = []
        for minute in range(0, 60, 1):
            self.now = 1_000_000 + minute * 60
            self.autoresume()
            if self.cups()["queues"]["MF4100-Series"]["state"] == "idle":
                enables.append(minute)
                self.edit(lambda d: d["queues"]["MF4100-Series"].update(stop))
        self.assertEqual(enables, [0, 5, 15, 35])       # odstup 5, 10, 20 min (pak 40 min ... 6 h)

    def test_network_printer_comes_back(self):
        """Sitova tiskarna (dnssd): zastavena fronta se povoli, kdyz se sluzba znovu ohlasi (avahi)."""
        uri = "dnssd://HP%20LaserJet%20M110w._ipp._tcp.local/?uuid=3cf9787f-057b-317d-4660-aa66ee44b2b8"
        self.cups({"active": True, "queues": {"HP": {
            "uri": uri, "state": "stopped", "message": "Printer stopped due to backend errors.",
            "reasons": ["paused"], "accepting": True, "policy": "stop-printer", "info": "HP LaserJet M110w"}},
            "jobs": [{"id": 7, "queue": "HP", "user": "u", "state": "pending", "reasons": []}]})
        self.autoresume()
        self.assertEqual(self.notes(), ["waiting\tHP LaserJet M110w\tnetwork"])
        self.services = lp.parse_avahi(
            '=;wlan0;IPv4;HP\\032LaserJet\\032M110w;_ipp._tcp;local;hp.local;10.0.0.5;631;'
            '"UUID=3CF9787F-057B-317D-4660-AA66EE44B2B8" "pdl=image/urf"')
        self.now += 10
        self.h.auto_resume(st := self.h.load_state(), event=True)
        self.h.save_state(st)
        self.assertEqual(self.cups()["queues"]["HP"]["state"], "idle")

    def test_retry_job_hold_released_when_printer_returns(self):
        uri = "dnssd://HP._ipp._tcp.local/?uuid=1234abcd-0000"
        self.cups({"active": True, "queues": {"HP": {"uri": uri, "state": "idle", "message": "", "reasons": [],
                                                     "accepting": True, "policy": "retry-job", "info": "HP"}},
                   "jobs": [{"id": 9, "queue": "HP", "user": "u", "state": "held",
                             "reasons": ["resources-are-not-ready"]},
                            {"id": 10, "queue": "HP", "user": "u", "state": "held", "reasons": []}]})
        self.services = [{"iface": "wlan0", "proto": "IPv4", "name": "HP", "type": "_ipp._tcp", "domain": "local",
                          "host": "hp.local", "address": "10.0.0.5", "port": 631, "txt": {"uuid": "1234abcd-0000"}}]
        st = self.h.load_state()
        self.h.auto_resume(st, event=True)
        jobs = {j["id"]: j["state"] for j in self.cups()["jobs"]}
        self.assertEqual(jobs, {9: "pending", 10: "held"})      # uzivatelem pozdrzena zustava

    def test_waiting_notifications_transient_then_persistent_once(self):
        """Uloha ceka na vypnutou tiskarnu: hned kratke upozorneni, po 5 min jedno trvale, pak klid."""
        self.cups({"active": True, "queues": {"Canon": {
            "uri": CANON_URI, "state": "idle", "message": "", "reasons": [], "accepting": True,
            "policy": "retry-current-job", "info": "Canon MF4100 Series"}},
            "jobs": [{"id": 5, "queue": "Canon", "user": "antonin", "state": "pending", "reasons": []}]})
        self.simulate_cupsd()           # backend usb ceka na tiskarnu
        self.assertEqual(self.cups()["queues"]["Canon"]["message"], "Waiting for printer to become available.")
        for minute in range(0, 20):
            self.now = 2_000_000 + minute * 60
            self.autoresume()
        self.assertEqual(self.notes(), ["waiting\tCanon MF4100 Series\tusb", "waiting-long\tCanon MF4100 Series\tusb"])
        # zapnuti tiskarny: backend usb ulohu sam vytiskne (fronta nebyla zastavena)
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.assertEqual(self.simulate_cupsd()["printed"], [5])
        self.autoresume()
        self.assertEqual(self.h.load_state()["waiting"], {})
        self.assertFalse(any(c[0] == "cupsenable" for c in self.calls()))
        # dalsi uloha pozdeji: znovu jedno kratke upozorneni
        remove_usb_device(self.sysfs, "1-2")
        self.edit(lambda d: d["jobs"].append({"id": 6, "queue": "Canon", "user": "a", "state": "pending",
                                              "reasons": []}))
        self.simulate_cupsd()
        self.autoresume()
        self.assertEqual(self.notes()[-1], "waiting\tCanon MF4100 Series\tusb")
        self.assertEqual(len(self.notes()), 3)

    def test_job_held_by_user_is_not_reported(self):
        self.cups({"active": True, "queues": {"Canon": {
            "uri": CANON_URI, "state": "idle", "message": "", "reasons": [], "accepting": True, "info": "C"}},
            "jobs": [{"id": 5, "queue": "Canon", "user": "a", "state": "held", "reasons": []}]})
        self.autoresume()
        self.assertEqual(self.notes(), [])

    def test_no_cups_wakeup_when_idle(self):
        """cupsd nebezi a zadna fronta neni zastavena kvuli odpojeni -> zadny lpstat (cups.socket by CUPS probudil)."""
        self.canon_paused(jobs=0)
        self.edit(lambda d: d.update(active=False))
        self.edit(lambda d: d["queues"]["MF4100-Series"].update(state="stopped"))
        # printers.conf jako by ho zapsal cupsd
        with open(self.env["LUXOS_PRINTING_CUPS_CONF"], "w") as f:
            f.write(f"<Printer MF4100-Series>\nDeviceURI {CANON_URI}\nState Stopped\n"
                    "StateMessage Unplugged or turned off\nErrorPolicy stop-printer\n</Printer>\n")
        st = self.h.load_state()
        st["policy_version"] = self.h.POLICY_VERSION
        self.h.save_state(st)
        self.autoresume()
        self.assertFalse(self.cups().get("woken"))
        self.assertEqual([c[0] for c in self.calls()], ["systemctl"])
        # tiskarna pripojena -> ted uz ano: CUPS se probudi a fronta se povoli
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        self.autoresume()
        self.assertTrue(self.cups().get("woken"))
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "idle")

    def test_autoresume_skips_when_helper_busy(self):
        """Dlouha instalace ovladace drzi zamek: pravidelna kontrola neceka, jen tentokrat nic."""
        import fcntl
        self.canon_paused(jobs=0)
        add_usb_device(self.sysfs, "1-2", CANON_SERIAL)
        with open(self.env["LUXOS_PRINTING_LOCK"], "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.assertEqual(self.autoresume(), 0)
            self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "stopped")
        self.autoresume()
        self.assertEqual(self.cups()["queues"]["MF4100-Series"]["state"], "idle")


class Migration(FakeCups):
    def setUp(self):
        super().setUp()
        self._geteuid = os.geteuid
        os.geteuid = lambda: 0

    def tearDown(self):
        os.geteuid = self._geteuid
        super().tearDown()

    def queues(self):
        return {"Own_USB": {"uri": CANON_URI, "state": "idle", "policy": "retry-job"},
                "Own_IPPUSB": {"uri": "dnssd://Canon%20USB._ipp._tcp.local/?uuid=1", "state": "idle",
                               "policy": "retry-job"},
                "Own_Net": {"uri": "dnssd://HP._ipp._tcp.local/?uuid=2", "state": "idle", "policy": "retry-job"},
                "Foreign_USB": {"uri": "usb://HP/LaserJet%201020?serial=X", "state": "idle", "policy": "stop-printer"},
                "Foreign_Custom": {"uri": "usb://Epson/L3150?serial=Y", "state": "idle", "policy": "abort-job"},
                "Foreign_Net": {"uri": "socket://10.0.0.9", "state": "idle", "policy": "stop-printer"}}

    def prepare(self):
        d = {"active": True, "queues": self.queues(), "jobs": []}
        for q in d["queues"].values():
            q.update(message="", reasons=[], accepting=True, info="")
        self.cups(d)
        # printers.conf jako by ho zapsal cupsd
        subprocess.run(["fake-cupsd-save"], env={**os.environ, **self.env}, capture_output=True, check=True)
        st = self.h.load_state()
        for n, usb in (("Own_USB", True), ("Own_IPPUSB", True), ("Own_Net", False)):
            st["queues"][n] = {"key": n, "uri": self.queues()[n]["uri"], "usb": usb, "added": 1, "seen": 1}
        self.h.save_state(st)

    def test_migration_sets_policy_once(self):
        self.prepare()
        self.assertEqual(self.h.main(["migrate"]), 0)
        pol = {n: q["policy"] for n, q in self.cups()["queues"].items()}
        self.assertEqual(pol, {"Own_USB": "retry-current-job", "Own_IPPUSB": "retry-current-job",
                               "Own_Net": "retry-job", "Foreign_USB": "retry-current-job",
                               "Foreign_Custom": "abort-job", "Foreign_Net": "stop-printer"})
        self.assertEqual(self.h.load_state()["policy_version"], self.h.POLICY_VERSION)
        n = len([c for c in self.calls() if c[0] == "lpadmin"])
        self.assertEqual(n, 3)
        # podruhe (dalsi aktualizace, autoresume, sync) uz nic
        self.h.main(["migrate"])
        self.autoresume()
        self.assertEqual(len([c for c in self.calls() if c[0] == "lpadmin"]), n)

    def test_migration_waits_for_cups(self):
        """CUPS nedostupny (chroot instalatoru): migrace se neoznaci jako hotova a probehne pozdeji."""
        self.prepare()
        os.remove(os.path.join(self.bin, "lpstat"))
        with open(os.path.join(self.bin, "lpstat"), "w") as f:
            f.write("#!/bin/sh\necho 'lpstat: Bad file descriptor' >&2\nexit 1\n")
        os.chmod(os.path.join(self.bin, "lpstat"), 0o755)
        self.h.main(["migrate"])
        self.assertNotIn("policy_version", self.h.load_state())
        self.assertFalse(any(c[0] == "lpadmin" for c in self.calls()))

    def test_new_queues_get_policy(self):
        """Nove fronty: USB retry-current-job, sit retry-job (create_queue)."""
        cmds = []
        self.h.run = lambda cmd, timeout=60: (cmds.append(cmd), (0, "", ""))[1]
        self.h.models = lambda: lp.parse_lpinfo("Model: name = CNRCUPSMF4100ZK.ppd\n        make-and-model = "
                                                "Canon MF4100 Series UFRII LT\n        device-id = \n", "Model")
        dev = {"key": CANON_URI, "uri": CANON_URI, "name": "Canon MF4100 Series", "model": "Canon MF4100 Series",
               "usb": True, "classic": True, "device_id": "MFG:Canon;MDL:MF4100 Series;CMD:LIPSLX,CPCA;"}
        self.assertEqual(self.h.create_queue(dev, {})[1], None)
        net = {"key": "uuid:2", "uri": "dnssd://HP._ipp._tcp.local/?uuid=2", "name": "HP", "model": "HP",
               "usb": False, "driverless": True}
        ippusb = dict(net, uri="dnssd://Canon%20USB._ipp._tcp.local/?uuid=3", name="Canon USB", usb=True)
        self.h.create_queue(net, {})
        self.h.create_queue(ippusb, {})
        pol = [next(a for a in c if a.startswith("printer-error-policy=")) for c in cmds if c[:1] == ["lpadmin"]]
        self.assertEqual(pol, ["printer-error-policy=retry-current-job", "printer-error-policy=retry-job",
                               "printer-error-policy=retry-current-job"])


class AppStatus(unittest.TestCase):
    """Aplikace Tiskarny a skenery: srozumitelny stav misto "Paused"/"Printing…" u odpojene tiskarny."""

    CODE = r"""
import importlib.machinery as m, importlib.util as u, json, sys
l = m.SourceFileLoader('lp_app', sys.argv[1]); s = u.spec_from_loader('lp_app', l)
a = u.module_from_spec(s); l.exec_module(a)
canon = {"device-uri": "%(uri)s", "printer-state": 5, "printer-state-message": "Unplugged or turned off",
         "printer-state-reasons": ["paused"], "printer-is-accepting-jobs": True, "printer-location": "jupiter"}
job = [{"job-id": 40, "job-state": 3}]
out = [
  a.printer_info(canon, None, job, False),                                     # skutecny pripad
  a.printer_info(canon, None, [], None),                                       # bez serioveho cisla
  a.printer_info(dict(canon, **{"printer-state": 3, "printer-state-message": ""}), None, [], False),
  a.printer_info(dict(canon, **{"printer-state": 4, "printer-state-message":
                 "Waiting for printer to become available."}), None, job, False),
  a.printer_info(dict(canon, **{"printer-state-message": "Paused"}), None, [], True),
  a.printer_info(dict(canon, **{"printer-state": 3, "printer-state-message": ""}), None, [], True),
  a.printer_info({"device-uri": "dnssd://HP._ipp._tcp.local/?uuid=1", "printer-state": 3,
                  "printer-is-accepting-jobs": True}, {"online": False}, job),
  a.printer_info({"device-uri": "dnssd://Canon%%20USB._ipp._tcp.local/?uuid=2", "printer-state": 3,
                  "printer-location": "USB", "printer-is-accepting-jobs": True}, {"online": False}, []),
]
print(json.dumps(out, ensure_ascii=False))
""" % {"uri": CANON_URI}

    def info(self, lang):
        env = {**os.environ, "LANG": lang, "LC_ALL": lang, "LUXOS_I18N_DIR": I18N,
               "PYTHONPATH": FILES + os.pathsep + I18N}
        r = subprocess.run([sys.executable, "-c", self.CODE, os.path.join(FILES, "luxos-printers")],
                           capture_output=True, text=True, env=env, timeout=60)
        if r.returncode and "Gtk" in r.stderr and "display" in r.stderr.lower():
            self.skipTest("Gtk needs a display (run under xvfb-run)")
        self.assertEqual(r.returncode, 0, r.stderr)
        return [tuple(x) for x in json.loads(r.stdout)]

    def test_english(self):
        auto = "Not connected – connect the USB cable or turn the printer on. Documents will print automatically."
        self.assertEqual(self.info("C.UTF-8"), [
            (auto, "warn", False, "unplugged_auto"),
            (auto, "warn", False, "unplugged_auto"),
            ("Not connected – connect the USB cable or turn the printer on", "warn", False, "unplugged"),
            (auto, "warn", False, "unplugged_auto"),                # ne "Printing…"
            ("Paused", "err", True, "paused"),                      # pozastaveno uzivatelem: Obnovit
            ("Ready", "ok", False, None),
            ("Offline – turn the printer on. Documents will print automatically.", "warn", False, "offline_auto"),
            ("Not connected – connect the USB cable or turn the printer on", "warn", False, "unplugged"),   # ipp-usb
        ])

    def test_czech(self):
        res = self.info("cs_CZ.UTF-8")
        self.assertEqual(res[0][0], "Nepřipojená – připojte kabel USB nebo zapněte tiskárnu. "
                                    "Dokumenty se vytisknou automaticky.")


# ---------------------------------------------------------------- skripty v bashi

class NotifyScript(unittest.TestCase):
    """luxos-printing-notify: texty a hint transient (kratke stavove upozorneni nezustane ve zvonku)."""

    def setUp(self):
        self.tmp = tmpdir()
        os.makedirs(os.path.join(self.tmp, "bin"))
        self.log = os.path.join(self.tmp, "notify-send.log")
        fake = os.path.join(self.tmp, "bin", "notify-send")
        with open(fake, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, os, sys\n"
                    f"open({self.log!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
        os.chmod(fake, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def send(self, *args, lang="en_US.UTF-8"):
        if os.path.exists(self.log):
            os.remove(self.log)
        env = {"PATH": os.path.join(self.tmp, "bin") + os.pathsep + "/usr/bin:/bin", "LANG": lang, "LC_ALL": lang,
               "LUXOS_I18N_DIR": I18N, "HOME": self.tmp}
        r = subprocess.run(["bash", os.path.join(FILES, "luxos-printing-notify"), *args], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            return json.loads(f.readline())

    def test_waiting_usb_transient(self):
        a = self.send("waiting", "Canon MF4100 Series", "usb")
        self.assertIn("boolean:transient:true", a)
        self.assertEqual(a[-2:], ["Printer “Canon MF4100 Series” is not connected",
                                  "Connect the USB cable or turn the printer on. The document will print automatically."])

    def test_waiting_long_persistent(self):
        a = self.send("waiting-long", "HP", "network")
        self.assertNotIn("boolean:transient:true", a)
        self.assertEqual(a[-2:], ["A document is waiting for printer “HP”",
                                  "Turn the printer on and connect it to the same network. "
                                  "The document will print automatically."])

    def test_resumed_transient(self):
        a = self.send("resumed", "Canon")
        self.assertIn("boolean:transient:true", a)
        self.assertEqual(a[-1], "Waiting documents are printing now.")

    def test_ready_unchanged(self):
        a = self.send("printer", "HP")
        self.assertNotIn("boolean:transient:true", a)
        self.assertEqual(a[-2], "Printer “HP” is ready")

    @unittest.skipUnless(os.path.exists("/usr/lib/luxos/i18n.sh"), "i18n.sh (luxos-i18n) is not installed")
    def test_czech(self):
        a = self.send("waiting", "Canon", "usb", lang="cs_CZ.UTF-8")
        self.assertEqual(a[-2], "Tiskárna „Canon“ není připojená")
        self.assertIn("vytiskne automaticky", a[-1])


class WatchScript(unittest.TestCase):
    """luxos-printing-watch: sync po udalosti avahi, pravidelne autoresume jen kdyz ma smysl."""

    def setUp(self):
        self.tmp = tmpdir()
        b = os.path.join(self.tmp, "bin")
        os.makedirs(b)
        self.calls = os.path.join(self.tmp, "helper.log")
        self.active = os.path.join(self.tmp, "active")
        scripts = {
            "helper": f"#!/bin/sh\necho \"$@\" >> {self.calls}\n",
            "systemctl": f"#!/bin/sh\n[ -e {self.active} ]\n",
            # jedna nova sluzba po 0,3 s, pak ticho (avahi-browse bezi dal)
            "avahi-browse": "#!/bin/sh\ncase \"$*\" in *_ipp._tcp*) sleep 0.3; "
                            "echo '+;wlan0;IPv4;HP;_ipp._tcp;local';; esac\nexec sleep 30\n",
        }
        for n, text in scripts.items():
            p = os.path.join(b, n)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, 0o755)
        self.conf = os.path.join(self.tmp, "printers.conf")
        self.env = {"PATH": b + os.pathsep + "/usr/bin:/bin", "LUXOS_PRINTING_HELPER": os.path.join(b, "helper"),
                    "LUXOS_PRINTING_CUPS_CONF": self.conf, "LUXOS_PRINTING_WATCH_INTERVAL": "1",
                    "LUXOS_PRINTING_WATCH_FIRST": "1"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def watch(self, seconds):
        # vlastni skupina procesu: skript konci "kill 0" a nesmi zasahnout test
        p = subprocess.Popen(["bash", os.path.join(FILES, "luxos-printing-watch")], env=self.env,
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(seconds)
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=10)
        try:
            with open(self.calls) as f:
                return f.read().split("\n")
        except OSError:
            return []

    def test_idle_system_only_sync(self):
        """cupsd nebezi, zadna zastavena fronta: zadny Python kazdych 30 s, jen sync po udalosti."""
        calls = self.watch(6.5)
        self.assertIn("sync", calls)
        self.assertNotIn("autoresume", calls)

    def test_periodic_when_cups_runs(self):
        open(self.active, "w").close()
        calls = self.watch(6.5)
        self.assertIn("sync", calls)
        self.assertGreaterEqual(calls.count("autoresume"), 2)

    def test_periodic_when_queue_stopped(self):
        with open(self.conf, "w") as f:
            f.write("<Printer X>\nDeviceURI usb://X/Y\nState Stopped\nStateMessage Unplugged or turned off\n</Printer>\n")
        calls = self.watch(4.5)
        self.assertGreaterEqual(calls.count("autoresume"), 1)


class Rules(unittest.TestCase):
    def test_udev_add_triggers_sync(self):
        with open(os.path.join(FILES, "udev", "99-zz-luxos-printing.rules")) as f:
            text = f.read()
        self.assertIn('ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_USB_INTERFACES}=="*:0701??:*"',
                      text)
        self.assertIn('SYSTEMD_WANTS}+="luxos-printing-sync.service"', text)

    def test_upgrade_restarts_watch_and_migrates(self):
        with open(os.path.join(HERE, "..", "luxos-printing.install")) as f:
            text = f.read()
        self.assertIn("systemctl try-restart luxos-printing-watch.service", text)
        self.assertIn("luxos-printing-helper migrate", text)

    def test_translations(self):
        """Nove texty jsou ve vsech 12 jazycich."""
        texts = ["Printer “%s” is not connected", "A document is waiting for printer “%s”",
                 "Turn the printer on and connect it to the same network. The document will print automatically.",
                 "Connect the USB cable or turn the printer on. The document will print automatically.",
                 "Printer “%s” is connected again", "Waiting documents are printing now.",
                 "Not connected – connect the USB cable or turn the printer on",
                 "Not connected – connect the USB cable or turn the printer on. Documents will print automatically.",
                 "Offline – turn the printer on. Documents will print automatically.", "Waiting for the printer"]
        tsvs = sorted(f for f in os.listdir(I18N) if f.endswith(".tsv"))
        self.assertEqual(len(tsvs), 12)
        for tsv in tsvs:
            with open(os.path.join(I18N, tsv), encoding="utf-8") as f:
                have = {line.split("\t", 1)[0]: line.rstrip("\n").split("\t", 1)[1] for line in f
                        if "\t" in line and not line.startswith("#")}
            for t in texts:
                self.assertIn(t, have, f"{tsv}: {t}")
                self.assertEqual(t.count("%s"), have[t].count("%s"), f"{tsv}: {t}")


if __name__ == "__main__":
    unittest.main()
