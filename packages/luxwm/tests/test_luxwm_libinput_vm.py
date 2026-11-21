"""Mys a touchpad v luxwm na skutecnych zarizenich libinput: headless backend je nema, proto QEMU VM.

Host VM ma mysi QEMU (USB mys, VMMouse/PS2) a test v nem pres /dev/uinput vytvori touchpad (clickpad) a za behu
druhou mys - pro libinput jsou to obycejna zarizeni evdev. luxwm bezi ve VM na backendu headless + libinput
(libinput_guest.py), overuje se, co libinput skutecne nastavil (IPC get_input): nastaveni z luxwm.conf po
reload, pripojeni za behu, navrat vychozich hodnot po smazani polozek a odpojeni.

Obraz: nahled Waylandu (scripts/wl-preview/build-image.sh, adresar s base.qcow2, vmlinuz, initramfs.img) v
LUXWM_VM_IMAGE, vychozi out/vm-wayland-preview. Obraz se nemeni (vlastni prekryvny disk qcow2). Bez obrazu nebo
/dev/kvm se test preskoci. Potrebuje ~2,5 GB pameti:
  MEM=3G .../runiso.sh python3 -m unittest -v packages/luxwm/tests/test_luxwm_libinput_vm.py
"""
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
GUEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libinput_guest.py")


def image_dir():
    for d in (os.environ.get("LUXWM_VM_IMAGE", ""), os.path.join(ROOT, "out", "vm-wayland-preview"),
              os.path.expanduser("~/LuxOS-Arch/out/vm-wayland-preview")):
        if d and all(os.path.exists(os.path.join(d, f)) for f in ("base.qcow2", "vmlinuz", "initramfs.img")):
            return d
    return None


