#!/usr/bin/env python3
"""LuxOS installer - kontrola GUI rucniho rozdeleni bez instalace (FAKE, potrebuje displej, napr. Xvfb).

    xvfb-run -a python3 packages/luxos-installer/tests/gui-smoke.py

Postavi okno instalatoru, projde editor (predvolby, upravy modelu, odemceni FAKE LUKS),
souhrn (seznam mazani + potvrzeni) a konfiguraci pro backend: tu prozene
  1) simulovanym backendem (FAKE_BACKEND) az do @@DONE,
  2) skutecnou kontrolou layout.sh (layout_parse + layout_validate) - bez chyb.
"""
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
os.environ["LUXOS_INSTALL_FAKE"] = "1"
os.environ.setdefault("LUXOS_I18N_DIR", I18N)
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)
gui = SourceFileLoader("luxos_install_gui", os.path.join(FILES, "luxos-install-gui")).load_module()
lay = gui.lay
from gi.repository import Gtk  # noqa: E402

FAILS = []


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(desc)


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def bash_validate(cfg):
    """Konfigurace z GUI -> eval v bash -> layout.sh: chyby (prazdne = OK)."""
    script = f'''
set -uo pipefail
. "{FILES}/layout.sh"
T() {{ local f=$1; shift; printf -- "$f" "$@"; }}
eval "$(cat)"
BOOTMODE=${{BOOTMODE:-uefi}} BOOTLOADER=auto
layout_parse "$LAYOUT"; layout_validate
printf '%s\\n' "${{LY_ERR[@]}}"
'''
    r = subprocess.run(["bash", "-c", script], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, BOOTMODE=os.environ.get("BM", "uefi")))
    return r.stdout.strip() + r.stderr.strip()


