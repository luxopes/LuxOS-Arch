#!/usr/bin/env python3
"""LuxOS - testy prihlaseni otiskem: skript luxos-fingerprint-pam a skutecne vyhodnoceni PAM.

    python3 packages/luxos-desktop/tests/test_fingerprint_pam.py

1. luxos-fingerprint-pam nad falesnym korenem (LUXOS_PAM_ROOT): vlozeni, idempotence, odebrani,
   kopie sluzby z /usr/lib/pam.d, sync podle pritomnosti pam_fprintd.so.
2. Vygenerovane radky se nechaji vyhodnotit skutecnou knihovnou libpam (pam_start_confdir) -
   pam_fprintd nahradi testovaci modul fake_pam.so (otisk: shoda / neshoda / bez ctecky)
   a pam_unix jeho rezim "password" (heslo "secret"). Overuje, ze heslo funguje vzdy, spatne
   heslo nikdy neprojde a ze greeterem zapsany uzivatel otisk preskoci.
3. Otisk nahrazuje jen heslo: docasne zamceny ucet (pam_faillock), /etc/nologin a neplatny shell
   (sluzby prihlaseni) neprojdou ani otiskem; uspesny otisk vynuluje pocitadlo chyb (authsucc).
   Skutecne moduly Arch Linuxu (pam_faillock, pam_nologin, pam_shells, pam_unix account - vyprseny
   ucet) overuje tests/fingerprint/container-pam-test.sh v kontejneru.
"""
import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "fingerprint", "luxos-fingerprint-pam")
FAKE_SRC = os.path.join(HERE, "fingerprint", "fake_pam.c")
BEGIN = "# LuxOS fingerprint: begin (managed by luxos-fingerprint-pam)"

# Soubory jako v Arch Linuxu (lightdm, sudo; polkit jen v /usr/lib/pam.d)
LIGHTDM = """#%PAM-1.0
auth        include     system-login
-auth       optional    pam_gnome_keyring.so
account     include     system-login
password    include     system-login
-password   optional    pam_gnome_keyring.so use_authtok
session     include     system-login
-session    optional    pam_gnome_keyring.so auto_start
"""
SUDO = """#%PAM-1.0
auth		include		system-auth
account		include		system-auth
session		include		system-auth
"""
POLKIT = """#%PAM-1.0

auth       include      system-auth
account    include      system-auth
password   include      system-auth
session    include      system-auth
"""


