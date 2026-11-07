"""Ovladace: rozpoznany hardware a stav ovladacu, instalace doporucenych ovladacu (prubeh).

Ukazkovy notebook (AMD Ryzen + Radeon, NVIDIA GeForce GTX 1650, ctecka otisku prstu) jako falesny /sys a
/proc pro luxos-hwdetect ze zdroju; falesna databaze baliku; pkexec a pomocnik jsou nahrazene (_c_drivers.py).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PCI_IDS = """1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t1638  Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]
10de  NVIDIA Corporation
\t1f99  TU117M [GeForce GTX 1650 Mobile / Max-Q]
"""
INSTALLED = ("linux-luxos-7.2.13-1", "mesa-1:25.2.6-1", "vulkan-radeon-1:25.2.6-1", "amd-ucode-20251021-1")


def fake_root(root):
    def put(rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    for slot, cls, vendor, dev in (("0000:05:00.0", "030000", "1002", "1638"),
                                   ("0000:01:00.0", "030200", "10de", "1f99")):
        for k, v in (("class", cls), ("vendor", vendor), ("device", dev)):
            put(f"sys/bus/pci/devices/{slot}/{k}", f"0x{v}\n")
    put("sys/bus/usb/devices/3-3/idVendor", "06cb\n")          # ctecka otisku prstu (Synaptics)
    put("sys/bus/usb/devices/3-3/idProduct", "00bd\n")
    put("sys/class/power_supply/BAT0/type", "Battery\n")
    put("sys/module/amdgpu/refcnt", "1\n")
    put("proc/cpuinfo", "processor\t: 0\nvendor_id\t: AuthenticAMD\nmodel name\t: AMD Ryzen 5 5500U\n")
    put("usr/lib/modules/7.2.13-1-luxos/pkgbase", "linux-luxos\n")
    put("usr/share/hwdata/pci.ids", PCI_IDS)
    for p in INSTALLED:
        os.makedirs(os.path.join(root, "var/lib/lux/local", p), exist_ok=True)


def shots(s):
    root = os.path.join(s.tmp, "hw")
    fake_root(root)
    s.python_env("luxos-drivers")
    gui = s.src("luxos-drivers/luxos-drivers")
    helper = os.path.join(HERE, "_c_drivers.py")
    env = {"LUXOS_HW_ROOT": root, "LUXOS_HW_DATA": s.src("luxos-drivers"), "LUXOS_HW_VIRT": "none",
           "LUXOS_HW_DRIVERS_MAP": os.path.join(root, "none.tsv"),
           "DEMO_HWDETECT": s.src("luxos-drivers/luxos-hwdetect")}
    p = s.launch([sys.executable, helper, "gui", gui, "list"], env=env)
    win = s.window(pid=p.pid, size=(700, 540))
    s.sleep(1.5)
    s.capture("1", win)
    s.stop()
    p = s.launch([sys.executable, helper, "gui", gui, "install"], env=env)
    win = s.window(pid=p.pid, size=(700, 540))
    s.sleep(3.0)
    s.capture("2", win)
