#!/usr/bin/env python3
"""LuxOS installer - GUI bezpecneho smazani (WIPE) bez instalace (FAKE, jen virtualni displej).

    env -u DISPLAY xvfb-run -a python3 packages/luxos-installer/tests/gui-wipe.py

Souhrn: karta "Erase securely first" ve vsech rezimech disku (odhad casu podle velikosti a typu disku,
doporuceni se sifrovanim), konfigurace pro backend (WIPE, WIPE_CANCEL_FILE) a simulovana instalace
(FAKE_BACKEND): krok mazani, tlacitko "Skip Erasing" -> backend preskoci zbytek a instalace dobehne.
"""
import os
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader

if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
os.environ["LUXOS_INSTALL_FAKE"] = "1"
os.environ["LUXOS_INSTALL_FAKE_DELAY"] = "0.15"
os.environ["LUXOS_INSTALL_FAKE_WIPE_CHUNKS"] = "200"
os.environ.setdefault("LUXOS_I18N_DIR", I18N)
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)
gui = SourceFileLoader("luxos_install_gui", os.path.join(FILES, "luxos-install-gui")).load_module()
lay = gui.lay
from gi.repository import GLib, Gtk  # noqa: E402

FAILS = []


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(desc)


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


def labels(win):
    return [x.get_text() for x in walk(win.scroll) if isinstance(x, Gtk.Label)]


def wipe_switch(win):
    """Prepinac v karte mazani (karta = Box s titulkem "Erase securely first (slow)")."""
    for w in walk(win.scroll):
        if isinstance(w, Gtk.Box) and any(isinstance(x, Gtk.Label) and x.get_text() == gui._("Erase securely first (slow)")
                                          for x in walk(w)):
            sws = [x for x in walk(w) if isinstance(x, Gtk.Switch)]
            if len(sws) == 1:
                return sws[0]
    return None


def summary(win, **state):
    win.s.update(state)
    win.idx = win.steps.index("summary")
    win.render()
    pump()


