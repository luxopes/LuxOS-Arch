#!/usr/bin/env python3
"""LuxOS - upozorneni na chybejici ovladace po prihlaseni (luxos_drivers_hub.lsl v luxos-hub, drive
luxos_drivers_session.py): stav zarizeni z luxos-hwdetect --json proti databazi baliku, jednou za start
pocitace, v live systemu nikdy, odmitnute baliky. Upozorneni a jeho akce testuje test_luxos_hub_lsl.py.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_drivers_hub.py -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL_DIR = os.path.join(HERE, "..", "files", "lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
TMP = PROBE = None


def setUpModule():
    global TMP, PROBE
    if not LSLC:
        raise unittest.SkipTest("lslc (lsl) is not installed")
    TMP = tempfile.mkdtemp(prefix="luxos-drivers-hub-test-")
    PROBE = os.path.join(TMP, "luxos-drivers-probe")
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", LSL_DIR,
                        os.path.join(HERE, "lsl", "luxos-drivers-probe.lsl"), PROBE],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def dev(id_, pkgs=(), alts=(), title="X"):
    return {"id": id_, "kind": "gpu", "title": title, "note": "", "packages": list(pkgs), "services": [],
            "module": "", "reboot": False, "alternatives": list(alts)}


# stejna zarizeni jako luxos-drivers/tests/test_luxos_drivers.py
NV_OPEN = dev("gpu-1", ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"])
KEPLER = dev("gpu-2", ["vulkan-nouveau", "linux-firmware-nvidia"], alts=[
    {"id": "nvidia-470xx", "title": "NVIDIA 470 legacy driver", "note": "", "reboot": True, "module": "nvidia",
     "services": [], "packages": ["nvidia-470xx-dkms", "nvidia-470xx-utils", "linux-zen-headers"]}])
VM = dev("gpu-3", [])
CPU = dev("cpu", ["intel-ucode", "thermald"])


class DriversHub(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.env = dict(os.environ, LUXOS_DRIVERS_ROOT=os.path.join(self.root, "sys"),
                        XDG_CACHE_HOME=os.path.join(self.root, "cache"), XDG_CONFIG_HOME=os.path.join(self.root, "config"))

    def probe(self, *args):
        r = subprocess.run([PROBE, *args], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def eval(self, devices, installed, ignored=""):
        path = os.path.join(self.root, "in.json")
        with open(path, "w") as f:
            json.dump({"devices": devices, "installed": installed, "ignored": ignored}, f)
        return json.loads(self.probe("eval", path))

    def test_statuses(self):
        r = self.eval([NV_OPEN, VM, CPU], ["intel-ucode", "thermald"])
        self.assertEqual([s["status"] for s in r["states"]], ["available", "ok", "ok"])
        self.assertEqual(r["states"][0]["missing"], ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers"])
        self.assertEqual(r["key"], "linux-zen-headers nvidia-open-dkms nvidia-utils")

    def test_equivalent_packages(self):
        # prebuilt nvidia-open nebo uz nainstalovany ovladac 580 (umi i Turing+) staci
        r = self.eval([NV_OPEN], ["nvidia-open", "nvidia-utils", "linux-zen-headers"])
        self.assertEqual(r["states"][0]["status"], "ok")
        r = self.eval([NV_OPEN], ["nvidia-580xx-dkms", "nvidia-580xx-utils", "linux-zen-headers"])
        self.assertEqual((r["states"][0]["status"], r["key"], r["notify"]), ("ok", "", False))

    def test_alternative(self):
        r = self.eval([KEPLER], ["nvidia-470xx-dkms", "nvidia-470xx-utils", "linux-zen-headers"])
        self.assertEqual((r["states"][0]["status"], r["key"]), ("ok", ""))      # nouveau se pak nenabizi
        r = self.eval([KEPLER], ["nvidia-470xx-dkms", "nvidia-470xx-utils"])
        self.assertEqual(r["states"][0]["missing"], ["linux-zen-headers"])
        r = self.eval([KEPLER], [])
        self.assertEqual(r["states"][0]["missing"], ["vulkan-nouveau", "linux-firmware-nvidia"])

    def test_notify_rules(self):
        key = "intel-ucode linux-zen-headers nvidia-open-dkms nvidia-utils thermald"
        self.assertEqual(self.eval([CPU, NV_OPEN], [])["key"], key)
        self.assertTrue(self.eval([CPU, NV_OPEN], [])["notify"])
        self.assertFalse(self.eval([CPU, NV_OPEN], [], key)["notify"])
        # jiny hardware (novy balik) -> znovu upozornit
        self.assertTrue(self.eval([CPU, NV_OPEN], [], "intel-ucode thermald")["notify"])
        everything = ["nvidia-open-dkms", "nvidia-utils", "linux-zen-headers", "intel-ucode", "thermald"]
        self.assertFalse(self.eval([CPU, NV_OPEN], everything)["notify"])

    def test_package_database(self):
        # adresare jmeno-verze-vydani v /var/lib/lux/local, starsi systemy /var/lib/pacman/local
        for name in ("intel-ucode-20250812-1", "thermald-2.5.9-1", "lib32-nvidia-580xx-utils-580.82-2"):
            os.makedirs(os.path.join(self.root, "sys", "var", "lib", "pacman", "local", name))
        r = self.eval([CPU, dev("g", ["lib32-nvidia-utils"])], None)
        self.assertEqual(r["key"], "")
        os.makedirs(os.path.join(self.root, "sys", "var", "lib", "lux", "local", "thermald-2.5.9-1"))
        self.assertEqual(self.eval([CPU], None)["key"], "intel-ucode")

    def test_once_per_boot_and_live(self):
        self.assertEqual(self.probe("should", "boot-a"), "True")
        os.makedirs(os.path.join(self.root, "cache", "luxos"))
        with open(os.path.join(self.root, "cache", "luxos", "drivers-checked"), "w") as f:
            f.write("boot-a\n")
        self.assertEqual(self.probe("should", "boot-a"), "False")
        self.assertEqual(self.probe("should", "boot-b"), "True")
        os.makedirs(os.path.join(self.root, "sys", "run", "archiso"))
        self.assertEqual(self.probe("should", "boot-b"), "False")


if __name__ == "__main__":
    unittest.main()
