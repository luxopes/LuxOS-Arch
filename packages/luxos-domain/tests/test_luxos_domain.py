"""Testy luxos-domain: konfigurace, join/leave, navrat pri chybe, kolize jmen (R4), offline (R5), CLI, pomocnik.

    python3 packages/luxos-domain/tests/test_luxos_domain.py -v

Bez rootu, bez site a bez zasahu do systemu: vsechny soubory jsou v docasnem koreni
(LUXOS_DOMAIN_ROOT), realm/adcli/sssctl/getent/systemctl/... jsou zastupne skripty (LUXOS_DOMAIN_BIN),
ktere zapisuji argumenty a stdin. Nic se nespousti proti skutecne domene.
"""
import contextlib
import datetime
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
import luxos_domain as dom  # noqa: E402

PASSWORD = "Tajne-Heslo-123"

FAKE_TOOL = r"""#!/bin/bash
n=$(basename "$0")
printf '%s\n' "$n $*" >>"$FAKE/argv.log"
if [[ $n == adcli && ( $1 == join || $1 == delete-computer ) ]]; then
    IFS= read -r pw; printf '%s %s %s\n' "$n" "$1" "$pw" >>"$FAKE/stdin.log"
fi
if [[ -f "$FAKE/fail-$n-$1" ]]; then cat "$FAKE/fail-$n-$1" >&2; exit 1; fi
case $n in
  adcli)
    case $1 in
      info) cat "$FAKE/adcli-info" ;;
      join) printf 'computer-name = LUXPC\ndomain-short = FIRMA\n'
            for a; do [[ $a == --host-keytab=* ]] && echo keytab >"${a#--host-keytab=}"; done ;;
      testjoin) [[ -f $FAKE/online ]] || exit 1 ;;
    esac ;;
  realm) [[ $1 == discover ]] && printf '%s\n  type: kerberos\n  server-software: ipa\n' "$2" ;;
  sssctl) if [[ -f $FAKE/online ]]; then echo "Online status: Online"; else echo "Online status: Offline"; fi ;;
  getent) if [[ -f "$FAKE/getent-$1-$2" ]]; then cat "$FAKE/getent-$1-$2"; else exit 2; fi ;;
  ldapsearch) [[ -f $FAKE/dctime ]] && printf 'dn:\ncurrentTime: %s.0Z\n' "$(cat "$FAKE/dctime")" ;;
  visudo) grep -q 'ALL=(ALL:ALL) ALL' "$2" || exit 1 ;;
  luxos-care) echo "Snapshot 2026-10-26_12-00-00 created." ;;
esac
exit 0
"""

TOOLS = ("adcli", "realm", "sssctl", "sss_override", "sss_cache", "systemctl", "kinit", "klist", "ldapsearch",
         "visudo", "luxos-care", "logger", "getent", "timedatectl", "lpadmin")

PAM_STOCK = """#%PAM-1.0

auth       required                    pam_faillock.so      preauth
-auth      [success=2 default=ignore]  pam_systemd_home.so
auth       [success=1 default=bad]     pam_unix.so          try_first_pass nullok
auth       [default=die]               pam_faillock.so      authfail
"""
NSS_STOCK = ("# Name Service Switch configuration file.\npasswd: files systemd\ngroup: files [SUCCESS=merge] systemd\n"
             "shadow: files systemd\nhosts: mymachines mdns_minimal [NOTFOUND=return] resolve files myhostname dns\n")
KRB5_STOCK = "[libdefaults]\n    default_realm = EXAMPLE.COM\n"
ADCLI_INFO = """[domain]
domain-name = firma.local
domain-short = FIRMA
domain-forest = firma.local
domain-controller = dc1.firma.local
domain-controller-site = Default-First-Site-Name
domain-controllers = dc1.firma.local dc2.firma.local
[computer]
computer-site = Default-First-Site-Name
"""
NOW = datetime.datetime(2026, 10, 26, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)


