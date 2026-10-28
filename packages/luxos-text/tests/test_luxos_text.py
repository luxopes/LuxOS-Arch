#!/usr/bin/env python3
"""LuxOS Textovy editor - testy programu luxos-text.

    LUXOS_TEXT_BIN=cesta/k/luxos-text XDG_RUNTIME_DIR=$(mktemp -d) GTK_USE_PORTAL=0 GIO_USE_VFS=local NO_AT_BRIDGE=1 \\
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS xvfb-run -a -s "-screen 0 1280x800x24" dbus-run-session -- \\
        python3 -m unittest -v packages/luxos-text/tests/test_luxos_text.py

Okna se testuji jen pod xvfb-run (nikdy na skutecne obrazovce), kazdy test s vlastnim procesem editoru
a docasnym HOME. Stav okna se cte pres testovaci akce aplikace (LUXOS_TEXT_TEST=1, D-Bus org.gtk.Actions):
test-dump (JSON), test-shot (snimek okna), test-type, test-goto, test-action. Klavesove zkratky
(Ctrl+S, Ctrl+F, Ctrl+H...) a psani jdou skutecnou klavesnici pres xdotool.
LUXOS_TEXT_SHOTS=adresar ulozi snimky svetleho a tmaveho vzhledu.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
FILES = os.path.join(PKG, "files")
ROOT = os.path.abspath(os.path.join(PKG, "..", ".."))
IN_REPO = os.path.isdir(os.path.join(ROOT, "packages", "luxos-i18n", "files"))
I18N_DIR = os.path.join(ROOT, "packages/luxos-i18n/files") if IN_REPO else "/usr/share/luxos/i18n"
BIN = os.environ.get("LUXOS_TEXT_BIN") or shutil.which("luxos-text") or ""
APP_ICON = (os.path.join(ROOT, "packages/luxos-branding/files/icons/luxos-notes.png")
            if os.path.exists(os.path.join(ROOT, "packages/luxos-branding/files/icons/luxos-notes.png"))
            else "/usr/share/icons/hicolor/512x512/apps/luxos-notes.png")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
APP_ID = "cz.luxos.TextEditor"
LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")

# ceska veta "Prilis zlutoucky kun..." - t a d s hackem (0x9D, 0xEF) jsou jen ve Windows-1250
CZ = "Příliš žluťoučký kůň úpěl ďábelské ódy."


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def tsv(lang):
    table = {}
    for line in read(os.path.join(I18N_DIR, lang + ".tsv")).splitlines():
        if "\t" in line and not line.startswith("#"):
            k, v = line.split("\t", 1)
            table[k] = v.strip("\t")
    return table


def source_strings():
    """Vsechny prekladane texty: T("...") v luxos-text.c a nazvy skupin kodovani v text-core.c."""
    src = read(os.path.join(FILES, "luxos-text.c"))
    keys = set(re.findall(r'\bT\("((?:[^"\\]|\\.)*)"\)', src))
    # T("...") pres vic radku (spojene retezce)
    for m in re.finditer(r'\bT\(((?:\s*"(?:[^"\\]|\\.)*"\s*)+)\)', src):
        keys.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
    # zoom: {"Zoom Out", "app.zoom-out", ...}
    keys.update(re.findall(r'\{"(Smaller Text|Default Text Size|Bigger Text)"', src))
    core = read(os.path.join(FILES, "text-core.c"))
    keys.update(re.findall(r'\{"[^"]+", "[^"]+", "([A-Z][a-z][^"]+)", "', core))
    return {k.encode().decode("unicode_escape").encode("latin-1").decode("utf-8") for k in keys}


class SourceTest(unittest.TestCase):
    @unittest.skipUnless(IN_REPO, "needs the LuxOS source tree")
    def test_translations(self):
        """Kazdy text z luxos-text.c je prelozeny ve vsech 12 jazycich (stejne %s a %d)."""
        keys = source_strings()
        self.assertGreater(len(keys), 80)
        for k in ("Central European", "Untitled", "Lines: %s", "Text Editor", "Bigger Text"):
            self.assertIn(k, keys)
        langs = sorted(f[:-4] for f in os.listdir(I18N_DIR) if f.endswith(".tsv"))
        self.assertEqual(tuple(sorted(LANGS)), tuple(langs))
        for lang in langs:
            table = tsv(lang)
            for k in sorted(keys):
                self.assertTrue(table.get(k), f"{lang}: missing {k!r}")
                for fmt in ("%s", "%d"):
                    self.assertEqual(k.count(fmt), table[k].count(fmt), f"{lang}: {k!r}")

    def test_desktop_file(self):
        d = read(os.path.join(FILES, "luxos-text.desktop"))
        for lang in LANGS:
            self.assertIn(f"Name[{lang}]=", d)
            self.assertIn(f"Comment[{lang}]=", d)
            self.assertIn(f"Keywords[{lang}]=", d)
        self.assertIn("Name=Text Editor\n", d)
        self.assertIn("Name[cs]=Textový editor\n", d)
        self.assertIn("Exec=luxos-text %U\n", d)
        self.assertIn("Icon=luxos-notes\n", d)
        self.assertIn("StartupWMClass=luxos-text\n", d)
        mime = re.search(r"^MimeType=(.*)$", d, re.M).group(1).split(";")
        for m in ("text/plain", "text/markdown", "text/x-python", "application/x-shellscript", "application/json"):
            self.assertIn(m, mime)
        self.assertNotIn("text/html", mime)    # HTML otevira prohlizec

    def test_icon(self):
        # vlastni ikona LuxOS luxos-notes (luxos-branding), drive u Mousepadu
        with open(os.path.join(FILES, "luxos-text.c"), encoding="utf-8") as f:
            self.assertIn('#define APP_ICON "luxos-notes"', f.read())

    def test_styles_and_language(self):
        import xml.etree.ElementTree as ET
        for name in ("luxos-light", "luxos-dark"):
            root = ET.parse(os.path.join(FILES, "styles", name + ".xml")).getroot()
            self.assertEqual(root.get("id"), name)
            styles = {s.get("name") for s in root.iter("style")}
            for s in ("text", "selection", "current-line", "line-numbers", "draw-spaces", "def:keyword",
                      "def:string", "def:comment", "def:heading", "search-match"):
                self.assertIn(s, styles, name)
        root = ET.parse(os.path.join(FILES, "language-specs", "lsl.lang")).getroot()
        self.assertEqual(root.get("id"), "lsl")

    @unittest.skipUnless(IN_REPO, "needs the LuxOS source tree")
    def test_default_app(self):
        """Vychozi editor pro text (mimeapps.list v /etc/xdg/luxos) a Dock misto Mousepadu."""
        m = read(os.path.join(ROOT, "packages/luxos-desktop/files/xdg/mimeapps.list"))
        self.assertIn("[Default Applications]", m)
        self.assertRegex(m, r"(?m)^text/plain=luxos-text\.desktop;")
        dconf = read(os.path.join(ROOT, "packages/luxos-desktop/files/dconf/10-luxos"))
        self.assertIn("'luxos-text.dockitem'", dconf)
        self.assertNotIn("mousepad", dconf)
        pkgbuild = read(os.path.join(ROOT, "packages/luxos-desktop/PKGBUILD"))
        deps = pkgbuild.split("depends=(", 1)[1].split("\n)", 1)[0]
        self.assertIn("luxos-text", deps)
        self.assertNotRegex(deps, r"(?m)^[^#]*\bmousepad\b")


@unittest.skipUnless(IN_REPO, "needs the LuxOS source tree")
class IntegrationTest(unittest.TestCase):
    """Vychozi aplikace pres GIO (jako Soubory a "Otevrit pomoci") a jednorazovy prechod z Mousepadu."""

    def test_gio_default_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, data = os.path.join(tmp, "xdg"), os.path.join(tmp, "data")
            os.makedirs(cfg)
            os.makedirs(os.path.join(data, "applications"))
            shutil.copy(os.path.join(ROOT, "packages/luxos-desktop/files/xdg/mimeapps.list"), cfg)
            shutil.copy(os.path.join(FILES, "luxos-text.desktop"), os.path.join(data, "applications"))
            # GIO bere jen aplikace, jejichz program z Exec= je v PATH
            os.makedirs(os.path.join(tmp, "bin"))
            with open(os.path.join(tmp, "bin", "luxos-text"), "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(os.path.join(tmp, "bin", "luxos-text"), 0o755)
            env = dict(os.environ, PATH=os.path.join(tmp, "bin") + ":" + os.environ["PATH"],
                       XDG_CONFIG_DIRS=cfg, XDG_DATA_DIRS=data + ":/usr/share",
                       XDG_CONFIG_HOME=os.path.join(tmp, "home-config"), XDG_DATA_HOME=os.path.join(tmp, "home-data"),
                       XDG_CURRENT_DESKTOP="XFCE")
            code = ("import gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio\n"
                    "for t in ('text/plain', 'text/x-python', 'application/x-shellscript', 'text/markdown', "
                    "'application/json', 'text/x-csrc', 'text/html'):\n"
                    "    a = Gio.AppInfo.get_default_for_type(t, False)\n"
                    "    print(t, a.get_id() if a else None)\n")
            out = subprocess.run(["python3", "-c", code], env=env, capture_output=True, text=True, timeout=30).stdout
            got = dict(line.split(" ", 1) for line in out.splitlines())
            for t in ("text/plain", "text/x-python", "application/x-shellscript", "text/markdown", "application/json",
                      "text/x-csrc"):
                self.assertEqual(got.get(t), "luxos-text.desktop", t)
            self.assertNotEqual(got.get("text/html"), "luxos-text.desktop")

    def test_session_migration_from_mousepad(self):
        src = read(os.path.join(ROOT, "packages/luxos-desktop/files/bin/luxos-session")).splitlines()
        start = next(i for i, line in enumerate(src) if line.startswith("# Textovy editor LuxOS misto Mousepadu"))
        end = next(i for i in range(start, len(src)) if src[i] == "fi")
        block = "\n".join(src[start:end + 1])
        with tempfile.TemporaryDirectory() as tmp:
            conf, stub = os.path.join(tmp, ".config"), os.path.join(tmp, "bin")
            launchers = os.path.join(conf, "plank/dock1/launchers")
            os.makedirs(launchers)
            os.makedirs(stub)
            os.makedirs(os.path.join(conf, "luxos"))
            with open(os.path.join(launchers, "org.xfce.mousepad.dockitem"), "w") as f:
                f.write("[PlankDockItemPreferences]\nLauncher=file:///x/org.xfce.mousepad.desktop\n")
            with open(os.path.join(conf, "mimeapps.list"), "w") as f:
                f.write("[Added Associations]\ntext/plain=org.xfce.mousepad.desktop;\n\n[Default Applications]\n"
                        "text/plain=org.xfce.mousepad.desktop;\nimage/png=ristretto.desktop;\n")
            log = os.path.join(tmp, "calls.log")
            stubs = {
                "luxos-text": "exit 0",
                "gsettings": f'echo "gsettings $*" >> {log}\n'
                             '[[ $1 == get ]] && echo "[\'thunar.dockitem\', \'org.xfce.mousepad.dockitem\']"; exit 0',
                "xfconf-query": f'echo "xfconf $*" >> {log}\n'
                                '[[ " $* " == *" -n "* ]] || printf "Value is an array with 2 items:\\n\\n'
                                'firefox.desktop\\norg.xfce.mousepad.desktop\\n"; exit 0',
            }
            for name, body in stubs.items():
                p = os.path.join(stub, name)
                with open(p, "w") as f:
                    f.write("#!/bin/bash\n" + body + "\n")
                os.chmod(p, 0o755)
            script = f'cfg="{conf}/luxos"\n{block}\n'
            env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=conf, PATH=stub + ":" + os.environ["PATH"])
            for _ in range(2):        # podruhe uz nic (znacka text-editor-migrated)
                r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(os.path.join(conf, "luxos/text-editor-migrated")))
            self.assertFalse(os.path.exists(os.path.join(launchers, "org.xfce.mousepad.dockitem")))
            self.assertIn("luxos-text.desktop", read(os.path.join(launchers, "luxos-text.dockitem")))
            calls = read(log)
            self.assertIn("gsettings set net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/ "
                          "dock-items ['thunar.dockitem', 'luxos-text.dockitem']", calls)
            self.assertIn("-n -t string -s firefox.desktop -t string -s luxos-text.desktop", calls)
            self.assertEqual(calls.count("gsettings set"), 1)
            mime = read(os.path.join(conf, "mimeapps.list"))
            self.assertIn("[Added Associations]\ntext/plain=org.xfce.mousepad.desktop;", mime)
            self.assertIn("[Default Applications]\ntext/plain=luxos-text.desktop;\nimage/png=ristretto.desktop;", mime)


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN or not os.access(BIN, os.X_OK):
            raise unittest.SkipTest("luxos-text binary not found (LUXOS_TEXT_BIN)")

    def test_version(self):
        r = subprocess.run([BIN, "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^luxos-text \S+ \(GtkSourceView 4\.\d+\.\d+\)")

    def test_help(self):
        r = subprocess.run([BIN, "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn("+LINE", r.stdout)


# ---------------------------------------------------------------------------------------------------
class Editor:
    """Spusteny luxos-text s docasnym HOME; ovladani pres D-Bus (org.gtk.Actions) a xdotool."""

    def __init__(self, home, args, env=None, cwd=None):
        self.home = home
        e = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                 XDG_DATA_HOME=os.path.join(home, ".local/share"), XDG_CACHE_HOME=os.path.join(home, ".cache"),
                 XDG_STATE_HOME=os.path.join(home, ".local/state"), LUXOS_TEXT_TEST="1",
                 LUXOS_TEXT_DATA_DIR=FILES, LUXOS_I18N_DIR=I18N_DIR, LANG="en_US.UTF-8", LC_ALL="",
                 LUXOS_TEXT_ICON=APP_ICON, GTK_THEME="WhiteSur-Light")
        e.pop("LANGUAGE", None)
        e.update(env or {})
        self.env = e
        self.errf = open(os.path.join(home, "stderr.log"), "a")
        self.proc = subprocess.Popen([BIN] + list(args), env=e, cwd=cwd or home, stdout=subprocess.DEVNULL,
                                     stderr=self.errf)
        self.dump_path = os.path.join(home, "dump.json")
        self.wait(lambda s: s.get("windows", 0) >= 1 and s.get("xid"), timeout=15)

    def call(self, action, param=None):
        """Aktivuje akci aplikace (app.*) pres D-Bus."""
        if param is None:
            p = "[]"
        elif isinstance(param, int):
            p = f"[<int32 {param}>]"
        else:
            p = "[<'" + param.replace("\\", "\\\\").replace("'", "\\'") + "'>]"
        r = subprocess.run(["gdbus", "call", "--session", "--dest", APP_ID, "--object-path", "/cz/luxos/TextEditor",
                            "--method", "org.gtk.Actions.Activate", action, p, "{}"],
                           capture_output=True, text=True, env=self.env, timeout=10)
        return r.returncode == 0

    def action(self, name):
        """Akce aktivniho okna (win.*), napr. "replace-all" nebo "encoding:WINDOWS-1250"."""
        return self.call("test-action", name)

    def dump(self):
        try:
            os.unlink(self.dump_path)
        except FileNotFoundError:
            pass
        if not self.call("test-dump", self.dump_path):
            return {}
        for _ in range(50):
            if os.path.exists(self.dump_path):
                try:
                    return json.loads(read(self.dump_path))
                except ValueError:
                    pass
            time.sleep(0.05)
        return {}

    def wait(self, cond, timeout=6.0):
        end = time.monotonic() + timeout
        s = {}
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise AssertionError("luxos-text exited: " + read(self.errf.name)[-3000:])
            s = self.dump()
            if s and cond(s):
                return s
            time.sleep(0.1)
        raise AssertionError(f"timeout, last state: {json.dumps(s, ensure_ascii=False)[:1500]}")

    def key(self, *keys):
        s = self.dump()
        xid = str(s["xid"])
        subprocess.run(["xdotool", "windowfocus", "--sync", xid], env=self.env, timeout=10)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "--delay", "40"] + list(keys), env=self.env, timeout=10)
        time.sleep(0.25)

    def type(self, text):
        s = self.dump()
        subprocess.run(["xdotool", "windowfocus", "--sync", str(s["xid"])], env=self.env, timeout=10)
        subprocess.run(["xdotool", "type", "--delay", "20", text], env=self.env, timeout=30)
        time.sleep(0.25)

    def shot(self, path):
        self.call("test-shot", path)
        for _ in range(50):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
            time.sleep(0.05)
        raise AssertionError("no screenshot")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.errf.close()


@unittest.skipUnless(UNDER_XVFB, "GUI tests only under xvfb-run")
class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN or not os.access(BIN, os.X_OK):
            raise unittest.SkipTest("luxos-text binary not found (LUXOS_TEXT_BIN)")
        if not shutil.which("xdotool") or not shutil.which("gdbus"):
            raise unittest.SkipTest("needs xdotool and gdbus")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-text-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".config"))
        self.ed = None

    def tearDown(self):
        if self.ed:
            self.ed.close()
        log = os.path.join(self.home, "stderr.log")
        errors = read(log) if os.path.exists(log) else ""
        shutil.rmtree(self.tmp, ignore_errors=True)
        # zadne chyby GTK/Pango/GLib (CRITICAL) ani chyby v CSS
        bad = [line for line in errors.splitlines() if "CRITICAL" in line or "Theme parsing error" in line]
        self.assertEqual(bad, [])

    def start(self, *args, **kw):
        self.ed = Editor(self.home, [str(a) for a in args], **kw)
        return self.ed

    def write(self, name, data):
        p = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return p

    # --- otevreni, uprava, ulozeni ---
    def test_open_edit_save_keeps_cp1250_crlf(self):
        text = f"{CZ}\r\nDruhý řádek\r\n"
        p = self.write("cesky.txt", text.encode("cp1250"))
        ed = self.start(p)
        s = ed.wait(lambda s: s.get("path") == p)
        self.assertEqual(s["encoding"], "WINDOWS-1250")
        self.assertEqual(s["line_ending"], "CRLF")
        self.assertEqual(s["encoding_label"], "Central European (Windows-1250)")
        self.assertEqual(s["title"], "cesky.txt")
        self.assertEqual(s["text"], f"{CZ}\nDruhý řádek\n")
        self.assertFalse(s["modified"])
        ed.key("ctrl+End")
        ed.type("Hello LuxOS")
        s = ed.wait(lambda s: s["modified"])
        self.assertEqual(s["title"], "cesky.txt — Edited")
        ed.key("ctrl+s")
        s = ed.wait(lambda s: not s["modified"])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), (text + "Hello LuxOS").encode("cp1250"))
        # nedavne soubory v nastaveni
        conf = read(os.path.join(self.home, ".config/luxos/text-editor.conf")) if os.path.exists(
            os.path.join(self.home, ".config/luxos/text-editor.conf")) else ""
        if p not in conf:
            time.sleep(0.8)
            conf = read(os.path.join(self.home, ".config/luxos/text-editor.conf"))
        self.assertIn(p, conf)

    def test_utf16_bom_round_trip(self):
        raw = "\ufeffUTF-16 dokument ✓\n".encode("utf-16-le")
        p = self.write("u16.txt", raw)
        ed = self.start(p)
        s = ed.wait(lambda s: s.get("path") == p)
        self.assertEqual(s["encoding"], "UTF-16LE")
        ed.call("test-type", "!")
        ed.wait(lambda s: s["modified"])
        ed.key("ctrl+s")
        ed.wait(lambda s: not s["modified"])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), "\ufeff!UTF-16 dokument ✓\n".encode("utf-16-le"))

    def test_encoding_and_line_ending_selectors(self):
        p = self.write("a.txt", "řádek\nšest\n")
        ed = self.start(p)
        ed.wait(lambda s: s.get("path") == p)
        ed.action("line-ending:CRLF")
        s = ed.wait(lambda s: s["line_ending"] == "CRLF")
        self.assertTrue(s["modified"])
        ed.key("ctrl+s")
        ed.wait(lambda s: not s["modified"])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), "řádek\r\nšest\r\n".encode())

    def test_status_bar(self):
        p = self.write("stats.md", "# Source Code\nHello, world!\n\n## Build\nDon't stop.\n")
        ed = self.start(p)
        s = ed.wait(lambda s: s.get("path") == p and s.get("lines") == "Lines: 6")
        self.assertEqual(s["chars"], "Characters: 45")
        self.assertEqual(s["words"], "Words: 7")
        self.assertEqual(s["size"], "50 bytes")
        self.assertEqual(s["encoding_label"], "Unicode (UTF-8)")
        self.assertEqual(s["line_ending"], "LF")
        self.assertEqual(s["language"], "Markdown")
        self.assertEqual(s["outline"], ["Source Code", "Build"])
        self.assertEqual(s["outline_label"], "Source Code")
        ed.call("test-goto", 4)
        s = ed.wait(lambda s: s["outline_label"] == "Build")
        self.assertEqual(s["position"], "5:1")

    def test_language_detection(self):
        p = self.write("tool", "#!/usr/bin/env python3\nclass A:\n    def run(self):\n        pass\n")
        ed = self.start(p)
        s = ed.wait(lambda s: s.get("path") == p and s.get("outline"))
        self.assertEqual(s["language_id"], "python3")
        self.assertEqual(s["outline"], ["A", "run"])
        self.assertTrue(s["insert_spaces"])
        q = self.write("hello.lsl", "function motor(power):\n\treturn power\nend\n")
        ed.close()
        ed = self.start(q)
        s = ed.wait(lambda s: s.get("path") == q and s.get("outline"))
        self.assertEqual(s["language"], "LSL")
        self.assertFalse(s["insert_spaces"])     # soubor odsazeny tabulatory

    def test_find_replace(self):
        p = self.write("find.txt", "apple banana apple\ncherry Apple\n")
        ed = self.start(p)
        ed.wait(lambda s: s.get("path") == p)
        ed.key("ctrl+f")
        ed.type("apple")
        s = ed.wait(lambda s: s["find_visible"] and s["find_count"] == "1 of 3")
        ed.key("Return")
        ed.wait(lambda s: s["find_count"] == "2 of 3")
        ed.action("find-case")
        ed.wait(lambda s: s["find_count"].endswith("of 2") or s["find_count"] == "2 found")
        ed.key("Escape")
        s = ed.wait(lambda s: not s["find_visible"])
        # nahrazeni s regularnim vyrazem: Ctrl+H, a.p -> X
        ed.key("ctrl+h")
        ed.key("ctrl+a")
        ed.type("[aA]pple")
        ed.action("find-regex")
        ed.wait(lambda s: s["find_count"].endswith("of 2") or s["find_count"].endswith("found"))
        ed.action("find-case")        # vypnout rozlisovani velikosti
        ed.wait(lambda s: s["find_count"].endswith("of 3") or s["find_count"] == "3 found")
        ed.key("ctrl+h")              # druhe Ctrl+H = pole Nahradit
        ed.type("fruit")
        ed.action("replace-all")
        s = ed.wait(lambda s: s["find_count"] == "3 replaced")
        self.assertEqual(s["text"], "fruit banana fruit\ncherry fruit\n")
        ed.key("ctrl+z")
        s = ed.wait(lambda s: "apple" in s["text"])

    def test_go_to_line(self):
        p = self.write("lines.txt", "".join(f"line {i}\n" for i in range(1, 101)))
        ed = self.start(p)
        ed.wait(lambda s: s.get("path") == p)
        ed.key("ctrl+l")
        ed.key("ctrl+a")
        ed.type("42:3")
        ed.key("Return")
        s = ed.wait(lambda s: s["position"] == "42:3")

    def test_sidebar_tree(self):
        d = os.path.join(self.tmp, "proj")
        self.write("proj/README.md", "# Proj\n")
        self.write("proj/src/main.c", "int main(void) {\n}\n")
        self.write("proj/src/util.py", "def f():\n    pass\n")
        self.write("proj/.hidden", "x")
        os.makedirs(os.path.join(d, "docs"))
        ed = self.start(d, os.path.join(d, "src/util.py"))
        s = ed.wait(lambda s: s.get("path", "") and s["path"].endswith("util.py") and s["sidebar"])
        self.assertEqual(s["root"], d)
        self.assertEqual(s["sidebar_rows"], ["docs", "src", " main.c", " util.py", "README.md"])
        self.assertEqual(s["sidebar_selected"], os.path.join(d, "src/util.py"))
        # novy soubor zvenku se ve stromu objevi
        self.write("proj/src/new.txt", "")
        s = ed.wait(lambda s: " new.txt" in s["sidebar_rows"])
        # sidebar se da skryt (F9)
        ed.key("F9")
        ed.wait(lambda s: not s["sidebar"])

    def test_sidebar_new_file(self):
        """Tlacitko + v postrannim panelu: novy soubor ve vybrane slozce se vytvori a otevre."""
        d = os.path.join(self.tmp, "proj")
        self.write("proj/src/a.txt", "a\n")
        ed = self.start(d, os.path.join(d, "src/a.txt"))
        ed.wait(lambda s: s.get("sidebar_selected") == os.path.join(d, "src/a.txt"))
        # akce otevre modalni dialog - volani D-Bus skonci az po jeho zavreni
        call = subprocess.Popen(["gdbus", "call", "--session", "--dest", APP_ID, "--object-path",
                                 "/cz/luxos/TextEditor", "--method", "org.gtk.Actions.Activate", "test-action",
                                 "[<'new-file'>]", "{}"], env=ed.env, stdout=subprocess.DEVNULL)
        dlg = ""
        for _ in range(50):
            dlg = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^New File$"], env=ed.env,
                                 capture_output=True, text=True).stdout.split()
            if dlg:
                break
            time.sleep(0.1)
        self.assertTrue(dlg, "no New File dialog")
        subprocess.run(["xdotool", "windowfocus", "--sync", dlg[0]], env=ed.env, timeout=10)
        subprocess.run(["xdotool", "key", "ctrl+a"], env=ed.env, timeout=10)
        subprocess.run(["xdotool", "type", "--delay", "20", "notes.md"], env=ed.env, timeout=10)
        subprocess.run(["xdotool", "key", "Return"], env=ed.env, timeout=10)
        call.wait(15)
        new = os.path.join(d, "src/notes.md")
        s = ed.wait(lambda s: s.get("path") == new)
        self.assertTrue(os.path.isfile(new))
        self.assertIn(" notes.md", s["sidebar_rows"])
        self.assertEqual(s["sidebar_selected"], new)
        self.assertEqual(s["language"], "Markdown")
        self.assertEqual(s["tabs"], 2)

    def test_external_change_warning(self):
        p = self.write("ext.txt", "original\n")
        ed = self.start(p)
        ed.wait(lambda s: s.get("path") == p)
        time.sleep(0.3)
        with open(p, "w") as f:
            f.write("changed by another program\n")
        ed.wait(lambda s: s["infobar"])

    def test_unsaved_changes_dialog(self):
        p = self.write("u.txt", "abc\n")
        ed = self.start(p)
        ed.wait(lambda s: s.get("path") == p)
        ed.call("test-type", "X")
        ed.wait(lambda s: s["modified"])
        ed.key("ctrl+w")
        # dialog je modalni - Escape = Zrusit, dokument zustane otevreny
        time.sleep(0.5)
        subprocess.run(["xdotool", "key", "Escape"], env=ed.env, timeout=10)
        s = ed.wait(lambda s: s.get("windows") == 1 and s["modified"])
        # znovu a Enter = Ulozit (vychozi tlacitko)
        ed.key("ctrl+w")
        time.sleep(0.5)
        subprocess.run(["xdotool", "key", "Return"], env=ed.env, timeout=10)
        for _ in range(50):
            if ed.proc.poll() is not None:
                break
            time.sleep(0.1)
        self.assertEqual(read(p), "Xabc\n")

    def test_single_instance_new_window(self):
        a = self.write("a.txt", "A\n")
        b = self.write("b.txt", "B\n")
        c = self.write("c.txt", "C\n")
        ed = self.start(a)
        ed.wait(lambda s: s.get("path") == a)
        t0 = time.monotonic()
        r = subprocess.run([BIN, b, c], env=ed.env, timeout=15, capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assertLess(time.monotonic() - t0, 5)
        s = ed.wait(lambda s: s["windows"] == 2 and s["tabs"] == 2)
        self.assertEqual(s["path"], c)

    def test_window_icons(self):
        # ikona luxos-notes je PNG 512 px (luxos-branding): ze zdroju v repozitari, jinak nainstalovana
        if not os.path.exists(APP_ICON):
            self.skipTest("luxos-notes icon (luxos-branding) not available")
        ed = self.start()
        s = ed.wait(lambda s: s.get("xid"))
        out = ""
        for _ in range(40):
            out = subprocess.run(["xprop", "-len", "4000000", "-id", str(s["xid"]), "_NET_WM_ICON", "WM_CLASS"], env=ed.env,
                                 capture_output=True, text=True).stdout
            if "256 x 256" in out:
                break
            time.sleep(0.1)
        for size in (16, 32, 48, 64, 128, 256):
            self.assertIn(f"Icon ({size} x {size})", out)
        self.assertIn('"luxos-text"', out)

    @unittest.skipUnless(IN_REPO or "Lines: %s\t" in open(os.path.join(I18N_DIR, "cs.tsv"), errors="replace").read()
                         if os.path.exists(os.path.join(I18N_DIR, "cs.tsv")) else False,
                         "Czech translations of luxos-text not available (older luxos-i18n in the build root)")
    def test_czech_ui(self):
        p = self.write("x.txt", "slovo\n")
        ed = self.start(p, env={"LANG": "cs_CZ.UTF-8"})
        s = ed.wait(lambda s: s.get("path") == p and s.get("lines") == "Řádky: 2")
        self.assertEqual(s["lines"], "Řádky: 2")
        self.assertEqual(s["words"], "Slova: 1")
        self.assertEqual(s["language"], "Prostý text")
        self.assertEqual(s["subtitle"].split(" — ")[0], "Textový editor")

    def test_light_and_dark(self):
        p = self.write("demo.md", "# Source Code\n\nLuxOS **Text Editor** with `code`.\n\n```python\n"
                                  "def hello(name):\n    return f\"Hello {name}\"  # greeting\n```\n")
        shots = os.environ.get("LUXOS_TEXT_SHOTS")
        for theme, dark in (("WhiteSur-Light", False), ("WhiteSur-Dark", True)):
            ed = self.start(p, env={"GTK_THEME": theme})
            s = ed.wait(lambda s: s.get("path") == p and s.get("outline"))
            self.assertEqual(s["dark"], dark)
            self.assertEqual(s["scheme"], "luxos-dark" if dark else "luxos-light")
            png = ed.shot(os.path.join(self.tmp, f"shot-{theme}.png"))
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file(png)
            px = pb.get_pixels()
            # pixel v editoru vpravo dole (pozadi textu)
            x, y = pb.get_width() - 40, pb.get_height() - 60
            o = y * pb.get_rowstride() + x * pb.get_n_channels()
            lum = sum(px[o:o + 3]) / 3
            self.assertLess(lum, 80) if dark else self.assertGreater(lum, 200)
            if shots:
                os.makedirs(shots, exist_ok=True)
                shutil.copy(png, os.path.join(shots, f"text-editor-{'dark' if dark else 'light'}.png"))
            ed.close()


if __name__ == "__main__":
    unittest.main()
