#!/usr/bin/env python3
"""Poradi disku v pruvodci instalaci (U-14): vychozi cil je prvni disk. Drive vyhraval USB flash disk (sda pred
nvme0n1). Ted: vnitrni pred USB/vymenitelnymi, SSD/NVMe pred HDD, pak nejvetsi; u USB jen velikost.
Spusteni: python3 packages/luxos-installer/tests/test_disk_order.py"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
import luxos_layout as lay  # noqa: E402

GB = 1000 ** 3


def dev(name, size_gb, tran, rm=False, rota=False, ro=False, typ="disk", model=""):
    # tvar jako lsblk -J (novejsi lsblk: bool, starsi: "0"/"1" - obe se musi zvladnout)
    return {"name": name, "path": "/dev/" + name, "size": size_gb * GB, "type": typ, "ro": ro, "rm": rm,
            "rota": rota, "tran": tran, "model": model, "children": []}


MACHINE = [
    dev("sda", 64, "usb", rm=True, model="SanDisk Ultra"),
    dev("sdb", 2000, "sata", rota=True, model="WDC WD20EZRZ"),
    dev("sdc", 256, "sata", model="Crucial MX500"),
    dev("sdd", 32, "usb", model="Ventoy USB"),            # instalacni medium
    dev("sde", 8, "sata", model="Tiny"),                  # pod 20 GB
    dev("sdf", 500, "usb", rota=True, model="External HDD"),
    dev("nvme0n1", 512, "nvme", model="Samsung SSD 980 PRO"),
    dev("mmcblk0", 64, None),                             # interni eMMC (levne notebooky)
    dev("zram0", 40, None),
    dev("sr0", 1, "sata", rm=True, rota=True, ro=True, typ="rom"),
]
EXPECTED = ["/dev/nvme0n1", "/dev/sdc", "/dev/mmcblk0", "/dev/sdb", "/dev/sdf", "/dev/sda"]


def gui_list_disks(devices, iso="sdd"):
    """list_disks z luxos-install-gui s napodobenym lsblk/findmnt (bez GTK a bez roota)."""
    with open(os.path.join(FILES, "luxos-install-gui"), encoding="utf-8") as f:
        src = f.read()
    ns = {"os": os, "json": json, "lay": lay, "FAKE": False, "MIN_DISK": 20 * GB}

    def cmd_out(*cmd, timeout=20):
        if cmd[0] == "findmnt":
            return "/dev/" + iso + "1" if iso else ""
        if cmd[:2] == ("lsblk", "-nsro"):
            return f"{iso}1 part\n{iso} disk"
        if cmd[:2] == ("lsblk", "-J"):
            assert "RM" in cmd[-1].split(",") and "ROTA" in cmd[-1].split(","), cmd
            return json.dumps({"blockdevices": devices})
        raise AssertionError(cmd)
    ns["cmd_out"] = cmd_out
    exec(src[src.index("def iso_disk():"):src.index("def probe_disk(")], ns)
    return ns["list_disks"]()


class DiskOrder(unittest.TestCase):
    def test_gui_default_is_internal_nvme_not_usb(self):
        disks = gui_list_disks(MACHINE)
        self.assertEqual(disks[0]["path"], "/dev/nvme0n1")
        self.assertEqual([d["path"] for d in disks], EXPECTED)

    def test_gui_old_lsblk_strings(self):
        old = [dict(d, rm="1" if d["rm"] else "0", rota="1" if d["rota"] else "0", ro="1" if d["ro"] else "0")
               for d in MACHINE]
        self.assertEqual([d["path"] for d in gui_list_disks(old)], EXPECTED)

    def test_only_usb_disks_still_offered_biggest_first(self):
        disks = gui_list_disks([d for d in MACHINE if d["name"] in ("sda", "sdf")], iso="")
        self.assertEqual([d["path"] for d in disks], ["/dev/sdf", "/dev/sda"])

    def test_ssd_before_bigger_hdd(self):
        disks = gui_list_disks([dev("sda", 4000, "sata", rota=True), dev("sdb", 240, "sata")], iso="")
        self.assertEqual(disks[0]["path"], "/dev/sdb")

    def test_vm_virtio_disk(self):
        disks = gui_list_disks([dev("vda", 40, None, rota=True), dev("sdb", 32, "usb", rm=True)], iso="")
        self.assertEqual(disks[0]["path"], "/dev/vda")

    def test_key_is_stable_for_equal_disks(self):
        a = {"path": "/dev/sdb", "size": 500 * GB, "tran": "sata"}
        b = {"path": "/dev/sda", "size": 500 * GB, "tran": "sata"}
        self.assertEqual(sorted([a, b], key=lay.disk_order_key)[0]["path"], "/dev/sda")

    def test_manual_layout_scan_same_order(self):
        saved = (lay._run, lay._sys_int)

        def run(cmd):
            if cmd[0] == "lsblk" and cmd[1] == "-J":
                return json.dumps({"blockdevices": MACHINE})
            if cmd[0] == "findmnt":
                return "/dev/sdd1"
            if cmd[:2] == ["lsblk", "-no"]:
                return "sdd"
            return ""
        lay._run, lay._sys_int = run, lambda *a: 0
        try:
            result = lay.scan_system(minsizes=False)
        finally:
            lay._run, lay._sys_int = saved
        disks = result["disks"] if isinstance(result, dict) else result[0]
        paths = [d["path"] for d in disks]
        self.assertEqual(paths[0], "/dev/nvme0n1")
        self.assertLess(paths.index("/dev/sdb"), paths.index("/dev/sda"))


if __name__ == "__main__":
    unittest.main()
