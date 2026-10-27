"""Testy lux-config (format /etc/lux/lux.conf - TOML i stary format LuxOS 0.9, generovani
/run/lux/engine.conf, prevod pacman.conf, prevod stareho formatu na TOML).

    python3 -m unittest discover -s packages/lux-engine/tests -v
"""
import os
import re
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import tomllib
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
import lux_config as lc  # noqa: E402

# vychozi lux.conf LuxOS 0.9 (stary format "klic hodnota") - zpetna kompatibilita a prevod
OLD_DEFAULT = os.path.join(HERE, "lux.conf.0.9")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
                                              text=lc.without_drivers_repo(read(os.path.join(PKG, "lux.conf"))))))

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
        msg = self.error("[options]\nColor\n")
        self.assertIn(":2: Expected '=' after a key", msg)
        self.assertIn("looks like pacman.conf; convert it with: lux-config convert-pacman", msg)
        # stary format: '[...]' az za prvnim klicem
        self.assertIn(":2: '[options]' looks like pacman.conf syntax", self.error("color on\n[options]\n"))
        self.assertIn("without '='", self.error("color on\nparallel-downloads = 5\n"))

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
        for rel, add in (("etc/lux/lux.conf", "\n[paths]\nhooks = \"/srv/hooks\"\n"),
                         ("etc/lux/mirrorlist", "https://new.example/$repo/os/$arch\n")):
            with open(self.path(rel), "a") as f:
                f.write(add)
            self.assertFalse(lc.is_fresh(self.out), rel)
            self.ensure()
            self.assertTrue(lc.is_fresh(self.out))
        with open(self.out) as f:
            text = f.read()
        self.assertIn("HookDir = /srv/hooks\n", text)
        self.assertIn("Server = https://new.example/$repo/os/$arch\n", text)
        # novy soubor v conf.d
        self.write("etc/lux/conf.d/a.conf", "[repo.a]\nserver = \"https://a.example/\"\n")
        self.assertFalse(lc.is_fresh(self.out))
        self.ensure()
        with open(self.out) as f:
            self.assertIn("[a]\n", f.read())

    def test_broken_config_keeps_last_good(self):
        self.ensure()
        with open(self.out) as f:
            good = f.read()
        with open(self.conf, "a") as f:
            f.write("[downloads.x]\nparallel = \"many\"\n[packages.y]\n")
        with open(self.conf) as f:
            text = f.read()
        with open(self.conf, "w") as f:
            f.write(text.replace("parallel = 10", "parallel = 0"))
        path, state, err = self.ensure()
        self.assertEqual((path, state), (self.out, "stale"))
        self.assertIn("lux.conf:11: 'parallel' in [downloads] must be a whole number of at least 1", err)
        self.assertIn("last working configuration", err)
        with open(self.out) as f:
            self.assertEqual(f.read(), good)

    def test_broken_config_without_last_good(self):
        with open(self.conf, "a") as f:
            f.write("[options]\nColor\n")
        path, state, err = self.ensure()
        self.assertEqual((path, state), (None, "error"))
        self.assertIn("looks like pacman.conf", err)


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
        with open(self.conf, "w") as f:
            f.write(lc.toml_set(read(self.conf), "packages", "hold", ["vim"]))
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
        self.assertIn("lux.conf:49: Expected '=' after a key", r.stderr)


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
        for line in ("[downloads]\nparallel = 3", 'hold = ["linux", "linux-headers"]', 'ignore_group = ["kde"]',
                     'no_upgrade = ["etc/x.conf"]', '[paths]\ncache = ["/srv/cache/"]',
                     '[repo.multilib]\nmirrors = "/etc/lux/mirrorlist"',
                     '[repo.chaotic-aur]\nmirrors = "/etc/lux/chaotic-mirrorlist"',
                     '[repo.mine]\nserver = "file:///home/me/repo"\nsignatures = "optional"',
                     '# ── Other repositories ────────────────────────', '[include]\nfiles = ["/etc/lux/conf.d/*.conf"]'):
            self.assertIn(line + "\n", text)
        self.assertEqual(lc.detect_format(text), "toml")
        self.assertEqual(list(extra), ["/etc/lux/chaotic-mirrorlist"])
        self.assertIn("https://cdn.chaotic.example/$repo/$arch\n", extra["/etc/lux/chaotic-mirrorlist"])
        self.assertTrue(any("XferCommand" in w for w in warns))
        self.write("etc/lux/chaotic-mirrorlist", extra["/etc/lux/chaotic-mirrorlist"])
        cfg = self.parse(text)          # vysledek je platna lux.conf
        self.assertEqual(cfg.get("parallel-downloads"), "3")

    def test_holdpkg_pacman_becomes_lux_engine(self):
        self.write("etc/pacman.conf", "[options]\nHoldPkg = pacman glibc\n[core]\nServer = https://x/$repo\n")
        text, _e, _w = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        self.assertIn('protect = ["lux-engine", "glibc"]\n', text)       # = vychozi

    def test_plain_pacman_defaults(self):
        """Konfigurace bez voleb LuxOS (holy Arch): vychozi hodnoty pacmanu se zachovaji."""
        self.write("etc/pacman.conf", "[options]\nArchitecture = auto\nSigLevel = Required DatabaseOptional\n"
                   "[core]\nInclude = /etc/pacman.d/mirrorlist\n")
        text, _e, _w = lc.convert_pacman_conf("/etc/pacman.conf", self.root)
        for line in ("color = false", "candy = false", "parallel = 1", 'user = "none"'):
            self.assertIn(line + "\n", text)
        cfg = self.parse(text)
        self.assertEqual((cfg.get("color"), cfg.get("parallel-downloads"), cfg.get("download-user")), ("off", "1", "none"))

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
        pkg = read(OLD_DEFAULT)
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

    def test_toml_added_after_luxos_apps(self):
        text = lc.without_drivers_repo(read(os.path.join(PKG, "lux.conf")))
        self.assertNotIn("luxos-drivers", text)
        self.assertNotIn("\n\n\n", text)
        conf, stamp = self.conf(text)
        self.assertTrue(lc.add_drivers_repo(conf, stamp))
        # znovu presne vychozi soubor (za [repo.luxos-apps], pred oddelovacem Archu)
        self.assertEqual(read(conf), read(os.path.join(PKG, "lux.conf")))


