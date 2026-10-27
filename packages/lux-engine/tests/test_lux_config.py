"""Testy lux-config (format /etc/lux/lux.conf, generovani /run/lux/engine.conf, prevod pacman.conf).

    python3 -m unittest discover -s packages/lux-engine/tests -v
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
import lux_config as lc  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lux-config-test-")
        os.makedirs(self.path("etc/lux/conf.d"))
        shutil.copy(os.path.join(PKG, "mirrorlist"), self.path("etc/lux/mirrorlist"))
        shutil.copy(os.path.join(PKG, "lux.conf"), self.path("etc/lux/lux.conf"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w") as f:
            f.write(text)

    def parse(self, text=None):
        if text is not None:
            self.write("etc/lux/lux.conf", text)
        return lc.parse("/etc/lux/lux.conf", root=self.root)

    def error(self, text):
        with self.assertRaises(lc.ConfigError) as cm:
            self.parse(text)
        return str(cm.exception)


class Format(Base):
    def test_default_config(self):
        cfg = self.parse()
        self.assertEqual([r.name for r in cfg.repos], ["luxos", "luxos-apps", "luxos-drivers", "core", "extra"])
        eng = lc.render_engine(cfg)
        body = eng.split("[options]", 1)[1]
        for line in ("Architecture = auto", "ParallelDownloads = 10", "SigLevel = Required DatabaseOptional",
                     "LocalFileSigLevel = Optional", "Color", "ILoveCandy", "CheckSpace", "VerbosePkgLists",
                     "DownloadUser = alpm", "HoldPkg = lux-engine glibc",
                     "[luxos]\nServer = https://luxos.lux-ai.cz/repo/$repo/$arch",
                     "[core]\nServer = https://geo.mirror.pkgbuild.com/$repo/os/$arch"):
            self.assertIn(line + "\n", body)
        # cesty jadra jen jako vychozi (pacstrap -r by jinak pouzil cesty hostitele)
        for d in ("DBPath", "CacheDir", "LogFile", "GPGDir", "HookDir", "Include"):
            self.assertNotIn(d, body)

    def test_same_semantics_as_old_luxos_pacman_conf(self):
        """Vychozi lux.conf = konfigurace LuxOS 0.9.5 (pacman.conf) se stejnymi zrcadly."""
        self.write("etc/pacman.conf", OLD_PACMAN_CONF)
        text, extra, warns = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        self.assertEqual(warns, [])
        self.assertEqual(extra, {})
        self.assertEqual(lc.semantic(self.parse(text)),
                         lc.semantic(lc.parse("/etc/lux/lux.conf", root=self.root,
                                              text=lc.without_drivers_repo(open(os.path.join(PKG, "lux.conf")).read()))))

    def test_comments_and_indent(self):
        cfg = self.parse("# a\nhold  linux   # keep\n\nrepo r1\n\tserver https://x.example/$repo/$arch # main\n"
                         "    # comment inside\n    signatures optional\n    usage sync search\n")
        self.assertEqual(cfg.lists["hold"], ["linux"])
        r = cfg.repo("r1")
        self.assertEqual([u for u, _o in r.servers], ["https://x.example/$repo/$arch"])
        eng = lc.render_engine(cfg)
        self.assertIn("[r1]\nSigLevel = Optional TrustAll\nUsage = Sync Search\nServer = https://x.example/$repo/$arch\n",
                      eng)

    def test_hold_and_lists(self):
        cfg = self.parse("hold linux linux-headers\nhold firefox\nignore-group gnome\nno-upgrade etc/a.conf\n"
                         "no-extract usr/share/doc/* !usr/share/doc/x/*\nprotect glibc\n")
        eng = lc.render_engine(cfg)
        for line in ("IgnorePkg = linux linux-headers", "IgnorePkg = firefox", "IgnoreGroup = gnome",
                     "NoUpgrade = etc/a.conf", "NoExtract = usr/share/doc/* !usr/share/doc/x/*", "HoldPkg = glibc"):
            self.assertIn(line + "\n", eng)
        self.assertNotIn("HoldPkg = lux-engine glibc", eng)

    def test_booleans_and_paths(self):
        cfg = self.parse("color off\ncandy no\ndownload-timeout off\ndownload-sandbox off\ndownload-user none\n"
                         "cache /srv/pkg\ncache /var/cache/lux/pkg\nlog /var/log/x.log\nsyslog on\n"
                         "repo a\n    server file:///srv/repo\n    signatures never\n")
        eng = lc.render_engine(cfg)
        body = eng.split("[options]", 1)[1]
        self.assertNotIn("\nColor\n", body)
        self.assertNotIn("ILoveCandy", body)
        self.assertNotIn("DownloadUser", body)
        for line in ("DisableDownloadTimeout", "DisableSandbox", "CacheDir = /srv/pkg", "CacheDir = /var/cache/lux/pkg",
                     "LogFile = /var/log/x.log", "UseSyslog", "SigLevel = Never"):
            self.assertIn(line + "\n", body)

    def test_cli_settings_and_legacy_lines(self):
        cfg = self.parse("aur off\nclean-keep 5\nrepo a\n    server https://a/$repo\n")
        self.assertEqual((cfg.get("aur"), cfg.get("clean-keep"), cfg.get("flatpak")), ("off", "5", "on"))
        cfg = self.parse("AUR=0\nREVIEW_PKGBUILD=1\nFLATPAK=0\nCLEAN_KEEP=3\n")
        self.assertTrue(cfg.legacy)
        self.assertEqual((cfg.get("aur"), cfg.get("flatpak"), cfg.get("clean-keep")), ("off", "off", "3"))
        # nastaveni lux se do konfigurace jadra nedostanou
        self.assertNotIn("aur", lc.render_engine(cfg).lower().split("[options]")[1])

    def test_include(self):
        self.write("etc/lux/conf.d/50-my.conf", "repo my\n    server https://my.example/$repo/$arch\nhold vim\n")
        self.write("etc/lux/conf.d/10-a.conf", "repo a\n    server https://a.example/$arch\n")
        self.write("etc/lux/conf.d/readme.txt", "garbage\n")
        cfg = self.parse()
        self.assertEqual([r.name for r in cfg.repos], ["luxos", "luxos-apps", "luxos-drivers", "core", "extra", "a", "my"])
        self.assertEqual(cfg.lists["hold"], ["vim"])
        self.assertIn(self.path("etc/lux/conf.d/50-my.conf"), cfg.sources)

    def test_mirrorlist_formats(self):
        self.write("etc/lux/m2", "# x\nServer = https://r.example/$repo/os/$arch\n\nhttps://s.example/$repo/os/$arch\n")
        cfg = self.parse("repo core\n    mirrors /etc/lux/m2\n")
        self.assertEqual([u for u, _o in cfg.repo("core").servers],
                         ["https://r.example/$repo/os/$arch", "https://s.example/$repo/os/$arch"])


class Errors(Base):
    def test_unknown_key_with_line_and_hint(self):
        msg = self.error("color on\n\nparalel-downloads 5\n")
        self.assertIn("lux.conf:3: unknown key 'paralel-downloads'", msg)
        self.assertIn("did you mean 'parallel-downloads'", msg)

    def test_pacman_syntax(self):
        self.assertIn(":1: '[options]' looks like pacman.conf syntax", self.error("[options]\nColor\n"))
        self.assertIn(":1:", self.error("ParallelDownloads = 5\n"))
        self.assertIn("without '='", self.error("parallel-downloads = 5\n"))

    def test_values(self):
        self.assertIn(":1: 'parallel-downloads' must be a whole number of at least 1", self.error("parallel-downloads 0\n"))
        self.assertIn("must be on or off", self.error("color maybe\n"))
        self.assertIn("required, optional or never", self.error("signatures sometimes\n"))
        self.assertIn("needs a value", self.error("hold\n"))
        self.assertIn("absolute path", self.error("cache var/cache\n"))

    def test_repo_errors(self):
        self.assertIn(":1: indented line", self.error("  server https://x/\n"))
        self.assertIn(":2: 'server' belongs to a repository", self.error("repo a\nserver https://x/\n"))
        self.assertIn(":1: repository 'a' has no 'server'", self.error("repo a\nhold x\n"))
        self.assertIn(":3: repository 'a' is already defined at", self.error(
            "repo a\n  server https://x/\nrepo a\n  server https://y/\n"))
        self.assertIn("'local' cannot be used", self.error("repo local\n  server https://x/\n"))
        self.assertIn("unknown repository key 'mirror'", self.error("repo a\n  mirror /etc/lux/mirrorlist\n"))
        self.assertIn("global keys must not be indented", self.error("repo a\n  hold x\n"))
        self.assertIn("https://, http://, ftp:// or file://", self.error("repo a\n  server example.org\n"))

    def test_signatures_never_only_local(self):
        self.assertIn("only allowed for a local repository", self.error("signatures never\n"))
        self.assertIn("downloads from the internet", self.error("repo a\n  server https://x/\n  signatures never\n"))
        self.parse("repo a\n  server file:///srv/r\n  signatures never\n")

    def test_mirrors_errors(self):
        self.assertIn(":2: mirror list /etc/lux/nope does not exist", self.error("repo a\n  mirrors /etc/lux/nope\n"))
        self.write("etc/lux/empty", "# all commented\n#https://x/\n")
        self.assertIn("has no mirrors", self.error("repo a\n  mirrors /etc/lux/empty\n"))
        self.write("etc/lux/bad", "https://ok/$repo\nnot a url\n")
        self.assertIn("bad:2: not a mirror address", self.error("repo a\n  mirrors /etc/lux/bad\n"))

    def test_include_errors(self):
        self.write("etc/lux/conf.d/x.conf", "repo a\n  server https://a/\nbogus 1\n")
        self.assertIn("conf.d/x.conf:3: unknown key 'bogus'", self.error("include /etc/lux/conf.d/*.conf\n"))
        self.assertIn("does not exist", self.error("include /etc/lux/missing.conf\n"))
        self.write("etc/lux/loop.conf", "include /etc/lux/loop.conf\n")
        self.assertIn("too many nested includes", self.error("include /etc/lux/loop.conf\n"))


class Ensure(Base):
    """ensure(): /run/lux/engine.conf jen kdyz se zdroje zmenily; rozbita lux.conf = posledni funkcni."""

    def setUp(self):
        super().setUp()
        self.conf = self.path("etc/lux/lux.conf")
        self.out = self.path("run/lux/engine.conf")
        # lux.conf odkazuje na /etc/lux/mirrorlist - v testu absolutni cesty do docasneho korene
        with open(self.conf) as f:
            text = f.read().replace("/etc/lux/", self.path("etc/lux/"))
        with open(self.conf, "w") as f:
            f.write(text)

    def ensure(self):
        import io
        err = io.StringIO()
        path, state = lc.ensure(self.conf, self.out, err=err)
        return path, state, err.getvalue()

    def test_generate_and_fresh(self):
        path, state, err = self.ensure()
        self.assertEqual((path, state, err), (self.out, "ok", ""))
        self.assertTrue(lc.is_fresh(self.out))
        st = os.stat(self.out)
        self.assertEqual(st.st_mode & 0o777, 0o644)
        mtime = st.st_mtime_ns
        self.ensure()
        self.assertEqual(os.stat(self.out).st_mtime_ns, mtime)          # beze zmeny se nepise

    def test_change_of_any_source_regenerates(self):
        self.ensure()
        for rel, add in (("etc/lux/lux.conf", "hold vim\n"), ("etc/lux/mirrorlist", "https://new.example/$repo/os/$arch\n")):
            with open(self.path(rel), "a") as f:
                f.write(add)
            self.assertFalse(lc.is_fresh(self.out), rel)
            self.ensure()
            self.assertTrue(lc.is_fresh(self.out))
        with open(self.out) as f:
            text = f.read()
        self.assertIn("IgnorePkg = vim\n", text)
        self.assertIn("Server = https://new.example/$repo/os/$arch\n", text)
        # novy soubor v conf.d
        self.write("etc/lux/conf.d/a.conf", "repo a\n  server https://a.example/\n")
        self.assertFalse(lc.is_fresh(self.out))
        self.ensure()
        with open(self.out) as f:
            self.assertIn("[a]\n", f.read())

    def test_broken_config_keeps_last_good(self):
        self.ensure()
        with open(self.out) as f:
            good = f.read()
        with open(self.conf, "a") as f:
            f.write("bogus-key 1\n")
        path, state, err = self.ensure()
        self.assertEqual((path, state), (self.out, "stale"))
        self.assertIn("unknown key 'bogus-key'", err)
        self.assertIn("last working configuration", err)
        with open(self.out) as f:
            self.assertEqual(f.read(), good)

    def test_broken_config_without_last_good(self):
        with open(self.conf, "a") as f:
            f.write("[options]\n")
        path, state, err = self.ensure()
        self.assertEqual((path, state), (None, "error"))
        self.assertIn("looks like pacman.conf syntax", err)


class Wrapper(Base):
    """lux-engine-wrapper: rychla kontrola cerstvosti v bashi = lux_config.is_fresh."""

    def setUp(self):
        super().setUp()
        self.bin = self.path("bin")
        self.libexec = self.path("libexec")
        os.makedirs(self.bin)
        os.makedirs(self.libexec)
        shutil.copy(os.path.join(PKG, "lux-engine-wrapper"), os.path.join(self.bin, "lux-engine"))
        os.symlink("lux-engine", os.path.join(self.bin, "pacman"))      # docasny odkaz po migraci
        with open(os.path.join(self.libexec, "lux-engine"), "w") as f:
            f.write('#!/bin/bash\nprintf "%s\\n" "$@" >"$WRAP_LOG"\n')
        os.chmod(os.path.join(self.libexec, "lux-engine"), 0o755)
        self.tool = self.path("lux-config")
        with open(self.tool, "w") as f:
            f.write(f'#!/bin/bash\necho call >>"$WRAP_LOG.calls"\nexec python3 "{PKG}/lux_config.py" "$@"\n')
        os.chmod(self.tool, 0o755)
        self.conf = self.path("etc/lux/lux.conf")
        with open(self.conf) as f:
            text = f.read().replace("/etc/lux/", self.path("etc/lux/"))
        with open(self.conf, "w") as f:
            f.write(text)
        self.out = self.path("run/lux/engine.conf")
        self.log = self.path("log")

    def run_wrapper(self, *args, name="lux-engine"):
        env = dict(os.environ, LUX_ENGINE_LIBEXEC=self.libexec, LUX_ENGINE_DEFAULT_CONF=self.out,
                   LUX_CONFIG_TOOL=self.tool, WRAP_LOG=self.log)
        env.pop("LUX_ENGINE_CONF_FILE", None)
        # lux-config ensure v testu s vlastni lux.conf a vystupem
        with open(self.tool, "w") as f:
            f.write(f'#!/bin/bash\necho call >>"$WRAP_LOG.calls"\nexec python3 "{PKG}/lux_config.py" "$@" '
                    f'--config "{self.conf}" --output "{self.out}"\n')
        r = subprocess.run([os.path.join(self.bin, name)] + list(args), capture_output=True, text=True, env=env)
        with open(self.log) as f:
            argv = f.read().splitlines()
        try:
            with open(self.log + ".calls") as f:
                calls = len(f.read().splitlines())
        except OSError:
            calls = 0
        return r, argv, calls

    def test_generates_once_then_fast_path(self):
        r, argv, calls = self.run_wrapper("-Qi", "x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(argv, ["-Qi", "x"])
        self.assertEqual(calls, 1)
        self.assertTrue(os.path.exists(self.out))
        r, argv, calls = self.run_wrapper("-Q")
        self.assertEqual(calls, 1)                      # cerstva: bez Pythonu
        time.sleep(0.01)
        with open(self.conf, "a") as f:
            f.write("hold vim\n")
        r, argv, calls = self.run_wrapper("-Q")
        self.assertEqual(calls, 2)
        with open(self.out) as f:
            self.assertIn("IgnorePkg = vim", f.read())

    def test_compat_name_runs_engine(self):
        r, argv, _calls = self.run_wrapper("-Syu", name="pacman")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(argv, ["-Syu"])

    def test_user_copy_passed_with_config(self):
        """Kopie konfigurace uzivatele (LUX_ENGINE_CONF_FILE od lux): jadro ji dostane pres --config."""
        user = self.path("user/engine.conf")
        os.makedirs(os.path.dirname(user))
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "ensure", "--config", self.conf,
                            "--output", user], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = dict(os.environ, LUX_ENGINE_LIBEXEC=self.libexec, LUX_ENGINE_DEFAULT_CONF=self.out,
                   LUX_ENGINE_CONF_FILE=user, LUX_CONFIG_TOOL="/nonexistent", WRAP_LOG=self.log)
        r = subprocess.run([os.path.join(self.bin, "lux-engine"), "-Q"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            self.assertEqual(f.read().splitlines(), ["--config", user, "-Q"])

    def test_own_config_skips_generation(self):
        r, argv, calls = self.run_wrapper("--config", "/x.conf", "-Q")
        self.assertEqual((argv, calls), (["--config", "/x.conf", "-Q"], 0))

    def test_broken_config(self):
        with open(self.conf, "a") as f:
            f.write("nonsense\n")
        with open(self.tool, "w") as f:
            f.write(f'#!/bin/bash\nexec python3 "{PKG}/lux_config.py" "$@" --config "{self.conf}" --output "{self.out}"\n')
        env = dict(os.environ, LUX_ENGINE_LIBEXEC=self.libexec, LUX_ENGINE_DEFAULT_CONF=self.out,
                   LUX_CONFIG_TOOL=self.tool, WRAP_LOG=self.log)
        r = subprocess.run([os.path.join(self.bin, "lux-engine"), "-Q"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown key 'nonsense'", r.stderr)


class Convert(Base):
    def test_custom_repos_and_options(self):
        self.write("etc/pacman.d/chaotic-mirrorlist", "# c\nServer = https://cdn.chaotic.example/$repo/$arch\n")
        self.write("etc/pacman.conf", OLD_PACMAN_CONF.replace("ParallelDownloads = 10", "ParallelDownloads = 3") +
                   "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n\n[chaotic-aur]\n"
                   "Include = /etc/pacman.d/chaotic-mirrorlist\n\n[mine]\nSigLevel = Optional TrustAll\n"
                   "Server = file:///home/me/repo\n\n[options]\nIgnorePkg = linux linux-headers\n"
                   "IgnoreGroup = kde\nNoUpgrade = etc/x.conf\nXferCommand = /usr/bin/curl %u\n"
                   "CacheDir = /srv/cache/\n")
        text, extra, warns = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        for line in ("parallel-downloads  3", "hold  linux linux-headers", "ignore-group  kde",
                     "no-upgrade  etc/x.conf", "cache  /srv/cache/", "repo multilib\n    mirrors  /etc/lux/mirrorlist",
                     "repo chaotic-aur\n    mirrors  /etc/lux/chaotic-mirrorlist",
                     "repo mine\n    server  file:///home/me/repo\n    signatures  optional"):
            self.assertIn(line + "\n", text)
        self.assertEqual(list(extra), ["/etc/lux/chaotic-mirrorlist"])
        self.assertIn("https://cdn.chaotic.example/$repo/$arch\n", extra["/etc/lux/chaotic-mirrorlist"])
        self.assertTrue(any("XferCommand" in w for w in warns))
        self.write("etc/lux/chaotic-mirrorlist", extra["/etc/lux/chaotic-mirrorlist"])
        cfg = self.parse(text)          # vysledek je platna lux.conf
        self.assertEqual(cfg.get("parallel-downloads"), "3")

    def test_holdpkg_pacman_becomes_lux_engine(self):
        self.write("etc/pacman.conf", "[options]\nHoldPkg = pacman glibc\n[core]\nServer = https://x/$repo\n")
        text, _e, _w = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        self.assertNotIn("protect", text)       # = vychozi "lux-engine glibc"

    def test_plain_pacman_defaults(self):
        """Konfigurace bez voleb LuxOS (holy Arch): vychozi hodnoty pacmanu se zachovaji."""
        self.write("etc/pacman.conf", "[options]\nArchitecture = auto\nSigLevel = Required DatabaseOptional\n"
                   "[core]\nInclude = /etc/pacman.d/mirrorlist\n")
        text, _e, _w = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        for line in ("color  off", "candy  off", "parallel-downloads  1", "download-user  none"):
            self.assertIn(line + "\n", text)

    def test_mirrors_import_cli(self):
        src = self.path("reflector.out")
        self.write("reflector.out", "##\n## Arch Linux repository mirrorlist\n##\n\nServer = https://a.example/$repo/os/$arch\n"
                   "Server = https://b.example/$repo/os/$arch\n")
        out = self.path("etc/lux/mirrorlist")
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "mirrors-import", src, "--output", out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as f:
            text = f.read()
        self.assertTrue(text.startswith("# LuxOS - download mirrors"))
        self.assertTrue(text.endswith("\nhttps://a.example/$repo/os/$arch\nhttps://b.example/$repo/os/$arch\n"))
        self.assertNotIn("Server", text)
        # prazdny vystup reflectoru seznam nezmeni
        self.write("reflector.out", "# nothing\n")
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "mirrors-import", src, "--output", out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        with open(out) as f:
            self.assertEqual(f.read(), text)

    def test_enable_repo(self):
        conf = self.path("etc/lux/lux.conf")
        with open(conf) as f:
            text = f.read().replace("/etc/lux/", self.path("etc/lux/"))
        with open(conf, "w") as f:
            f.write(text)
        self.assertTrue(lc.enable_repo("multilib", conf, mirrors=self.path("etc/lux/mirrorlist")))
        self.assertFalse(lc.enable_repo("multilib", conf, mirrors=self.path("etc/lux/mirrorlist")))
        cfg = lc.parse(conf)
        self.assertEqual(cfg.repos[-1].name, "multilib")
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "has-repo", "multilib", "--config", conf])
        self.assertEqual(r.returncode, 0)
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "has-repo", "nope", "--config", conf])
        self.assertEqual(r.returncode, 1)


OLD_PACMAN_CONF = """# LuxOS - pacman
[options]
HoldPkg     = pacman glibc
Architecture = auto
Color
ILoveCandy
CheckSpace
VerbosePkgLists
ParallelDownloads = 10
DownloadUser = alpm
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

