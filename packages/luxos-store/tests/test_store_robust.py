#!/usr/bin/env python3
"""LuxOS Store - odolnost operaci a stahovani (bez site: mistni server, bez instalace balicku).

Jen pod virtualnim displejem (modul nacita GTK), se soukromym XDG_RUNTIME_DIR a docasnym HOME:
    env -u DISPLAY xvfb-run -a python3 packages/luxos-store/tests/test_store_robust.py -v
Overuje: neplatne UTF-8 ve vystupu operace ani chyba pri zpracovani radku nezastavi cteni (operace
by visela na plne roure s drzenym zamkem databaze a okno by ukazovalo prubeh navzdy); useknute
stazeni snimku a ikon (curl s chybou, napr. po --max-time) se do mezipameti neulozi.
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
import http.server
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGES = os.path.abspath(os.path.join(HERE, "..", ".."))
FILES = os.path.join(PACKAGES, "luxos-store", "files")

TMP = tempfile.mkdtemp(prefix="luxos-store-robust-")
os.environ["HOME"] = os.path.join(TMP, "home")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.makedirs(os.environ["HOME"])
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.update({"LUXOS_I18N_DIR": os.path.join(PACKAGES, "luxos-i18n", "files"), "NO_AT_BRIDGE": "1"})

if not os.environ.get("DISPLAY"):
    raise unittest.SkipTest("needs xvfb-run (the module loads GTK)")

loader = importlib.machinery.SourceFileLoader("luxos_store", os.path.join(FILES, "luxos-store"))
spec = importlib.util.spec_from_loader("luxos_store", loader)
store = importlib.util.module_from_spec(spec)
loader.exec_module(store)

FULL = b"\x89PNG" + b"x" * 50000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(FULL)))
        self.end_headers()
        if self.path.startswith("/cut"):
            self.wfile.write(FULL[:1000])          # spojeni skonci driv, nez prisla cela data
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(FULL)

    def log_message(self, *_a):
        pass


class Server:
    def __enter__(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Follow(unittest.TestCase):
    CHILD = ("import sys\n"
             "out = sys.stdout.buffer\n"
             "out.write(b'@@PHASE install\\n')\n"
             "out.write(b'scriptlet: caf\\xe9 \\xff\\xfe broken utf-8\\n')\n"
             "for i in range(5000):\n"
             "    out.write(b'line %d padding padding padding padding\\n' % i)\n"     # vic nez roura (64 KiB)
             "out.write(b'error: final message\\n')\n"
             "sys.exit(3)\n")

    def run_follow(self, on_line, errors="replace"):
        p = subprocess.Popen([sys.executable, "-c", self.CHILD], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors=errors, bufsize=1)
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("r", store.follow(p, on_line, lambda: "")))
        t.start()
        t.join(30)
        if t.is_alive():
            p.kill()
            self.fail("follow() hangs - operation output not drained")
        self.assertIsNotNone(p.returncode)
        return result["r"], p

    def test_invalid_utf8_and_parse_error_do_not_stop_reading(self):
        seen = []

        def on_line(line):
            seen.append(line)
            if "broken" in line:
                raise ValueError("parser bug")
        (rc, err), _p = self.run_follow(on_line)
        self.assertEqual(rc, 3)
        self.assertEqual(err, "parser bug")
        self.assertIn("�", seen[1])
        self.assertEqual(seen[-1], "error: final message\n")      # cteni pokracovalo az do konce

    def test_strict_decoding_still_finishes(self):
        # i kdyby nekdo zapomnel errors="replace": operace dobehne a okno dostane vysledek
        (rc, err), _p = self.run_follow(lambda line: None, errors="strict")
        self.assertEqual(rc, 3)
        self.assertIn("decode", err)

    def test_run_rc_replaces_invalid_utf8(self):
        rc, out = store.run_rc(sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'a\\xffb'); sys.exit(2)")
        self.assertEqual((rc, out), (2, "a�b"))
        self.assertEqual(store.run_rc("/nonexistent/x"), (-1, ""))


@unittest.skipUnless(shutil.which("curl"), "curl not installed")
class Downloads(unittest.TestCase):
    def test_truncated_screenshot_not_cached(self):
        with Server() as base:
            self.assertIsNone(store.fetch_screenshot(base + "/cut/shot.png"))
            self.assertFalse(os.path.exists(store.screen_cache_path(base + "/cut/shot.png")))
            path = store.fetch_screenshot(base + "/ok/shot.png")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), FULL)
        self.assertEqual([n for n in os.listdir(store.SCREEN_CACHE) if n.endswith(".part")], [])

    def test_truncated_icon_not_cached(self):
        cat = store.Catalog()
        good, bad = os.path.join(store.ICON_CACHE, "good.png"), os.path.join(store.ICON_CACHE, "bad.png")
        with Server() as base:
            cat.pending_icons = [("good-app", base + "/ok/i.png", good), ("bad-app", base + "/cut/i.png", bad)]
            changed = cat.fetch_icons()
        self.assertEqual(changed, {"good-app"})
        with open(good, "rb") as f:
            self.assertEqual(f.read(), FULL)
        self.assertFalse(os.path.exists(bad))
        self.assertFalse(os.path.exists(bad + ".part"))

    def test_curl_complete_parsing(self):
        p = os.path.join(TMP, "x.part")
        with open(p, "wb") as f:
            f.write(b"12345")
        self.assertEqual(store.curl_complete(f"0 5 {p}\n18 3 {p}\n0 9 {p}\ngarbage\n"), {p})
        self.assertEqual(store.curl_complete(f"28 5 {p}\n"), set())


if __name__ == "__main__":
    unittest.main()