def load_vmctl(vm_dir):
    spec = importlib.util.spec_from_file_location("vmctl", os.path.join(ROOT, "scripts", "vmctl.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.T = vm_dir
    return mod


def by_name(devices, name):
    return [d for d in devices if d["name"] == name]


class LuxwmLibinputVM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = image_dir()
        if not image:
            raise unittest.SkipTest("no VM image (LUXWM_VM_IMAGE with base.qcow2, vmlinuz, initramfs.img)")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK) or not shutil.which("qemu-system-x86_64"):
            raise unittest.SkipTest("no KVM / QEMU")
        for f in ("luxwm", "libluxcomp.so.0"):
            if not os.path.exists(os.path.join(BUILD, f)):
                raise unittest.SkipTest(f"no {f} in {BUILD} (packages/luxwm/tests/build-host.sh)")
        os.makedirs(os.path.join(ROOT, "out", "luxwm-test"), exist_ok=True)
        cls.dir = tempfile.mkdtemp(prefix="vm-", dir=os.path.join(ROOT, "out", "luxwm-test"))
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b",
                        os.path.join(image, "base.qcow2"), os.path.join(cls.dir, "disk.qcow2")], check=True)
        d = cls.dir
        cls.qemu_log = open(os.path.join(d, "qemu.log"), "w")
        cls.qemu = subprocess.Popen(
            ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-smp", "2", "-m", "1536",
             "-display", "none", "-vga", "std", "-nic", "none",
             "-kernel", os.path.join(image, "vmlinuz"), "-initrd", os.path.join(image, "initramfs.img"),
             "-append", "root=/dev/vda rw quiet", "-drive", f"file={d}/disk.qcow2,if=virtio,format=qcow2",
             "-device", "qemu-xhci", "-device", "usb-mouse",
             "-device", "virtio-serial", "-chardev", f"socket,path={d}/qga.sock,server=on,wait=off,id=qga0",
             "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
             "-qmp", f"unix:{d}/qmp.sock,server=on,wait=off"],
            stdout=cls.qemu_log, stderr=subprocess.STDOUT)
        cls.vm = load_vmctl(d)
        try:
            cls.boot_and_run()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def boot_and_run(cls):
        deadline = time.monotonic() + 240
        while True:
            try:
                cls.vm.qga("guest-ping", timeout=5)
                break
            except Exception:
                if time.monotonic() > deadline or cls.qemu.poll() is not None:
                    raise RuntimeError("VM did not boot: " + open(os.path.join(cls.dir, "qemu.log")).read())
                time.sleep(2)
        # prihlasovaci obrazovka (luxwm --greeter na DRM) by zbytecne drzela stejna zarizeni
        cls.vm.gexec("systemctl stop luxos-greetd; mkdir -p /root/t", timeout=60)
        for src, dst in ((os.path.join(BUILD, "luxwm"), "luxwm"), (os.path.join(BUILD, "libluxcomp.so.0"), "libluxcomp.so.0"),
                         (GUEST, "guest.py")):
            h = cls.vm.qga("guest-file-open", {"path": "/root/t/" + dst, "mode": "wb"})
            with open(src, "rb") as f:
                while chunk := f.read(48 * 1024):
                    cls.vm.qga("guest-file-write", {"handle": h, "buf-b64": base64.b64encode(chunk).decode()})
            cls.vm.qga("guest-file-close", {"handle": h})
        rc, out, err = cls.vm.gexec("chmod +x /root/t/luxwm && python3 /root/t/guest.py /root/t", timeout=180)
        if rc != 0:
            raise RuntimeError(f"guest script failed rc={rc}: {err[-3000:]}")
        cls.result = json.loads(out.strip().splitlines()[-1])
        with open(os.path.join(cls.dir, "result.json"), "w") as f:
            json.dump(cls.result, f, indent=1)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "qemu", None) and cls.qemu.poll() is None:
            try:
                cls.vm.qmp("quit")
            except Exception:
                pass
            try:
                cls.qemu.wait(15)
            except subprocess.TimeoutExpired:
                cls.qemu.kill()
                cls.qemu.wait()
        if getattr(cls, "qemu_log", None):
            cls.qemu_log.close()
        if getattr(cls, "dir", None):
            # vysledek a log zustanou pro rozbor, disk ne
            for f in ("disk.qcow2", "qga.sock", "qmp.sock"):
                try:
                    os.unlink(os.path.join(cls.dir, f))
                except FileNotFoundError:
                    pass

    def devices(self, step):
        return self.result[step]["devices"]

    def test_devices_are_real_and_classified(self):
        devs = self.devices("defaults")
        usb = by_name(devs, "QEMU QEMU USB Mouse")
        pad = by_name(devs, "LuxOS Test Touchpad")
        self.assertEqual(len(usb), 1, devs)
        self.assertEqual(usb[0]["kind"], "mouse")
        self.assertEqual(len(pad), 1, devs)
        self.assertEqual(pad[0]["kind"], "touchpad")
        # vychozi hodnoty libinput: bez zmen z luxwm.conf
        self.assertEqual(usb[0]["speed"], 0)
        self.assertEqual(usb[0]["accel"], "adaptive")
        self.assertIs(pad[0]["tap"], False)
        self.assertNotIn("tap", usb[0], "mys klepnuti nema")

    def test_config_applied_to_mice_and_touchpad(self):
        devs = self.devices("configured")
        for mouse in [d for d in devs if d["kind"] == "mouse"]:
            self.assertIs(mouse["natural_scroll"], True, mouse)
            self.assertIs(mouse["left_handed"], True, mouse)
            if "speed" in mouse:
                self.assertEqual(mouse["speed"], -50, mouse)
                self.assertEqual(mouse["accel"], "flat", mouse)
        usb = by_name(devs, "QEMU QEMU USB Mouse")[0]
        self.assertIs(usb["middle_emulation"], True)
        pad = by_name(devs, "LuxOS Test Touchpad")[0]
        self.assertEqual((pad["speed"], pad["accel"]), (30, "adaptive"), "touchpad ma vlastni rychlost, ne mysi")
        self.assertIs(pad["natural_scroll"], True)
        self.assertIs(pad["left_handed"], False, "mouse_left_handed na touchpad nepatri")
        self.assertIs(pad["tap"], True)
        self.assertIs(pad["tap_drag"], False)
        self.assertIs(pad["disable_while_typing"], False)
        self.assertEqual(pad["click_method"], "clickfinger")
        self.assertEqual(pad["scroll_method"], "edge")

    def test_hotplugged_mouse_gets_settings(self):
        extra = by_name(self.devices("hotplug"), "LuxOS Test Mouse")
        self.assertEqual(len(extra), 1)
        self.assertEqual((extra[0]["kind"], extra[0]["speed"], extra[0]["accel"]), ("mouse", -50, "flat"))
        self.assertIs(extra[0]["natural_scroll"], True)
        self.assertIs(extra[0]["left_handed"], True)
        self.assertEqual(by_name(self.devices("configured"), "LuxOS Test Mouse"), [])

    def test_removed_keys_return_device_defaults(self):
        devs = self.devices("reloaded")
        for mouse in [d for d in devs if d["kind"] == "mouse"]:
            self.assertIs(mouse["natural_scroll"], False, mouse)
            self.assertIs(mouse["left_handed"], False, mouse)
            if "speed" in mouse:
                self.assertEqual((mouse["speed"], mouse["accel"]), (20, "adaptive"), mouse)
        pad = by_name(devs, "LuxOS Test Touchpad")[0]
        self.assertEqual(pad["speed"], 0)
        self.assertIs(pad["natural_scroll"], True)
        self.assertIs(pad["tap"], False)
        self.assertIs(pad["tap_drag"], True)
        self.assertIs(pad["disable_while_typing"], True)
        self.assertEqual(pad["click_method"], "areas")
        self.assertEqual(pad["scroll_method"], "two_finger")

    def test_unplugged_device_leaves_list(self):
        self.assertEqual(by_name(self.devices("unplugged"), "LuxOS Test Mouse"), [])
        self.assertEqual(len(by_name(self.devices("unplugged"), "LuxOS Test Touchpad")), 1)
        self.assertNotIn("refused", self.result["log"])


if __name__ == "__main__":
    unittest.main()