def main():
    gui.main  # noqa: B018 - modul nacten
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    win = gui.Installer()
    win.s.update({"fullname": "Jana Test", "username": "jana", "pw1": "pw", "pw2": "pw", "hostname": "jana-luxos"})
    pump()
    # Destination -> Manual: krok Partitions se objevi
    win.idx = win.steps.index("disk")
    win.disks = gui.fake_disks()
    win.s["disk"] = "/dev/nvme0n1"
    win.render()
    win.pick_mode("manual")
    pump()
    check("krok Partitions za Destination", win.steps[win.steps.index("disk") + 1] == "partitions")
    win.pick_mode("erase")
    check("bez rucniho rozdeleni krok zmizi", "partitions" not in win.steps)
    win.pick_mode("manual")
    win.idx = win.steps.index("partitions")
    win.layout = lay.Layout(lay.fake_scan())
    win.render()
    pump()
    check("prazdny plan: Continue zablokovano", not win.valid())
    check("duvod: chybi /", "root file system" in win.why(), win.why())

    # Predvolba + heslo
    win.apply_preset("/dev/sdb", "lvm_var")
    win.s["luks1"] = win.s["luks2"] = "tajne"
    win.layout.passphrase = "tajne"
    win.render()
    pump()
    check("predvolba s /var a /tmp je platna", win.valid(), str(win.layout_problems()))
    msgs = [m[1] for m in win.layout_problems()]
    check("predvolba bez varovani", not msgs, str(msgs))

    # Upravy modelu jako z dialogu: odemknout stary LUKS na sdb? (sdb je smazany) -> preset na sda
    L = win.layout
    L.wipe_disk("/dev/sdb", False)
    check("zpet: sdb ma zase puvodni oddily", any(n.dev == "/dev/sdb2" for n in L.of("part")))
    luks = next(n for n in L.of("luks") if n.existing)
    check("stary LUKS na sdb2 je zamceny", luks.locked)
    check("FAKE odemceni spatnym heslem selze", not win.unlock(luks, L.nodes[luks.on], "spatne"))
    check("FAKE odemceni heslem luxos", win.unlock(luks, L.nodes[luks.on], "luxos"))
    pump()
    L = win.layout
    vg = next((n for n in L.of("vg") if n.name == "oldvg"), None)
    check("po odemceni je videt VG oldvg a jeji LV", vg is not None and len(L.lvs_of(vg.id)) == 2)
    # Pouzit stare /home bez formatovani, novy / na nvme volnem miste (sifrovany), ESP Windows v /efi
    home = next(n for n in L.lvs_of(vg.id) if n.name == "home")
    L.set_use(home.id, {"type": "fs", "mount": "/home", "fstype": "ext4", "format": False})
    oldroot = next(n for n in L.lvs_of(vg.id) if n.name == "root")
    L.remove(oldroot.id)
    esp = next(n for n in L.of("part") if n.dev == "/dev/nvme0n1p1")
    L.set_use(esp.id, {"type": "fs", "mount": "/efi", "fstype": "vfat", "format": False})
    r = L.add_part("/dev/nvme0n1", 60 * lay.GiB)
    cr = L.encrypt(r.id)
    L.set_use(cr.id, {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True})
    sw = L.add_part("/dev/nvme0n1", 4 * lay.GiB)
    cs = L.encrypt(sw.id)
    cs.use = {"type": "swap", "format": True}
    win.render()
    pump()
    probs = win.layout_problems()
    check("smiseny plan (Windows + stary sifrovany /home) je platny", win.valid(), str(probs))
    destroy = [t % a for t, a in L.destroy_list()]
    check("seznam mazani: stary LV root", any("oldvg/root" in d for d in destroy), str(destroy))
    check("seznam mazani: nic z Windows", not any("nvme0n1p3" in d or "nvme0n1p1" in d for d in destroy), str(destroy))

    # Souhrn: potvrzeni smazani je povinne
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    check("souhrn: bez potvrzeni nelze instalovat", not win.valid())
    win.s["layout_ok"] = True
    win.render()
    pump()
    check("souhrn: po potvrzeni lze instalovat", win.valid())

    cfg = win.build_config()
    check("konfigurace: DISK_MODE=layout", "DISK_MODE=layout" in cfg)
    check("konfigurace: hesla nejsou v LAYOUT", "tajne" not in cfg.split("LAYOUT=")[1].split("\n\n")[0].split("LUKS_PASS")[0])
    check("konfigurace: heslo stareho LUKS zvlast", "LUKS_PASS_C_SDB2=luxos" in cfg, cfg)
    errs = bash_validate(cfg)
    check("backend (layout.sh) prijme rozlozeni bez chyb", errs == "", errs)
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0"))
    check("FAKE backend dobehne (@@DONE)", "@@DONE" in r.stdout, r.stdout[-500:] + r.stderr[-500:])
    steps = [ln.split(" ", 3)[3] for ln in r.stdout.splitlines() if ln.startswith("@@STEP")]
    check("FAKE kroky rucniho rozdeleni", steps[:4] == ["Preparing disks", "Encrypting volumes", "Setting up LVM",
                                                       "Creating file systems"], str(steps))
    check("heslo neni ve vystupu", "tajne" not in r.stdout)

    # Regrese: rezim "smazat disk" beze zmeny (bez LAYOUT, puvodni kroky)
    win.s.update({"mode": "erase", "disk": "/dev/nvme0n1", "encrypt": True, "luks1": "k", "luks2": "k"})
    cfg = win.build_config()
    check("erase: bez LAYOUT, DISK_MODE=erase, ENCRYPT=1", "\nLAYOUT=" not in cfg and "DISK_MODE=erase" in cfg
          and "ENCRYPT=1" in cfg, cfg)
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0"))
    steps = [ln.split(" ", 3)[3] for ln in r.stdout.splitlines() if ln.startswith("@@STEP")]
    check("erase: puvodni kroky", steps[:3] == ["Preparing disk /dev/nvme0n1", "Encrypting the disk",
                                                "Creating file systems"] and "@@DONE" in r.stdout, str(steps))
    win.s["mode"] = "freespace"
    check("freespace: DISK_MODE=freespace", "DISK_MODE=freespace" in win.build_config())

    # Regrese z VM: predvolba na 24 GiB disku je platna, puvodni plan (30 GiB LV ve ~23 GiB VG) GUI zablokuje
    small = {"bootmode": "uefi", "vgs": [], "disks": [{"path": "/dev/vdx", "name": "vdx", "size": 24 * lay.GiB,
                                                       "parts": [], "model": "small", "pttype": ""}]}
    win.s["mode"] = "manual"
    win.idx = win.steps.index("partitions")
    win.layout = lay.Layout(small)
    win.s["luks1"] = win.s["luks2"] = "tajne"
    win.layout.passphrase = "tajne"
    win.apply_preset("/dev/vdx", "lvm_var")
    pump()
    win.render()
    pump()
    check("24 GiB: predvolba s /var a /tmp je platna", win.valid(), str(win.layout_problems()))
    for lv, sz in zip(sorted(win.layout.of("lv"), key=lambda n: n.id), (16, 8, 4, 2)):
        lv.size = sz * lay.GiB
    win.render()
    pump()
    check("24 GiB: puvodni chybny plan GUI zablokuje (vg_full)",
          not win.valid() and any(p[1] == "vg_full" for p in win.layout_problems()), str(win.layout_problems()))
    # Prilis maly disk: hlaska a plan beze zmeny (dialog se v testu jen zaznamena)
    shown = []
    orig_run = Gtk.MessageDialog.run
    Gtk.MessageDialog.run = lambda dlg: shown.append(dlg.get_property("text")) or Gtk.ResponseType.OK
    tiny = dict(small, disks=[dict(small["disks"][0], size=12 * lay.GiB)])
    win.layout = lay.Layout(tiny)
    before = set(win.layout.nodes)
    win.apply_preset("/dev/vdx", "lvm_var")
    Gtk.MessageDialog.run = orig_run
    check("12 GiB: predvolba ukaze hlasku o malem disku", shown and "too small" in shown[0], str(shown))
    check("12 GiB: plan zustal beze zmeny", set(win.layout.nodes) == before and not win.layout.disk_node("/dev/vdx").wipe)

    # BIOS: predvolba vytvori BIOS boot + /boot ext4
    os.environ["BM"] = "bios"
    L2 = lay.Layout(lay.fake_scan("bios"))
    L2.preset("/dev/sda", "lvm")
    L2.passphrase = "x"
    check("BIOS predvolba platna", not [p for p in L2.validate() if p[0] == "error"], str(L2.validate()))
    errs = bash_validate("".join(f"{k}={gui.shlex.quote(v)}\n" for k, v in L2.config_values().items()))
    check("BIOS predvolba: backend bez chyb", errs == "", errs)
    win.destroy()
    print(f"\nVysledek: {len(FAILS)} FAIL")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