def run(root, *args):
    env = dict(os.environ, LUXOS_PAM_ROOT=root)
    return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-fp-pam-")
        self.addCleanup(shutil.rmtree, self.root)
        write(f"{self.root}/etc/pam.d/lightdm", LIGHTDM)
        write(f"{self.root}/etc/pam.d/sudo", SUDO)
        write(f"{self.root}/usr/lib/pam.d/polkit-1", POLKIT)
        os.chmod(f"{self.root}/etc/pam.d/sudo", 0o640)

    def p(self, name):
        return f"{self.root}/etc/pam.d/{name}"

    def test_apply_inserts_before_first_auth(self):
        r = run(self.root, "apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = read(self.p("lightdm")).splitlines()
        self.assertEqual(lines[0], "#%PAM-1.0")
        self.assertEqual(lines[1], BEGIN)
        end = lines.index("# LuxOS fingerprint: end")
        blk = [x.split() for x in lines[2:end]]
        # sluzba prihlaseni: nologin a shells (jako system-login), zamek pam_faillock, pak otisk
        self.assertEqual(blk[0], ["auth", "requisite", "pam_nologin.so"])
        self.assertEqual(blk[1], ["auth", "requisite", "pam_shells.so"])
        self.assertEqual(blk[2], ["auth", "requisite", "pam_faillock.so", "preauth"])
        self.assertIn("pam_listfile.so item=user sense=deny file=/run/luxos-fingerprint/password-only onerr=succeed",
                      lines[2 + 3])
        self.assertEqual(blk[4][:3], ["-auth", "[success=1", "default=ignore]"])
        self.assertEqual(blk[4][3], "pam_fprintd.so")
        self.assertEqual(blk[5], ["auth", "[default=1]", "pam_permit.so"])
        self.assertEqual(blk[6], ["auth", "sufficient", "pam_faillock.so", "authsucc"])
        self.assertEqual(lines[end + 1].split(), ["auth", "include", "system-login"])
        self.assertNotIn("sufficient  pam_fprintd", read(self.p("lightdm")), "fingerprint never 'sufficient'")
        sudo = read(self.p("sudo"))
        self.assertIn("-auth      [success=1 default=ignore]  pam_fprintd.so max-tries=3 timeout=10", sudo)
        self.assertIn("auth       requisite   pam_faillock.so preauth", sudo)
        self.assertNotIn("pam_listfile", sudo)
        # sudo/polkit nejsou sluzby prihlaseni: bez nologin/shells (puvodni sluzba je take nema)
        self.assertNotIn("pam_nologin", sudo)
        self.assertNotIn("pam_shells", sudo)
        self.assertNotIn("pam_nologin", read(self.p("polkit-1")))
        self.assertEqual(os.stat(self.p("sudo")).st_mode & 0o777, 0o640, "permissions kept")
        # polkit: kopie z /usr/lib/pam.d, puvodni soubor nedotcen
        self.assertTrue(read(self.p("polkit-1")).startswith("# LuxOS fingerprint: copy of /usr/lib/pam.d\n"))
        self.assertEqual(read(f"{self.root}/usr/lib/pam.d/polkit-1"), POLKIT)
        self.assertFalse(os.path.exists(self.p("xfce4-screensaver")), "missing service is not created")

    def test_idempotent(self):
        run(self.root, "apply")
        first = {n: read(self.p(n)) for n in ("lightdm", "sudo", "polkit-1")}
        st = os.stat(self.p("lightdm")).st_mtime_ns
        run(self.root, "apply")
        self.assertEqual(first, {n: read(self.p(n)) for n in ("lightdm", "sudo", "polkit-1")})
        self.assertEqual(st, os.stat(self.p("lightdm")).st_mtime_ns, "unchanged file is not rewritten")
        self.assertEqual(read(self.p("lightdm")).count(BEGIN), 1)

    def test_remove_restores_original(self):
        run(self.root, "apply")
        r = run(self.root, "remove")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(self.p("lightdm")), LIGHTDM)
        self.assertEqual(read(self.p("sudo")), SUDO)
        self.assertFalse(os.path.exists(self.p("polkit-1")), "own copy removed")
        self.assertEqual(sorted(os.listdir(f"{self.root}/etc/pam.d")), ["lightdm", "sudo"], "no temp files left")

    def test_remove_keeps_admin_edited_copy(self):
        run(self.root, "apply")
        with open(self.p("polkit-1"), "a", encoding="utf-8") as f:
            f.write("session    optional     pam_admin.so\n")
        run(self.root, "remove")
        text = read(self.p("polkit-1"))
        self.assertIn("pam_admin.so", text)
        self.assertNotIn("pam_fprintd", text)

    def test_upgrade_replaced_file(self):
        # aktualizace baliku prepise soubor (bez bloku) - hook ho znovu doplni
        run(self.root, "apply")
        write(self.p("lightdm"), LIGHTDM)
        run(self.root, "apply")
        self.assertEqual(read(self.p("lightdm")).count(BEGIN), 1)

    def test_migrates_old_block(self):
        # instalace se starsim blokem (otisk "sufficient" pred vsim) -> po aktualizaci jen novy blok
        old = ("#%PAM-1.0\n" + BEGIN + "\n-auth      sufficient  pam_fprintd.so max-tries=3 timeout=10\n"
               "# LuxOS fingerprint: end\n" + SUDO.split("\n", 1)[1])
        write(self.p("sudo"), old)
        r = run(self.root, "apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = read(self.p("sudo"))
        self.assertEqual(text.count(BEGIN), 1)
        self.assertNotIn("sufficient  pam_fprintd", text)
        self.assertIn("pam_faillock.so preauth", text)
        run(self.root, "remove")
        self.assertEqual(read(self.p("sudo")), SUDO)

    def test_sync_follows_module(self):
        r = run(self.root, "sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("pam_fprintd", read(self.p("lightdm")), "no fprintd -> nothing added")
        write(f"{self.root}/usr/lib/security/pam_fprintd.so", "")
        run(self.root, "sync")
        self.assertIn("pam_fprintd", read(self.p("lightdm")))
        self.assertIn("lightdm: fingerprint", run(self.root, "status").stdout)
        os.remove(f"{self.root}/usr/lib/security/pam_fprintd.so")
        run(self.root, "sync")
        self.assertEqual(read(self.p("lightdm")), LIGHTDM)
        self.assertIn("lightdm: password only", run(self.root, "status").stdout)

    def test_file_without_auth_untouched(self):
        write(self.p("sudo"), "#%PAM-1.0\naccount include system-auth\n")
        r = run(self.root, "apply")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(read(self.p("sudo")), "#%PAM-1.0\naccount include system-auth\n")

    def test_bad_command(self):
        self.assertEqual(run(self.root, "bogus").returncode, 2)


# ---- skutecne vyhodnoceni PAM ----------------------------------------------------------
class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(PamMessage)),
                        ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV), ("appdata_ptr", ctypes.c_void_p)]