class Toml(Base):
    """Format TOML (LuxOS 1.0): typy hodnot, chyby s cisly radku, varovani, komentare."""

    def warnings(self, text):
        return [lc.format_warning(w) for w in self.parse(text).warnings]

    def test_default_config_values(self):
        d = lc.load("/etc/lux/lux.conf", root=self.root)
        self.assertEqual(d["general"], {"architecture": "auto", "color": True, "candy": True, "verbose": True,
                                        "syslog": False})
        self.assertEqual(d["downloads"], {"parallel": 10, "check_space": True, "user": "alpm", "timeout": True,
                                          "sandbox": True})
        self.assertEqual(d["security"], {"signatures": "required", "local_signatures": "optional",
                                         "protect": ["lux-engine", "glibc"]})
        self.assertEqual(d["packages"], {"aur": True, "review_pkgbuild": True, "flatpak": True, "cache_keep": 2,
                                         "hold": [], "ignore_group": [], "no_upgrade": [], "no_extract": []})
        self.assertEqual([r["name"] for r in d["repos"]], ["luxos", "luxos-apps", "luxos-drivers", "core", "extra"])
        core = d["repos"][3]
        self.assertEqual((core["mirrors"], core["server"], core["signatures"], core["usage"]),
                         (["/etc/lux/mirrorlist"], [], None, ["all"]))
        self.assertTrue(core["servers"])
        self.assertEqual(d["include"], [])          # conf.d je prazdny
        self.assertEqual(d["warnings"], [])
        self.assertEqual(set(d["formats"].values()), {"toml"})
        self.assertEqual(json.loads(json.dumps(d)), d)          # serializovatelne (lux-config json)

    def test_same_as_old_default(self):
        """Nova vychozi lux.conf = vychozi lux.conf LuxOS 0.9 (stejna konfigurace jadra i nastaveni lux)."""
        new = lc.parse("/etc/lux/lux.conf", root=self.root)
        old = lc.parse("/etc/lux/lux.conf", root=self.root, text=read(OLD_DEFAULT))
        self.assertEqual(lc.comparable(new), lc.comparable(old))
        self.assertEqual(lc.semantic(new), lc.semantic(old))
        self.assertEqual(old.formats, {"/etc/lux/lux.conf": "old"})

    def test_all_value_types(self):
        cfg = self.parse(textwrap.dedent('''\
            # komentar ── s unicode ┌─┐ a "uvozovkami" = nic
            [general]
            architecture = ["x86_64", "x86_64_v3"]   # vic architektur
            color = false
            syslog = true
            [downloads]
            parallel = 3
            user = "none"
            timeout = false
            sandbox = false
            [security]
            signatures = "optional"
            protect = []
            [packages]
            aur = false
            cache_keep = 0
            hold = [
                "linux",          # jadro
                "linux-headers",
                # firefox nechat
                "firefox",
            ]
            ignore_group = "kde gnome"
            no_extract = ["usr/share/doc/*", "!usr/share/doc/x/*"]
            [paths]
            cache = ["/srv/pkg", "/var/cache/lux/pkg"]
            log = "/var/log/x.log"
            hooks = "/srv/hooks"
            [repo.my-repo_2]
            server = 'file:///srv/repo'
            signatures = "never"
            usage = ["sync", "search"]
            [repo."dotted.name+x"]
            server = ["https://a.example/$repo/$arch", "https://b.example/\\u0024repo"]
            usage = "install upgrade"
            '''))
        self.assertEqual(cfg.warnings, [])
        eng = lc.render_engine(cfg).split("[options]", 1)[1]
        for line in ("Architecture = x86_64 x86_64_v3", "ParallelDownloads = 3", "SigLevel = Optional TrustAll",
                     "UseSyslog", "DisableDownloadTimeout", "DisableSandbox", "IgnorePkg = linux linux-headers firefox",
                     "IgnoreGroup = kde gnome", "NoExtract = usr/share/doc/* !usr/share/doc/x/*",
                     "CacheDir = /srv/pkg", "CacheDir = /var/cache/lux/pkg", "LogFile = /var/log/x.log",
                     "HookDir = /srv/hooks",
                     "[my-repo_2]\nSigLevel = Never\nUsage = Sync Search\nServer = file:///srv/repo",
                     "[dotted.name+x]\nUsage = Install Upgrade\nServer = https://a.example/$repo/$arch\n"
                     "Server = https://b.example/$repo"):
            self.assertIn(line + "\n", eng)
        for absent in ("Color", "HoldPkg", "DownloadUser"):
            self.assertNotIn(absent, eng)
        self.assertEqual((cfg.get("aur"), cfg.get("clean-keep")), ("off", "0"))
        d = lc.to_dict(cfg)
        self.assertEqual(d["packages"]["hold"], ["linux", "linux-headers", "firefox"])
        self.assertEqual(d["general"]["architecture"], "x86_64 x86_64_v3")
        self.assertEqual(d["security"]["protect"], [])
        self.assertEqual(d["repos"][1]["name"], "dotted.name+x")

    def test_string_escapes_and_comments(self):
        cfg = self.parse('[repo.a]\nserver = "https://x.example/a\\"b\\\\c#d"  # komentar # dalsi\n'
                         "usage = 'sync'#bez mezery\n")
        self.assertEqual(cfg.repo("a").servers[0][0], 'https://x.example/a"b\\c#d')

    def test_errors_with_line_numbers(self):
        cases = [
            ("[downloads]\nparallel = 0\n", ":2: 'parallel' in [downloads] must be a whole number of at least 1"),
            ("[downloads]\nparallel = \"10\"\n", ":2: 'parallel' in [downloads] must be a whole number of at least 1 "
                                                 "(without quotes), not \"10\""),
            ("\n[general]\ncolor = \"on\"\n", ":3: 'color' in [general] must be true or false, not \"on\""),
            ("[packages]\ncache_keep = true\n", ":2: 'cache_keep' in [packages] must be a whole number"),
            ("[security]\nsignatures = \"sometimes\"\n", ":2: 'signatures' in [security] must be required, optional"),
            ("[security]\nsignatures = \"never\"\n", ":2: 'signatures = \"never\"' is only allowed for a local"),
            ("[packages]\nhold = [1, 2]\n", ":2: 'hold' in [packages] must be text in quotes or a list of texts, not 1"),
            ("[paths]\ncache = \"var/cache\"\n", ":2: 'cache' in [paths] needs an absolute path"),
            ("[downloads]\nuser = \"a b\"\n", ":2: 'user' in [downloads] takes one value, got 2"),
            ("[repo.a]\nserver = \"example.org\"\n", ":2: 'server' in [repo.a] must be an https://"),
            ("[repo.a]\nusage = [\"sometimes\"]\n", ":2: unknown usage 'sometimes'"),
            ("x = 1\n[repo.a]\nmirrors = \"/etc/lux/nope\"\n", ":3: mirror list /etc/lux/nope does not exist"),
            ("[repo.a]\n\nsignatures = \"optional\"\n", ":1: repository 'a' has no 'server' or 'mirrors' line"),
            ("[repo.a]\nserver = \"https://x/\"\n[repo.a]\n", ":3: Cannot declare ('repo', 'a') twice"),
            ("[repo.local]\nserver = \"https://x/\"\n", ":1: 'local' cannot be used as a repository name"),
            ("[repo.\"a b\"]\nserver = \"https://x/\"\n", ":1: invalid repository name 'a b'"),
            ("[repo]\na = 1\n", ":2: repository 'a' must be a table"),
            ("general = 1\n", ":1: 'general' must be a table"),
            ("[general]\ncolor = true\ncolor = false\n", ":3: Cannot overwrite a value"),
            ("[general]\ncolor = yes\n", ":2: Invalid value - text values need quotes"),
            ("[packages]\nhold = [\"a\",\n", ":3: Invalid value"),
            ("[packages]\nhold  linux\n", ":2: Expected '=' after a key in a key/value pair - 'hold  linux' is the "
                                          "old 'key value' format"),
            ("[repo.a]\nserver = \"https://x/\"\nsignatures = \"never\"\n",
             ":1: 'signatures never' is only allowed for a local repository (file://), 'a' downloads"),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertIn("lux.conf" + want, self.error(text))

    def test_repo_duplicate_across_files(self):
        self.write("etc/lux/conf.d/a.conf", "[repo.core]\nserver = \"https://x/\"\n")
        with self.assertRaises(lc.ConfigError) as cm:
            self.parse()
        self.assertIn("conf.d/a.conf:1: repository 'core' is already defined at /etc/lux/lux.conf:", str(cm.exception))

    def test_unknown_keys_are_warnings(self):
        w = self.warnings("bogus = 1\n[general]\nparalel = 3\ncolor = true\n[downloads]\nparallel-downloads = 3\n"
                          "colour = 1\n[nope]\nx = 1\n[repo.a]\nserver = \"https://x/\"\nmirror = \"/x\"\n"
                          "[include]\nfile = \"/x\"\n")
        self.assertEqual(w, [
            "/etc/lux/lux.conf:1: unknown key 'bogus' outside of a table - ignored",
            "/etc/lux/lux.conf:3: unknown key 'paralel' in [general] (did you mean 'parallel' in [downloads]?) - ignored",
            "/etc/lux/lux.conf:6: unknown key 'parallel-downloads' in [downloads] (did you mean 'parallel'?) - ignored",
            "/etc/lux/lux.conf:7: unknown key 'colour' in [downloads] (did you mean 'color' in [general]?) - ignored",
            "/etc/lux/lux.conf:8: unknown table [nope] - ignored",
            "/etc/lux/lux.conf:12: unknown repository key 'mirror' in [repo.a] (did you mean 'mirrors'?) - ignored",
            "/etc/lux/lux.conf:14: unknown key 'file' in [include] (use: files = [...]) - ignored",
        ])
        w = self.warnings("[general]\nparallel = 3\n")
        self.assertEqual(w, ["/etc/lux/lux.conf:2: unknown key 'parallel' in [general] (it belongs to [downloads]) "
                             "- ignored"])

    def test_include_forms(self):
        self.write("etc/lux/conf.d/50-my.conf", "[repo.my]\nserver = \"https://my.example/$repo/$arch\"\n"
                                                "[packages]\nhold = [\"vim\"]\n")
        self.write("etc/lux/conf.d/10-old.conf", "repo old\n    server https://old.example/$arch\nhold  nano\n")
        self.write("etc/lux/extra.toml", "[packages]\nhold = \"emacs\"\nflatpak = false\n")
        base = "[repo.a]\nserver = \"https://a/\"\n"
        for inc in ('[include]\nfiles = ["/etc/lux/conf.d/*.conf", "extra.toml"]\n',
                    'include = ["/etc/lux/conf.d/*.conf", "/etc/lux/extra.toml"]\n' + base.replace("[repo.a]", "[repo.b]")):
            with self.subTest(inc=inc):
                cfg = self.parse((base + inc) if inc.startswith("[") else (inc.split("\n", 1)[0] + "\n" + base))
                self.assertEqual([r.name for r in cfg.repos], ["a", "old", "my"])
                self.assertEqual(lc.to_dict(cfg)["packages"]["hold"], ["nano", "vim", "emacs"])
                self.assertEqual(cfg.get("flatpak"), "off")
                self.assertEqual(cfg.formats["/etc/lux/conf.d/10-old.conf"], "old")
                self.assertEqual(cfg.warnings, [])

    def test_user_layout_include_inside_last_repo(self):
        """Tvar ze zadani (include = ... az za [repo.extra]): v TOML patri do [repo.extra] - pouzije se, varovani."""
        self.write("etc/lux/conf.d/a.conf", "[repo.mine]\nserver = \"https://m/\"\n")
        cfg = self.parse("[repo.extra]\nmirrors = \"/etc/lux/mirrorlist\"\n\n# ── Additional ──\n\n"
                         "include = \"/etc/lux/conf.d/*.conf\"\n")
        self.assertEqual([r.name for r in cfg.repos], ["extra", "mine"])
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn(":6: in TOML this 'include' belongs to the repository table", lc.format_warning(cfg.warnings[0]))

    def test_detect_format(self):
        for text, fmt in (("", "toml"), ("# only comment\n", "toml"), ("[general]\n", "toml"),
                          ("  # c\n\nx = 1\n", "toml"), ('"quoted key" = 1\n', "toml"), ("color on\n", "old"),
                          ("AUR=1\n", "old"), ("repo core\n  mirrors /x\n", "old"), ("[options]\nColor\n", "toml"),
                          ("include  /etc/lux/conf.d/*.conf\n", "old")):
            self.assertEqual(lc.detect_format(text), fmt, text)

    def test_user_override_toml(self):
        home = self.path("home")
        self.write("home/lux/lux.conf", "[packages]\naur = false\ncache_keep = 5\n")
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = home
        try:
            vals, _cfg = lc.cli_settings("/etc/lux/lux.conf", root=self.root)
            d = lc.load("/etc/lux/lux.conf", root=self.root, user=True)
        finally:
            if old is None:
                del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old
        self.assertEqual((vals["aur"], vals["clean-keep"], vals["flatpak"]), ("off", "5", "on"))
        self.assertEqual((d["packages"]["aur"], d["packages"]["cache_keep"]), (False, 5))

    def test_cli_check_warnings_and_old_format(self):
        conf = self.path("etc/lux/lux.conf")
        with open(conf) as f:
            text = f.read().replace("/etc/lux/", self.path("etc/lux/"))
        with open(conf, "w") as f:
            f.write(text.replace("cache_keep = 2", "cache_keep = 2\nkeep = 3"))
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "check", conf],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lux.conf:25: unknown key 'keep' in [packages]", r.stderr)
        self.assertIn("lux.conf: OK (1 warning)", r.stdout)
        with open(conf, "w") as f:
            f.write(read(OLD_DEFAULT).replace("/etc/lux/", self.path("etc/lux/")))
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "check", conf],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uses the old LuxOS 0.9 format (still read); convert it with: lux config migrate", r.stderr)
        for key, want in (("packages.cache_keep", "2"), ("clean-keep", "2"), ("downloads.parallel", "10"),
                          ("security.protect", "lux-engine glibc")):
            r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "get", key, "--config", conf],
                               capture_output=True, text=True, env=dict(os.environ, XDG_CONFIG_HOME=self.path("none")))
            self.assertEqual(r.stdout.strip(), want, key)