def readf(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-domain-test-")
        self.root = os.path.join(self.tmp, "root")
        self.bin = os.path.join(self.tmp, "bin")
        self.fake = os.path.join(self.tmp, "fake")
        os.makedirs(self.bin)
        os.makedirs(self.fake)
        for t in TOOLS:
            write(os.path.join(self.bin, t), FAKE_TOOL, 0o755)
        r = self.root
        write(r + "/etc/pam.d/system-auth", PAM_STOCK)
        write(r + "/etc/nsswitch.conf", NSS_STOCK)
        write(r + "/etc/krb5.conf", KRB5_STOCK)
        write(r + "/etc/passwd", "root:x:0:0::/root:/bin/bash\njan:x:1000:1000:Jan:/home/jan:/usr/bin/lsh\n"
              "petr:x:1001:1001:Petr:/home/petr:/usr/bin/lsh\n")
        write(r + "/etc/os-release", 'NAME="LuxOS"\nVERSION_ID="1.0.0"\n')
        write(r + "/var/lib/sss/db/cache_firma.local.ldb", "cached")
        write(r + "/home/jan/notes.txt", "osobni data")
        write(self.fake + "/adcli-info", ADCLI_INFO)
        write(self.fake + "/online", "")
        self.saved = {k: os.environ.get(k) for k in ("LUXOS_DOMAIN_BIN", "LUXOS_DOMAIN_TEMPLATES", "FAKE",
                                                     "LUXOS_DOMAIN_NOW", "LUXOS_DOMAIN_ROOT")}
        os.environ.update({"LUXOS_DOMAIN_BIN": self.bin, "LUXOS_DOMAIN_TEMPLATES": os.path.join(FILES, "templates"),
                           "FAKE": self.fake, "LUXOS_DOMAIN_NOW": str(NOW)})
        self.old_root = dom.ROOT
        dom.ROOT = self.root
        self.out = io.StringIO()
        self.prog = dom.Progress(machine=True, out=self.out)

    def tearDown(self):
        dom.ROOT = self.old_root
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def argv_log(self):
        try:
            return readf(self.fake + "/argv.log").splitlines()
        except OSError:
            return []

    def stdin_log(self):
        try:
            return readf(self.fake + "/stdin.log").splitlines()
        except OSError:
            return []

    def all_files_text(self):
        out = []
        for d, _ds, fs in os.walk(self.root):
            for f in fs:
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    out.append(readf(os.path.join(d, f)))
        return "\n".join(out)

    def join(self, **kw):
        kw.setdefault("prog", self.prog)
        return dom.join("Firma.Local", "admin", PASSWORD, **kw)

    def state(self):
        return json.loads(readf(self.root + dom.STATE))


class DiscoverTest(Base):
    def test_discover_ok_and_clock(self):
        write(self.fake + "/dctime", datetime.datetime.fromtimestamp(NOW + 30, datetime.timezone.utc)
              .strftime("%Y%m%d%H%M%S"))
        info = dom.discover("firma.local")
        self.assertEqual(info["short"], "FIRMA")
        self.assertEqual(info["controllers"], ["dc1.firma.local", "dc2.firma.local"])
        self.assertEqual(info["realm"], "FIRMA.LOCAL")
        self.assertEqual(info["clock_skew"], 30)

    def test_discover_errors(self):
        with self.assertRaises(dom.DomainError) as cm:
            dom.discover("not a domain")
        self.assertEqual(cm.exception.code, "invalid")
        write(self.fake + "/fail-adcli-info", "adcli: couldn't lookup domain info: Couldn't resolve host")
        with self.assertRaises(dom.DomainError) as cm:
            dom.discover("firma.local")
        self.assertEqual(cm.exception.code, "dns")
        write(self.fake + "/fail-adcli-info", "adcli: No logon servers")
        with self.assertRaises(dom.DomainError) as cm:
            dom.discover("firma.local")
        self.assertEqual(cm.exception.code, "unsupported")        # realm: FreeIPA, ne AD

    def test_classify(self):
        self.assertEqual(dom.classify("Couldn't authenticate as: admin@FIRMA.LOCAL: Preauthentication failed"),
                         "password")
        self.assertEqual(dom.classify("Insufficient permissions to modify computer account"), "rights")
        self.assertEqual(dom.classify("Clock skew too great"), "clock")
        self.assertEqual(dom.classify("something odd"), "failed")


class JoinTest(Base):
    def test_join_writes_everything_and_password_only_on_stdin(self):
        state = self.join(ou="OU=LuxOS,DC=firma,DC=local", admins=["Domain Admins", "Účtárna IT"])
        self.assertTrue(state["joined"])
        r = self.root
        sssd = readf(r + dom.SSSD_CONF)
        self.assertEqual(stat.S_IMODE(os.stat(r + dom.SSSD_CONF).st_mode), 0o600)
        self.assertIn("[domain/firma.local]", sssd)
        self.assertIn("offline_credentials_expiration = 30", sssd)
        self.assertIn("cache_credentials = True", sssd)
        self.assertIn("use_fully_qualified_names = False", sssd)
        self.assertIn("access_provider = ad", sssd)
        self.assertIn("default_ccache_name = KCM:", readf(r + dom.KRB5_CONF))
        self.assertIn("pam_sss.so", readf(r + dom.PAM_AUTH))
        self.assertIn("pam_mkhomedir.so", readf(r + dom.PAM_AUTH))
        nss = readf(r + dom.NSSWITCH)
        self.assertIn("passwd: files systemd sss", nss)
        self.assertIn("group: files [SUCCESS=merge] systemd sss", nss)
        self.assertNotIn("hosts: mymachines mdns_minimal [NOTFOUND=return] resolve files myhostname dns sss", nss)
        sudo = readf(r + dom.SUDOERS)
        self.assertIn('%"domain admins" ALL=(ALL:ALL) ALL', sudo)
        self.assertIn('%"účtárna it" ALL=(ALL:ALL) ALL', sudo)
        self.assertEqual(stat.S_IMODE(os.stat(r + dom.SUDOERS).st_mode), 0o440)
        self.assertIn('["domain admins", "účtárna it"]', readf(r + dom.POLKIT_RULES))
        self.assertIn("greeter-show-manual-login=true", readf(r + dom.LIGHTDM_CONF))
        self.assertIn("realm = FIRMA.LOCAL", readf(r + dom.SMB_CONF))
        self.assertEqual(json.loads(readf(r + dom.FIREFOX_POLICIES))["policies"]["Authentication"]["SPNEGO"],
                         ["firma.local"])
        self.assertTrue(os.path.exists(r + dom.KEYTAB))
        st = self.state()
        self.assertEqual(st["computer"], "LUXPC")
        self.assertEqual(st["offline_days"], 30)
        self.assertEqual(st["admin_offline_days"], 7)
        # heslo: jen na stdin adcli, nikde v argumentech ani v souborech
        self.assertEqual(self.stdin_log(), [f"adcli join {PASSWORD}"])
        self.assertFalse(any(PASSWORD in a for a in self.argv_log()))
        self.assertNotIn(PASSWORD, self.all_files_text())
        join_argv = [a for a in self.argv_log() if a.startswith("adcli join")][0]
        self.assertIn("--stdin-password", join_argv)
        self.assertIn("--domain-ou=OU=LuxOS,DC=firma,DC=local", join_argv)
        self.assertIn("--os-name=LuxOS", join_argv)
        self.assertIn("systemctl enable --now sssd.service", self.argv_log())
        self.assertIn("systemctl enable --now sssd-kcm.socket", self.argv_log())
        self.assertIn("luxos-care snapshot --kind system", self.argv_log())
        self.assertIn("@@STEP 7 7", self.out.getvalue())
        with self.assertRaises(dom.DomainError) as cm:
            self.join()
        self.assertEqual(cm.exception.code, "already-joined")

    def test_failed_join_restores_everything(self):
        before = {p: readf(self.root + p) for p in (dom.PAM_AUTH, dom.NSSWITCH, dom.KRB5_CONF)}
        write(self.fake + "/fail-adcli-join", "adcli: Couldn't authenticate as: admin@FIRMA.LOCAL: "
                                              "Preauthentication failed")
        with self.assertRaises(dom.DomainError) as cm:
            self.join()
        self.assertEqual(cm.exception.code, "password")
        for p, text in before.items():
            self.assertEqual(readf(self.root + p), text, p)
        for p in (dom.SSSD_CONF, dom.SUDOERS, dom.POLKIT_RULES, dom.LIGHTDM_CONF, dom.SMB_CONF, dom.KEYTAB,
                  dom.STATE, dom.FIREFOX_POLICIES):
            self.assertFalse(os.path.exists(self.root + p), p)
        self.assertFalse(dom.joined())

    def test_failed_service_start_rolls_back(self):
        write(self.fake + "/fail-systemctl-enable", "Failed to enable unit")
        with self.assertRaises(dom.DomainError):
            self.join()
        self.assertEqual(readf(self.root + dom.NSSWITCH), NSS_STOCK)
        self.assertFalse(os.path.exists(self.root + dom.KEYTAB))
        self.assertIn("systemctl disable --now sssd.service", self.argv_log())

    def test_clock_skew_stops_before_changes(self):
        write(self.fake + "/dctime", datetime.datetime.fromtimestamp(NOW + 900, datetime.timezone.utc)
              .strftime("%Y%m%d%H%M%S"))
        with self.assertRaises(dom.DomainError) as cm:
            self.join()
        self.assertEqual(cm.exception.code, "clock")
        self.assertFalse(any(a.startswith("adcli join") for a in self.argv_log()))
        self.assertEqual(readf(self.root + dom.KRB5_CONF), KRB5_STOCK)

    def test_join_in_installer_chroot(self):
        self.join(chroot=True)
        log = self.argv_log()
        self.assertIn("systemctl enable sssd.service", log)
        self.assertNotIn("systemctl enable --now sssd.service", log)
        self.assertFalse(any(a.startswith("luxos-care") for a in log))     # bez snimku v instalatoru
        self.assertFalse(any(a.startswith("getent") for a in log))         # SSSD tam nebezi

    def test_invalid_input(self):
        for kw, code in (({"ou": "Computers"}, "invalid"), ({"computer": "a-much-too-long-name"}, "invalid"),
                         ({"admins": ["bad\ngroup"]}, "invalid")):
            with self.assertRaises(dom.DomainError) as cm:
                self.join(**kw)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(dom.DomainError) as cm:
            dom.join("firma.local", "admin", "", prog=self.prog)
        self.assertEqual(cm.exception.code, "password")
        self.assertEqual(dom.check_login("FIRMA\\admin"), "admin")

    def test_existing_smb_conf_and_firefox_policies_are_kept(self):
        write(self.root + dom.SMB_CONF, "[global]\n   workgroup = HOME\n")
        write(self.root + dom.FIREFOX_POLICIES, json.dumps({"policies": {"DisableTelemetry": True}}))
        self.join()
        self.assertEqual(readf(self.root + dom.SMB_CONF), "[global]\n   workgroup = HOME\n")
        pol = json.loads(readf(self.root + dom.FIREFOX_POLICIES))["policies"]
        self.assertTrue(pol["DisableTelemetry"])
        self.assertIn("Authentication", pol)
        dom.leave(prog=self.prog)
        pol = json.loads(readf(self.root + dom.FIREFOX_POLICIES))["policies"]
        self.assertEqual(pol, {"DisableTelemetry": True})
        self.assertEqual(readf(self.root + dom.SMB_CONF), "[global]\n   workgroup = HOME\n")


class LeaveTest(Base):
    def test_leave_restores_and_keeps_personal_data(self):
        self.join()
        write(self.root + dom.GPO_FRAGMENT, "load config\nconfig = {}\n")
        old_min = dom.DOMAIN_UID_MIN
        dom.DOMAIN_UID_MIN = 0             # v testu patri /home/jan nam (bez rootu nelze chown)
        try:
            warnings, homes = dom.leave("admin", PASSWORD, prog=self.prog)
        finally:
            dom.DOMAIN_UID_MIN = old_min
        self.assertEqual(warnings, [])
        self.assertIn("/home/jan", homes)
        r = self.root
        self.assertEqual(readf(r + dom.PAM_AUTH), PAM_STOCK)
        self.assertEqual(readf(r + dom.NSSWITCH), NSS_STOCK)
        self.assertEqual(readf(r + dom.KRB5_CONF), KRB5_STOCK)
        for p in (dom.SSSD_CONF, dom.SUDOERS, dom.POLKIT_RULES, dom.LIGHTDM_CONF, dom.KEYTAB, dom.STATE,
                  dom.GPO_FRAGMENT, dom.SMB_CONF, dom.FIREFOX_POLICIES):
            self.assertFalse(os.path.exists(r + p), p)
        self.assertEqual(os.listdir(r + "/var/lib/sss/db"), [])          # cache s otisky hesel pryc
        self.assertEqual(readf(r + "/home/jan/notes.txt"), "osobni data")  # osobni data zustanou (R8)
        left = json.loads(readf(r + dom.LEFT))
        self.assertFalse(left["joined"])
        self.assertIn("adcli delete-computer --domain=firma.local --login-user=admin --stdin-password LUXPC",
                      self.argv_log())
        self.assertIn(f"adcli delete-computer {PASSWORD}", self.stdin_log())
        self.assertNotIn(PASSWORD, self.all_files_text())
        self.assertIn("systemctl disable --now sssd.service", self.argv_log())

    def test_leave_without_rights_continues(self):
        self.join()
        write(self.fake + "/fail-adcli-delete-computer", "Insufficient permissions to delete computer")
        warnings, _h = dom.leave("user", "x", prog=self.prog)
        self.assertEqual(len(warnings), 1)
        self.assertFalse(dom.joined())

    def test_leave_keeps_pam_edited_by_admin(self):
        self.join()
        write(self.root + dom.PAM_AUTH, "#%PAM-1.0\n# vlastni\n")
        dom.leave(prog=self.prog)
        self.assertEqual(readf(self.root + dom.PAM_AUTH), "#%PAM-1.0\n# vlastni\n")

    def test_not_joined(self):
        with self.assertRaises(dom.DomainError) as cm:
            dom.leave(prog=self.prog)
        self.assertEqual(cm.exception.code, "not-joined")


class NamesTest(Base):
    """R4: kratke jmeno, pri kolizi s mistnim uctem plne jmeno jan@firma.local."""

    def test_clash_gets_full_name(self):
        self.join(chroot=True)
        write(self.fake + "/getent-passwd-jan@firma.local", "jan:*:1234567:1234567:Jan Novak:/home/jan:/usr/bin/lsh\n")
        dom.refresh()
        self.assertIn("sss_override user-add jan@firma.local -n jan@firma.local -h /home/jan@firma.local",
                      self.argv_log())
        self.assertNotIn("petr", " ".join(a for a in self.argv_log() if a.startswith("sss_override")))
        st = self.state()
        self.assertEqual(st["clashes"], ["jan"])
        self.assertEqual(dom.display_name("jan", st), "jan@firma.local")
        self.assertEqual(dom.display_name("FIRMA\\eva", st), "eva")
        self.assertEqual(dom.display_name("eva@firma.local", st), "eva")
        # podruhe uz se nic neprepisuje
        n = len([a for a in self.argv_log() if a.startswith("sss_override")])
        dom.refresh()
        self.assertEqual(len([a for a in self.argv_log() if a.startswith("sss_override")]), n)

    def test_same_uid_is_not_a_clash(self):
        self.join(chroot=True)
        write(self.fake + "/getent-passwd-jan@firma.local", "jan:x:1000:1000:Jan:/home/jan:/usr/bin/lsh\n")
        self.assertEqual(dom.find_clashes(self.state()), [])

    def test_luxos_admins_group_added_when_present(self):
        self.join(chroot=True)
        write(self.fake + "/getent-group-luxos admins", "luxos admins:*:1500:\n")
        dom.refresh()
        self.assertEqual(self.state()["admin_groups"], ["Domain Admins", "LuxOS Admins"])
        self.assertIn('%"luxos admins"', readf(self.root + dom.SUDOERS))


class OfflineTest(Base):
    """R5: offline prihlaseni 30 dni (SSSD), prava spravce jen 7 dni bez spojeni."""

    def set_last_online(self, days_ago):
        st = self.state()
        st["last_online"] = dom.iso(NOW - days_ago * 86400)
        dom.save_state(st)

    def test_admin_rights_expire_offline_and_return(self):
        self.join(chroot=True)
        os.unlink(self.fake + "/online")
        self.set_last_online(3)
        st = dom.refresh()
        self.assertFalse(st["online"])
        self.assertTrue(st["admins_active"])
        self.assertEqual(st["offline_left_days"], 27)
        self.set_last_online(8)
        st = dom.refresh()
        self.assertFalse(st["admins_active"])
        sudo = readf(self.root + dom.SUDOERS)
        self.assertIn('# %"domain admins"', sudo)
        self.assertNotIn('\n%"domain admins"', sudo)
        self.assertIn("var luxosDomainAdmins = [];", readf(self.root + dom.POLKIT_RULES))
        status = dom.status()
        self.assertFalse(status["admins_active"])
        self.assertEqual(status["offline_left_days"], 22)
        info = dom.greeter_info()
        self.assertEqual(info["short"], "FIRMA")
        self.assertFalse(info["online"])
        self.assertEqual(info["offline_left_days"], 22)
        # spojeni zpet -> prava se vrati
        write(self.fake + "/online", "")
        st = dom.refresh()
        self.assertTrue(st["admins_active"])
        self.assertIn('\n%"domain admins" ALL=(ALL:ALL) ALL', readf(self.root + dom.SUDOERS))
        self.assertEqual(json.loads(readf(self.root + dom.RUN_STATUS))["offline_left_days"], 30)

    def test_offline_days_setting(self):
        self.join(chroot=True)
        dom.set_option("offline-days", "14")
        self.assertIn("offline_credentials_expiration = 14", readf(self.root + dom.SSSD_CONF))
        dom.set_option("admin-offline-days", "0")
        dom.set_option("offline-days", "0")
        sssd = readf(self.root + dom.SSSD_CONF)
        self.assertIn("cache_credentials = False", sssd)            # 0 = bez offline prihlaseni
        with self.assertRaises(dom.DomainError):
            dom.set_option("offline-days", "500")
        with self.assertRaises(dom.DomainError):
            dom.set_option("admin-offline-days", "5")                # delsi nez offline prihlaseni (0)

    def test_greeter_info_outside_domain(self):
        self.assertIsNone(dom.greeter_info())
        self.assertEqual(dom.status(), {"joined": False})


class AdminsTest(Base):
    def test_admins_and_login_groups(self):
        self.join(chroot=True)
        dom.admins_change("IT", True)
        dom.admins_change("domain admins", False)               # bez ohledu na velikost pismen
        st = self.state()
        self.assertEqual(st["admin_groups"], ["IT"])
        self.assertIn('%"it" ALL=(ALL:ALL) ALL', readf(self.root + dom.SUDOERS))
        self.assertTrue(any(a.startswith("visudo -cf") for a in self.argv_log()))
        dom.login_change("Účtárna", True)
        sssd = readf(self.root + dom.SSSD_CONF)
        self.assertIn("access_provider = simple", sssd)
        self.assertIn("simple_allow_groups = účtárna", sssd)
        dom.login_change("Účtárna", False)
        self.assertIn("access_provider = ad", readf(self.root + dom.SSSD_CONF))
        with self.assertRaises(dom.DomainError):
            dom.admins_change("a,b", True)

    def test_bad_sudoers_is_never_written(self):
        self.join(chroot=True)
        write(self.fake + "/fail-visudo--cf", "syntax error")
        before = readf(self.root + dom.SUDOERS)
        with self.assertRaises(dom.DomainError):
            dom.admins_change("IT", True)
        self.assertEqual(readf(self.root + dom.SUDOERS), before)


class MiscTest(Base):
    def test_repair_after_package_update(self):
        self.join(chroot=True)
        write(self.root + dom.NSSWITCH, NSS_STOCK)          # novy nsswitch.conf z balicku
        write(self.root + dom.PAM_AUTH, PAM_STOCK)
        self.assertTrue(dom.repair())
        self.assertIn("passwd: files systemd sss", readf(self.root + dom.NSSWITCH))
        self.assertIn("pam_sss.so", readf(self.root + dom.PAM_AUTH))

    def test_repair_outside_domain_does_nothing(self):
        self.assertFalse(dom.repair())
        self.assertEqual(readf(self.root + dom.NSSWITCH), NSS_STOCK)

    def test_shares_bookmarks_and_printers(self):
        self.join(chroot=True)
        dom.shares_change("smb://fs.firma.local/data", "Firemní data", True)
        with self.assertRaises(dom.DomainError):
            dom.shares_change("http://x", "", True)
        home = os.path.join(self.tmp, "home-eva")
        self.assertEqual(dom.session_bookmarks(home=home, uid=1234567), ["smb://fs.firma.local/data"])
        self.assertEqual(dom.session_bookmarks(home=home, uid=1234567), [])       # jen jednou
        self.assertEqual(dom.session_bookmarks(home=home, uid=1000), [])          # mistni uzivatel ne
        self.assertIn("smb://fs.firma.local/data Firemní data",
                      readf(os.path.join(home, ".config/gtk-3.0/bookmarks")))
        dom.printers_change("Tiskarna", "smb://print.firma.local/Tiskarna", True)
        self.assertIn("lpadmin -p Tiskarna -E -v smb://print.firma.local/Tiskarna -m drv:///sample.drv/generic.ppd "
                      "-o auth-info-required=negotiate -o printer-is-shared=false", self.argv_log())
        dom.leave(prog=self.prog)
        self.assertIn("lpadmin -x Tiskarna", self.argv_log())

    def test_sync_time(self):
        self.join(chroot=True)
        write(self.fake + "/dctime", "20261026120500")
        stamp = dom.sync_time()
        self.assertTrue(stamp.startswith("2026-10-26"))
        self.assertIn("NTP=dc1.firma.local dc2.firma.local", readf(self.root + dom.TIMESYNC_CONF))
        self.assertIn("timedatectl set-ntp true", self.argv_log())


class CliTest(Base):
    """lux-domain a luxos-domain-helper jako samostatne procesy (protokol @@STEP/@@ERROR/@@DONE)."""

    def run_cli(self, args, stdin="", prog="lux-domain"):
        env = dict(os.environ, LUXOS_DOMAIN_ROOT=self.root, LUXOS_DOMAIN_PYTHON=FILES, LANG="C.UTF-8",
                   LUXOS_DOMAIN_CLI_ROOT=os.path.join(FILES, "lux-domain"), NO_COLOR="1")
        env.pop("DISPLAY", None)
        r = subprocess.run([sys.executable, os.path.join(FILES, prog)] + args, input=stdin, capture_output=True,
                           text=True, env=env, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def test_join_progress_and_status(self):
        rc, out = self.run_cli(["join", "firma.local", "-U", "admin", "--password-stdin", "--yes", "--progress",
                                "--offline-install"], stdin=PASSWORD + "\n")
        self.assertEqual(rc, 0, out)
        self.assertIn("@@STEP 1 7", out)
        self.assertTrue(out.rstrip().endswith("@@DONE"))
        self.assertNotIn(PASSWORD, out)
        rc, out = self.run_cli(["status", "--json"])
        st = json.loads(out)
        self.assertTrue(st["joined"])
        self.assertEqual(st["admin_groups"], ["Domain Admins"])
        rc, out = self.run_cli(["status"])
        self.assertIn("firma.local (FIRMA)", out)

    def test_join_error_line(self):
        write(self.fake + "/fail-adcli-join", "Insufficient permissions to create computer account")
        rc, out = self.run_cli(["join", "firma.local", "-U", "admin", "--password-stdin", "--yes", "--progress"],
                               stdin=PASSWORD + "\n")
        self.assertEqual(rc, 1)
        self.assertIn("@@ERROR rights ", out)

    def test_discover_json_error(self):
        write(self.fake + "/fail-adcli-info", "Couldn't resolve")
        rc, out = self.run_cli(["discover", "firma.local", "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["error"], "dns")

    def test_helper(self):
        rc, out = self.run_cli(["join", "firma.local", "admin", "OU=PC,DC=firma,DC=local"], stdin=PASSWORD + "\n",
                               prog="luxos-domain-helper")
        self.assertEqual(rc, 0, out)
        self.assertIn("@@DONE", out)
        self.assertIn("--domain-ou=OU=PC,DC=firma,DC=local", "\n".join(self.argv_log()))
        rc, out = self.run_cli(["admins-add", "IT"], prog="luxos-domain-helper")
        self.assertEqual(rc, 0, out)
        self.assertIn("@@DONE", out)
        rc, out = self.run_cli(["set-offline-days", "10"], prog="luxos-domain-helper")
        self.assertEqual(rc, 0, out)
        rc, out = self.run_cli(["rm", "-rf", "/"], prog="luxos-domain-helper")
        self.assertEqual(rc, 2)
        self.assertIn("@@ERROR invalid", out)
        rc, out = self.run_cli(["set-offline-days", "1; reboot"], prog="luxos-domain-helper")
        self.assertEqual(rc, 2)
        rc, out = self.run_cli(["leave", "admin"], stdin=PASSWORD + "\n", prog="luxos-domain-helper")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"adcli delete-computer {PASSWORD}", self.stdin_log())
        self.assertFalse(any(PASSWORD in a for a in self.argv_log()))


class TranslationTest(unittest.TestCase):
    def test_all_strings_translated(self):
        """Kazdy text _("...") z lux-domain, luxos_domain.py a Nastaveni je ve vsech 12 prekladech."""
        import ast
        texts = set()
        for name in ("luxos_domain.py", "lux-domain", "luxos-domain-settings"):
            with open(os.path.join(FILES, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    texts.add(node.args[0].value)
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "HELP" for t in node.targets):
                    texts |= {el.elts[1].value for el in node.value.elts}
        i18n = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
        if not os.path.isdir(i18n):
            self.skipTest("luxos-i18n not available")
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            with open(os.path.join(i18n, lang + ".tsv"), encoding="utf-8") as f:
                tr = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            missing = sorted(t for t in texts if not tr.get(t))
            self.assertEqual(missing, [], lang)
            for t in texts:
                self.assertEqual(t.count("%s"), tr[t].count("%s"), (lang, t))
                self.assertEqual(t.count("%d"), tr[t].count("%d"), (lang, t))


if __name__ == "__main__":
    unittest.main()