def find_libpam():
    for name in ("libpam.so.0", "libpam.so"):
        try:
            lib = ctypes.CDLL(name)
            lib.pam_start_confdir  # noqa: B018 - libpam >= 1.4
            return lib
        except (OSError, AttributeError):
            continue
    return None


LIBPAM = find_libpam()
LIBC = ctypes.CDLL(None)
LIBC.calloc.restype = ctypes.c_void_p
LIBC.strdup.restype = ctypes.c_void_p
LIBC.strdup.argtypes = [ctypes.c_char_p]


def pam_auth(confdir, service, user, password):
    """Probehne pam_authenticate; vrati (vysledek, zpravy, pocet vyzev k heslu)."""
    msgs, prompts = [], [0]

    def conv(n, mp, rp, _data):
        arr = LIBC.calloc(n, ctypes.sizeof(PamResponse))
        resp = ctypes.cast(arr, ctypes.POINTER(PamResponse))
        for i in range(n):
            m = mp[i].contents
            text = m.msg.decode()
            if m.msg_style in (1, 2):           # vyzva
                prompts[0] += 1
                resp[i].resp = LIBC.strdup(password.encode())
            else:
                msgs.append(("error" if m.msg_style == 3 else "info", text))
        rp[0] = resp
        return 0

    cb = CONV(conv)
    c = PamConv(cb, None)
    h = ctypes.c_void_p()
    rc = LIBPAM.pam_start_confdir(service.encode(), user.encode(), ctypes.byref(c), confdir.encode(),
                                  ctypes.byref(h))
    assert rc == 0, rc
    rc = LIBPAM.pam_authenticate(h, 0)
    LIBPAM.pam_end(h, rc)
    return rc, msgs, prompts[0]


