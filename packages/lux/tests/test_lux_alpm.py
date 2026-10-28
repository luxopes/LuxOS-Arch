"""Testy backendu lux (lux_alpm.py) nad napodobeninou pyalpm (tests/fake_pyalpm.py).

    python3 -m unittest discover -s packages/lux/tests -v

Overuje formatovani vystupu, prikazovou radku, cteni konfigurace, prubeh transakci, strojovy
rezim a srozumitelne chyby. Skutecne libalpm (podpisy, hooky, konflikty) se tu neoveruje.
"""
import importlib.util
import io
import os
import shutil
import tempfile
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_pyalpm as fake  # noqa: E402
# lux_config z repozitare (ne /usr/lib/lux nainstalovaneho systemu)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "lux-engine")))

spec = importlib.util.spec_from_file_location("lux_alpm", os.path.join(HERE, "..", "lux_alpm.py"))
lux_alpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lux_alpm)

os.environ["LUX_ALLOW_NONROOT"] = "1"
os.environ["LUX_RETRY_DELAY"] = "0"
os.environ["LANG"] = "C"
os.environ.pop("LC_ALL", None)
os.environ.pop("NO_COLOR", None)

CONF = """[options]
RootDir = /
DBPath = /var/lib/lux/
CacheDir = /var/cache/lux/pkg/
HookDir = /etc/lux/hooks/
GPGDir = /etc/lux/keyring/
LogFile = /var/log/lux.log
HoldPkg = lux-engine glibc
Architecture = x86_64
CheckSpace
ParallelDownloads = 10
DownloadUser = alpm
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional

[luxos]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[luxos-apps]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[core]
Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch

[extra]
Usage = Sync Search Install Upgrade
Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch
"""


class TTY(io.StringIO):
    def isatty(self):
        return True


def world(h):
    """Repozitare a nainstalovane balicky jednoho testovaciho systemu."""
    by = {db.name: db for db in h.sync}
    by["core"].add(fake.Package("glibc", "2.40-1", "GNU C Library", isize=40_000_000, size=10_000_000))
    by["core"].add(fake.Package("pacman", "7.0.0-1", "package manager"))
    by["core"].add(fake.Package("archlinux-keyring", "20261001-1", "keys"))
    by["extra"].add(fake.Package("firefox", "131.0-1", "Fast, Private & Safe Web Browser",
                                 depends=["nss", "libvpx>=1.0"], isize=250_000_000, size=70_000_000))
    by["extra"].add(fake.Package("nss", "3.104-1", "Network Security Services", isize=5_000_000, size=2_000_000))
    by["extra"].add(fake.Package("libvpx", "1.14-1", "VP8 and VP9 codec", isize=4_000_000, size=1_000_000))
    by["extra"].add(fake.Package("vlc", "3.0.21-1", "Multi-platform MPEG, VCD/DVD, and DivX player",
                                 groups=["multimedia"], provides=["video-player"]))
    by["extra"].add(fake.Package("htop", "3.3.0-2", "Interactive process viewer"))
    by["luxos-apps"].add(fake.Package("lsl", "1.2-1", "Lux Simple Lang"))
    loc = h.local
    loc.add(fake.Package("glibc", "2.40-1", isize=40_000_000, reason=1, files=["usr/lib/libc.so.6", "usr/lib/"]))
    loc.add(fake.Package("pacman", "7.0.0-1", depends=["glibc"], files=["usr/bin/pacman"]))
    loc.add(fake.Package("archlinux-keyring", "20260901-1", reason=1))
    loc.add(fake.Package("htop", "3.3.0-1", isize=500_000, files=["usr/bin/htop"]))
    loc.add(fake.Package("orphan-lib", "1.0-1", reason=1, isize=2_000_000))
    loc.add(fake.Package("aur-tool", "0.1-1", files=["usr/bin/aur-tool"]))
    loc.pkgcache[-3].files = [("usr/bin/htop", 0, 0)]
    # archlinux-keyring nikdo nevyzaduje, ale neni sirotek: vyzaduje ho pacman (tady zjednoduseno)
    loc.get_pkg("pacman").depends.append("archlinux-keyring")


def make_api():
    api = types.ModuleType("pyalpm")
    api.__dict__.update({k: v for k, v in fake.__dict__.items() if not k.startswith("__")})

    class H(fake.Handle):
        last = None

        def __init__(self, root, dbpath):
            super().__init__(root, dbpath)
            H.last = self

    api.Handle = H
    orig = api.Handle.register_syncdb

    def register(self, name, sig):
        db = orig(self, name, sig)
        if name == "extra":
            world(self)
        return db
    api.Handle.register_syncdb = register
    return api


def run(argv, tty=False, answer="", api=None, prepare=None, conf=CONF):
    """-> (rc, vystup, handle)"""
    api = api or make_api()
    out = TTY() if tty else io.StringIO()
    inp = TTY(answer) if tty else io.StringIO(answer)
    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        if prepare:
            orig_init = api.Handle.__init__

            def init(self, root, dbpath):
                orig_init(self, root, dbpath)
                prepare(self)
            api.Handle.__init__ = init
        rc = lux_alpm.main(argv, api=api, conf=lux_alpm.EngineConf(conf), out=out, inp=inp)
    finally:
        sys.stderr = old
    return rc, out.getvalue() + err.getvalue(), api.Handle.last


def strip(s):
    return lux_alpm.ANSI.sub("", s).replace("\r\x1b[2K", "\n")


