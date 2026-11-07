"""Tiskarny a skenery: vychozi tiskarna s naplnemi a tiskovou frontou, druha tiskarna a skener.

CUPS je napodoben falesnym modulem `cups` (pycups) v docasne slozce na zacatku PYTHONPATH - aplikace
nevidi skutecne tiskarny ani frontu a nic v CUPS nezmeni (tisk zkusebni stranky, ruseni uloh jen
vrati uspech). Falesne scanimage/lpq/avahi-browse/ipptool/pkexec z _d.py v PATH."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))

FAKE_CUPS = r'''"""Falesny pycups pro snimky Obchodu (ukazkove tiskarny, nic se nikam neposila)."""


class IPPError(Exception):
    pass


PRINTERS = {
    "Canon_TS5300": {
        "printer-info": "Canon TS5300 series", "printer-make-and-model": "Canon TS5300 series, driverless",
        "device-uri": "usb://Canon/TS5300%20series?serial=1A2B3C", "printer-location": "USB",
        "printer-state": 4, "printer-state-reasons": ["none"], "printer-is-accepting-jobs": True,
        "printer-is-shared": False, "printer-type": 0},
    "HP_LaserJet_MFP_M140w": {
        "printer-info": "HP LaserJet MFP M140w", "printer-make-and-model": "HP LaserJet MFP M140w, driverless",
        "device-uri": "ipp://192.168.1.42/ipp/print", "printer-location": "",
        "printer-state": 3, "printer-state-reasons": ["none"], "printer-is-accepting-jobs": True,
        "printer-is-shared": False, "printer-type": 0},
}
MARKERS = {
    "Canon_TS5300": {"marker-names": ["Black", "Cyan", "Magenta", "Yellow"],
                     "marker-levels": [72, 46, 58, 23],
                     "marker-colors": ["#000000", "#00ACEC", "#EC008C", "#FFE600"],
                     "marker-types": ["ink-cartridge"] * 4},
    "HP_LaserJet_MFP_M140w": {"marker-names": "Black Toner", "marker-levels": 64, "marker-colors": "#000000",
                              "marker-types": "toner-cartridge"},
}
JOBS = {
    41: {"job-name": "Holiday photos.pdf", "job-printer-uri": "ipp://localhost/printers/Canon_TS5300",
         "job-state": 5, "job-originating-user-name": "alex", "time-at-creation": 1767225600},
    42: {"job-name": "Boarding pass.pdf", "job-printer-uri": "ipp://localhost/printers/Canon_TS5300",
         "job-state": 3, "job-originating-user-name": "alex", "time-at-creation": 1767225660},
}


class Connection:
    def __init__(self, *a, **kw):
        pass

    def getPrinters(self):
        return {k: dict(v) for k, v in PRINTERS.items()}

    def getDefault(self):
        return "Canon_TS5300"

    def getJobs(self, *a, **kw):
        return {k: dict(v) for k, v in JOBS.items()}

    def getPrinterAttributes(self, name, *a, **kw):
        if name not in MARKERS:
            raise IPPError(0, "not found")
        return dict(MARKERS[name])

    def printTestPage(self, name, *a, **kw):
        return 43

    def cancelJob(self, *a, **kw):
        return None

    def __getattr__(self, name):
        raise IPPError(0, "not available in the demo: " + name)
'''


def helper():
    spec = importlib.util.spec_from_file_location("shots_group_d", os.path.join(HERE, "_d.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shots(s):
    env = helper().fake_bin(s)
    mods = os.path.join(s.tmp, "fake-python")
    os.makedirs(mods, exist_ok=True)
    with open(os.path.join(mods, "cups.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_CUPS)
    s.python_env("luxos-printing/files")
    env["PYTHONPATH"] = mods + os.pathsep + s.env["PYTHONPATH"]
    p = s.launch_python("luxos-printing/files/luxos-printers", env=env, paths=("luxos-printing/files",))
    win = s.window(pid=p.pid, size=(940, 640))
    s.sleep(3)
    s.capture("1", win)
    # skener v postrannim panelu -> skenovani primo v aplikaci
    s.click(80, 222, win)
    s.sleep(2)
    s.click(684, 173, win)            # druh Barevne
    s.click(837, 460, win)            # Skenovat (falesny scanimage -> ukazkovy recept)
    s.sleep(4)
    s.capture("2", win)
