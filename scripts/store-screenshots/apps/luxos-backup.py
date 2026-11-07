"""Zalohy: prehled (disky, volby), obnova souboru podle casu a pridani disku.

Ukazkove zalohy ukazkove domovske slozky na "disk" v docasne slozce (_c_backup.py); zadne skutecne disky,
udisks, klicenka ani oznameni.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def shots(s):
    disk = os.path.join(s.tmp, "disk")
    home = os.path.join(s.tmp, "anna")
    os.makedirs(disk)
    os.makedirs(home)
    ctl = os.path.join(s.tmp, "backup-ctl")
    open(ctl, "w").close()
    s.python_env("luxos-backup/files")
    env = {"DEMO_DISK": disk, "DEMO_CTL": ctl, "LUXOS_BACKUP_HOME": home, "LUXOS_BACKUP_HOST": "annas-laptop",
           "LUXOS_BACKUP_ENGINE": "python", "LUXOS_BACKUP_NO_NOTIFY": "1"}
    s.launch([sys.executable, os.path.join(HERE, "_c_backup.py"), s.src("luxos-backup/files/luxos-backup-gui")],
             env=env)
    win = s.window(name="^Backups$", size=(820, 752), timeout=60)
    s.capture("1", win)

    def cmd(c, wait=1.5):
        with open(ctl, "a") as f:
            f.write(c + "\n")
        s.sleep(wait)
    cmd("browser", 2.5)
    cmd("docs", 1.0)
    s.capture("2", win)
    cmd("main")
    cmd("adddisk")
    dlg = s.window(name="Add Backup Disk", size=None, place=False)
    s.capture("3", dlg)