def cfg_dict(cfg):
    out = subprocess.run(["bash", "-c", 'eval "$(cat)"; printf "%s\\n%s\\n" "$WIPE" "$WIPE_CANCEL_FILE"'],
                         input=cfg, capture_output=True, text=True).stdout.split("\n")
    return {"WIPE": out[0], "WIPE_CANCEL_FILE": out[1]}


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    win = gui.Installer()
    win.s.update({"fullname": "Jana Test", "username": "jana", "pw1": "pw", "pw2": "pw", "hostname": "jana-luxos"})
    win.disks = gui.fake_disks()
    pump()

    # --- erase, NVMe 512 GB
    summary(win, mode="erase", disk="/dev/nvme0n1", erase_ok=True)
    sw = wipe_switch(win)
    check("erase: karta mazani se prepinacem", sw is not None)
    check("erase: vychozi vypnuto", sw is not None and not sw.get_active() and not win.s["wipe"])
    texts = labels(win)
    check("erase: velikost oblasti (512 GB)", any("(%s)" % gui.size_text(512 * 1000 ** 3) in t for t in texts), str(texts[-6:]))
    check("erase NVMe: odhad ~6 min", any("This can take long: about 6 min" in t for t in texts), str(texts[-6:]))
    check("bez sifrovani: bez doporuceni", not any("Recommended with encryption" in t for t in texts))
    c = cfg_dict(win.build_config())
    check("vypnuto: WIPE=none a bez souboru", c == {"WIPE": "none", "WIPE_CANCEL_FILE": ""}, str(c))
    sw.set_active(True)
    pump()
    check("prepinac -> stav wipe", win.s["wipe"])
    c = cfg_dict(win.build_config())
    check("zapnuto: WIPE=zero + soubor pro preskoceni", c["WIPE"] == "zero" and c["WIPE_CANCEL_FILE"].endswith("/skip-wipe")
          and os.path.isdir(os.path.dirname(c["WIPE_CANCEL_FILE"])), str(c))
    check("soubor zatim neexistuje", not os.path.exists(c["WIPE_CANCEL_FILE"]))
    check("adresar jen pro uzivatele (700)", oct(os.stat(os.path.dirname(c["WIPE_CANCEL_FILE"])).st_mode & 0o777) == "0o700")
    summary(win)
    check("volba zustava po prekresleni", wipe_switch(win).get_active())

    # --- erase, HDD 1 TB, sifrovani
    summary(win, disk="/dev/sda", encrypt=True, luks1="k", luks2="k")
    texts = labels(win)
    check("erase HDD 1 TB: odhad ~2 h 8 min", any("about 2 h 8 min" in t for t in texts), str(texts[-6:]))
    check("sifrovani: doporuceni", any("Recommended with encryption" in t for t in texts))

    # --- vedle jinych systemu a existujici oddil
    summary(win, mode="freespace", disk="/dev/nvme0n1", encrypt=False)
    check("freespace: jen volne misto (260.5 GB)", any("(%s)" % gui.size_text(int(260.5 * 1000 ** 3)) in t for t in labels(win)))
    summary(win, mode="partition", part="/dev/nvme0n1p3", home_part=None)
    check("partition: jen vybrany oddil (250.0 GB)", any("(%s)" % gui.size_text(250 * 1000 ** 3) in t for t in labels(win)))
    check("partition: plan = vybrany oddil", win.wipe_plan() == [(win.selected_disk(), 250 * 1000 ** 3)])

    # --- rucni rozdeleni: stejne cile jako model (nove oddily)
    win.s["mode"] = "manual"
    win.layout = lay.Layout(lay.fake_scan())
    win.apply_preset("/dev/sdb", "lvm")
    win.layout.passphrase = "x"
    summary(win, layout_ok=True)
    total, _sec = win.wipe_estimate()
    want = sum(b for _n, b in win.layout.wipe_targets())
    check("manual: soucet = wipe_targets modelu", total == want and total > 0, f"{total} vs {want}")
    check("manual: sifrovana predvolba -> doporuceni", any("Recommended with encryption" in t for t in labels(win)))
    check("manual: karta mazani", wipe_switch(win) is not None)

    # --- FAKE backend primo: krok mazani na 2. miste, bez WIPE beze zmen
    for wipe, want in (("none", None), ("zero", "Erasing the space for LuxOS")):
        win.s.update({"mode": "erase", "disk": "/dev/nvme0n1", "encrypt": False, "wipe": wipe == "zero"})
        r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=win.build_config(), capture_output=True, text=True,
                           env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0", LUXOS_INSTALL_FAKE_WIPE_CHUNKS="5"))
        steps = [ln.split(" ", 3)[3] for ln in r.stdout.splitlines() if ln.startswith("@@STEP")]
        if want:
            check("FAKE: krok mazani hned po rozdeleni", steps[1] == want and "@@WIPE START" in r.stdout
                  and "@@WIPE END" in r.stdout and "@@DONE" in r.stdout, str(steps))
        else:
            check("FAKE: bez WIPE puvodni kroky", want not in steps and "@@WIPE" not in r.stdout
                  and steps[:2] == ["Preparing disk /dev/nvme0n1", "Creating file systems"], str(steps))

    # --- simulovana instalace s preskocenim
    win.s.update({"mode": "erase", "disk": "/dev/nvme0n1", "encrypt": False, "wipe": True, "templates": []})
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    win.go_next()
    pump(0.2)
    check("instalace bezi", win.installing and win.current() == "install")
    end = time.monotonic() + 20
    while not win.wipe_box.get_visible() and time.monotonic() < end:
        pump(0.05)
    check("behem mazani: tlacitko Skip Erasing", win.wipe_box.get_visible() and win.wipe_btn.get_sensitive())
    check("behem mazani: krok 2 ma vahu podle odhadu", win.step_n == 2 and win.wipe_weight >= 4
          and win.step_range()[1] - win.step_range()[0] > 0.04, str((win.step_n, win.wipe_weight, win.step_range())))
    pump(1.0)
    shown = win.shown
    check("pruh se behem mazani hybe podle @@PCT", shown > win.step_range()[0], str((shown, win.step_range())))
    skip_file = win.wipe_cancel_file()
    win.wipe_btn.clicked()
    pump()
    check("klik: soubor vytvoren, tlacitko neaktivni", os.path.exists(skip_file) and not win.wipe_btn.get_sensitive())
    while win.wipe_box.get_visible() and time.monotonic() < end:
        pump(0.05)
    check("backend preskocil zbytek (@@WIPE END)", not win.wipe_box.get_visible())
    check("hlaska o preskoceni", "Erasing was skipped" in win.status_label.get_text(), win.status_label.get_text())
    log = "\n".join(win.lines)
    check("mazani nedobehlo vsechny kusy", "@@PCT 100" not in log)
    end = time.monotonic() + 60
    while win.installing and time.monotonic() < end:
        pump(0.05)
    check("instalace dobehla uspesne", win.result == ("ok",), str(win.result))
    check("docasny adresar smazan", not os.path.exists(os.path.dirname(skip_file)))

    win.destroy()
    pump()
    print()
    print("Vysledek:", "OK" if not FAILS else f"{len(FAILS)} FAIL")
    return 1 if FAILS else 0


if __name__ == "__main__":
    GLib.set_prgname("luxos-install-gui-test")
    sys.exit(main())
