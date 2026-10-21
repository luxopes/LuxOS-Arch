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
