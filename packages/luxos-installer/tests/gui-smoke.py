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
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

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


def walk(w):
    """Vsechny widgety pod w (vcetne w)."""
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


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
    # Dual boot do existujici sifrovane VG (jako Debian): novy LV pro / -> VG s pvs (sd-encrypt + rd.luks)
    trial = L.add_lv(vg.id, "luxos", 0, True)
    L.set_use(trial.id, {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True})
    txt = L.to_text()
    vgline = next((ln for ln in txt.splitlines() if ln.startswith("vg ") and "name=oldvg" in ln), "")
    check("existujici VG pod novym / ma pvs (LUKS)", "keep=1" in vgline and f"pvs={luks.id}" in vgline, vgline)
    L.remove(trial.id)
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

    # Existujici oddil (DISK_MODE=partition): vyber oddilu, duvody, /home, souhrn, konfigurace
    out = ("FREESPACE_ERR=no_space\nPART_BOOT_ERR=\nPART_ESP=/dev/vda1\n"
           "PART=/dev/vda1\t536870912\tvfat\tEFI\tesp\tesp\t\t\n"
           "PART=/dev/vda2\t64424509440\text4\t\t\t\tos\tUbuntu 24.04.1 LTS\n")
    pr = gui.parse_probe(out)
    check("parse_probe: radky PART v PARTS", [p["dev"] for p in pr["PARTS"]] == ["/dev/vda1", "/dev/vda2"]
          and pr["PARTS"][1]["name"] == "Ubuntu 24.04.1 LTS" and pr["PARTS"][0]["root_err"] == "esp"
          and pr["PART_ESP"] == "/dev/vda1", str(pr))
    win.s.update({"mode": None, "disk": "/dev/nvme0n1", "encrypt": False, "luks1": "", "luks2": "",
                  "layout_ok": False, "part": None, "home_part": None})
    win.layout = None
    win.disks = gui.fake_disks()
    win.idx = win.steps.index("disk")
    win.render()
    win.pick_mode("partition")
    pump()
    check("partition: bez kroku Partitions", "partitions" not in win.steps)
    check("partition: bez vyberu nelze pokracovat", not win.valid() and "Choose a partition" in win.why(), win.why())
    radios = {}
    for w in walk(win.scroll):
        if isinstance(w, Gtk.RadioButton) and w.get_child():
            texts = [x.get_text() for x in walk(w) if isinstance(x, Gtk.Label)]
            radios[texts[0].split()[0]] = (w, texts)
    check("partition: vsechny 4 oddily v seznamu", sorted(radios) == ["/dev/nvme0n1p%d" % i for i in range(1, 5)],
          str(sorted(radios)))
    check("partition: ESP nelze vybrat (duvod)", not radios["/dev/nvme0n1p1"][0].get_sensitive()
          and "Not available: EFI system partition" in radios["/dev/nvme0n1p1"][1])
    check("partition: MSR/recovery nelze vybrat", not radios["/dev/nvme0n1p2"][0].get_sensitive()
          and not radios["/dev/nvme0n1p4"][0].get_sensitive())
    check("partition: Windows lze vybrat, obsah popsan", radios["/dev/nvme0n1p3"][0].get_sensitive()
          and "Operating system: Windows" in radios["/dev/nvme0n1p3"][1])
    radios["/dev/nvme0n1p3"][0].set_active(True)
    pump()
    labels = [x.get_text() for x in walk(win.scroll) if isinstance(x, Gtk.Label)]
    check("partition: vybran oddil a lze pokracovat", win.s["part"] == "/dev/nvme0n1p3" and win.valid())
    check("partition: silne varovani o Windows", any("contains Windows" in t for t in labels))
    check("partition: hlaska o sdilenem ESP", any("/dev/nvme0n1p1 is shared" in t for t in labels))
    combo = next(w for w in walk(win.scroll) if isinstance(w, Gtk.ComboBoxText))
    ids = [r[1] for r in combo.get_model()]
    check("partition: /home kandidati z obou disku (ext4)", ids == ["", "/dev/sda1", "/dev/sda2"], str(ids))
    combo.set_active_id("/dev/sda2")
    check("partition: /home zvolen", win.s["home_part"] == "/dev/sda2" and win.valid())
    win.s["encrypt"] = True
    check("partition: sifrovani bez hesla blokuje", not win.valid())
    win.s["luks1"] = win.s["luks2"] = "tajne"
    check("partition: sifrovani s heslem OK", win.valid())
    # souhrn: potvrzeni smazani, obsah a varovani
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    labels = [x.get_text() for x in walk(win.scroll) if isinstance(x, Gtk.Label)]
    check("partition souhrn: bez potvrzeni nelze instalovat", not win.valid())
    check("partition souhrn: co se smaze vcetne obsahu",
          any("ERASE partition /dev/nvme0n1p3" in t and "Operating system: Windows" in t for t in labels), str(labels))
    check("partition souhrn: silne varovani", any("WARNING: /dev/nvme0n1p3 contains Windows" in t for t in labels))
    check("partition souhrn: /home a /efi bez formatovani", "/home" in labels and "/efi" in labels
          and labels.count("keep data") == 2, str(labels))
    check("partition souhrn: cervene tlacitko Install", win.btn_next.get_style_context().has_class("danger-btn"))
    win.s["layout_ok"] = True
    win.render()
    pump()
    check("partition souhrn: po potvrzeni lze instalovat", win.valid())
    cfg = win.build_config()
    check("partition: konfigurace", all(x in cfg for x in ("DISK_MODE=partition", "ROOT_PART=/dev/nvme0n1p3",
                                                            "HOME_PART=/dev/sda2", "ENCRYPT=1")), cfg)
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0"))
    steps = [ln.split(" ", 3)[3] for ln in r.stdout.splitlines() if ln.startswith("@@STEP")]
    check("partition: FAKE kroky jako backend (layout.sh)", steps[:3] == ["Preparing disks", "Encrypting volumes",
                                                                          "Creating file systems"]
          and "@@DONE" in r.stdout, str(steps))
    # bez EFI oddilu: vysvetleni, nelze pokracovat
    win.idx = win.steps.index("disk")
    win.disks[0]["probe"] = dict(win.disks[0]["probe"], PART_BOOT_ERR="no_esp")
    win.s["layout_ok"] = False
    win.render()
    pump()
    labels = [x.get_text() for x in walk(win.scroll) if isinstance(x, Gtk.Label)]
    check("partition: bez ESP nelze pokracovat", not win.valid() and "No EFI system partition" in win.why(), win.why())
    check("partition: bez ESP vysvetleni na strance", any("No EFI system partition found" in t for t in labels))
    win.disks = gui.fake_disks()
    win.s.update({"mode": "manual", "part": None, "home_part": None})
    win.sync_steps()   # dalsi testy pokracuji v rucnim rozdeleni

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