class Writers(Base):
    """Zapis do lux.conf v TOML: zbytek souboru (komentare, poradi) zustane."""

    def test_enable_repo_toml(self):
        conf = self.path("etc/lux/lux.conf")
        with open(conf) as f:
            text = f.read().replace("/etc/lux/", self.path("etc/lux/"))
        with open(conf, "w") as f:
            f.write(text)
        self.assertTrue(lc.enable_repo("multilib", conf, mirrors=self.path("etc/lux/mirrorlist")))
        new = read(conf)
        self.assertIn('mirrorlist"\n\n[repo.multilib]\nmirrors = "%s"\n\n# ── Additional configuration'
                      % self.path("etc/lux/mirrorlist"), new)
        self.assertTrue(new.startswith(text.split("[repo.extra]")[0]))
        self.assertTrue(lc.enable_repo("my.repo", conf, server="https://x.example/$repo"))
        self.assertIn('[repo."my.repo"]\nserver = "https://x.example/$repo"\n', read(conf))
        self.assertEqual([r.name for r in lc.parse(conf).repos][-2:], ["multilib", "my.repo"])

    def test_enable_repo_conf_d_old_format_stays_old(self):
        conf = self.path("etc/lux/conf.d/x.conf")
        self.write("etc/lux/conf.d/x.conf", "repo a\n    server https://a/\n")
        self.assertTrue(lc.enable_repo("b", conf, server="https://b/"))
        self.assertEqual(read(conf), "repo a\n    server https://a/\n\nrepo b\n    server  https://b/\n")

    def test_toml_set(self):
        text = read(os.path.join(PKG, "lux.conf"))
        t = lc.toml_set(text, "packages", "aur", False)
        self.assertEqual(t, text.replace("aur = true", "aur = false"))
        t = lc.toml_set(text, "packages", "hold", ["linux", "nano"])
        self.assertIn('cache_keep = 2\nhold = ["linux", "nano"]\n\n# ── LuxOS', t)
        t = lc.toml_set(t, "packages", "hold", ["vim"])
        self.assertIn('hold = ["vim"]\n', t)
        t = lc.toml_set(text, "paths", "log", "/var/log/x.log")
        self.assertIn('cache_keep = 2\n\n[paths]\nlog = "/var/log/x.log"\n\n# ── LuxOS', t)
        t = lc.toml_set('[downloads]\nparallel = 3  # pomala linka\n', "downloads", "parallel", 1)
        self.assertEqual(t, "[downloads]\nparallel = 1  # pomala linka\n")
        t = lc.toml_set('[packages]\nhold = [\n  "a",  # x\n  "b",\n]\nflatpak = true\n', "packages", "hold", ["c"])
        self.assertEqual(t, '[packages]\nhold = ["c"]\nflatpak = true\n')
        self.assertEqual(lc.toml_set("", "general", "color", False), "[general]\ncolor = false\n")
        for t in (lc.toml_set(text, "packages", "hold", ["x"]), lc.toml_set(text, "paths", "log", "/x")):
            tomllib.loads(t)

    def test_moved_servers_toml(self):
        pkg = read(os.path.join(PKG, "lux.conf"))
        conf = self.path("etc/lux/lux.conf")
        with open(conf, "w") as f:
            f.write(pkg.replace("https://luxos.lux-ai.cz/repo/", "https://lsl.lux-ai.cz/luxos/"))
        with open(conf + ".luxnew", "w") as f:
            f.write(pkg)
        self.assertTrue(lc.update_moved_servers(conf))
        self.assertEqual(read(conf), pkg)
        self.assertFalse(os.path.exists(conf + ".luxnew"))