@unittest.skipUnless(LIBPAM and shutil.which("gcc"), "needs libpam >= 1.4 and gcc")
class PamStackTest(unittest.TestCase):
    """Bloky ze skriptu nad zjednodusenymi system-login/system-auth z Arch Linuxu."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-fp-stack-")
        cls.fake = os.path.join(cls.tmp, "fake_pam.so")
        subprocess.run(["gcc", "-shared", "-fPIC", "-o", cls.fake, FAKE_SRC, "-l:libpam.so.0"], check=True)
        root = os.path.join(cls.tmp, "root")
        write(f"{root}/etc/pam.d/lightdm", LIGHTDM)
        write(f"{root}/etc/pam.d/sudo", SUDO)
        r = run(root, "apply")
        assert r.returncode == 0, r.stderr
        cls.skip = os.path.join(cls.tmp, "password-only")
        cls.conf = os.path.join(cls.tmp, "pam.d")
        os.makedirs(cls.conf)
        for svc in ("lightdm", "sudo"):
            text = read(f"{root}/etc/pam.d/{svc}")
            text = text.replace("pam_fprintd.so", cls.fake + " finger").replace(
                "/run/luxos-fingerprint/password-only", cls.skip)
            for mod in ("faillock", "nologin", "shells"):
                text = text.replace(f"pam_{mod}.so", f"{cls.fake} {mod}")
            # moduly, ktere tu nejsou (gnome-keyring), PAM tise preskoci diky "-"
            write(os.path.join(cls.conf, svc), text)
        # verze bez pam_fprintd (balik odinstalovan, radky zustaly)
        write(os.path.join(cls.conf, "lightdm-nofp"),
              read(os.path.join(cls.conf, "lightdm")).replace(cls.fake + " finger", "/nonexistent/pam_fprintd.so"))
        # Arch: system-login (shells, nologin) + system-auth (faillock, unix, faillock authfail, env)
        write(os.path.join(cls.conf, "system-login"), f"auth required {cls.fake} shells\n"
              f"auth requisite {cls.fake} nologin\nauth include system-auth\n"
              "account required pam_permit.so\npassword required pam_permit.so\nsession required pam_permit.so\n")
        write(os.path.join(cls.conf, "system-auth"), f"auth required {cls.fake} faillock preauth\n"
              f"auth [success=1 default=bad] {cls.fake} password\n"
              f"auth [default=die] {cls.fake} faillock authfail\nauth optional pam_permit.so\n"
              f"auth required pam_permit.so\nauth required {cls.fake} faillock authsucc\n"
              "account required pam_permit.so\npassword required pam_permit.so\nsession required pam_permit.so\n")
        cls.log = os.path.join(cls.tmp, "calls")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def auth(self, service, fp, password, skip_users=None, all_calls=False, **flags):
        os.environ["FAKE_FP"] = fp
        for name in ("FAKE_LOCKED", "FAKE_NOLOGIN", "FAKE_BADSHELL"):
            os.environ[name] = "1" if flags.get(name.lower()[5:]) else "0"
        os.environ["FAKE_LOG"] = self.log
        if skip_users is None:
            if os.path.exists(self.skip):
                os.remove(self.skip)
        else:
            write(self.skip, "".join(u + "\n" for u in skip_users))
            os.chmod(self.skip, 0o644)
        if os.path.exists(self.log):
            os.remove(self.log)
        rc, msgs, prompts = pam_auth(self.conf, service, "anna", password)
        calls = read(self.log).split() if os.path.exists(self.log) else []
        if not all_calls:
            calls = [c for c in calls if c in ("finger", "password")]
        return rc, msgs, prompts, calls

    def test_finger_match_logs_in_without_password(self):
        for svc in ("lightdm", "sudo"):
            rc, msgs, prompts, calls = self.auth(svc, "match", "wrong", [])
            self.assertEqual(rc, 0, svc)
            self.assertEqual(prompts, 0, svc)
            self.assertEqual(calls, ["finger"], svc)
            self.assertEqual(msgs[0][0], "info")

    def test_finger_nomatch_falls_back_to_password(self):
        for svc in ("lightdm", "sudo"):
            rc, msgs, prompts, calls = self.auth(svc, "nomatch", "secret", [])
            self.assertEqual((rc, prompts, calls), (0, 1, ["finger", "password"]), svc)
            self.assertIn(("error", "Failed to match fingerprint"), msgs)
            rc, _m, _p, _c = self.auth(svc, "nomatch", "wrong", [])
            self.assertNotEqual(rc, 0, f"{svc}: wrong password must fail")

    def test_no_reader_password_only(self):
        for svc in ("lightdm", "sudo"):
            rc, msgs, prompts, calls = self.auth(svc, "unavail", "secret", [])
            self.assertEqual((rc, prompts, msgs), (0, 1, []), svc)
            self.assertNotEqual(self.auth(svc, "unavail", "wrong", [])[0], 0, svc)
            self.assertNotEqual(self.auth(svc, "unavail", "", [])[0], 0, f"{svc}: empty password")

    def test_greeter_password_only_skips_finger(self):
        rc, msgs, prompts, calls = self.auth("lightdm", "match", "secret", ["petr", "anna"])
        self.assertEqual((rc, prompts, calls, msgs), (0, 1, ["password"], []))
        # zapsany uzivatel s otiskem, ale spatnym heslem: nesmi projit
        rc, _m, _p, calls = self.auth("lightdm", "match", "wrong", ["anna"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(calls, ["password"])
        # jiny uzivatel v souboru: otisk se pouzije
        rc, _m, prompts, calls = self.auth("lightdm", "match", "wrong", ["petr"])
        self.assertEqual((rc, prompts, calls), (0, 0, ["finger"]))

    def test_missing_skip_file_is_harmless(self):
        rc, _m, prompts, calls = self.auth("lightdm", "match", "x", None)
        self.assertEqual((rc, prompts, calls), (0, 0, ["finger"]))
        rc, _m, prompts, calls = self.auth("lightdm", "unavail", "secret", None)
        self.assertEqual((rc, prompts, calls), (0, 1, ["finger", "password"]))

    def test_finger_match_runs_account_checks_first(self):
        rc, _m, prompts, calls = self.auth("lightdm", "match", "wrong", [], all_calls=True)
        self.assertEqual((rc, prompts), (0, 0))
        self.assertEqual(calls, ["nologin", "shells", "preauth", "finger", "authsucc"])
        rc, _m, prompts, calls = self.auth("sudo", "match", "wrong", [], all_calls=True)
        self.assertEqual((rc, prompts, calls), (0, 0, ["preauth", "finger", "authsucc"]))

    def test_locked_account_refused_even_with_finger(self):
        for svc in ("lightdm", "sudo"):
            rc, msgs, prompts, calls = self.auth(svc, "match", "secret", [], locked=True)
            self.assertNotEqual(rc, 0, f"{svc}: locked account must not pass with a fingerprint")
            self.assertEqual((prompts, calls), (0, []), f"{svc}: no reader wait, no password prompt")
            self.assertTrue(any("locked" in t for _k, t in msgs), msgs)
            # ani spravne heslo behem zamku (jako dosud), heslo pres greeter (password-only) take ne
            self.assertNotEqual(self.auth(svc, "unavail", "secret", [], locked=True)[0], 0, svc)
        self.assertNotEqual(self.auth("lightdm", "match", "secret", ["anna"], locked=True)[0], 0)

    def test_nologin_refuses_finger_on_login(self):
        rc, _m, prompts, calls = self.auth("lightdm", "match", "secret", [], nologin=True)
        self.assertNotEqual(rc, 0)
        self.assertEqual((prompts, calls), (0, []))
        # sudo neni sluzba prihlaseni - /etc/nologin ho neovlivni (stejne jako s heslem)
        self.assertEqual(self.auth("sudo", "match", "x", [], nologin=True)[0], 0)

    def test_bad_shell_refuses_finger_on_login(self):
        rc, _m, prompts, calls = self.auth("lightdm", "match", "secret", [], badshell=True)
        self.assertNotEqual(rc, 0)
        self.assertEqual((prompts, calls), (0, []))
        self.assertNotEqual(self.auth("lightdm", "unavail", "secret", [], badshell=True)[0], 0)

    def test_failed_finger_does_not_reset_counter(self):
        rc, _m, _p, calls = self.auth("sudo", "nomatch", "wrong", [], all_calls=True)
        self.assertNotEqual(rc, 0)
        self.assertNotIn("authsucc", calls)
        self.assertIn("authfail", calls, "wrong password after failed finger is still counted")

    def test_world_writable_skip_file_means_password(self):
        # pam_listfile odmita soubor zapisovatelny vsemi -> bezpecny smer: jen heslo
        write(self.skip, "")
        os.chmod(self.skip, 0o666)
        os.environ.update(FAKE_FP="match", FAKE_LOG=self.log, FAKE_LOCKED="0", FAKE_NOLOGIN="0", FAKE_BADSHELL="0")
        rc, _m, prompts = pam_auth(self.conf, "lightdm", "anna", "wrong")
        self.assertNotEqual(rc, 0)
        self.assertEqual(prompts, 1)

    def test_fprintd_uninstalled(self):
        for skip in ([], ["anna"]):
            rc, msgs, prompts, calls = self.auth("lightdm-nofp", "match", "secret", skip)
            self.assertEqual((rc, prompts, calls), (0, 1, ["password"]), skip)
            self.assertNotEqual(self.auth("lightdm-nofp", "match", "wrong", skip)[0], 0, skip)


if __name__ == "__main__":
    unittest.main(verbosity=2)
