"""Testy formatu balicku .lux (luxpkg.sh) bez rootu a bez site: index z mezipameti, prikazy z bin{},
zavislosti v cyklu. Instalace jde do docasneho LUX_ROOT; /usr/local/bin se v testech nedotkne."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUXPKG = os.path.join(HERE, "..", "luxpkg.sh")

PRELUDE = r"""
set -o pipefail
T() { local f=$1; shift; printf "$f" "$@"; }
die() { echo "DIE: $*"; exit 1; }
warn() { echo "WARN: $*"; }
ok() { echo "OK: $*"; }
say() { echo "SAY: $*"; }
ask() { return 1; }
B= R=
source "$LUXPKG"
LUX_ROOT=$T/root LUX_DB=$T/db LUX_SHARE=$T/share LUX_CACHE=$T/cache
lp_verify() { [[ -f $2 ]]; }
# "server": soubory v $T/srv/<adresa bez https://>
curl() {
    local out= url= a
    while (($#)); do a=$1; shift
        case $a in -o) out=$1; shift ;; --connect-timeout|--max-time) shift ;; -*) ;; *) url=$a ;; esac
    done
    cp "$T/srv/${url#https://}" "$out" 2>/dev/null
}
"""


class LuxPkg(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxpkg-test-")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def sh(self, body, env=None):
        e = dict(os.environ, T=self.t, LUXPKG=LUXPKG, **(env or {}))
        r = subprocess.run(["bash", "-c", PRELUDE + body], capture_output=True, text=True, env=e, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def serve(self, url, generated, names):
        d = os.path.join(self.t, "srv", url)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.json"), "w") as f:
            json.dump({"format": 1, "generated": generated,
                       "packages": [{"name": n, "version": "1", "file": n + ".lux"} for n in names]}, f)
        open(os.path.join(d, "index.json.sig"), "w").close()

    def pkg(self, name, meta=None, files=None, links=None):
        d = os.path.join(self.t, "src", name)
        os.makedirs(os.path.join(d, "app"), exist_ok=True)
        with open(os.path.join(d, "lux.json"), "w") as f:
            json.dump(dict({"format": 1, "name": name, "version": "1"}, **(meta or {})), f)
        for rel, text in (files or {}).items():
            p = os.path.join(d, "app", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        for rel, target in (links or {}).items():
            os.symlink(target, os.path.join(d, "app", rel))
        out = os.path.join(self.t, "pkgs")
        os.makedirs(out, exist_ok=True)
        f = os.path.join(out, name + ".lux")
        subprocess.run(["tar", "-C", d, "--zstd", "-cf", f, "lux.json", "app"], check=True)
        return f

    def test_older_signed_index_is_refused(self):
        self.serve("x.invalid/repo", 200, ["new"])
        rc, out = self.sh('LUX_INDEX_URL=https://x.invalid/repo; lp_index | jq -r ".packages[0].name"')
        self.assertEqual(out.strip(), "new")
        self.serve("x.invalid/repo", 100, ["old"])          # podvrzena starsi (platne podepsana) kopie
        rc, out = self.sh('LUX_INDEX_URL=https://x.invalid/repo LUX_REFRESH=1; lp_index | jq -r ".packages[0].name"')
        self.assertEqual(out.strip(), "new")

    def test_cache_belongs_to_one_channel(self):
        self.serve("x.invalid/repo", 200, ["stable-app"])
        self.serve("x.invalid/staging", 50, ["staging-app"])
        self.sh('LUX_INDEX_URL=https://x.invalid/repo; lp_index >/dev/null')
        rc, out = self.sh('LUX_INDEX_URL=https://x.invalid/staging; lp_index | jq -r ".packages[0].name"')
        self.assertEqual(out.strip(), "staging-app")

    def test_bin_outside_app_is_refused(self):
        outside = os.path.join(self.t, "outside")
        with open(outside, "w") as f:
            f.write("x")
        os.chmod(outside, 0o600)
        for meta, links in (({"bin": {"x": "../../../outside"}}, None),
                            ({"bin": {"x": "d/outside"}}, {"d": self.t})):
            f = self.pkg("evil", meta, links=links)
            rc, out = self.sh(f'lp_install_file "{f}" 1')
            self.assertEqual(rc, 1, out)
            self.assertIn("Missing files listed in bin", out)
            self.assertEqual(os.stat(outside).st_mode & 0o777, 0o600)
            self.assertFalse(os.path.exists(os.path.join(self.t, "root", "evil")))

    def test_dependency_cycle_terminates(self):
        self.pkg("aa", {"depends": {"lux": ["bb"]}})
        self.pkg("bb", {"depends": {"lux": ["aa"]}})
        rc, out = self.sh('lp_install_name() { echo "FETCH $1"; lp_install_file "$T/pkgs/$1.lux" 1; }\n'
                          'lp_install_name aa')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("FETCH"), 2, out)
        for n in ("aa", "bb"):
            self.assertTrue(os.path.isfile(os.path.join(self.t, "db", n + ".json")), out)

    def test_invalid_dependency_name_refused(self):
        f = self.pkg("aa", {"depends": {"lux": ["../../etc/x"]}})
        rc, out = self.sh(f'lp_install_file "{f}" 1')
        self.assertEqual(rc, 1, out)
        self.assertIn("Invalid package name", out)

    def test_reinstall_replaces_previous_version(self):
        self.pkg("aa", files={"v": "1"})
        self.sh('lp_install_file "$T/pkgs/aa.lux" 1')
        self.pkg("aa", files={"v": "2"})
        rc, out = self.sh('lp_install_file "$T/pkgs/aa.lux" 1')
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.t, "root", "aa", "app", "v")) as f:
            self.assertEqual(f.read(), "2")
        self.assertEqual([x for x in os.listdir(os.path.join(self.t, "root")) if x.startswith(".")], [])

    def test_broken_update_does_not_run_old_pre_remove(self):
        # vadna nova verze (chybi prikaz z bin) se odmitne a stara zustane cela - bez pre_remove
        self.pkg("aa", files={"v": "1"})
        self.sh('lp_install_file "$T/pkgs/aa.lux" 1')
        script = os.path.join(self.t, "root", "aa", "scripts", "pre_remove")
        os.makedirs(os.path.dirname(script))
        with open(script, "w") as f:
            f.write('touch "$LUX_PREFIX/../pre_remove-ran"\n')
        self.pkg("aa", {"bin": {"aa": "missing"}}, files={"v": "2"})
        rc, out = self.sh('lp_install_file "$T/pkgs/aa.lux" 1')
        self.assertEqual(rc, 1, out)
        self.assertFalse(os.path.exists(os.path.join(self.t, "root", "pre_remove-ran")))
        self.pkg("aa", files={"v": "3"})
        rc, out = self.sh('lp_install_file "$T/pkgs/aa.lux" 1')
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.t, "root", "pre_remove-ran")))


if __name__ == "__main__":
    unittest.main()