class Migrate(Base):
    """Stary format LuxOS 0.9 -> TOML: stejne hodnoty, komentare, puvodni soubor *.old-format."""

    def setUp(self):
        super().setUp()
        self.write("usr/share/lux/lux.conf.default", read(os.path.join(PKG, "lux.conf")))
        self.conf = "/etc/lux/lux.conf"
        self.tmpl = "/usr/share/lux/lux.conf.default"

    def migrate(self, text, **kw):
        self.write("etc/lux/lux.conf", text)
        return lc.migrate_file(self.conf, self.root, template=self.tmpl, **kw)

    def assert_same(self, old_text):
        old = lc.parse(self.conf, root=self.root, text=old_text)
        new = lc.parse(self.conf, root=self.root)
        self.assertEqual(lc.comparable(old), lc.comparable(new))
        # konfigurace jadra: stejne az na spojeni opakovanych radku (IgnorePkg = a b / IgnorePkg = c)
        norm = lambda c: sorted(" ".join(sorted(ln.split())) for ln in lc.semantic(c).splitlines())  # noqa: E731
        self.assertEqual(norm(old)[:0], norm(new)[:0])
        opts_old, repos_old = lc.engine_options(old)
        opts_new, repos_new = lc.engine_options(new)
        self.assertEqual(repos_old, repos_new)
        words = lambda opts: sorted((d, w) for d, v in opts for w in (v or "").split())  # noqa: E731
        self.assertEqual(words(opts_old), words(opts_new))
        self.assertEqual(new.formats[self.conf], "toml")

    def test_old_default_becomes_exact_package_default(self):
        """Nezmenena konfigurace -> presne soubor baliku (pristi aktualizace bez .luxnew)."""
        for old in (read(OLD_DEFAULT), read(OLD_DEFAULT).replace("    ", "\t"),
                    lc.without_drivers_repo(read(OLD_DEFAULT)) + "\nrepo luxos-drivers\n"
                    "    server  https://luxos.lux-ai.cz/repo/$repo/$arch\n"):
            state, warns = self.migrate(old)
            self.assertEqual((state, warns), ("migrated", []))
            self.assertEqual(read(self.path("etc/lux/lux.conf")), read(os.path.join(PKG, "lux.conf")))
            self.assertEqual(read(self.path("etc/lux/lux.conf.old-format")), old)
            os.unlink(self.path("etc/lux/lux.conf.old-format"))

    def test_round_trip_custom(self):
        old = read(OLD_DEFAULT).replace("protect             lux-engine glibc\n", textwrap.dedent("""\
            protect             lux-engine glibc
            # jadro drzet ── kvuli ovladaci
            hold  linux linux-headers   # LTS
            hold  firefox
            ignore-group  kde
            no-upgrade  etc/ssh/sshd_config
            no-extract  usr/share/doc/*
            cache  /srv/pkg
            cache  /var/cache/lux/pkg
            syslog on
            download-timeout off
            """)).replace("aur                 on ", "aur                 off").replace(
            "clean-keep          2", "clean-keep          5").replace(
            "include  /etc/lux/conf.d/*.conf", textwrap.dedent("""\
            # muj repozitar
            repo my.repo   # moje baliky
                server  https://a.example/$repo/$arch   # hlavni
                server  https://b.example/$repo/$arch
                signatures  optional
                usage  sync search

            repo local-files
                server file:///srv/repo
                signatures never

            include  /etc/lux/conf.d/*.conf
            # konec souboru"""))
        state, warns = self.migrate(old)
        self.assertEqual((state, warns), ("migrated", []))
        new = read(self.path("etc/lux/lux.conf"))
        self.assert_same(old)
        for want in ('hold = [\n    # jadro drzet ── kvuli ovladaci\n    "linux", "linux-headers",  # LTS\n'
                     '    "firefox",\n]\n', "aur = false\n", "cache_keep = 5\n", 'ignore_group = ["kde"]\n',
                     '[paths]\ncache = ["/srv/pkg", "/var/cache/lux/pkg"]\n', "syslog = true\n", "timeout = false\n",
                     '# muj repozitar\n[repo."my.repo"]  # moje baliky\nserver = [\n'
                     '    "https://a.example/$repo/$arch",  # hlavni\n    "https://b.example/$repo/$arch",\n]\n'
                     'signatures = "optional"\nusage = ["sync", "search"]\n',
                     '[repo.local-files]\nserver = "file:///srv/repo"\nsignatures = "never"\n',
                     '# ── Other repositories ─', '[include]\nfiles = ["/etc/lux/conf.d/*.conf"]\n\n# konec souboru\n'):
            self.assertIn(want, new)
        for gone in ("# lux itself", "Format: one", "# LuxOS repositories (packages"):
            self.assertNotIn(gone, new)
        # podruhe nic
        self.assertEqual(lc.migrate_file(self.conf, self.root, template=self.tmpl), ("already", []))

    def test_legacy_shell_lines_and_yes_no(self):
        old = "AUR=0\nFLATPAK=1\nCLEAN_KEEP=4\ncolor no\ncandy yes\nrepo core\n  mirrors /etc/lux/mirrorlist\n"
        self.migrate(old)
        self.assert_same(old)
        d = lc.load(self.conf, root=self.root)
        self.assertEqual((d["packages"]["aur"], d["packages"]["cache_keep"], d["general"]["color"]), (False, 4, False))

    def test_own_header_kept(self):
        old = "# Spravce: Jana\n# telefon 123\n\n# hlavni volba\nparallel-downloads 3\n" \
              "repo core\n  mirrors /etc/lux/mirrorlist\n"
        self.migrate(old)
        new = read(self.path("etc/lux/lux.conf"))
        self.assertTrue(new.startswith("# Spravce: Jana\n# telefon 123\n\n[general]\n"), new)
        self.assertIn("# hlavni volba\nparallel = 3\n", new)
        self.assert_same(old)

    def test_conf_d_only_set_keys(self):
        self.write("etc/lux/conf.d/50-x.conf", "# pridano balikem x\nrepo x\n    server https://x.example/$arch\n"
                                               "hold vim\n")
        self.write("etc/lux/lux.conf", read(OLD_DEFAULT))
        before = lc.comparable(lc.parse(self.conf, root=self.root))
        res = lc.migrate_all(self.conf, root=self.root, template=self.tmpl)
        self.assertEqual([(f, s) for f, s, _w in res], [("/etc/lux/lux.conf", "migrated"),
                                                        ("/etc/lux/conf.d/50-x.conf", "migrated")])
        self.assertEqual(read(self.path("etc/lux/conf.d/50-x.conf")),
                         '# pridano balikem x\n\n[packages]\nhold = ["vim"]\n\n[repo.x]\nserver = "https://x.example/$arch"\n')
        self.assertTrue(os.path.exists(self.path("etc/lux/conf.d/50-x.conf.old-format")))
        cfg = lc.parse(self.conf, root=self.root)
        self.assertEqual(lc.comparable(cfg), before)
        self.assertEqual(set(cfg.formats.values()), {"toml"})
        # *.old-format se do conf.d/*.conf nepocita
        self.assertEqual(cfg.includes, ["/etc/lux/conf.d/50-x.conf"])

    def test_dry_run_and_refusal(self):
        state, info = self.migrate(read(OLD_DEFAULT), dry_run=True)
        self.assertEqual(state, "dry-run")
        self.assertEqual(info[-1], read(os.path.join(PKG, "lux.conf")))
        self.assertEqual(read(self.path("etc/lux/lux.conf")), read(OLD_DEFAULT))
        with self.assertRaises(lc.ConfigError):
            self.migrate("bogus-key 1\n")          # rozbita stara konfigurace: beze zmeny
        self.assertEqual(read(self.path("etc/lux/lux.conf")), "bogus-key 1\n")
        self.assertFalse(os.path.exists(self.path("etc/lux/lux.conf.old-format")))

    def test_migrate_cli(self):
        conf = self.path("etc/lux/lux.conf")
        self.write("etc/lux/lux.conf", read(OLD_DEFAULT).replace("/etc/lux/", self.path("etc/lux/")))
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "migrate", conf],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("converted to the new format (original: %s.old-format)" % conf, r.stdout)
        self.assertEqual(lc.detect_format(read(conf)), "toml")
        self.assertTrue(read(conf).startswith("# LuxOS Package Manager\n"))      # hlavni soubor: cely
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "migrate", conf],
                           capture_output=True, text=True)
        self.assertIn("already in the new format", r.stdout)
        # ~/.config/lux/lux.conf: jen nastavene klice (vychozi by prepsaly systemove nastaveni)
        user = self.path("home/.config/lux/lux.conf")
        self.write("home/.config/lux/lux.conf", "flatpak off\n")
        r = subprocess.run([sys.executable, os.path.join(PKG, "lux_config.py"), "migrate", user],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(user), "[packages]\nflatpak = false\n")

    def test_order_warning(self):
        self.write("etc/lux/conf.d/a.conf", "repo a\n  server https://a/\n")
        old = "include /etc/lux/conf.d/*.conf\nrepo core\n  mirrors /etc/lux/mirrorlist\n"
        state, warns = self.migrate(old)
        self.assertEqual(state, "migrated")
        self.assertEqual(warns, ["repository order changed (included files are read after the repositories of "
                                 "this file): a core -> core a"])
        # stejna hodnota v conf.d pod/nad include: zmena vysledku = odmitnuti
        self.write("etc/lux/conf.d/a.conf", "repo a\n  server https://a/\ncolor off\n")
        with self.assertRaises(lc.ConfigError) as cm:
            self.migrate("include /etc/lux/conf.d/*.conf\ncolor on\n")
        self.assertIn("would change the configuration", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
