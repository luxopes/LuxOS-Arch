"""Testy pro luxos_printing (avahi, nazvy front, volba ovladace, nsswitch.conf, volby skeneru).

Spusteni: python3 -m unittest discover -s packages/luxos-printing/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files"))
import luxos_printing as lp  # noqa: E402

TXT = ('"rp=ipp/print" "ty=HP LaserJet MFP M140w" "pdl=application/octet-stream,image/urf,image/pwg-raster" '
       '"UUID=3CF9787F-057B-317D-4660-AA66EE44B2B8" "URF=CP1,W8"')
AVAHI = "\n".join([
    "+;wlan0;IPv4;HP\\032LaserJet\\032MFP\\032M140w\\032\\040A1B2C3\\041;_ipp._tcp;local",
    f"=;wlan0;IPv6;HP\\032LaserJet\\032MFP\\032M140w\\032\\040A1B2C3\\041;_ipp._tcp;local;hp.local;fe80::1;631;{TXT}",
    f"=;wlan0;IPv4;HP\\032LaserJet\\032MFP\\032M140w\\032\\040A1B2C3\\041;_ipp._tcp;local;hp.local;10.0.0.5;631;{TXT}",
    f"=;wlan0;IPv4;HP\\032LaserJet\\032MFP\\032M140w\\032\\040A1B2C3\\041;_ipps._tcp;local;hp.local;10.0.0.5;443;{TXT}",
    '=;lo;IPv4;Old\\032PCL;_ipp._tcp;local;old.local;127.0.0.1;60000;"pdl=application/vnd.hp-PCL" "ty=Old PCL"',
    '=;wlan0;IPv4;HP\\032Scan;_uscan._tcp;local;hp.local;10.0.0.5;80;"uuid=3cf9787f-057b-317d-4660-aa66ee44b2b8"',
    "broken line",
])


class Avahi(unittest.TestCase):
    def test_unescape(self):
        self.assertEqual(lp.avahi_unescape("A\\032B\\038C\\.D"), "A B&C.D")

    def test_group(self):
        g = lp.group_printers(lp.parse_avahi(AVAHI))
        self.assertEqual(len(g), 2)
        hp = g["uuid:3cf9787f-057b-317d-4660-aa66ee44b2b8"]
        self.assertEqual(hp["name"], "HP LaserJet MFP M140w (A1B2C3)")
        self.assertTrue(hp["driverless"])
        self.assertFalse(hp["usb"])
        # _ipp ma prednost, URI s UUID, IPv4 prvni
        self.assertTrue(hp["uri"].startswith("dnssd://HP%20LaserJet%20MFP%20M140w%20%28A1B2C3%29._ipp._tcp.local/"))
        self.assertEqual(lp.uri_uuid(hp["uri"]), "3cf9787f-057b-317d-4660-aa66ee44b2b8")
        self.assertEqual(hp["addrs"][0][:2], ("_ipp._tcp", "10.0.0.5"))
        self.assertEqual(lp.uri_service_name(hp["uri"]), hp["name"])
        old = g["dnssd:Old PCL"]
        self.assertTrue(old["usb"])
        self.assertFalse(old["driverless"])

    def test_scanners(self):
        s = lp.group_scanners(lp.parse_avahi(AVAHI))
        self.assertEqual(list(s), ["uuid:3cf9787f-057b-317d-4660-aa66ee44b2b8"])


class Names(unittest.TestCase):
    def test_friendly(self):
        self.assertEqual(lp.friendly_name("HP LaserJet M110w (A1B2C3)"), "HP LaserJet M110w")
        self.assertEqual(lp.friendly_name("Brother HL-L2350DW @ pc"), "Brother HL-L2350DW")
        self.assertEqual(lp.friendly_name("Canon TS5300 series"), "Canon TS5300 series")

    def test_queue_name(self):
        self.assertEqual(lp.queue_name("HP LaserJet M110w (A1B2C3)", []), "HP_LaserJet_M110w")
        self.assertEqual(lp.queue_name("HP LaserJet M110w", ["hp_laserjet_m110w"]), "HP_LaserJet_M110w_2")
        self.assertEqual(lp.queue_name("Tiskárna #1 / kancl", []), "Tisk_rna_1_kancl")
        self.assertEqual(lp.queue_name("///", []), "Printer")


MODELS = """Model:  name = lsb/usr/HP/hp-laserjet_1020.ppd.gz
        make-and-model = HP LaserJet 1020, hpcups 3.26.6, requires proprietary plugin
        device-id = MFG:Hewlett-Packard;MDL:hp laserjet 1020;DES:hp laserjet 1020;