# ---- formatovani ------------------------------------------------------------------------------
class Format(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(lux_alpm.fmt_size(12_400_000), "12.4 MB")
        self.assertEqual(lux_alpm.fmt_size(48_000_000), "48 MB")
        self.assertEqual(lux_alpm.fmt_size(950), "950 B")
        self.assertEqual(lux_alpm.fmt_size(1_500), "1.5 kB")
        self.assertEqual(lux_alpm.fmt_size(250_000_000), "250 MB")
        self.assertEqual(lux_alpm.fmt_size(3_100_000_000), "3.1 GB")
        self.assertEqual(lux_alpm.fmt_delta(48_000_000), "+48 MB")
        self.assertEqual(lux_alpm.fmt_delta(-3_100_000), "-3.1 MB")
        self.assertEqual(lux_alpm.fmt_delta(0), "+0 B")

    def test_duration(self):
        self.assertEqual(lux_alpm.fmt_duration(8.2), "8.2 s")
        self.assertEqual(lux_alpm.fmt_duration(72), "1 min 12 s")

    def test_question_exact(self):
        self.assertEqual(lux_alpm.plan_question("install", 3, 12_400_000, 48_000_000),
                         "Install 3 packages (12.4 MB download, +48 MB disk)?")
        self.assertEqual(lux_alpm.plan_question("install", 1, 0, 1_000_000), "Install 1 package (+1 MB disk)?")
        self.assertEqual(lux_alpm.plan_question("remove", 2, 0, -5_000_000), "Remove 2 packages (-5 MB disk)?")

    def test_summary_exact(self):
        self.assertEqual(lux_alpm.summary_line("install", [("firefox", "131.0-1")], 2, 8.2),
                         "Installed firefox 131.0-1 (+2 deps) in 8.2 s")
        self.assertEqual(lux_alpm.summary_line("upgrade", [], 57, 41), "Upgraded 57 packages in 41.0 s")
        self.assertEqual(lux_alpm.summary_line("remove", [("vlc", "3.0-1")], 0, 1.25), "Removed vlc 3.0-1 in 1.2 s")
        many = [(f"p{i}", "1-1") for i in range(5)]
        self.assertEqual(lux_alpm.summary_line("install", many, 1, 2), "Installed 5 packages (+1 deps) in 2.0 s")

    def test_plural_few_key(self):
        old = os.environ.get("LANG")
        os.environ["LANG"] = "cs_CZ.UTF-8"
        saved = lux_alpm._TR
        lux_alpm._TR = {"%d packages": "%d balíků", "%d packages|few": "%d balíky", "1 package": "1 balík"}.get
        try:
            tr = lux_alpm._TR
            lux_alpm._TR = lambda s: tr(s) or s
            self.assertEqual(lux_alpm.n_packages(1), "1 balík")
            self.assertEqual(lux_alpm.n_packages(3), "3 balíky")
            self.assertEqual(lux_alpm.n_packages(5), "5 balíků")
            self.assertEqual(lux_alpm.n_packages(22), "22 balíků")      # cestina: jen 2-4
            os.environ["LANG"] = "pl_PL.UTF-8"
            self.assertEqual(lux_alpm.n_packages(22), "22 balíky")      # polstina: 22-24 jako 2-4
            self.assertEqual(lux_alpm.n_packages(12), "12 balíků")
        finally:
            lux_alpm._TR = saved
            os.environ["LANG"] = old

    def test_classify(self):
        c = lux_alpm.classify
        self.assertEqual(c("failed to init transaction (unable to lock database)"), "locked")
        self.assertEqual(c("failed retrieving file 'core.db' from x : timeout"), "network")
        self.assertEqual(c("invalid or corrupted package (PGP signature)"), "keyring")
        self.assertEqual(c("a: /usr/bin/x exists in filesystem"), "conflict")
        self.assertEqual(c("Partition / too full: not enough free disk space"), "disk")
        self.assertEqual(c("could not satisfy dependencies"), "deps")
        self.assertEqual(c("invalid or corrupted package (checksum)"), "corrupt")
        self.assertEqual(c("something odd"), "unknown")

    def test_describe_conflicts_like_pacman(self):
        lines = lux_alpm.describe_data([("linux", 1, "/usr/lib/modules/6.11.1-arch1-1/vmlinuz", None)])
        self.assertEqual(lines, ["linux: /usr/lib/modules/6.11.1-arch1-1/vmlinuz exists in filesystem"])
        self.assertEqual(lux_alpm.describe_data(["a", "b"]), ["a", "b"])
        self.assertEqual(lux_alpm.describe_data(None), [])


# ---- konfigurace -----------------------------------------------------------------------------
class NativeConfig(unittest.TestCase):
    """LuxOS 1.0: lux nastavi libalpm primo z /etc/lux/lux.conf (EngineConf.from_lux) - stejne jako
    lux-engine-conf (parser jadra v C) nad vygenerovanou /run/lux/engine.conf."""
    TOOL = "/usr/lib/lux/alpm/libexec/lux-engine-conf"

    def setUp(self):
        self.lc = lux_alpm.lux_config
        self.assertIsNotNone(self.lc)
        self.dir = tempfile.mkdtemp(prefix="lux-native-")
        pkg = os.path.join(HERE, "..", "..", "lux-engine")
        shutil.copy(os.path.join(pkg, "mirrorlist"), os.path.join(self.dir, "mirrorlist"))
        with open(os.path.join(pkg, "lux.conf")) as f:
            self.default = f.read().replace("/etc/lux/mirrorlist", os.path.join(self.dir, "mirrorlist"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def snapshot(conf):
        api = make_api()
        h, extra = lux_alpm.build_handle(api, conf)
        state = {k: v for k, v in vars(h).items() if k not in ("local", "sync", "transactions") and not k.endswith("cb")}
        state["dbs"] = [(d.name, d.servers, d.siglevel) for d in h.get_syncdbs()]
        state["usage"] = [(r["name"], sorted(r["_usage"])) for r in conf.repos]
        state["held"] = sorted(conf.list("HoldPkg"))
        return state, extra

    def configs(self):
        custom = self.lc.toml_set(self.default, "packages", "hold", ["linux", "linux-headers"])
        custom = self.lc.toml_set(custom, "downloads", "parallel", 3)
        custom = self.lc.toml_set(custom, "security", "local_signatures", "required")
        custom = self.lc.toml_set(custom, "paths", "cache", ["/srv/pkg", "/var/cache/lux/pkg/"])
        custom = self.lc.toml_set(custom, "general", "architecture", ["x86_64", "x86_64_v3"])
        custom = self.lc.toml_insert_repo(custom, "mine", [("server", "file:///srv/mine/$arch"),
                                                           ("signatures", "never"), ("usage", ["sync", "search"])])
        custom = self.lc.toml_insert_repo(custom, "opt", [("server", "https://o.example/$repo"),
                                                          ("signatures", "optional")])
        return [self.default, custom]

    def test_from_lux_defaults(self):
        path = os.path.join(self.dir, "lux.conf")
        with open(path, "w") as f:
            f.write(self.default)
        c = lux_alpm.EngineConf.from_lux(self.lc.parse(path))
        for k, v in (("RootDir", "/"), ("DBPath", "/var/lib/lux/"), ("CacheDir", "/var/cache/lux/pkg/"),
                     ("GPGDir", "/etc/lux/keyring/"), ("LogFile", "/var/log/lux.log"), ("ParallelDownloads", "10")):
            self.assertEqual(c.get(k), v)
        self.assertEqual(c.list("HoldPkg"), ["lux-engine", "glibc"])
        self.assertTrue(c.has("Color") and c.has("CheckSpace"))
        self.assertEqual([r["name"] for r in c.repos], ["luxos", "luxos-apps", "luxos-drivers", "core", "extra"])

    def test_same_handle_as_engine_conf_tool(self):
        if not os.access(self.TOOL, os.X_OK):
            self.skipTest("lux-engine-conf of lux-engine is not installed")
        import subprocess
        for i, text in enumerate(self.configs()):
            with self.subTest(config=i):
                path = os.path.join(self.dir, f"lux{i}.conf")
                with open(path, "w") as f:
                    f.write(text)
                cfg = self.lc.parse(path)
                eng = os.path.join(self.dir, f"engine{i}.conf")
                with open(eng, "w") as f:
                    f.write(self.lc.render_engine(cfg, path))
                r = subprocess.run([self.TOOL, "--config", eng], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                native, via_tool = self.snapshot(lux_alpm.EngineConf.from_lux(cfg)), \
                    self.snapshot(lux_alpm.EngineConf(r.stdout))
                self.assertEqual(native, via_tool)

    def test_broken_config_is_an_error(self):
        path = os.path.join(self.dir, "lux.conf")
        with open(path, "w") as f:
            f.write(self.default.replace("parallel = 10", "parallel = 0"))
        saved = self.lc.LUX_CONF
        env = os.environ.pop("LUX_ENGINE_CONF", None)
        self.lc.LUX_CONF = path
        try:
            with self.assertRaises(lux_alpm.LuxError) as cm:
                lux_alpm.load_engine_conf()
            self.assertIn("lux.conf:13: 'parallel' in [downloads] must be a whole number", cm.exception.message)
            with open(path, "w") as f:
                f.write(self.default)
            self.assertEqual(lux_alpm.load_engine_conf().get("ParallelDownloads"), "10")
        finally:
            self.lc.LUX_CONF = saved
            if env is not None:
                os.environ["LUX_ENGINE_CONF"] = env


class Config(unittest.TestCase):
    def test_parse(self):
        c = lux_alpm.EngineConf(CONF)
        self.assertEqual(c.list("HoldPkg"), ["lux-engine", "glibc"])
        self.assertTrue(c.has("CheckSpace"))
        self.assertFalse(c.has("Color"))
        self.assertEqual([r["name"] for r in c.repos], ["luxos", "luxos-apps", "core", "extra"])
        self.assertEqual(c.repos[0]["Server"], ["https://lsl.lux-ai.cz/luxos/$repo/$arch"])

    def test_siglevel(self):
        b = lux_alpm.sig_bits()
        g = lux_alpm.parse_siglevel(["Required DatabaseOptional"])
        self.assertEqual(g, b["P"] | b["D"] | b["DO"])
        self.assertEqual(lux_alpm.parse_siglevel(["Optional"], g), b["P"] | b["PO"] | b["D"] | b["DO"])
        # Never vypne kontrolu; priznak Optional zustane jako u pacmanu (bez zakladniho bitu nema vliv)
        self.assertEqual(lux_alpm.parse_siglevel(["Never"], g) & (b["P"] | b["D"]), 0)
        self.assertEqual(lux_alpm.parse_siglevel(["PackageRequired", "PackageTrustAll"], 0), b["P"] | b["PM"] | b["PU"])
        self.assertEqual(lux_alpm.parse_siglevel([], g), g)            # repozitar bez SigLevel = globalni
        # vystup pacman-conf (plne rozepsane hodnoty) dava stejny vysledek
        self.assertEqual(lux_alpm.parse_siglevel(
            ["PackageRequired PackageTrustedOnly DatabaseOptional DatabaseTrustedOnly"], 0), g)
        with self.assertRaises(lux_alpm.LuxError):
            lux_alpm.parse_siglevel(["Sometimes"])

    def test_handle_like_engine(self):
        api = make_api()
        h, extra = lux_alpm.build_handle(api, lux_alpm.EngineConf(CONF))
        self.assertEqual(h.gpgdir, "/etc/lux/keyring/")
        self.assertEqual(h.logfile, "/var/log/lux.log")
        self.assertEqual(h.cachedirs, ["/var/cache/lux/pkg/"])
        self.assertIn("/etc/lux/hooks/", h.hookdirs)
        self.assertIn("/usr/share/libalpm/hooks/", h.hookdirs)
        self.assertEqual(h.parallel_downloads, 10)
        self.assertEqual([d.name for d in h.get_syncdbs()], ["luxos", "luxos-apps", "core", "extra"])
        self.assertEqual(h.sync[0].servers, ["https://lsl.lux-ai.cz/luxos/luxos/x86_64"])
        b = lux_alpm.sig_bits()
        self.assertEqual(h.sync[0].siglevel, b["P"] | b["D"] | b["DO"])
        self.assertEqual(extra["local_siglevel"], b["P"] | b["PO"] | b["D"] | b["DO"])

    def test_unsupported_config_falls_back(self):
        api = make_api()
        with self.assertRaises(lux_alpm.LuxError) as cm:
            lux_alpm.build_handle(api, lux_alpm.EngineConf(CONF.replace("CheckSpace", "XferCommand = /usr/bin/wget %u")))
        self.assertEqual(cm.exception.rc, lux_alpm.EXIT_UNAVAILABLE)

        class Strict:
            """pyalpm bez nastaveni gpgdir -> nepouzitelne (rc 3), lux pak vola pacman."""
            __slots__ = ("cachedirs", "hookdirs", "logfile", "arch", "sync")

            def __init__(self, root, dbpath):
                self.sync = []

            def register_syncdb(self, name, sig):
                return fake.DB(name, siglevel=sig)
        api.Handle = Strict
        with self.assertRaises(lux_alpm.LuxError) as cm:
            lux_alpm.build_handle(api, lux_alpm.EngineConf(CONF))
        self.assertEqual(cm.exception.rc, 3)
        self.assertIn("GPGDir", cm.exception.message)

    def test_hookdir_only_needed_for_transactions(self):
        """Sdileny ESP: hook v /etc/lux/hooks a pyalpm bez hookdirs -> kontrola aktualizaci (Obchod)
        funguje, instalace radeji pres lux-engine (rc 3)."""
        api = make_api()
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "etc/lux/hooks"))
        with open(os.path.join(root, "etc/lux/hooks/99-luxos-esp-sync.hook"), "w") as f:
            f.write("[Trigger]\n")

        class NoHooks(api.Handle):
            def __init__(self, *a):
                super().__init__(*a)
                self._ready = True

            def __setattr__(self, name, value):
                if name == "hookdirs" and getattr(self, "_ready", False):
                    raise AttributeError(name)      # starsi pyalpm: hookdirs jen pro cteni
                object.__setattr__(self, name, value)
        api.Handle = NoHooks
        conf = lux_alpm.EngineConf(CONF.replace("RootDir = /", "RootDir = " + root))
        saved = lux_alpm.TRANSACTION
        try:
            lux_alpm.TRANSACTION = False
            lux_alpm.build_handle(api, conf)          # bez vyjimky
            lux_alpm.TRANSACTION = True
            with self.assertRaises(lux_alpm.LuxError) as cm:
                lux_alpm.build_handle(api, conf)
            self.assertIn("HookDir", cm.exception.message)
        finally:
            lux_alpm.TRANSACTION = saved
            shutil.rmtree(root, ignore_errors=True)

    def test_available_without_pyalpm(self):
        saved = sys.modules.get("pyalpm")
        sys.modules["pyalpm"] = None          # import selze
        try:
            rc = lux_alpm.main(["available"], conf=lux_alpm.EngineConf(CONF), out=io.StringIO())
        finally:
            if saved is not None:
                sys.modules["pyalpm"] = saved
            else:
                sys.modules.pop("pyalpm", None)
        self.assertEqual(rc, 3)

    def test_available_requires_question_callback(self):
        api = make_api()
        rc, out, _h = run(["available"], api=api)
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

        class NoQ(api.Handle):
            __slots__ = ()

            def __getattribute__(self, name):
                if name == "questioncb":
                    raise AttributeError(name)
                return object.__getattribute__(self, name)
        api.Handle = NoQ
        rc, out, _h = run(["available"], api=api)
        self.assertEqual(rc, 3)


# ---- prikazova radka ---------------------------------------------------------------------------
class Parsing(unittest.TestCase):
    def p(self, *a):
        return lux_alpm.build_parser().parse_args(list(a))

    def test_commands(self):
        a = self.p("-y", "--machine", "install", "--needed", "--", "firefox", "vlc")
        self.assertTrue(a.yes and a.machine and a.needed)
        self.assertEqual(a.targets, ["firefox", "vlc"])
        u = self.p("update")
        self.assertTrue(u.refresh and u.keyring_first)
        u = self.p("upgrade")
        self.assertFalse(u.refresh or u.keyring_first or u.download_only)
        u = self.p("upgrade", "--refresh", "--download-only")
        self.assertTrue(u.refresh and u.download_only)
        self.assertEqual(self.p("list").mode, "installed")
        self.assertEqual(self.p("list", "--upgradable").mode, "upgradable")
        self.assertEqual(self.p("list", "--installed", "--", "fire").pattern, "fire")
        self.assertEqual(self.p("--color=never", "owns", "/usr/bin/x").paths, ["/usr/bin/x"])

    def test_bad_usage(self):
        self.assertEqual(lux_alpm.main(["frobnicate"], out=io.StringIO()), 2)
        self.assertEqual(lux_alpm.main(["install"], out=io.StringIO()), 2)


# ---- transakce nad napodobeninou libalpm -------------------------------------------------------
class Transactions(unittest.TestCase):
    def test_install_plain_output(self):
        rc, out, h = run(["-y", "install", "--needed", "firefox"])
        self.assertEqual(rc, 0, out)
        lines = [x for x in strip(out).splitlines() if x.strip()]
        self.assertTrue(lines[0].startswith("✓ Downloading"), lines)
        self.assertIn("✓ Installed firefox 131.0-1 (+2 deps) in ", out)
        self.assertIsNotNone(h.local.get_pkg("firefox"))
        self.assertEqual(h.local.get_pkg("nss").reason, 1)
        self.assertEqual(h.local.get_pkg("firefox").reason, 0)
        self.assertTrue(h.transactions[-1].released)
        self.assertEqual(h.transactions[-1].flags, {"needed": True})
        self.assertNotIn("\x1b[", out)                                  # ne-tty: bez barev

    def test_install_tty_question_and_bars(self):
        rc, out, h = run(["install", "--needed", "firefox"], tty=True, answer="\n")
        self.assertEqual(rc, 0, out)
        plain = strip(out)
        first = plain.lstrip("\n").splitlines()[0]
        self.assertEqual(first, "Install 3 packages (73 MB download, +259 MB disk)? [Y/n] ")
        self.assertIn("█", out)
        for phase in ("Downloading", "Verifying", "Installing"):
            self.assertIn(phase, plain)
        self.assertIn("\x1b[", out)                                     # tty: barvy

    def test_no_color(self):
        os.environ["NO_COLOR"] = "1"
        try:
            rc, out, _h = run(["install", "--needed", "htop"], tty=True, answer="y\n")
        finally:
            os.environ.pop("NO_COLOR")
        self.assertEqual(rc, 0)
        self.assertNotIn("\x1b[3", out)
        self.assertNotIn("\x1b[1m", out)

    def test_install_declined(self):
        rc, out, h = run(["install", "firefox"], tty=True, answer="n\n")
        self.assertEqual(rc, 1)
        self.assertIsNone(h.local.get_pkg("firefox"))
        self.assertIn("Cancelled", out)
        self.assertTrue(h.transactions[-1].released)

    def test_no_confirmation_without_terminal(self):
        rc, out, h = run(["install", "firefox"])
        self.assertEqual(rc, 1)
        self.assertIn("add -y", out)
        self.assertIsNone(h.local.get_pkg("firefox"))

    def test_needed_skips_installed(self):
        rc, out, h = run(["-y", "install", "--needed", "glibc"])
        self.assertEqual(rc, 0)
        self.assertIn("Already installed: glibc", out)
        self.assertEqual(h.transactions, [])

    def test_resolve_group_provides_repo(self):
        rc, out, _h = run(["resolve", "multimedia", "video-player", "extra/vlc", "luxos-apps/lsl", "nope", "core/vlc"])
        self.assertEqual(out.splitlines(), ["repo\tmultimedia", "repo\tvideo-player", "repo\textra/vlc",
                                            "repo\tluxos-apps/lsl", "none\tnope", "none\tcore/vlc"])

    def test_not_found(self):
        rc, out, h = run(["-y", "install", "nope"])
        self.assertEqual(rc, 1)
        self.assertIn("Package 'nope' not found. Try: lux search nope", out)

    def test_machine_output(self):
        rc, out, h = run(["--machine", "-y", "install", "--needed", "--", "firefox"])
        self.assertEqual(rc, 0, out)
        lines = out.splitlines()
        self.assertIn("@@PLAN install 3 73000000 259000000", lines)
        self.assertTrue(any(x.startswith("Packages (3) firefox-131.0-1") for x in lines))
        self.assertIn("@@PHASE download", lines)
        self.assertIn("@@PHASE verify", lines)
        self.assertIn("@@PHASE install", lines)
        self.assertIn("installing firefox...", lines)               # pro starsi ctenare (LuxOS Care)
        self.assertIn(":: Running post-transaction hooks...", lines)
        self.assertEqual(lines[-1], "@@DONE 0")
        self.assertTrue(all(x.startswith(("@@", "Packages", "installing", ":: ", "==>")) or x.endswith("downloading...")
                            for x in lines), lines)
        order = [x for x in lines if x.startswith("@@PHASE")]
        self.assertEqual(order, ["@@PHASE download", "@@PHASE verify", "@@PHASE install", "@@PHASE hooks"])

    def test_store_progress_regex_matches(self):
        """Obchod LuxOS (stary parser) i LuxOS Care pocitaji instalace z radku 'installing x...'."""
        import re
        rc, out, _h = run(["--machine", "-y", "update"])
        care_rx = re.compile(r"^(installing|upgrading|reinstalling|downgrading|removing) \S+\.\.\.")
        hits = [x for x in out.splitlines() if care_rx.match(x)]
        self.assertEqual(sorted(hits), ["upgrading archlinux-keyring...", "upgrading htop..."])

    def test_update_keyring_first(self):
        rc, out, h = run(["-y", "update"])
        self.assertEqual(rc, 0, out)
        self.assertGreaterEqual(h.sync[2].updated, 1)               # obnoveny databaze
        first, second = h.transactions[0], h.transactions[1]
        self.assertEqual([p.name for p in first.to_add], ["archlinux-keyring"])
        self.assertEqual([p.name for p in second.to_add], ["htop"])
        self.assertIn("Upgraded 1 package in", out)
        self.assertEqual(h.local.get_pkg("htop").version, "3.3.0-2")

    def test_upgrade_nothing(self):
        def prep(h):
            pass
        rc, out, h = run(["-y", "upgrade"])
        rc, out, h = run(["-y", "upgrade"], prepare=lambda hh: None)
        self.assertEqual(rc, 0)
        api = make_api()
        rc, out, h = run(["-y", "install", "--needed", "htop", "archlinux-keyring"], api=api)
        self.assertEqual(rc, 0)

    def test_download_only(self):
        rc, out, h = run(["--machine", "-y", "upgrade", "--download-only"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(h.transactions[-1].flags, {"downloadonly": True})
        self.assertEqual(h.local.get_pkg("htop").version, "3.3.0-1")
        self.assertIn("@@SUMMARY download", out)

    def test_network_retry_without_second_question(self):
        def prep(h):
            h.commit_errors.append(fake.error("failed to retrieve some files", 54, None))
        rc, out, h = run(["install", "--needed", "htop"], tty=True, answer="y\n", prepare=prep)
        self.assertEqual(rc, 0, out)
        self.assertEqual(strip(out).count("[Y/n]"), 1)
        self.assertIn("trying again (2/3)", out)
        self.assertIn("Server mirror.example is not responding", out)
        self.assertEqual(h.local.get_pkg("htop").version, "3.3.0-2")

    def test_network_gives_up_after_three(self):
        def prep(h):
            h.commit_errors.extend([fake.error("failed to retrieve some files", 54, None)] * 3)
        rc, out, h = run(["--machine", "-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1)
        self.assertIn("@@RETRY 2", out)
        self.assertIn("@@RETRY 3", out)
        self.assertIn("@@ERROR network Some packages could not be downloaded.", out)
        self.assertIn("error: failed to commit transaction (failed to retrieve some files)", out)

    def test_stale_package_list_404(self):
        """404 u baliku: zastaraly seznam baliku, bez zbytecneho opakovani a bez rady o internetu."""
        def prep(h):
            h.commit_log = ("failed retrieving file 'sshfs-3.7.5-1-x86_64.pkg.tar.zst' from mirror.example : "
                            "The requested URL returned error: 404")
            h.commit_errors.append(fake.error("failed to retrieve some files", 54, None))
        rc, out, h = run(["-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1, out)
        self.assertIn("The package lists are out of date", out)
        self.assertIn("lux update", out)
        self.assertIn("returned error: 404", out)
        self.assertNotIn("trying again", out)

    def test_corrupted_cache_file_deleted_and_downloaded_again(self):
        """Poskozeny balik v mezipameti: smaze se bez otazky, stahne znovu a instalace dobehne."""
        import tempfile
        d = tempfile.mkdtemp(prefix="lux-cache-")
        bad = os.path.join(d, "htop-3.3.0-2-x86_64.pkg.tar.zst")
        open(bad, "w").write("poskozeno")

        def prep(h):
            h.commit_questions.append((lux_alpm.Q_CORRUPTED_PKG, bad, "invalid or corrupted package (checksum)"))
            h.commit_errors.append(fake.error("invalid or corrupted package (checksum)", 41, None))
        rc, out, h = run(["install", "htop"], tty=True, answer="y\n", prepare=prep)
        self.assertEqual(rc, 0, out)
        self.assertEqual(strip(out).count("[Y/n]"), 1)          # bez dalsi otazky (ani na smazani)
        self.assertIn("Downloaded package htop was damaged, downloading it again", out)
        self.assertFalse(os.path.exists(bad))
        self.assertEqual(h.local.get_pkg("htop").version, "3.3.0-2")

    def test_corrupted_twice_names_package(self):
        def prep(h):
            for _i in range(2):
                h.commit_questions.append((lux_alpm.Q_CORRUPTED_PKG, "/var/cache/lux/pkg/htop-3.3.0-2-x86_64.pkg.tar.zst",
                                           "invalid or corrupted package (checksum)"))
                h.commit_errors.append(fake.error("invalid or corrupted package (checksum)", 41, None))
        rc, out, h = run(["--machine", "-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1, out)
        self.assertIn("@@RETRY corrupt", out)
        self.assertIn("@@ERROR corrupt The package htop was damaged again after a new download.", out)
        self.assertEqual(lux_alpm.package_from_file("/x/lib32-gcc-libs-15.1.1+r7-1-x86_64.pkg.tar.zst"), "lib32-gcc-libs")

    def test_file_conflict_plain_and_verbose(self):
        def prep(h):
            h.commit_errors.append(fake.error("conflicting files", 31,
                                              [("htop", 1, "/usr/bin/htop", "other")]))
        rc, out, h = run(["-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1)
        self.assertIn("already exist on the system (file conflict)", out)
        # prvni radky skutecne chyby i bez --verbose (bez nich se chyba neda dohledat)
        self.assertIn("htop: /usr/bin/htop exists in filesystem (owned by other)", out)
        rc, out, h = run(["-y", "--verbose", "install", "htop"], prepare=prep)
        self.assertIn("htop: /usr/bin/htop exists in filesystem (owned by other)", out)
        rc, out, h = run(["--machine", "-y", "install", "htop"], prepare=prep)
        self.assertIn("htop: /usr/bin/htop exists in filesystem", out)  # cte LuxOS Care (release_kept)
        self.assertIn("@@ERROR conflict", out)

    def test_locked_database(self):
        def prep(h):
            h.locked = True
        rc, out, h = run(["-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1)
        self.assertIn("lux fix", out)
        rc, out, h = run(["--machine", "-y", "install", "htop"], prepare=prep)
        self.assertIn("error: failed to init transaction (unable to lock database)", out)

    def test_missing_dependency(self):
        def prep(h):
            h.prepare_errors.append(fake.error("could not satisfy dependencies", 30, [("firefox", "libfoo>=2")]))
        rc, out, h = run(["-y", "install", "firefox"], prepare=prep)
        self.assertEqual(rc, 1)
        self.assertIn("Dependencies can not be satisfied: firefox: libfoo>=2", out)

    def test_keyring_error_message(self):
        def prep(h):
            h.commit_errors.append(fake.error("invalid or corrupted package (PGP signature)", 40, ["htop"]))
        rc, out, h = run(["-y", "install", "htop"], prepare=prep)
        self.assertIn("lux fix", out)
        self.assertEqual(rc, 1)

    def test_refresh_retry(self):
        def prep(h):
            pass
        api = make_api()
        orig = api.Handle.register_syncdb

        def reg(self, name, sig):
            db = orig(self, name, sig)
            if name == "core":
                db.update_errors.append(fake.error("failed to retrieve some files", 54, None))
            return db
        api.Handle.register_syncdb = reg
        rc, out, h = run(["--machine", "sync"], api=api)
        self.assertEqual(rc, 0, out)
        self.assertIn("@@RETRY 2", out)

    def test_refresh_signature_mismatch_refetches(self):
        # QA 1.0: databaze z ISO novejsi nez na serveru -> server ji neposle znovu, ale podpis ano;
        # podpis pak nesedi. Jednou se ta databaze stahne nacisto (force), ostatni ne.
        api = make_api()
        orig = api.Handle.register_syncdb
        forces = []

        def reg(self, name, sig):
            db = orig(self, name, sig)
            if name == "core":
                db.update_errors.append(fake.error("invalid or corrupted database (PGP signature)", 17, None))
                real = db.update

                def update(force, real=real):
                    forces.append(force)
                    return real(force)
                db.update = update
            return db
        api.Handle.register_syncdb = reg
        rc, out, h = run(["--machine", "sync"], api=api)
        self.assertEqual(rc, 0, out)
        self.assertEqual(forces, [False, True])

    def test_invalid_syncdb_on_prepare_is_explained(self):
        def prep(h):
            h.prepare_errors.append(fake.error("transaction preparation failed", 16, []))
        rc, out, h = run(["-y", "install", "htop"], prepare=prep)
        self.assertEqual(rc, 1)
        self.assertIn("do not match their signatures", out)
        self.assertIn("lux update", out)

    # ---- zamcena databaze: cekani na jinou aktualizaci, opusteny zamek, presne hlasky ----
    def _locked(self, procs, argv=("--machine", "sync")):
        import tempfile
        d = tempfile.mkdtemp(prefix="lux-lock-")
        open(os.path.join(d, "db.lck"), "w").close()
        old = lux_alpm.running_package_managers
        lux_alpm.running_package_managers = lambda: procs
        try:
            rc, out, h = run(list(argv), prepare=lambda h: setattr(h, "dbpath", d))
        finally:
            lux_alpm.running_package_managers = old
        return rc, out, os.path.exists(os.path.join(d, "db.lck"))

    def test_stale_lock_removed(self):
        rc, out, still = self._locked([])
        self.assertEqual(rc, 0, out)
        self.assertFalse(still)

    def test_running_update_waits_then_explains(self):
        old = lux_alpm.LOCK_WAIT
        lux_alpm.LOCK_WAIT = 0
        try:
            rc, out, still = self._locked(["LuxOS Care"], argv=("sync",))
        finally:
            lux_alpm.LOCK_WAIT = old
        self.assertEqual(rc, 1)
        self.assertTrue(still)                                   # cizi zamek se nemaze
        self.assertIn("Another update is still running (LuxOS Care)", out)
        self.assertNotIn("internet", out)

    def test_unknown_refresh_error_is_not_network(self):
        api = make_api()
        orig = api.Handle.register_syncdb

        def reg(self, name, sig):
            db = orig(self, name, sig)
            db.update_errors.extend(fake.error("unable to update database", 99, None) for _ in range(3))
            return db
        api.Handle.register_syncdb = reg
        rc, out, _h = run(["sync"], api=api)
        self.assertEqual(rc, 1)
        self.assertIn("The package lists could not be refreshed: unable to update database", out)
        self.assertNotIn("internet", out)

    def test_running_package_managers_scan(self):
        import tempfile
        proc = tempfile.mkdtemp(prefix="lux-proc-")

        def add(pid, comm, *argv):
            os.makedirs(os.path.join(proc, str(pid)))
            with open(os.path.join(proc, str(pid), "comm"), "w") as f:
                f.write(comm + "\n")
            with open(os.path.join(proc, str(pid), "cmdline"), "wb") as f:
                f.write(b"\0".join(a.encode() for a in argv) + b"\0")
        add(101, "python3", "/usr/bin/python3", "/usr/lib/luxos/luxos_care.py", "update")
        add(102, "pacman", "pacman", "-Syu")
        add(103, "python3", "python3", "/usr/bin/other.py")
        add(os.getpid(), "python3", "python3", "/usr/lib/lux/lux_alpm.py")   # vlastni proces se nepocita
        self.assertEqual(lux_alpm.running_package_managers(proc), ["LuxOS Care", "pacman"])

    def test_remove_recursive_and_holdpkg(self):
        def prep(h):
            pass
        rc, out, h = run(["-y", "remove", "htop"])
        self.assertEqual(rc, 0, out)
        self.assertIsNone(h.local.get_pkg("htop"))
        # zmenene konfiguracni soubory zustanou jako *.luxsave (bez nosave, jako pacman -Rs)
        self.assertEqual(h.transactions[-1].flags, {"recurse": True})
        self.assertIn("Removed htop 3.3.0-1 in", out)
        rc, out, h = run(["-y", "remove", "--nosave", "--", "htop"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(h.transactions[-1].flags, {"recurse": True, "nosave": True})
        # HoldPkg: s -y se jako u pacmanu --noconfirm neodebere
        rc, out, h = run(["-y", "remove", "glibc"])
        self.assertEqual(rc, 1)
        self.assertIn("essential", out)
        self.assertIsNotNone(h.local.get_pkg("glibc"))
        rc, out, h = run(["remove", "glibc"], tty=True, answer="y\ny\n")
        self.assertEqual(rc, 0, out)

    def test_remove_not_installed(self):
        rc, out, h = run(["-y", "remove", "firefox"])
        self.assertEqual(rc, 1)
        self.assertIn("is not installed", out)

    def test_autoremove(self):
        rc, out, h = run(["-y", "autoremove"])
        self.assertEqual(rc, 0, out)
        self.assertIsNone(h.local.get_pkg("orphan-lib"))
        self.assertIsNotNone(h.local.get_pkg("glibc"))              # vyzaduje ho pacman
        self.assertIsNotNone(h.local.get_pkg("archlinux-keyring"))
        rc, out, h = run(["-y", "autoremove"], prepare=lambda hh: None)

    def test_reinstall(self):
        rc, out, h = run(["-y", "reinstall", "glibc"])
        self.assertEqual(rc, 0, out)
        self.assertIn("Reinstalled glibc 2.40-1", out)
        rc, out, h = run(["-y", "reinstall", "aur-tool"])            # neni v repozitari ani v cache
        self.assertEqual(rc, 1)
        self.assertIn("not in the repositories or the package cache", out)
        rc, out, h = run(["-y", "reinstall", "firefox"])
        self.assertIn("is not installed", out)

    def test_install_local_file(self):
        import tempfile
        d = tempfile.mkdtemp()
        f = os.path.join(d, "hello-1.0-1-x86_64.pkg.tar.zst")
        open(f, "wb").close()
        rc, out, h = run(["-y", "install", f])
        self.assertEqual(rc, 0, out)
        self.assertIsNotNone(h.local.get_pkg("hello"))
        os.unlink(f)
        os.rmdir(d)

    def test_interrupt_in_prompt(self):
        class Boom(TTY):
            def readline(self):
                raise KeyboardInterrupt
        api = make_api()
        out = TTY()
        rc = lux_alpm.main(["install", "htop"], api=api, conf=lux_alpm.EngineConf(CONF), out=out, inp=Boom())
        self.assertEqual(rc, 130)
        self.assertTrue(api.Handle.last.transactions[-1].released)


# ---- prechod luxos-pacman (LuxOS 0.9) -> lux-engine ---------------------------------------
ENGINE_VER = "7.1.0.r9.g54d9411-3.1"


def engine_world(h):
    """Nainstalovany LuxOS 0.9 (luxos-pacman) a repozitar [luxos] s lux-engine (replaces luxos-pacman)."""
    luxos = next(db for db in h.sync if db.name == "luxos")
    luxos.add(fake.Package("lux-engine", ENGINE_VER, "Package engine of lux", depends=["glibc"],
                           provides=["pacman=7.1.0.r9.g54d9411", "libalpm.so", "luxos-pacman=7.1.0.r9.g54d9411"],
                           conflicts=["pacman", "luxos-pacman"], replaces=["pacman", "luxos-pacman"]))
    luxos.add(fake.Package("lux", "0.3.0-9", "LuxOS package manager", depends=["lux-engine", "pyalpm"]))
    loc = h.local
    loc.pkgcache = [p for p in loc.pkgcache if p.name != "pacman"]
    loc.add(fake.Package("luxos-pacman", ENGINE_VER, provides=["pacman=7.1.0.r9.g54d9411", "libalpm.so"],
                         depends=["glibc"], files=["usr/bin/pacman", "usr/lib/lux/alpm/pacman"]))
    loc.add(fake.Package("pyalpm", "0.11-1", depends=["pacman>=6"], reason=1))
    loc.add(fake.Package("lux", "0.3.0-8", depends=["pacman", "pyalpm"]))
    # stejna verze pacmanu je i v [core]: nesmi vratit Arch pacman misto lux-engine
    core = next(db for db in h.sync if db.name == "core")
    core.add(fake.Package("pacman", "7.1.0.r9.g54d9411-3", "package manager", replaces=[]))


def engine_api():
    api = make_api()
    orig = api.Handle.register_syncdb

    def register(self, name, sig):
        db = orig(self, name, sig)
        if name == "extra":           # posledni repozitar: world() uz probehl
            engine_world(self)
        return db
    api.Handle.register_syncdb = register
    return api


class SystemProtection(unittest.TestCase):
    """Ochrana systemu LuxOS (luxos_protect z luxos-care): /usr zapisovatelny jen po dobu commitu."""

    def setUp(self):
        import contextlib
        self.events = []
        self.fail_unlock = False
        mod = types.ModuleType("luxos_protect")
        test = self

        @contextlib.contextmanager
        def writable():
            if test.fail_unlock:
                raise RuntimeError("unlock_failed")
            test.events.append("unlock")
            try:
                yield True
            finally:
                test.events.append("lock")
        mod.writable = writable
        self._old = sys.modules.get("luxos_protect")
        sys.modules["luxos_protect"] = mod

    def tearDown(self):
        if self._old is None:
            sys.modules.pop("luxos_protect", None)
        else:
            sys.modules["luxos_protect"] = self._old

    def test_commit_inside_writable(self):
        def prepare(h):
            orig = h.init_transaction

            def init(**flags):
                t = orig(**flags)
                commit = t.commit

                def wrapped():
                    self.events.append("commit")
                    return commit()
                t.commit = wrapped
                return t
            h.init_transaction = init
        rc, out, h = run(["-y", "install", "htop"], prepare=prepare)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.events, ["unlock", "commit", "lock"])

    def test_download_only_stays_locked(self):
        rc, out, _h = run(["-y", "upgrade", "--download-only"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.events, [])

    def test_unlock_failure_is_clear_error(self):
        self.fail_unlock = True
        rc, out, h = run(["--machine", "-y", "install", "firefox"])
        self.assertEqual(rc, 1)
        self.assertIn("@@ERROR protected", out)
        self.assertIsNone(h.local.get_pkg("firefox"))
        self.assertTrue(h.transactions[-1].released)


class EngineReplacement(unittest.TestCase):
    """Upgrade LuxOS 0.9: sysupgrade nahradi luxos-pacman balikem lux-engine (replaces). Overuje
    obsluhu otazky na nahrazeni v lux; samotne nahrazeni tu simuluje fake_pyalpm podle libalpm."""

    def test_update_replaces_luxos_pacman(self):
        rc, out, h = run(["-y", "update"], api=engine_api())
        self.assertEqual(rc, 0, out)
        t = h.transactions[-1]
        self.assertIn("luxos-pacman", [p.name for p in t.to_remove])
        self.assertIn("lux-engine", [p.name for p in t.to_add])
        self.assertIn("lux", [p.name for p in t.to_add])
        self.assertNotIn("pacman", [p.name for p in t.to_add])
        self.assertIsNone(h.local.get_pkg("luxos-pacman"))
        self.assertEqual(h.local.get_pkg("lux-engine").version, ENGINE_VER)

    def test_update_replaces_arch_pacman(self):
        """System s pacmanem z Archu (bez luxos-pacman): lux-engine nahradi i balik pacman."""
        api = make_api()
        orig = api.Handle.register_syncdb

        def register(self, name, sig):
            db = orig(self, name, sig)
            if name == "extra":
                engine_world(self)
                self.local.pkgcache = [p for p in self.local.pkgcache if p.name != "luxos-pacman"]
                self.local.add(fake.Package("pacman", "7.1.0.r9.g54d9411-3", provides=["libalpm.so"]))
            return db
        api.Handle.register_syncdb = register
        rc, out, h = run(["-y", "update"], api=api)
        self.assertEqual(rc, 0, out)
        self.assertIn("pacman", [p.name for p in h.transactions[-1].to_remove])
        self.assertIsNone(h.local.get_pkg("pacman"))
        self.assertIsNotNone(h.local.get_pkg("lux-engine"))

    def test_machine_mode_replaces_without_question(self):
        rc, out, h = run(["--machine", "-y", "update"], api=engine_api())
        self.assertEqual(rc, 0, out)
        self.assertIsNotNone(h.local.get_pkg("lux-engine"))
        self.assertIsNone(h.local.get_pkg("luxos-pacman"))

    def test_interactive_asks_before_replacing(self):
        rc, out, h = run(["update"], tty=True, answer="y\ny\n", api=engine_api())
        self.assertEqual(rc, 0, out)
        self.assertIn("Replace a package with its successor?", strip(out))
        self.assertIsNotNone(h.local.get_pkg("lux-engine"))

    def test_hooks_get_engine_tools_on_path(self):
        old = os.environ.get("PATH")
        try:
            os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/bin"    # jako po sudo
            rc, out, h = run(["-y", "update"], api=engine_api())
            self.assertEqual(rc, 0, out)
            self.assertEqual(h.transactions[-1].env_path,
                             "/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin")
        finally:
            os.environ["PATH"] = old

    def test_engine_path(self):
        ep = lux_alpm.engine_path
        self.assertEqual(ep("/usr/bin"), "/usr/lib/lux/alpm/bin:/usr/bin")
        self.assertEqual(ep("/usr/lib/lux/alpm/bin:/usr/bin"), "/usr/lib/lux/alpm/bin:/usr/bin")
        self.assertEqual(ep("/usr/bin:/usr/lib/lux/alpm/bin"), "/usr/lib/lux/alpm/bin:/usr/bin")
        self.assertEqual(ep(""), "/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin")
        self.assertEqual(ep(None), "/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin")


class Queries(unittest.TestCase):
    def test_search(self):
        rc, out, _h = run(["search", "vlc"])
        self.assertEqual(rc, 0)
        self.assertIn("extra/vlc 3.0.21-1", out)
        rc, out, _h = run(["search", "htop"])
        self.assertIn("[installed]", out)
        rc, out, _h = run(["--color=always", "search", "lsl"])
        self.assertIn("✦ LuxOS", out)
        rc, out, _h = run(["search", "zzzz"])
        self.assertEqual(rc, 1)

    def test_info(self):
        rc, out, _h = run(["info", "htop"])
        self.assertEqual(rc, 0)
        self.assertIn("3.3.0-1", out)
        self.assertIn("Update", out)
        self.assertIn("3.3.0-2", out)
        rc, out, _h = run(["info", "firefox"])
        self.assertIn("Download size", out)
        rc, out, _h = run(["info", "aur-tool"])
        self.assertIn("not in repositories", out)
        rc, out, _h = run(["info", "nothing"])
        self.assertEqual(rc, 1)

    def test_list(self):
        rc, out, _h = run(["list", "--upgradable"])
        self.assertEqual(out.splitlines(), ["archlinux-keyring 20260901-1 -> 20261001-1", "htop 3.3.0-1 -> 3.3.0-2"])
        rc, out, _h = run(["list", "--foreign"])
        self.assertEqual(out.splitlines(), ["aur-tool 0.1-1", "orphan-lib 1.0-1"])
        rc, out, _h = run(["list", "--orphans"])
        self.assertEqual(out.splitlines(), ["orphan-lib 1.0-1"])
        rc, out, _h = run(["list", "--explicit"])
        self.assertIn("htop 3.3.0-1", out)
        self.assertNotIn("glibc", out)
        rc, out, _h = run(["list", "--", "HT"])
        self.assertEqual(out.splitlines(), ["htop 3.3.0-1"])

    def test_list_sync(self):
        """Seznam balicku repozitaru pro TUI lux a Obchod (drive expac)."""
        rc, out, _h = run(["list", "--sync"])
        self.assertEqual(rc, 0, out)
        rows = [ln.split("\t") for ln in out.splitlines()]
        self.assertTrue(all(len(r) == 5 for r in rows), rows)
        self.assertIn(["extra", "htop", "3.3.0-2"], [r[:3] for r in rows])
        self.assertTrue(all(r[3].isdigit() for r in rows))

    def test_check_updates_uses_temporary_db(self):
        tmp = tempfile.mkdtemp(prefix="lux-cu-test-")
        try:
            db = os.path.join(tmp, "db")
            rc, out, h = run(["check-updates", "--db", db])
            self.assertEqual(rc, 0, out)
            self.assertEqual(out.splitlines(), ["archlinux-keyring 20260901-1 -> 20261001-1", "htop 3.3.0-1 -> 3.3.0-2"])
            self.assertEqual(h.dbpath, db)                        # systemova databaze se nemeni
            self.assertTrue(all(d.updated for d in h.sync))
            self.assertEqual(os.readlink(os.path.join(db, "local")), "/var/lib/lux/local")

        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_check_updates_redownloads_mismatched_copy(self):
        """Kopie databaze ze systemu neprojde (podpis z jine chvile): smazat a stahnout nacisto."""
        tmp = tempfile.mkdtemp(prefix="lux-cu-test-")
        try:
            db = os.path.join(tmp, "db")
            os.makedirs(os.path.join(db, "sync"))
            for f in ("luxos.db", "luxos.db.sig"):
                open(os.path.join(db, "sync", f), "w").close()
            api = make_api()
            orig = api.Handle.register_syncdb

            def reg(self, name, sig):
                d = orig(self, name, sig)
                if name == "luxos":
                    d.update_errors.append(fake.error("unable to update database", 99, None))
                return d
            api.Handle.register_syncdb = reg
            rc, out, h = run(["check-updates", "--db", db], api=api)
            self.assertEqual(rc, 0, out)
            self.assertFalse(os.path.exists(os.path.join(db, "sync", "luxos.db.sig")))
            self.assertTrue(all(d.updated for d in h.sync))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_check_updates_removes_stale_lock_and_waits(self):
        """Zbyly db.lck v docasne slozce (preruseny beh) kontrolu neblokuje; soubezna kontrola pocka."""
        import fcntl
        tmp = tempfile.mkdtemp(prefix="lux-cu-test-")
        try:
            db = os.path.join(tmp, "db")
            os.makedirs(os.path.join(db, "sync"))
            open(os.path.join(db, "db.lck"), "w").close()
            rc, out, _h = run(["check-updates", "--db", db])
            self.assertEqual(rc, 0, out)
            self.assertFalse(os.path.exists(os.path.join(db, "db.lck")))
            # jina kontrola drzi zamek: po CHECK_UPDATES_WAIT srozumitelna chyba, ne hlaska o internetu
            holder = open(os.path.join(db, ".check-updates.lock"), "a")
            fcntl.flock(holder, fcntl.LOCK_EX)
            old = lux_alpm.CHECK_UPDATES_WAIT
            lux_alpm.CHECK_UPDATES_WAIT = 0.6
            try:
                rc, out, _h = run(["check-updates", "--db", db])
            finally:
                lux_alpm.CHECK_UPDATES_WAIT = old
                holder.close()
            self.assertNotIn(rc, (0, 2))
            self.assertIn("Another update check is still running", out)
            self.assertNotIn("internet", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_plan(self):
        files = ["/c/htop-3.3.0-1-x86_64.pkg.tar.zst", "/c/htop-3.3.0-2-x86_64.pkg.tar.zst",
                 "/c/htop-3.2.0-1-x86_64.pkg.tar.zst", "/c/htop-3.10.0-1-x86_64.pkg.tar.zst",
                 "/c/gone-1.0-1-any.pkg.tar.zst", "/c/lib32-x-1-1-x86_64.pkg.tar.xz", "/c/readme.txt",
                 "/c/my-tool-git-r10.abc-1-x86_64.pkg.tar.zst"]
        plan = lux_alpm.cache_plan(files, {"htop", "lib32-x", "my-tool-git"}, fake.vercmp, 2, 0)
        # nejnovejsi 2 verze (3.10.0 > 3.3.0 - porovnani verzi, ne textu), odinstalovane vsechny
        self.assertEqual(plan, ["/c/gone-1.0-1-any.pkg.tar.zst", "/c/htop-3.2.0-1-x86_64.pkg.tar.zst",
                                "/c/htop-3.3.0-1-x86_64.pkg.tar.zst"])
        self.assertEqual(lux_alpm.cache_plan(files, {"htop"}, fake.vercmp, 1, 1),
                         ["/c/htop-3.2.0-1-x86_64.pkg.tar.zst", "/c/htop-3.3.0-1-x86_64.pkg.tar.zst",
                          "/c/htop-3.3.0-2-x86_64.pkg.tar.zst"])

    def test_clean_removes_old_versions(self):
        tmp = tempfile.mkdtemp(prefix="lux-clean-test-")
        try:
            for f in ("htop-3.3.0-1-x86_64.pkg.tar.zst", "htop-3.3.0-1-x86_64.pkg.tar.zst.sig",
                      "htop-3.3.0-2-x86_64.pkg.tar.zst", "htop-3.2.0-1-x86_64.pkg.tar.zst", "gone-1-1-any.pkg.tar.zst"):
                with open(os.path.join(tmp, f), "w") as fh:
                    fh.write("x" * 10)
            rc, out, _h = run(["clean", "--keep", "1"], conf=CONF.replace("/var/cache/lux/pkg/", tmp + "/"))
            self.assertEqual(rc, 0, out)
            self.assertEqual(sorted(os.listdir(tmp)), ["htop-3.3.0-2-x86_64.pkg.tar.zst"])
            self.assertIn("Removed 3 old package files", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_files_and_owns(self):
        rc, out, _h = run(["files", "htop"])
        self.assertEqual(out.splitlines(), ["/usr/bin/htop"])
        self.assertEqual(lux_alpm.owner_paths("/usr/bin/../bin/htop"), "usr/bin/htop")
        rc, out, _h = run(["owns", "/usr/bin/htop"])
        self.assertEqual(rc, 0)
        self.assertIn("/usr/bin/htop is owned by htop 3.3.0-1", out)
        rc, out, _h = run(["owns", "/usr/lib"])
        self.assertIn("glibc", out)
        rc, out, _h = run(["owns", "/nonexistent/file"])
        self.assertEqual(rc, 1)
        self.assertIn("No package owns /nonexistent/file", out)


class CallbackShapes(unittest.TestCase):
    """dlcb ve dvou tvarech (pyalpm 0.10: udalost + data, starsi: stazeno/celkem)."""

    def setUp(self):
        self.out = io.StringIO()
        self.ui = lux_alpm.UI(machine=True, out=self.out)
        self.cb = lux_alpm.Callbacks(self.ui)
        self.cb.reset("commit", 1000)

    def test_new_style(self):
        self.cb.dl("a.pkg.tar.zst", 0, (False,))
        self.cb.dl("a.pkg.tar.zst", 1, (500, 1000))
        self.assertEqual(self.cb.files["a.pkg.tar.zst"], 500)
        self.cb.dl("a.pkg.tar.zst", 2, (True,))
        self.assertEqual(self.cb.files["a.pkg.tar.zst"], 0)
        self.cb.dl("a.pkg.tar.zst", 3, (1000, 0))
        self.assertIn("a.pkg.tar.zst downloading...", self.out.getvalue())

    def test_old_style(self):
        self.cb.dl("b.pkg.tar.zst", 250, 1000)
        self.assertEqual(self.cb.files["b.pkg.tar.zst"], 250)
        self.cb.dl("b.pkg.tar.zst", 1000, 1000)
        self.assertIn("b.pkg.tar.zst downloading...", self.out.getvalue())

    def test_progress_with_op_prefix(self):
        self.cb.reset("commit", 0, {"x": "upgrading"})
        self.cb.progress(1, "x", 50, 1, 1)
        self.assertIn("upgrading x...", self.out.getvalue())

    def test_questions_default_like_noconfirm(self):
        self.ui.yes = True
        self.assertEqual(self.cb.question(lux_alpm.Q_REPLACE_PKG), 1)
        self.assertEqual(self.cb.question(lux_alpm.Q_IMPORT_KEY), 1)
        self.assertEqual(self.cb.question(lux_alpm.Q_CONFLICT_PKG), 0)
        self.assertEqual(self.cb.question(lux_alpm.Q_REMOVE_PKGS), 0)

    def test_new_config_files_counted(self):
        """Varovani libalpm o nove verzi konfigurace: *.luxnew (lux-engine) i *.pacnew (starsi jadro)."""
        self.cb.log(2, "/etc/a.conf installed as /etc/a.conf.luxnew\n")
        self.cb.log(2, "/etc/b.conf installed as /etc/b.conf.pacnew\n")
        self.cb.log(2, "something else\n")
        self.assertEqual(self.cb.pacnew, 2)


if __name__ == "__main__":
    unittest.main()


class GpuProviders(unittest.TestCase):
    """Zavislost na vulkan-driver nesmi na ne-NVIDIA stroji vybrat ovladac NVIDIA z [luxos]."""

    def gpu_world(self, h):
        by = {db.name: db for db in h.sync}
        by["luxos"].add(fake.Package("lib32-nvidia-470xx-utils", "470.256-1", provides=["lib32-vulkan-driver"]))
        by["extra"].add(fake.Package("steam", "1.0-1", depends=["lib32-vulkan-driver"]))
        by["extra"].add(fake.Package("lib32-vulkan-swrast", "25.0-1", provides=["lib32-vulkan-driver"]))
        by["extra"].add(fake.Package("lib32-vulkan-radeon", "25.0-1", provides=["lib32-vulkan-driver"]))
        by["extra"].add(fake.Package("lib32-nvidia-utils", "615.0-1", provides=["lib32-vulkan-driver"]))

    def install(self, hw):
        old = lux_alpm.Lux.hw_packages
        lux_alpm.Lux.hw_packages = lambda self: list(hw)
        try:
            api = make_api()
            reg = api.Handle.register_syncdb

            def register(h, name, sig):
                db = reg(h, name, sig)
                if name == "extra":
                    self.gpu_world(h)
                return db
            api.Handle.register_syncdb = register
            rc, out, h = run(["-y", "--machine", "install", "steam"], api=api)
        finally:
            lux_alpm.Lux.hw_packages = old
        self.assertEqual(rc, 0, out)
        return {p.name for p in h.local.pkgcache}

    def test_amd_gets_radeon(self):
        got = self.install(["vulkan-radeon", "amd-ucode"])
        self.assertIn("lib32-vulkan-radeon", got)
        self.assertNotIn("lib32-nvidia-470xx-utils", got)

    def test_vm_gets_software_vulkan(self):
        got = self.install(["qemu-guest-agent"])
        self.assertIn("lib32-vulkan-swrast", got)
        self.assertNotIn("lib32-nvidia-470xx-utils", got)

    def test_modern_nvidia_gets_current_driver(self):
        got = self.install(["nvidia-open-dkms", "nvidia-utils"])
        self.assertIn("lib32-nvidia-utils", got)
        self.assertNotIn("lib32-nvidia-470xx-utils", got)

    def test_kepler_keeps_legacy(self):
        got = self.install(["lib32-nvidia-470xx-utils", "nvidia-470xx-dkms"])
        self.assertIn("lib32-nvidia-470xx-utils", got)


# ---- hooky: prubeh faze Dokoncuji / Pripravuji ---------------------------------------------------
HOOKS = {
    "05-snapshot": """# snimek pred transakci
[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Operation = Remove
Target = *

[Action]
Description = Saving a snapshot of the system...
When = PreTransaction
Exec = /usr/bin/luxos-care snapshot-pre
NeedsTargets
AbortOnFail
""",
    "20-desktop": """[Trigger]
Type = Path
Operation = Install
Operation = Upgrade
Operation = Remove
Target = usr/share/applications/*.desktop

[Action]
Description = Updating the desktop file MIME type cache...
When = PostTransaction
Exec = /usr/bin/update-desktop-database --quiet
""",
    "30-icons": """[Trigger]
Type = Path
Operation = Install
Operation = Upgrade
Operation = Remove
Target = usr/share/icons/*/
Target = !usr/share/icons/*/?*

[Action]
Description = Updating icon theme caches...
When = PostTransaction
Exec = /usr/share/libalpm/scripts/gtk-update-icon-cache
NeedsTargets
""",
    "40-initcpio": """[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Target = linux
Target = mkinitcpio

[Action]
Description = Updating linux initcpios...
When = PostTransaction
Exec = /usr/share/libalpm/scripts/mkinitcpio install
""",
    "50-htop": """[Trigger]
Type = Package
Operation = Upgrade
Target = htop

[Action]
When = PostTransaction
Exec = /bin/true
""",
    "60-kernel": """[Trigger]
Type = File
Operation = Install
Target = usr/lib/modules/*/vmlinuz

[Action]
Description = Kernel...
When = PostTransaction
Exec = /usr/bin/kernel-hook
""",
    "70-broken": """[Trigger]
Type = Package
Target = *

[Action]
When = PostTransaction
""",
}

FILES = {
    ("firefox", "131.0-1"): ["usr/", "usr/share/", "usr/share/applications/",
                             "usr/share/applications/firefox.desktop", "usr/share/icons/",
                             "usr/share/icons/hicolor/", "usr/share/icons/hicolor/48x48/apps/firefox.png"],
    ("nss", "3.104-1"): ["usr/lib/libnss3.so"],
    ("libvpx", "1.14-1"): ["usr/lib/libvpx.so"],
    ("htop", "3.3.0-1"): ["usr/bin/htop"],
    ("htop", "3.3.0-2"): ["usr/bin/htop", "usr/share/applications/htop.desktop"],
}


class HookWorld:
    """Docasny adresar s hooky (system + HookDir) a mistni databazi se seznamy souboru."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="lux-hooks-")
        self.sysdir = os.path.join(self.tmp, "usr/share/libalpm/hooks") + "/"
        self.userdir = os.path.join(self.tmp, "etc/lux/hooks") + "/"
        self.dbpath = os.path.join(self.tmp, "var/lib/lux") + "/"
        os.makedirs(self.sysdir)
        os.makedirs(self.userdir)
        for name, text in HOOKS.items():
            with open(os.path.join(self.sysdir, name + ".hook"), "w") as f:
                f.write(text)
        for (name, ver), files in FILES.items():
            d = os.path.join(self.dbpath, "local", f"{name}-{ver}")
            os.makedirs(d)
            with open(os.path.join(d, "files"), "w") as f:
                f.write("%FILES%\n" + "\n".join(files) + "\n\n%BACKUP%\netc/x.conf\tabc\n")

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class StubUI:
    """Zaznamenava fazi a prubeh (bez vykreslovani)."""

    def __init__(self):
        self.ph = None
        self.machine = self.verbose = False
        self.phases, self.steps, self.compats = [], [], []

    def phase(self, name):
        self.ph = {"name": name, "frac": 0.0, "detail": ""}
        self.phases.append(name)

    def progress(self, frac, detail=None):
        self.ph["frac"] = max(self.ph["frac"], frac)
        if detail is not None:
            self.ph["detail"] = detail
        self.steps.append((round(self.ph["frac"], 3), self.ph["detail"]))

    def compat(self, text):
        self.compats.append(text)

    def write(self, *a, **k):
        pass


class HookPlanTest(unittest.TestCase):
    def setUp(self):
        self.w = HookWorld()
        self.addCleanup(self.w.cleanup)

    def plan(self, installs=None, upgrades=None, removes=None):
        return lux_alpm.HookPlan.load([self.w.sysdir, self.w.userdir], self.w.dbpath, installs or {},
                                      upgrades or {}, removes or {})

    def names(self, hooks):
        return [h["name"] for h in hooks]

    def test_post_hooks_from_packages_and_paths(self):
        p = self.plan({"firefox": "131.0-1", "nss": "3.104-1"}, {"htop": ("3.3.0-1", "3.3.0-2")})
        self.assertEqual(self.names(p.run("pre")), ["05-snapshot"])
        # 30-icons: adresar usr/share/icons/hicolor/ (ne soubory pod nim); 40/60 nic nespousti;
        # 70-broken nema Exec -> libalpm ho nenacte
        self.assertEqual(self.names(p.run("post")), ["20-desktop", "30-icons", "50-htop"])
        self.assertEqual(lux_alpm.hook_label(p.run("post")[0]), "Updating the desktop file MIME type cache")
        self.assertEqual(lux_alpm.hook_label(p.run("post")[2]), "50-htop")       # bez Description

    def test_negated_target(self):
        self.assertEqual(lux_alpm.alpm_fnmatch_patterns(["usr/share/icons/*/", "!usr/share/icons/*/?*"],
                                                        "usr/share/icons/hicolor/"), 0)
        self.assertEqual(lux_alpm.alpm_fnmatch_patterns(["usr/share/icons/*/", "!usr/share/icons/*/?*"],
                                                        "usr/share/icons/hicolor/48x48/"), 1)
        self.assertEqual(lux_alpm.alpm_fnmatch_patterns(["usr/bin/*"], "etc/x"), -1)
        p = self.plan({"nss": "3.104-1"})
        self.assertNotIn("30-icons", self.names(p.run("post")))

    def test_upgrade_paths_use_new_files_after_and_old_before(self):
        p = self.plan(upgrades={"htop": ("3.3.0-1", "3.3.0-2")})
        self.assertIn("20-desktop", self.names(p.run("post")))      # novy htop.desktop
        self.assertEqual(self.names(p.run("pre")), ["05-snapshot"])

    def test_remove_reads_files_before_transaction(self):
        p = self.plan(removes={"firefox": "131.0-1"})
        shutil.rmtree(os.path.join(self.w.dbpath, "local", "firefox-131.0-1"))   # transakce ho odebrala
        self.assertEqual(self.names(p.run("post")), ["20-desktop", "30-icons"])

    def test_hookdir_overrides_and_masks(self):
        with open(os.path.join(self.w.userdir, "50-htop.hook"), "w") as f:
            f.write("")                                              # prazdny = maskovany hook
        with open(os.path.join(self.w.userdir, "20-desktop.hook"), "w") as f:
            f.write(HOOKS["20-desktop"].replace("Updating the desktop", "Custom desktop"))
        p = self.plan(upgrades={"htop": ("3.3.0-1", "3.3.0-2")})
        post = p.run("post")
        self.assertEqual(self.names(post), ["20-desktop"])
        self.assertTrue(post[0]["desc"].startswith("Custom desktop"))


class HookProgress(unittest.TestCase):
    """pyalpm 0.12 posila u hooku jen typ udalosti - prubeh se pocita z odhadu a logu 'executing'."""

    def setUp(self):
        self.w = HookWorld()
        self.addCleanup(self.w.cleanup)
        self.ui = StubUI()
        self.cb = lux_alpm.Callbacks(self.ui)
        plan = lux_alpm.HookPlan.load([self.w.sysdir], self.w.dbpath, {"firefox": "131.0-1"},
                                      {"htop": ("3.3.0-1", "3.3.0-2")}, {})
        self.cb.reset("commit", 0, {"firefox": "installing", "htop": "upgrading"}, hooks=plan)

    def hook(self, cmd):
        self.cb.event(36, "unknown event")
        self.cb.log(4, f'executing "{cmd}" under chroot "/"\n')
        self.cb.event(37, "unknown event")

    def install(self):
        self.cb.progress("firefox", 100, 2, 1)
        self.cb.progress("htop", 100, 2, 2)

    def test_pre_hooks_are_preparing(self):
        self.cb.event(34, "unknown event")
        self.assertEqual(self.ui.phases, ["prepare"])
        self.hook("/usr/bin/luxos-care")
        self.assertEqual(self.ui.steps[0], (0.0, "1/1 · Saving a snapshot of the system"))
        self.assertEqual(self.ui.steps[-1][0], 1.0)
        self.cb.event(35, "unknown event")
        self.install()
        self.assertEqual(self.ui.phases, ["prepare", "install"])
        self.assertIn(":: Running pre-transaction hooks...", self.ui.compats)

    def test_post_hooks_count_and_names(self):
        self.install()
        self.cb.event(34, "unknown event")
        self.assertEqual(self.ui.phases[-1], "hooks")
        for cmd in ("/usr/bin/update-desktop-database", "/usr/share/libalpm/scripts/gtk-update-icon-cache",
                    "/bin/true"):
            self.hook(cmd)
        self.cb.event(35, "unknown event")
        hooks = [s for s in self.ui.steps if "/" in s[1] and "·" in s[1]]
        self.assertEqual(hooks, [
            (0.0, "1/3 · Updating the desktop file MIME type cache"),
            (0.333, "1/3 · Updating the desktop file MIME type cache"),
            (0.333, "2/3 · Updating icon theme caches"),
            (0.667, "2/3 · Updating icon theme caches"),
            (0.667, "3/3 · 50-htop"),
            (1.0, "3/3 · 50-htop")])
        self.assertEqual(self.ui.steps[-1], (1.0, "3/3"))
        self.assertEqual(self.ui.compats.count(":: Running post-transaction hooks..."), 1)

    def test_unpredicted_and_skipped_hooks_resync(self):
        """Odhad [desktop, icons, htop]; skutecne bezi desktop, mkinitcpio (mimo odhad), htop."""
        self.install()
        self.cb.event(34, "unknown event")
        self.hook("/usr/bin/update-desktop-database")
        self.cb.event(36, "unknown event")
        self.cb.log(4, 'executing "/usr/share/libalpm/scripts/mkinitcpio" under chroot "/"\n')
        self.assertEqual(self.ui.ph["detail"], "2/4 · Updating linux initcpios")
        self.cb.event(37, "unknown event")
        self.cb.event(36, "unknown event")
        self.assertEqual(self.ui.ph["detail"], "3/4 · Updating icon theme caches")
        self.cb.log(4, 'executing "/bin/true" under chroot "/"\n')    # icons se nespustily
        self.assertEqual(self.ui.ph["detail"], "3/3 · 50-htop")
        self.cb.event(37, "unknown event")
        self.assertEqual(self.ui.ph["frac"], 1.0)

    def test_without_plan_counts_hooks(self):
        self.cb.reset("commit", 0, {"x": "installing"})
        self.cb.progress("x", 100, 1, 1)
        self.cb.event(34, "unknown event")
        self.cb.event(36, "unknown event")
        self.assertEqual(self.ui.ph["detail"], "1/1")
        self.cb.event(37, "unknown event")
        self.cb.event(36, "Updating icon theme caches...")       # pyalpm s popisem hooku
        self.assertEqual(self.ui.ph["detail"], "2/2 · Updating icon theme caches")

    def test_other_debug_logs_ignored(self):
        self.install()
        self.cb.event(34, "unknown event")
        self.cb.log(4, 'executing "/bin/sh" under chroot "/"\n')     # mimo bezici hook
        self.cb.log(4, "some debug message\n")
        self.assertEqual(self.cb.log_errors, [])
        self.assertEqual(self.cb.log_warnings, [])


class HookOutput(unittest.TestCase):
    """Cela aktualizace nad napodobeninou pyalpm: jedna radka Dokoncuji s poctem hooku, nic navic."""

    def setUp(self):
        self.w = HookWorld()
        self.addCleanup(self.w.cleanup)
        old = lux_alpm.HOOK_SYSDIR
        lux_alpm.HOOK_SYSDIR = self.w.sysdir
        self.addCleanup(setattr, lux_alpm, "HOOK_SYSDIR", old)

    def prepare(self, h):
        h.dbpath = self.w.dbpath
        h.hookdirs = [self.w.sysdir]
        h.pre_hooks = ["/usr/bin/luxos-care"]
        h.post_hooks = ["/usr/bin/update-desktop-database", "/usr/share/libalpm/scripts/gtk-update-icon-cache"]

    def test_plain_output(self):
        rc, out, _h = run(["-y", "install", "firefox"], prepare=self.prepare)
        self.assertEqual(rc, 0, out)
        lines = [x for x in strip(out).splitlines() if x.strip()]
        fin = [x for x in lines if "Finishing" in x]
        self.assertEqual(len(fin), 1, lines)
        self.assertIn("100%", fin[0])
        self.assertIn("2/2", fin[0])
        prep = [x for x in lines if "Preparing" in x]
        self.assertEqual(len(prep), 1, lines)
        self.assertFalse(any("executing" in x for x in lines), lines)

    def test_tty_shows_hook_names(self):
        orig = lux_alpm.UI.draw
        lux_alpm.UI.draw = lambda self, force=False: orig(self, True)     # bez omezeni na 12,5 snimku/s
        self.addCleanup(setattr, lux_alpm.UI, "draw", orig)
        rc, out, _h = run(["install", "firefox"], tty=True, answer="y\n", prepare=self.prepare)
        self.assertEqual(rc, 0, out)
        plain = strip(out)
        self.assertIn("1/2 · Updating the desktop file", plain)
        self.assertIn("2/2 · Updating icon theme caches", plain)
        self.assertIn("Saving a snapshot of the system", plain)

    def test_machine_phases(self):
        rc, out, _h = run(["--machine", "-y", "install", "firefox"], prepare=self.prepare)
        self.assertEqual(rc, 0, out)
        lines = out.splitlines()
        order = [x for x in lines if x.startswith("@@PHASE")]
        self.assertEqual(order, ["@@PHASE download", "@@PHASE verify", "@@PHASE prepare", "@@PHASE install",
                                 "@@PHASE hooks"])
        self.assertIn("@@PROGRESS hooks 100 2/2", lines)
        self.assertIn(":: Running pre-transaction hooks...", lines)
