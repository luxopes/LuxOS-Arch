#!/usr/bin/env python3
"""Zalohy pro snimky Obchodu: ukazkove zalohy na "disk" v docasne slozce, pak okno ze zdroju.

Spousti postup luxos-backup.py. Zadne skutecne disky: zjistovani disku (findmnt/lsblk/udisks), klicenka
a oznameni jsou nahrazene, zalohuje se ukazkova domovska slozka ($LUXOS_BACKUP_HOME) do slozky
$DEMO_DISK vestavenym enginem v Pythonu. Ovladani: soubor $DEMO_CTL (radek = prikaz: browser, adddisk).

    _c_backup.py BACKUP_GUI_PATH
"""
import importlib.machinery
import importlib.util
import os
import sys
import time as _time

import luxos_backup as core

DISK = os.environ["DEMO_DISK"]
HOME = os.environ["LUXOS_BACKUP_HOME"]

# --- nic skutecneho: disky, klicenka, oznameni ---------------------------------
core.fs_uuid = lambda path: (None, None)
core.fs_type = lambda path: "ext4"
core.secret_clear = lambda *a, **k: None
core.lsblk = lambda: []
core.external_disks = lambda: [
    {"path": "/dev/sdb1", "uuid": "demo-1", "fstype": "exfat", "inner_uuid": None, "inner_fstype": None,
     "label": "SanDisk Extreme", "size": 1_000_204_886_016, "model": "SanDisk Extreme 55AE", "mount": None,
     "drive": "/dev/sdb", "encrypted": False}]


class FakeTime:
    """Modul time s posunutym "ted" (zalohy z minulych dnu)."""

    def __init__(self, at):
        self.at = at

    def time(self):
        return self.at

    def __getattr__(self, name):
        return getattr(_time, name)


def write(rel, size, mtime):
    path = os.path.join(HOME, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(min(size, 4096)) * max(1, size // 4096))
    os.utime(path, (mtime, mtime))


def make_backups():
    now = _time.time()
    day = 86400
    files = [
        ("Documents/Budget 2027.ods", 48_000, 9), ("Documents/Thesis draft.odt", 312_000, 6),
        ("Documents/Insurance contract.pdf", 1_240_000, 20), ("Documents/Recipes/Grandma's apple pie.txt", 3_000, 30),
        ("Pictures/Summer 2026/IMG_3104.jpg", 2_400_000, 40), ("Pictures/Summer 2026/IMG_3105.jpg", 2_150_000, 40),
        ("Pictures/Family/Christmas.jpg", 1_800_000, 300), ("Music/Playlist.m3u", 2_000, 60),
        ("Desktop/Ideas.txt", 1_200, 2), ("Videos/Birthday.mp4", 3_800_000, 90),
        ("Projects/website/index.html", 9_000, 4), ("Downloads/Train tickets.pdf", 180_000, 3),
    ]
    for rel, size, ago in files:
        write(rel, size, now - ago * day)
    # slozky s realistickym casem zmeny (podle nejnovejsiho souboru)
    for top, dirs, names in os.walk(HOME, topdown=False):
        if top != HOME:
            newest = max(os.path.getmtime(os.path.join(top, n)) for n in names + dirs)
            os.utime(top, (newest, newest))
    cfg = core.load_config()
    disk = core.add_local_disk(cfg, DISK, "Backup Drive")
    cfg = core.load_config()
    for d in cfg["disks"]:
        if d["id"] == disk["id"]:
            d["encrypted"] = True          # jen pro zobrazeni (stitek "Sifrovano")
    cfg["disks"].append({"id": "nas", "kind": "sftp", "name": "nas.local:/volume1/backup", "host": "nas.local",
                         "user": "anna", "path": "/volume1/backup", "machine": core.machine_name(),
                         "added": core.snap_name()})
    cfg["excludes"] = [os.path.join(HOME, "Videos/Raw footage")]
    real = cfg["disks"][:1]
    core.save_config(dict(cfg, disks=real))
    for ago in (6 * day + 5000, 4 * day + 9000, 2 * day + 3000, day + 30000, day + 7200,
                5 * 3600, 3 * 3600, 1500):
        core.time = FakeTime(now - ago)
        if ago == day + 7200:
            write("Documents/Thesis draft.odt", 330_000, now - ago - 600)
        if ago == 3 * 3600:
            write("Desktop/Ideas.txt", 1_500, now - ago - 300)
        core.run_backup(manual=True, log=lambda *a: None)
    core.time = _time
    core.save_config(cfg)
    st = core.load_status()
    last = st.get("last_by_disk") or {}
    last["nas"] = now - day - 7200
    core.update_status(last_by_disk=last)


def main():
    make_backups()
    path = sys.argv[1]
    loader = importlib.machinery.SourceFileLoader("luxos_backup_gui", path)
    spec = importlib.util.spec_from_loader("luxos_backup_gui", loader)
    gui = importlib.util.module_from_spec(spec)
    loader.exec_module(gui)
    gui.core = core
    Gtk, GLib = gui.Gtk, gui.GLib
    state = {"pos": 0}

    def win():
        return [w for w in Gtk.Window.list_toplevels() if isinstance(w, gui.BackupWindow)][0]

    def poll():
        try:
            with open(os.environ["DEMO_CTL"], encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        for cmd in lines[state["pos"]:]:
            if cmd == "browser":
                win().show_browser()
            elif cmd == "docs":
                b = win().browser
                b.go("Documents")
                b.view.get_selection().select_path(Gtk.TreePath(2))
            elif cmd == "main":
                win().show_main()
            elif cmd == "adddisk":
                gui.AddDiskDialog(win(), preselect="/dev/sdb1").present()
        state["pos"] = len(lines)
        return True
    GLib.timeout_add(200, poll)
    gui.main([])


if __name__ == "__main__":
    main()
