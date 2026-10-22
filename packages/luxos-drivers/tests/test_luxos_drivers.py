"""Testy logiky aplikace Ovladace, pomocnika a kontroly po prihlaseni (bez rootu, bez zasahu do systemu).

    python3 -m unittest discover -s packages/luxos-drivers/tests -v
"""
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..")
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
os.environ.setdefault("LUXOS_I18N_DIR", os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

import luxos_drivers as drv  # noqa: E402


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def dev(id_, pkgs=(), module="", reboot=False, services=(), alts=(), kind="gpu", title="X"):
    return {"id": id_, "kind": kind, "title": title, "note": "", "packages": list(pkgs), "services": list(services),
            "module": module, "reboot": reboot, "alternatives": list(alts)}


NV_OPEN = dev("gpu-1", ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"], "nvidia", True)
KEPLER = dev("gpu-2", ["vulkan-nouveau", "linux-firmware-nvidia"], alts=[
    {"id": "nvidia-470xx", "title": "NVIDIA 470 legacy driver", "note": "", "reboot": True, "module": "nvidia",
     "services": [], "packages": ["nvidia-470xx-dkms", "nvidia-470xx-utils", "linux-zen-headers"]}])
VM = dev("gpu-3", [], kind="gpu")
CPU = dev("cpu", ["intel-ucode", "thermald"], services=["thermald.service"], kind="cpu")


class Evaluate(unittest.TestCase):
    def st(self, devices, installed, loaded=lambda m: False):
        return drv.evaluate({"devices": devices}, set(installed), loaded)

    def test_statuses(self):
        s = self.st([NV_OPEN, VM, CPU], ["intel-ucode", "thermald"])
        self.assertEqual([x["status"] for x in s], [drv.AVAILABLE, drv.WORKING, drv.INSTALLED])
        self.assertEqual(s[0]["missing"], ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"])
        self.assertEqual(drv.missing_packages(s), ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"])

    def test_restart_until_module_loaded(self):
        inst = ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"]
        self.assertEqual(self.st([NV_OPEN], inst)[0]["status"], drv.RESTART)
        self.assertTrue(drv.needs_restart(self.st([NV_OPEN], inst)))
        self.assertEqual(self.st([NV_OPEN], inst, lambda m: m == "nvidia")[0]["status"], drv.INSTALLED)

    def test_equivalent_packages(self):
        # prebuilt nvidia-open nebo uz nainstalovany ovladac 580 (umi i Turing+) staci
        s = self.st([NV_OPEN], ["nvidia-open", "nvidia-utils", "linux-zen-headers"], lambda m: True)
        self.assertEqual(s[0]["status"], drv.INSTALLED)
        s = self.st([NV_OPEN], ["nvidia-580xx-dkms", "nvidia-580xx-utils", "linux-zen-headers"], lambda m: True)
        self.assertEqual(s[0]["status"], drv.INSTALLED)
        self.assertEqual(drv.missing_packages(s), [])

    def test_alternative_active(self):
        s = self.st([KEPLER], ["nvidia-470xx-dkms", "nvidia-470xx-utils", "linux-zen-headers"], lambda m: True)
        self.assertEqual(s[0]["status"], drv.INSTALLED)
        self.assertEqual(s[0]["active"]["id"], "nvidia-470xx")
        # nouveau baliky se pak nenabizeji
        self.assertEqual(drv.missing_packages(s), [])
        # bez hlavicek (nove jadro) chybi jen hlavicky
        s = self.st([KEPLER], ["nvidia-470xx-dkms", "nvidia-470xx-utils"])
        self.assertEqual(s[0]["missing"], ["linux-zen-headers"])

    def test_alternative_not_installed(self):
        s = self.st([KEPLER], [])
        self.assertIsNone(s[0]["active"])
        self.assertEqual(s[0]["missing"], ["vulkan-nouveau", "linux-firmware-nvidia"])

    def test_services_only_for_relevant(self):
        s = self.st([CPU, VM], [])
        self.assertEqual(drv.wanted_services(s), ["thermald.service"])

    def test_notify_key_sorted(self):
        s = self.st([CPU, NV_OPEN], [])
        self.assertEqual(drv.notify_key(s), "intel-ucode linux-zen-headers nvidia-open-dkms nvidia-utils thermald")


class Plan(unittest.TestCase):
    data = {"devices": [NV_OPEN, KEPLER, CPU]}

    def test_recommended(self):
        pkgs, svcs, reboot = drv.plan(self.data, {"intel-ucode"}, loaded=lambda m: False)
        self.assertEqual(pkgs, ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers", "vulkan-nouveau",
                                "linux-firmware-nvidia", "thermald"])
        self.assertEqual(svcs, ["thermald.service"])
        self.assertTrue(reboot)

    def test_nothing_to_do(self):
        pkgs, _s, reboot = drv.plan({"devices": [CPU]}, {"intel-ucode", "thermald"})
        self.assertEqual(pkgs, [])
        self.assertFalse(reboot)

    def test_alternative(self):
        pkgs, svcs, reboot = drv.plan(self.data, {"linux-zen-headers"}, alternative=("gpu-2", "nvidia-470xx"))
        self.assertEqual(pkgs, ["nvidia-470xx-dkms", "nvidia-470xx-utils"])
        self.assertEqual(svcs, [])
        self.assertTrue(reboot)

    def test_unknown_alternative(self):
        with self.assertRaises(ValueError):
            drv.plan(self.data, set(), alternative=("gpu-1", "nvidia-470xx"))
        with self.assertRaises(ValueError):
            drv.plan(self.data, set(), alternative=("nope", "nvidia-470xx"))

    def test_rejects_bad_names(self):
        bad = {"devices": [dev("x", ["ok", "--overwrite=/*"])]}
        with self.assertRaises(ValueError):
            drv.plan(bad, set())
        bad = {"devices": [dev("x", ["ok"], services=["evil; rm"])]}
        with self.assertRaises(ValueError):
            drv.plan(bad, set())


class Headers(unittest.TestCase):
    def q(self, table):
        return lambda args: table.get(tuple(args))

    def test_in_sync(self):
        q = self.q({("-Q", "linux-zen"): "7.2.11.zen1-1", ("-Si", "linux-zen-headers"): "7.2.11.zen1-1"})
        self.assertEqual(drv.headers_out_of_sync(["nvidia-open-dkms", "linux-zen-headers"], q), [])

    def test_out_of_sync(self):
        q = self.q({("-Q", "linux-zen"): "7.2.10.zen1-1", ("-Si", "linux-zen-headers"): "7.2.11.zen1-1"})
        self.assertEqual(drv.headers_out_of_sync(["linux-zen-headers"], q), ["linux-zen-headers"])

    def test_missing_in_repo(self):
        q = self.q({("-Q", "linux-zen"): "7.2.10.zen1-1"})
        self.assertEqual(drv.headers_out_of_sync(["linux-zen-headers"], q), ["linux-zen-headers"])


class RootTree(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-drivers-test-")
        self.old = drv.ROOT
        drv.ROOT = self.root

    def tearDown(self):
        drv.ROOT = self.old
        shutil.rmtree(self.root, ignore_errors=True)

    def mk(self, path):
        os.makedirs(self.root + path, exist_ok=True)

    def test_installed_packages(self):
        for d in ("nvidia-utils-615.78.08-1", "lib32-nvidia-580xx-utils-580.178.04-1", "linux-zen-7.2.11.zen1-1",
                  "python-gobject-3.54.0-2"):
            self.mk("/var/lib/pacman/local/" + d)
        open(self.root + "/var/lib/pacman/local/ALPM_DB_VERSION", "w").close()
        self.assertEqual(drv.installed_packages(),
                         {"nvidia-utils", "lib32-nvidia-580xx-utils", "linux-zen", "python-gobject"})

    def test_installed_packages_no_db(self):
        self.assertEqual(drv.installed_packages(), set())

    def test_module_loaded(self):
        self.mk("/sys/module/nvidia_drm")
        self.assertTrue(drv.module_loaded("nvidia-drm"))
        self.assertFalse(drv.module_loaded("wl"))
        self.assertFalse(drv.module_loaded(""))


class WithHwdetect(unittest.TestCase):
    """Cela cesta: skutecny luxos-hwdetect nad falesnym /sys -> evaluate/plan."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-drivers-hw-")
        self.env = {k: os.environ.get(k) for k in ("LUXOS_HW_ROOT", "LUXOS_HW_DATA", "LUXOS_HW_VIRT")}
        os.environ.update(LUXOS_HW_ROOT=self.root, LUXOS_HW_DATA=PKG, LUXOS_HW_VIRT="none")
        self.old = (drv.HWDETECT, drv.ROOT)
        drv.HWDETECT = os.path.join(PKG, "luxos-hwdetect")
        drv.ROOT = self.root

    def tearDown(self):
        drv.HWDETECT, drv.ROOT = self.old
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.root, ignore_errors=True)

    def pci(self, slot, cls, vendor, device):
        d = f"{self.root}/sys/bus/pci/devices/{slot}"
        os.makedirs(d)
        for k, v in (("class", cls), ("vendor", vendor), ("device", device)):
            with open(f"{d}/{k}", "w") as f:
                f.write(f"0x{v}\n")

    def test_pascal_flow(self):
        self.pci("0000:01:00.0", "030000", "10de", "1c03")
        os.makedirs(f"{self.root}/usr/lib/modules/7.2.11-zen1-1-zen")
        with open(f"{self.root}/usr/lib/modules/7.2.11-zen1-1-zen/pkgbase", "w") as f:
            f.write("linux-zen\n")
        data = drv.detect()
        pkgs, svcs, reboot = drv.plan(data, {"linux-zen"})
        self.assertIn("nvidia-580xx-dkms", pkgs)
        self.assertIn("linux-zen-headers", pkgs)
        self.assertIn("nvidia-suspend.service", svcs)
        self.assertTrue(reboot)

    def test_kepler_alternative_flow(self):
        self.pci("0000:01:00.0", "030000", "10de", "1180")
        data = drv.detect()
        pkgs, _s, _r = drv.plan(data, set(), alternative=("gpu-0000:01:00.0", "nvidia-470xx"))
        self.assertEqual(pkgs[:2], ["nvidia-470xx-dkms", "nvidia-470xx-utils"])

    def test_detect_failure(self):
        drv.HWDETECT = "/bin/false"
        with self.assertRaises(RuntimeError):
            drv.detect()


class Gui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = load("luxos_drivers_app", os.path.join(PKG, "luxos-drivers"))

    def run_lines(self, lines):
        prog, seen = {}, []
        for line in lines:
            seen.append(self.gui.progress_from_line(line, prog))
        return prog, seen

    def test_progress_install_only(self):
        prog, seen = self.run_lines(["@@STEP install", "@@PROGRESS download 50", "@@PROGRESS install 100 3/3 nvidia-utils",
                                     "@@PROGRESS hooks 100", "@@STEP services", "@@REBOOT", "@@DONE 0"])
        fr = [f for f, _t in seen if f is not None]
        self.assertEqual(fr, sorted(fr), "progress must not go backwards")
        self.assertAlmostEqual(seen[1][0], 0.225)
        self.assertIn("nvidia-utils", seen[2][1])
        self.assertTrue(prog["reboot"])

    def test_progress_with_update(self):
        prog, seen = self.run_lines(["@@STEP update", "@@PROGRESS download 100", "@@PROGRESS install 100 1/1 linux-zen",
                                     "@@STEP install", "@@PROGRESS download 0", "@@PROGRESS install 100 1/1 x"])
        fr = [f for f, _t in seen if f is not None]
        self.assertEqual(fr, sorted(fr))
        self.assertLessEqual(max(fr[:3]), 0.4)
        self.assertGreaterEqual(fr[3], 0.4)

    def test_errors(self):
        prog, _ = self.run_lines(["@@ERROR network failed to download", "@@DONE 1"])
        self.assertIn("internet", prog["err"])
        prog, _ = self.run_lines(["@@ERROR weird Something odd"])
        self.assertEqual(prog["err"], "Something odd")
        prog, _ = self.run_lines(["error: target not found: foo"])
        self.assertEqual(prog["err"], "target not found: foo")
        _p, seen = self.run_lines(["plain pacman line", "@@RETRY 2"])
        self.assertEqual(seen[0], (None, None))
        self.assertIn("2", seen[1][1])

    def test_tr_lines(self):
        self.assertEqual(self.gui.tr_lines("a\n\nb"), "a\nb")
        self.assertEqual(self.gui.tr_lines(""), "")


class Helper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load("luxos_drivers_helper", os.path.join(PKG, "luxos-drivers-helper"))

    def call(self, argv, plan=(["nvidia-open-dkms", "linux-zen-headers"], ["thermald.service", "nvidia-suspend.service"], True),
             out_of_sync=(), lux=True, rc=0, euid=0, live=False):
        calls, sysd = [], []

        def fake_run(cmd):
            calls.append(cmd)
            return rc

        def fake_sub_run(cmd, **_kw):
            sysd.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        out = io.StringIO()
        real_isdir = os.path.isdir
        with mock.patch.object(self.h.os, "geteuid", return_value=euid), \
                mock.patch.object(self.h.drv, "detect", return_value={"devices": []}), \
                mock.patch.object(self.h.drv, "plan", return_value=plan) as p_plan, \
                mock.patch.object(self.h.drv, "headers_out_of_sync", return_value=list(out_of_sync)), \
                mock.patch.object(self.h, "lux_available", return_value=lux), \
                mock.patch.object(self.h, "run", side_effect=fake_run), \
                mock.patch.object(self.h, "pacman_retry", side_effect=lambda a: calls.append(["pacman", *a]) or rc), \
                mock.patch.object(self.h.subprocess, "run", side_effect=fake_sub_run), \
                mock.patch.object(self.h.os.path, "isdir",
                                  side_effect=lambda p: live if p == "/run/archiso" else real_isdir(p)), \
                redirect_stdout(out):
            try:
                code = self.h.main(argv)
            except SystemExit as e:
                code = e.code
        return code, calls, sysd, out.getvalue(), p_plan

    def test_requires_root(self):
        code, calls, *_ = self.call(["h", "install"], euid=1000)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])

    def test_bad_args(self):
        for argv in (["h"], ["h", "remove", "x"], ["h", "install", "extra"], ["h", "install-alt", "gpu;rm", "x"],
                     ["h", "install-alt", "a"]):
            code, calls, *_ = self.call(argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(calls, [])

    def test_live_refuses(self):
        code, calls, *_ = self.call(["h", "install"], live=True)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])

    def test_install_with_lux(self):
        code, calls, sysd, out, _p = self.call(["h", "install"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["/usr/lib/lux/lux_alpm.py", "--machine", "-y", "install", "--needed", "--",
                                  "nvidia-open-dkms", "linux-zen-headers"]])
        # nvidia-suspend se jen zapne (bez --now), thermald se rovnou spusti
        self.assertIn(["systemctl", "enable", "nvidia-suspend.service"], sysd)
        self.assertIn(["systemctl", "enable", "--now", "thermald.service"], sysd)
        self.assertIn("@@REBOOT", out)
        self.assertIn("@@STEP install", out)

    def test_update_first_when_headers_out_of_sync(self):
        code, calls, *_ = self.call(["h", "install"], out_of_sync=["linux-zen-headers"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["/usr/lib/lux/lux_alpm.py", "--machine", "-y", "update"])
        self.assertEqual(calls[1][3], "install")

    def test_failed_update_stops(self):
        code, calls, sysd, out, _p = self.call(["h", "install"], out_of_sync=["linux-zen-headers"], rc=1)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("@@REBOOT", out)

    def test_pacman_fallback(self):
        code, calls, *_ = self.call(["h", "install"], lux=False)
        self.assertEqual(calls, [["pacman", "-S", "--needed", "--noconfirm", "--", "nvidia-open-dkms",
                                  "linux-zen-headers"]])

    def test_alternative_passed_to_plan(self):
        code, _c, _s, _o, p_plan = self.call(["h", "install-alt", "gpu-0000:01:00.0", "nvidia-470xx"])
        self.assertEqual(code, 0)
        self.assertEqual(p_plan.call_args.kwargs["alternative"], ("gpu-0000:01:00.0", "nvidia-470xx"))

    def test_nothing_to_install(self):
        code, calls, sysd, out, _p = self.call(["h", "install"], plan=([], [], False))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertNotIn("@@REBOOT", out)


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-drivers-session-")
        self.s = load("luxos_drivers_session_t", os.path.join(PKG, "luxos_drivers_session.py"))
        self.s.CHECKED = os.path.join(self.tmp, "cache", "drivers-checked")
        self.s.IGNORED = os.path.join(self.tmp, "config", "drivers-ignored")
        self.old_root = drv.ROOT
        drv.ROOT = self.tmp

    def tearDown(self):
        drv.ROOT = self.old_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def states(self, installed=()):
        return drv.evaluate({"devices": [NV_OPEN, CPU]}, set(installed), lambda m: False)

    def test_once_per_boot(self):
        self.assertTrue(self.s.should_check("boot-a"))
        self.s._write(self.s.CHECKED, "boot-a")
        self.assertFalse(self.s.should_check("boot-a"))
        self.assertTrue(self.s.should_check("boot-b"))

    def test_live_never(self):
        os.makedirs(self.tmp + "/run/archiso")
        self.assertFalse(self.s.should_check("boot-a"))

    def test_notify_rules(self):
        st = self.states()
        self.assertTrue(self.s.should_notify(st, ""))
        self.assertFalse(self.s.should_notify(st, drv.notify_key(st)))
        # jiny hardware (novy balik) -> znovu upozornit
        self.assertTrue(self.s.should_notify(st, "intel-ucode thermald"))
        everything = ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers", "intel-ucode", "thermald"]
        self.assertFalse(self.s.should_notify(self.states(everything), ""))

    def test_check_flow(self):
        notified = []
        with mock.patch.object(self.s.drv, "boot_id", return_value="boot-x"), \
                mock.patch.object(self.s.drv, "detect", return_value={"devices": [NV_OPEN]}), \
                mock.patch.object(self.s.drv, "installed_packages", return_value=set()), \
                mock.patch.object(self.s.GLib, "idle_add", side_effect=lambda f: notified.append(f)):
            self.s.check()
            self.s.check()                       # podruhe ve stejnem startu nic
        self.assertEqual(len(notified), 1)
        with open(self.s.CHECKED) as f:
            self.assertEqual(f.read().strip(), "boot-x")

    def test_check_survives_errors(self):
        with mock.patch.object(self.s.drv, "boot_id", return_value="boot-y"), \
                mock.patch.object(self.s.drv, "detect", side_effect=RuntimeError("boom")), \
                mock.patch.object(self.s.GLib, "idle_add") as idle:
            self.s.check()
        idle.assert_not_called()

    def test_ignore_action(self):
        self.s._state.update(ids={7}, key="a b")
        self.s.on_action(None, None, None, None, None, mock.Mock(unpack=lambda: (7, "ignore")))
        with open(self.s.IGNORED) as f:
            self.assertEqual(f.read().strip(), "a b")
        # cizi upozorneni se ignoruje
        with mock.patch.object(self.s.subprocess, "Popen") as popen:
            self.s.on_action(None, None, None, None, None, mock.Mock(unpack=lambda: (8, "open")))
            popen.assert_not_called()


class Translations(unittest.TestCase):
    """Kazdy text aplikace a poznamky luxos-hwdetect musi mit preklad ve vsech jazycich."""

    def test_all_languages(self):
        import re
        i18n = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
        texts = set()
        for f in ("luxos-drivers", "luxos_drivers_session.py"):
            with open(os.path.join(PKG, f), encoding="utf-8") as fh:
                src = fh.read()
            texts |= set(re.findall(r'_\("((?:[^"\\]|\\.)*)"\)', src))
            texts |= {m for m in re.findall(r'"([A-Z][^"]{3,})"', src) if m in self.gui_tables(src)}
        with open(os.path.join(PKG, "luxos-hwdetect"), encoding="utf-8") as fh:
            hw = fh.read()
        texts |= set(re.findall(r'\bnote "([^"$]+)"', hw))
        texts |= {t for t in re.findall(r'device \S+ \S+ "([^"$]+)"', hw)}
        texts |= set(re.findall(r'alt nvidia-470xx "([^"]+)"', hw))
        texts |= set(re.findall(r'^\s+"(Faster 3D[^"]+)"', hw, re.M))
        texts = {t for t in texts if t not in ("VMware", "VirtualBox", "QEMU/KVM", "Hyper-V", "VMware SVGA")}
        self.assertGreater(len(texts), 40)
        langs = [f for f in os.listdir(i18n) if f.endswith(".tsv")]
        self.assertGreaterEqual(len(langs), 12)
        for lang in langs:
            keys = {}
            with open(os.path.join(i18n, lang), encoding="utf-8") as fh:
                for line in fh:
                    if "\t" in line and not line.startswith("#"):
                        k, v = line.rstrip("\n").split("\t", 1)
                        keys[k] = v
            missing = sorted(t for t in texts if not keys.get(t))
            self.assertEqual(missing, [], f"{lang}: missing translations")
            for t in texts:
                self.assertEqual(t.count("%s"), keys[t].count("%s"), f"{lang}: placeholder mismatch in {t!r}")

    @staticmethod
    def gui_tables(src):
        """Texty z tabulek STATUS/ERRORS (prekladaji se az pri zobrazeni)."""
        import re
        out = set()
        for name in ("STATUS", "ERRORS"):
            m = re.search(name + r" = \{(.*?)\}\n", src, re.S)
            if m:
                out |= set(re.findall(r'"([A-Z][^"]{3,})"', m.group(1)))
        return out


if __name__ == "__main__":
    unittest.main()