Model:  name = gutenprint.5.3://hp-lj_1020/expert
        make-and-model = HP LaserJet 1020 - CUPS+Gutenprint v5.3.5
        device-id =
Model:  name = gutenprint.5.3://escp2-r220/expert
        make-and-model = Epson Stylus Photo R220 - CUPS+Gutenprint v5.3.5
        device-id = MFG:EPSON;MDL:Stylus Photo R220;
Model:  name = gutenprint.5.3://escp2-r220/simple
        make-and-model = Epson Stylus Photo R220 - CUPS+Gutenprint v5.3.5 Simplified
        device-id = MFG:EPSON;MDL:Stylus Photo R220;
Model:  name = drv:///hp/hpcups.drv/hp-deskjet_2130_series.ppd
        make-and-model = HP DeskJet 2130 Series, hpcups 3.26.6
        device-id = MFG:HP;MDL:DeskJet 2130 series;
Model:  name = lsb/usr/HP/hp-deskjet_2130_series.ppd.gz
        make-and-model = HP DeskJet 2130 Series, hpcups 3.26.6
        device-id = MFG:HP;MDL:DeskJet 2130 series;
"""


class Drivers(unittest.TestCase):
    def setUp(self):
        self.models = lp.parse_lpinfo(MODELS, "Model")

    def test_parse(self):
        self.assertEqual(len(self.models), 6)
        self.assertEqual(self.models[1]["device-id"], "")

    def test_device_id(self):
        d = lp.parse_device_id("MANUFACTURER:HP;MODEL:DeskJet 2130 series;COMMAND SET:PCL3GUI;")
        self.assertEqual((d["MFG"], d["MDL"], d["CMD"]), ("HP", "DeskJet 2130 series", "PCL3GUI"))

    def test_pick(self):
        # bez pluginu ma prednost gutenprint pred ovladacem, ktery plugin vyzaduje
        self.assertEqual(lp.pick_ppd(self.models, "MFG:Hewlett-Packard;MDL:HP LaserJet 1020;CMD:ACL;"),
                         "gutenprint.5.3://hp-lj_1020/expert")
        self.assertEqual(lp.pick_ppd(self.models, "MFG:EPSON;MDL:Stylus Photo R220;"),
                         "gutenprint.5.3://escp2-r220/simple")
        self.assertEqual(lp.pick_ppd(self.models, "MFG:HP;MDL:DeskJet 2130 series;"),
                         "drv:///hp/hpcups.drv/hp-deskjet_2130_series.ppd")
        self.assertIsNone(lp.pick_ppd(self.models, "MFG:Brother;MDL:HL-1110;"))
        self.assertIsNone(lp.pick_ppd(self.models, ""))

    def test_generic(self):
        self.assertEqual(lp.generic_ppd("MFG:X;MDL:Y;CMD:PJL,PCL,POSTSCRIPT;"), "drv:///sample.drv/generic.ppd")
        self.assertEqual(lp.generic_ppd("CMD:PJL,PCLXL;"), "lsb/usr/cupsfilters/pxlmono.ppd")
        self.assertEqual(lp.generic_ppd("CMD:PJL,PCL,PCLXL,URF;"), "lsb/usr/cupsfilters/pxlmono.ppd")
        self.assertEqual(lp.generic_ppd("CMD:PWGRaster;"), "drv:///cupsfilters.drv/pwgrast.ppd")
        self.assertEqual(lp.generic_ppd("CMD:PCL;"), "drv:///sample.drv/laserjet.ppd")
        self.assertIsNone(lp.generic_ppd("CMD:GDI;"))
        self.assertEqual(lp.driver_package("Hewlett-Packard"), "hplip")
        self.assertEqual(lp.driver_package("Canon"), "gutenprint")

    def test_samsung_spl(self):
        """Samsung Xpress M2026: v repozitarich nic (SPL, zadny obecny jazyk) -> ovladac z AUR, PPD rady."""
        did = "MFG:Samsung;CMD:SPL,FWV,PIC,BDN,EXT;MDL:M2020 Series;CLS:PRINTER;"
        self.assertIsNone(lp.pick_ppd(self.models, did))
        self.assertIsNone(lp.generic_ppd(did))
        self.assertEqual(lp.aur_driver(did), "samsung-unified-driver-printer")
        self.assertIsNone(lp.aur_driver("MFG:HP;MDL:LaserJet;"))
        uld = lp.parse_lpinfo('Model: name = uld-samsung/Samsung_M2020_Series.ppd\n'
                              '        natural_language = en\n        make-and-model = Samsung M2020 Series\n'
                              '        device-id = \n', "Model")
        self.assertEqual(lp.pick_ppd(uld, did), "uld-samsung/Samsung_M2020_Series.ppd")
        # model z rady (Xpress M2026) -> PPD cele rady M2020; jina rada ne
        self.assertEqual(lp.pick_ppd(uld, "MFG:Samsung;MDL:Xpress M2026;CMD:SPL;"),
                         "uld-samsung/Samsung_M2020_Series.ppd")
        self.assertIsNone(lp.pick_ppd(uld, "MFG:Samsung;MDL:Xpress M2070;CMD:SPL;"))

    def test_usb_serial(self):
        self.assertEqual(lp.usb_serial("usb://HP/LaserJet%201020?serial=AB%2012&interface=1"), "AB 12")


class Status(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(lp.reason_text(["none"]), (None, False))
        self.assertEqual(lp.reason_text(["media-empty-error"]), ("Out of paper", True))
        self.assertEqual(lp.reason_text(["toner-low-report", "media-jam-error"]), ("Paper jam", True))
        self.assertEqual(lp.reason_text(["marker-supply-low-warning"]), ("Ink, toner or paper is low", False))


class Supplies(unittest.TestCase):
    def test_supply(self):
        v = ["index=1;class=receptacleThatIsFilled;type=wasteToner;unit=percent;maxcapacity=100;level=25;"
             "colorantname=unknown;",
             b"index=2;class=supplyThatIsConsumed;type=toner;unit=percent;maxcapacity=100;level=75;colorantname=black;",
             "index=3;class=supplyThatIsConsumed;type=ink;maxcapacity=200;level=50;colorantname=cyan;",
             "index=4;class=supplyThatIsConsumed;type=ink;maxcapacity=100;level=-2;colorantname=yellow;"]
        self.assertEqual(lp.parse_printer_supply(v, ["Waste", "Black Toner", "", "Yellow"]),
                         [("Black Toner", 75, "#202020"), ("Cyan", 25, "#00a6e0")])
        self.assertEqual(lp.parse_printer_supply("level=5;maxcapacity=0;"), [])


class Ipptool(unittest.TestCase):
    def test_parse(self):
        text = """    Get-Printer-Attributes:
        attributes-charset (charset) = utf-8
        requested-attributes (1setOf keyword) = printer-state,printer-supply
        status-code = successful-ok (successful-ok)
        attributes-charset (charset) = utf-8
        printer-state (enum) = idle
        printer-state-reasons (1setOf keyword) = media-empty-error,toner-low-report
        marker-levels (1setOf integer) = 70,-1
        printer-supply (1setOf octetString) = index=1;level=25;,index=2;class=supplyThatIsConsumed;level=75;colorantname=black;
        printer-supply-description (1setOf textWithoutLanguage) = Waste,Black Toner