# Repozitare LuxOS (baliky podepsane klicem z luxos-keyring)
[luxos]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[luxos-apps]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist
"""

if __name__ == "__main__":
    unittest.main()


class MovedServers(Base):
    def test_old_luxos_address_updated_and_identical_pacnew_dropped(self):
        pkg = open(os.path.join(PKG, "lux.conf")).read()
        old = pkg.replace("https://luxos.lux-ai.cz/repo/", "https://lsl.lux-ai.cz/luxos/")
        self.assertNotEqual(old, pkg)
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w") as f:
            f.write(old)
        with open(conf + ".pacnew", "w") as f:
            f.write(pkg)
        self.assertTrue(lc.update_moved_servers(conf))
        self.assertEqual(open(conf).read(), pkg)
        self.assertFalse(os.path.exists(conf + ".pacnew"))
        self.assertFalse(lc.update_moved_servers(conf))

    def test_identical_luxnew_dropped(self):
        """lux-engine od LuxOS 1.0 nechava lux.conf.luxnew (driv .pacnew)."""
        pkg = open(os.path.join(PKG, "lux.conf")).read()
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w") as f:
            f.write(pkg.replace("https://luxos.lux-ai.cz/repo/", "https://lsl.lux-ai.cz/luxos/"))
        with open(conf + ".luxnew", "w") as f:
            f.write(pkg)
        self.assertTrue(lc.update_moved_servers(conf))
        self.assertFalse(os.path.exists(conf + ".luxnew"))

    def test_custom_config_keeps_everything_else(self):
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        text = "hold  nano\n\nrepo luxos\n    server  https://lsl.lux-ai.cz/luxos/$repo/$arch   # LuxOS\n\nrepo mine\n    server  https://lsl.lux-ai.cz/other/$repo\n"
        with open(conf, "w") as f:
            f.write(text)
        with open(conf + ".pacnew", "w") as f:
            f.write("different")
        self.assertTrue(lc.update_moved_servers(conf))
        self.assertEqual(open(conf).read(), text.replace("https://lsl.lux-ai.cz/luxos/$repo", "https://luxos.lux-ai.cz/repo/$repo"))
        self.assertTrue(os.path.exists(conf + ".pacnew"))


class DriversRepo(Base):
    def conf(self, text):
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w") as f:
            f.write(text)
        return conf, os.path.join(self.root, "var/lib/lux/luxos-drivers-repo")

    def test_added_once_to_old_install(self):
        pkg = open(os.path.join(PKG, "lux.conf")).read()
        old = lc.without_drivers_repo(pkg)
        self.assertNotIn("luxos-drivers", old)
        conf, stamp = self.conf(old)
        self.assertTrue(lc.add_drivers_repo(conf, stamp))
        self.assertIn("repo luxos-drivers\n    server  https://luxos.lux-ai.cz/repo/$repo/$arch\n", open(conf).read())
        self.assertEqual(open(conf).read().count("repo luxos-drivers"), 1)
        # odebrano uzivatelem -> uz se nevrati
        with open(conf, "w") as f:
            f.write(old)
        self.assertFalse(lc.add_drivers_repo(conf, stamp))
        self.assertNotIn("luxos-drivers", open(conf).read())

    def test_new_install_already_has_it(self):
        conf, stamp = self.conf(open(os.path.join(PKG, "lux.conf")).read())
        before = open(conf).read()
        self.assertFalse(lc.add_drivers_repo(conf, stamp))
        self.assertEqual(open(conf).read(), before)
        self.assertTrue(os.path.exists(stamp))

    def test_not_added_without_luxos_repo(self):
        conf, stamp = self.conf("repo core\n    server  https://example.invalid/$repo/os/$arch\n")
        self.assertFalse(lc.add_drivers_repo(conf, stamp))
        self.assertNotIn("luxos-drivers", open(conf).read())
