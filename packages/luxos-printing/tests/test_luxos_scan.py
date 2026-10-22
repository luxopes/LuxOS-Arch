"""Testy pro luxos_scan (seznam skeneru, volby, chyby, skenovani s falesnym scanimage, nazvy souboru, PDF).

Spusteni: python3 -m unittest discover -s packages/luxos-printing/tests -v
Falesny scanimage je v tests/fake (pridava se na zacatek PATH).
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files"))
import luxos_scan as ls  # noqa: E402

FAKE = os.path.join(HERE, "fake")


class FakePath(unittest.TestCase):
    """Kazdy test s falesnym scanimage na PATH a vlastni docasnou slozkou."""

    def setUp(self):
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = FAKE + os.pathsep + self.old_path
        os.environ.pop("FAKE_SCAN", None)
        self.tmp = tempfile.mkdtemp(prefix="luxos-scan-test-")

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        os.environ.pop("FAKE_SCAN", None)
        shutil.rmtree(self.tmp, ignore_errors=True)


LIST = ("airscan:w1:HP LaserJet MFP M140w\tHP\tHP LaserJet MFP M140w (A1B2C3)\tWSD network scanner\n"
        "airscan:e0:HP LaserJet MFP M140w\tHP\tHP LaserJet MFP M140w (A1B2C3)\teSCL network scanner\n"
        "pixma:04A91234_ABC\tCANON\tCanon TS5300 series\tmultifunction peripheral\n"
        "airscan:e1:Brother USB\tBrother\tDCP-L2530DW USB\teSCL network scanner\n"
        "hpaio:/usb/Deskjet_2130?serial=CN1\tHewlett-Packard\tDeskjet 2130\tall-in-one\n"
        "garbage line\n\n")


class Devices(FakePath):
    def test_parse(self):
        d = ls.parse_devices(LIST)
        self.assertEqual([x["name"] for x in d],
                         ["Brother DCP-L2530DW USB", "Canon TS5300 series", "Hewlett-Packard Deskjet 2130",
                          "HP LaserJet MFP M140w"])
        hp = d[-1]
        # eSCL ma prednost pred WSD, pripona (A1B2C3) pryc
        self.assertEqual(hp["id"], "airscan:e0:HP LaserJet MFP M140w")
        self.assertEqual(hp["conn"], "network")
        self.assertEqual(d[0]["conn"], "usb")          # ipp-usb pres airscan
        self.assertEqual(d[1]["conn"], "")
        self.assertEqual(d[2]["conn"], "usb")
        self.assertEqual(ls.parse_devices(""), [])

    def test_list_fake(self):
        d = ls.list_devices()
        self.assertEqual([x["id"] for x in d], ["pixma:04A91234_ABC", "airscan:e0:HP LaserJet MFP M140w"])
        os.environ["FAKE_SCAN"] = "none"
        self.assertEqual(ls.list_devices(), [])

    def test_list_missing(self):
        os.environ["PATH"] = self.tmp       # zadny scanimage
        with self.assertRaises(OSError):
            ls.list_devices()

    def test_probe(self):
        o = ls.probe_options("test:0")
        self.assertEqual(o["mode"], (["Color", "Gray"], "Color"))
        self.assertEqual(ls.sources(o), [("Flatbed", "flatbed"), ("ADF", "adf"), ("ADF Duplex", "duplex")])
        os.environ["FAKE_SCAN"] = "busy"
        with self.assertRaises(ls.ScanError) as c:
            ls.probe_options("test:0")
        self.assertEqual(c.exception.kind, "busy")
        self.assertIn("Device busy", c.exception.details)


class Settings(unittest.TestCase):
    OPTS = {"mode": (["Lineart", "Gray", "Color"], "Color"), "resolution": ([75, 150, 300, 600, 1200], 150)}

    def test_document_photo(self):
        self.assertEqual(ls.scan_settings(self.OPTS, "document", True),
                         (["--mode", "Color", "--resolution", "300"], 300, False))
        self.assertEqual(ls.scan_settings(self.OPTS, "document", False),
                         (["--mode", "Gray", "--resolution", "300"], 300, True))
        self.assertEqual(ls.scan_settings(self.OPTS, "photo", True, "Flatbed"),
                         (["--mode", "Color", "--resolution", "600", "--source", "Flatbed"], 600, False))
        self.assertEqual(ls.scan_settings(self.OPTS, "photo", False)[0], ["--mode", "Gray", "--resolution", "600"])

    def test_limits(self):
        # skener do 400 dpi a jen v odstinech sedi
        o = {"mode": (["Gray"], "Gray"), "resolution": ((50, 400), 100)}
        self.assertEqual(ls.scan_settings(o, "photo", True), (["--mode", "Gray", "--resolution", "400"], 400, False))
        # jen barevny skener a cernobily dokument
        o = {"mode": (["24bit Color"], "24bit Color")}
        self.assertEqual(ls.scan_settings(o, "document", False), (["--mode", "24bit Color"], 300, True))
        # skener bez voleb (nepodarilo se zjistit) - scanimage pouzije sve vychozi
        self.assertEqual(ls.scan_settings({}, "photo", True), ([], 600, False))

    def test_source_kind(self):
        self.assertEqual(ls.source_kind("Automatic Document Feeder"), "adf")
        self.assertEqual(ls.source_kind("ADF Front"), "adf")
        self.assertEqual(ls.source_kind("ADF Duplex"), "duplex")
        self.assertEqual(ls.source_kind("Flatbed"), "flatbed")
        self.assertIsNone(ls.source_kind("Transparency Unit"))
        self.assertEqual(ls.sources({"source": (["Flatbed"], "Flatbed")}), [])


class Errors(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "scanimage: open of device airscan:e0:X failed: Device busy": "busy",
            "scanimage: sane_read: Document feeder jammed": "jammed",
            "scanimage: sane_start: Document feeder out of documents": "no_paper",
            "scanimage: sane_start: Scanner cover is open": "cover_open",
            "scanimage: open of device pixma:1 failed: Invalid argument": "not_found",
            "scanimage: sane_read: Error during device I/O": "io",
            "scanimage: open of device x failed: Access to resource has been denied": "denied",
            "scanimage: sane_start: Out of memory": "memory",
            "scanimage: sane_start: Operation was cancelled": "cancelled",
            "scanimage: something strange": "unknown",
            "": "unknown",
        }
        for text, kind in cases.items():
            self.assertEqual(ls.error_kind(text), kind, text)

    def test_messages_are_human(self):
        for kind in list(ls.ERRORS) + ["nonsense"]:
            title, hint = ls.error_message(kind)
            self.assertTrue(title)
            for raw in ("sane", "SANE_", "scanimage", "I/O"):
                self.assertNotIn(raw, title + hint)

    def test_clean(self):
        self.assertEqual(ls.clean_stderr("Progress: 10.0%\rProgress: 20.0%\rscanimage: boom\n\n"), "scanimage: boom")


class Scanning(FakePath):
    def test_single(self):
        log = os.path.join(self.tmp, "log")
        os.environ["FAKE_SCAN_LOG"] = log
        try:
            seen = []
            files = ls.Scan("test:0", ["--mode", "Gray", "--resolution", "300"], self.tmp, start=4).run(seen.append)
        finally:
            os.environ.pop("FAKE_SCAN_LOG")
        self.assertEqual(files, [os.path.join(self.tmp, "page-004.pnm")])
        self.assertTrue(ls.pnm_complete(files[0]))
        self.assertEqual(seen[-1], 1.0)
        self.assertGreaterEqual(len(seen), 2)          # prubeh chodi postupne
        self.assertTrue(all(0 <= f <= 1 for f in seen))
        with open(log) as f:
            cmd = f.read()
        self.assertIn("-d test:0 --mode Gray --resolution 300 --format=pnm -p -o", cmd)

    def test_adf_batch(self):
        files = ls.Scan("test:0", ["--source", "ADF"], self.tmp, batch=True, start=3).run()
        self.assertEqual([os.path.basename(f) for f in files], ["page-003.pnm", "page-004.pnm"])

    def test_adf_empty(self):
        os.environ["FAKE_SCAN"] = "adf-empty"
        with self.assertRaises(ls.ScanError) as c:
            ls.Scan("test:0", ["--source", "ADF"], self.tmp, batch=True).run()
        self.assertEqual(c.exception.kind, "no_paper")

    def test_errors(self):
        for mode, kind in (("busy", "busy"), ("jam", "jammed")):
            os.environ["FAKE_SCAN"] = mode
            with self.assertRaises(ls.ScanError) as c:
                ls.Scan("test:0", [], self.tmp).run()
            self.assertEqual(c.exception.kind, kind)
            self.assertNotIn("Progress", c.exception.details)
            self.assertEqual(os.listdir(self.tmp), [])

    def test_partial_file_is_error(self):
        os.environ["FAKE_SCAN"] = "partial"
        with self.assertRaises(ls.ScanError):
            ls.Scan("test:0", [], self.tmp).run()
        self.assertEqual(os.listdir(self.tmp), [])

    def test_missing(self):
        os.environ["PATH"] = self.tmp
        with self.assertRaises(ls.ScanError) as c:
            ls.Scan("test:0", [], self.tmp).run()
        self.assertEqual(c.exception.kind, "missing")

    def test_cancel(self):
        os.environ["FAKE_SCAN"] = "slow"
        scan = ls.Scan("test:0", [], self.tmp)
        res = {}

        def work():
            try:
                scan.run()
            except ls.ScanError as e:
                res["kind"] = e.kind
        t = threading.Thread(target=work)
        t0 = time.monotonic()
        t.start()
        for _i in range(50):
            if scan.proc:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        scan.cancel()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertLess(time.monotonic() - t0, 8)
        self.assertEqual(res.get("kind"), "cancelled")
        self.assertEqual(os.listdir(self.tmp), [])      # rozpracovany list smazany


class Pnm(FakePath):
    def write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_whiten(self):
        p = self.write("a.pnm", b"P5\n3 1\n255\n" + bytes([30, 128, 230]))
        self.assertTrue(ls.whiten(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read()[-3:], bytes([0, 119, 255]))
        self.assertFalse(ls.whiten(self.write("b.pnm", b"P4\n8 1\n\xff")))
        self.assertTrue(ls.pnm_complete(self.write("c.pnm", b"P4\n9 2\n\xff\xff\xff\xff")))
        self.assertFalse(ls.pnm_complete(self.write("d.pnm", b"P6\n2 2\n255\n" + b"\0" * 11)))
        self.assertFalse(ls.pnm_complete(self.write("e.pnm", b"GIF89a")))


class Names(FakePath):
    def test_base(self):
        now = datetime.datetime(2026, 10, 22, 14, 3, 59)
        self.assertEqual(ls.base_name(now=now), "Scan 2026-10-22 14.03")
        self.assertEqual(ls.base_name("Sken %s", now), "Sken 2026-10-22 14.03")
        self.assertEqual(ls.base_name("%s – Scan", now), "2026-10-22 14.03 – Scan")
        self.assertEqual(ls.base_name("Scan", now), "Scan 2026-10-22 14.03")     # preklad bez %s
        self.assertEqual(ls.base_name("a/b %s", now), "a-b 2026-10-22 14.03")

    def test_folder(self):
        self.assertEqual(ls.documents_dir("/home/u/Dokumenty", "/home/u"), "/home/u/Dokumenty")
        self.assertEqual(ls.documents_dir(None, "/home/u"), "/home/u/Documents")
        self.assertEqual(ls.documents_dir("/home/u/", "/home/u"), "/home/u/Documents")

    def test_unique(self):
        self.assertEqual(ls.unique_path(self.tmp, "Scan x", "pdf"), os.path.join(self.tmp, "Scan x.pdf"))
        open(os.path.join(self.tmp, "Scan x.pdf"), "w").close()
        open(os.path.join(self.tmp, "Scan x (2).pdf"), "w").close()
        self.assertEqual(ls.unique_path(self.tmp, "Scan x", "pdf"), os.path.join(self.tmp, "Scan x (3).pdf"))
        self.assertEqual([os.path.basename(p) for p in ls.image_paths(self.tmp, "Scan x", "jpg", 2)],
                         ["Scan x - 1.jpg", "Scan x - 2.jpg"])
        self.assertEqual([os.path.basename(p) for p in ls.image_paths(self.tmp, "Scan x", "jpg", 1)], ["Scan x.jpg"])


def make_jpeg(path_dir, w, h, gray=False):
    """JPEG pres GdkPixbuf (je v systemu kvuli aplikaci), jinak Pillow; None, kdyz neni ani jedno."""
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        pb.fill(0x3366ccff)
        return bytes(pb.save_to_bufferv("jpeg", ["quality"], ["80"])[1])
    except (ImportError, ValueError):
        pass
    try:
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("L" if gray else "RGB", (w, h), 128).save(b, "JPEG")
        return b.getvalue()
    except ImportError:
        return None


class Pdf(FakePath):
    def test_jpeg_info(self):
        sof = b"\xff\xd8\xff\xe0\x00\x04ab\xff\xc0\x00\x0b\x08\x00\x20\x00\x10\x01\x01\x11\x00"
        self.assertEqual(ls.jpeg_info(sof), (16, 32, 1))
        with self.assertRaises(ValueError):
            ls.jpeg_info(b"PNG")
        with self.assertRaises(ValueError):
            ls.jpeg_info(b"\xff\xd8\xff\xda\x00\x02")

    def test_write_pdf(self):
        j1 = make_jpeg(self.tmp, 300, 420)
        if j1 is None:
            self.skipTest("no JPEG encoder")
        j2 = make_jpeg(self.tmp, 600, 400)
        out = os.path.join(self.tmp, "Sken 2026-10-22 14.03.pdf")
        ls.write_pdf(out, [(j1, 100), (j2, 200)], title="Sken říjen")
        self.assertFalse(os.path.exists(out + ".part"))
        with open(out, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertEqual(data.count(b"/Type /Page "), 2)
        self.assertIn(b"/MediaBox [0 0 216.00 302.40]", data)     # 300 px pri 100 dpi = 3 palce
        self.assertIn(b"/MediaBox [0 0 216.00 144.00]", data)
        self.assertIn(j1, data)
        # xref ukazuje presne na objekty
        xref = int(data[data.rindex(b"startxref") + 10:].split()[0])
        entries = data[xref:].split(b"\n")[2:2 + 10]
        for n, e in enumerate(entries[1:], 1):
            off = int(e[:10])
            self.assertTrue(data[off:].startswith(b"%d 0 obj" % n), n)
        if shutil.which("pdfinfo"):
            r = subprocess.run(["pdfinfo", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Pages:           2", r.stdout)
            self.assertIn("Sken říjen", r.stdout)
            self.assertEqual(r.stderr.strip(), "")

    def test_no_pages(self):
        with self.assertRaises(ValueError):
            ls.write_pdf(os.path.join(self.tmp, "x.pdf"), [])

    def test_bad_jpeg_leaves_nothing(self):
        out = os.path.join(self.tmp, "x.pdf")
        with self.assertRaises(ValueError):
            ls.write_pdf(out, [(b"not a jpeg", 300)])
        self.assertEqual(os.listdir(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