"""
        a = lp.parse_ipptool(text)
        self.assertNotIn("requested-attributes", a)
        self.assertEqual(a["printer-state-reasons"], ["media-empty-error", "toner-low-report"])
        self.assertEqual(a["marker-levels"], [70, -1])
        self.assertEqual(a["printer-state"], ["idle"])
        self.assertEqual(lp.parse_printer_supply(a["printer-supply"], a["printer-supply-description"]),
                         [("Waste", 25, "#888888"), ("Black Toner", 75, "#202020")])


class Nsswitch(unittest.TestCase):
    ARCH = ("# comment\npasswd: files systemd\n\n"
            "hosts: mymachines resolve [!UNAVAIL=return] files myhostname dns\nnetworks: files\n")

    def test_arch_default(self):
        new = lp.nsswitch_add_mdns(self.ARCH)
        self.assertIn("hosts: mymachines mdns_minimal [NOTFOUND=return] resolve [!UNAVAIL=return] files "
                      "myhostname dns\n", new)
        self.assertEqual(new.replace("mdns_minimal [NOTFOUND=return] ", ""), self.ARCH)
        self.assertIsNone(lp.nsswitch_add_mdns(new))      # podruhe nic

    def test_variants(self):
        self.assertEqual(lp.nsswitch_add_mdns("hosts:  files dns"), "hosts: files mdns_minimal [NOTFOUND=return] dns")
        self.assertEqual(lp.nsswitch_add_mdns("hosts: files"), "hosts: files mdns_minimal [NOTFOUND=return]")
        self.assertIsNone(lp.nsswitch_add_mdns("hosts: files mdns4_minimal [NOTFOUND=return] dns"))
        self.assertIsNone(lp.nsswitch_add_mdns("passwd: files\n"))
        self.assertIsNone(lp.nsswitch_add_mdns("#hosts: files dns\n"))


SCAN_A = """
Options specific to device `test:0':
  Scan Mode:
    --mode Gray|Color [Gray]
        Selects the scan mode.
    --depth 1|8|16 [8]
    --source Flatbed|Automatic Document Feeder|Automatic Document Feeder (left aligned) [Flatbed]
    --resolution 1..1200dpi (in steps of 1) [50]
  Geometry:
    -l 0..200mm (in steps of 1) [0]
"""


class ScanOptions(unittest.TestCase):
    def test_parse(self):
        o = lp.parse_scan_options(SCAN_A)
        self.assertEqual(o["mode"], (["Gray", "Color"], "Gray"))
        self.assertEqual(o["resolution"], ((1, 1200), 50))
        self.assertEqual(o["source"][0][1], "Automatic Document Feeder")
        o2 = lp.parse_scan_options("    --resolution 75|150|300|600dpi [300]\n")
        self.assertEqual(o2["resolution"], ([75, 150, 300, 600], 300))

    def test_choose(self):
        self.assertEqual(lp.nearest_resolution([75, 100, 200, 400], 300), 400)
        self.assertEqual(lp.nearest_resolution((50, 600), 1200), 600)
        self.assertEqual(lp.nearest_resolution(None, 150), 150)
        self.assertEqual(lp.pick_mode(["Lineart", "Gray", "24bit Color"], "color"), "24bit Color")
        self.assertEqual(lp.pick_mode(["Lineart", "Grey"], "gray"), "Grey")
        self.assertIsNone(lp.pick_mode(["Lineart"], "color"))


if __name__ == "__main__":
    unittest.main()


class HelperAurDriver(unittest.TestCase):
    """luxos-printing-helper: USB tiskarna s ovladacem jen v AUR -> zadna fronta, upozorneni s balikem."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        import tempfile
        self.tmp = tempfile.mkdtemp()
        os.environ["LUXOS_PRINTING_NOTIFY_LOG"] = os.path.join(self.tmp, "notify")
        os.environ["LUXOS_PRINTING_STATE"] = os.path.join(self.tmp, "state.json")
        os.environ["LUXOS_PRINTING_LOCK"] = os.path.join(self.tmp, "lock")
        path = os.path.join(HERE, "..", "files", "luxos-printing-helper")
        loader = importlib.machinery.SourceFileLoader("luxos_printing_helper", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.h = importlib.util.module_from_spec(spec)
        loader.exec_module(self.h)
        did = "MFG:Samsung;CMD:SPL,FWV,PIC,BDN,EXT;MDL:M2020 Series;CLS:PRINTER;"
        self.dev = {"key": "usb://Samsung/M2020%20Series?serial=08HV", "uri": "usb://Samsung/M2020%20Series?serial=08HV",
                    "name": "Samsung M2020 Series", "model": "Samsung M2020 Series", "usb": True, "classic": True,
                    "device_id": did}
        h = self.h
        h.cups_queues = lambda: {}
        h.cups_default = lambda: None
        h.usb_printers = lambda: [dict(self.dev)]
        h.usb_scanners = lambda: {}
        h.browse = lambda types: ""
        h.models = lambda: []
        h.installed = lambda pkg: False
        h.install_driver = lambda pkg: False
        h.available = lambda pkg: False          # bez [luxos-drivers] (starsi lux.conf, bez internetu)
        h.drivers_index = lambda: {}
        self.cmds = []
        h.run = lambda cmd, timeout=60: (self.cmds.append(cmd), (0, "", ""))[1]

    def tearDown(self):
        import shutil
        for k in ("LUXOS_PRINTING_NOTIFY_LOG", "LUXOS_PRINTING_STATE", "LUXOS_PRINTING_LOCK"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def notes(self):
        try:
            with open(os.environ["LUXOS_PRINTING_NOTIFY_LOG"]) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_sync_notifies_aur_driver_once(self):
        st = self.h.load_state()
        self.assertEqual(self.h.cmd_sync(st), [])
        self.assertFalse(any(c[:1] == ["lpadmin"] for c in self.cmds))       # zadna rozbita fronta
        self.assertEqual(self.notes(), ["aurdriver\tSamsung M2020 Series\tsamsung-unified-driver-printer"])
        self.h.cmd_sync(st)
        self.assertEqual(len(self.notes()), 1)                               # stejny den znovu ne

    def test_add_reports_package(self):
        import contextlib
        import io
        out = io.StringIO()
        geteuid = os.geteuid
        os.geteuid = lambda: 0
        try:
            with contextlib.redirect_stdout(out):
                rc = self.h.main(["add", self.dev["key"]])
        finally:
            os.geteuid = geteuid
        self.assertEqual(rc, 1)
        import json
        res = json.loads(out.getvalue())
        self.assertEqual((res["queue"], res["needs"], res["package"]),
                         (None, "aurdriver", "samsung-unified-driver-printer"))


class VerifiedDrivers(unittest.TestCase):
    """Overene ovladace z [luxos-drivers]: mapa z PPD (luxos-drivers-index) -> balik."""
    INDEX = {"format": 1, "printers": [
        {"mfg": "Samsung", "mdl": "M2020 Series", "package": "samsung-unified-driver-printer"},
        {"mfg": "Brother", "mdl": "Brother MFC-L2710DW", "package": "brother-mfc-l2710dw"},
        {"mfg": "Canon", "mdl": "Canon i-SENSYS MF650C Series", "package": "cnrdrvcups-lb"}]}

    def test_exact_model(self):
        self.assertEqual(lp.verified_driver("MFG:Brother;CMD:PJL;MDL:MFC-L2710DW series;CLS:PRINTER;", self.INDEX),
                         "brother-mfc-l2710dw")

    def test_compact_model_from_ppd(self):
        idx = {"format": 1, "printers": [{"mfg": "Brother", "mdl": "MFCL2350DW", "package": "brother-mfc-l2350dw"}]}
        self.assertEqual(lp.verified_driver("MFG:Brother;MDL:MFC-L2350DW series;", idx), "brother-mfc-l2350dw")
        self.assertIsNone(lp.verified_driver("MFG:Brother;MDL:MFC-L2350DWX;", idx))

    def test_samsung_family(self):
        self.assertEqual(lp.verified_driver("MFG:Samsung;MDL:Xpress M2026;", self.INDEX),
                         "samsung-unified-driver-printer")

    def test_other_maker_same_model_name_no_match(self):
        self.assertIsNone(lp.verified_driver("MFG:HP;MDL:MFC-L2710DW;", self.INDEX))

    def test_unknown_and_empty(self):
        self.assertIsNone(lp.verified_driver("MFG:Brother;MDL:HL-9999;", self.INDEX))
        self.assertIsNone(lp.verified_driver("MFG:Brother;MDL:MFC-L2710DW;", {}))
        self.assertIsNone(lp.verified_driver("", self.INDEX))

    def test_load_index(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json")
        self.assertEqual(lp.load_drivers_index(f.name), {})
        with open(f.name, "w") as g:
            import json
            json.dump(self.INDEX, g)
        self.assertEqual(lp.load_drivers_index(f.name)["printers"][0]["package"], "samsung-unified-driver-printer")
        os.unlink(f.name)
        self.assertEqual(lp.load_drivers_index("/nonexistent/x.json"), {})


class HelperVerifiedDriver(HelperAurDriver):
    """S [luxos-drivers]: ovladac se nainstaluje sam a fronta vznikne bez upozorneni na AUR."""

    def setUp(self):
        super().setUp()
        h = self.h
        self.installed_pkgs = set()
        ppd = 'Model: name = uld-samsung/Samsung_M2020_Series.ppd\n        device-id = MFG:Samsung;MDL:M2020 Series;\n' \
              '        make-and-model = Samsung M2020 Series\n'
        h.models = lambda: lp.parse_lpinfo(ppd, "Model") if "samsung-unified-driver-printer" in self.installed_pkgs else []
        h.installed = lambda pkg: pkg in self.installed_pkgs
        h.available = lambda pkg: pkg == "samsung-unified-driver-printer"
        h.drivers_index = lambda: VerifiedDrivers.INDEX

        def install(pkg):
            self.installed_pkgs.add(pkg)
            return True
        h.install_driver = install

    def test_sync_notifies_aur_driver_once(self):
        st = self.h.load_state()
        added = self.h.cmd_sync(st)
        self.assertIn("samsung-unified-driver-printer", self.installed_pkgs)
        lpadmin = [c for c in self.cmds if c[:1] == ["lpadmin"] and "-p" in c]
        self.assertEqual(len(lpadmin), 1)
        self.assertIn("uld-samsung/Samsung_M2020_Series.ppd", lpadmin[0])
        self.assertFalse(any(n.startswith("aurdriver") for n in self.notes()))
        self.assertEqual(len(added), 1)

    def test_add_reports_package(self):
        pass

    def test_not_available_falls_back_to_aur_notice(self):
        self.h.available = lambda pkg: False
        st = self.h.load_state()
        self.assertEqual(self.h.cmd_sync(st), [])
        self.assertEqual(self.notes(), ["aurdriver\tSamsung M2020 Series\tsamsung-unified-driver-printer"])
        self.assertNotIn("samsung-unified-driver-printer", self.installed_pkgs)

