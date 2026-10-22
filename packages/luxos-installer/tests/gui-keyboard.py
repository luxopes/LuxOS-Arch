#!/usr/bin/env python3
"""LuxOS installer - krok Klavesnice v GUI: vice rozlozeni, vychozi, prepinani a konfigurace pro backend.

    env -u DISPLAY xvfb-run -a python3 packages/luxos-installer/tests/gui-keyboard.py

Bez instalace (FAKE); setxkbmap je napodoba v PATH (zapisuje volani do souboru). Konfiguraci z GUI
nakonec projde skutecny xkb_normalize z luxos-install a cast setup-chroot.sh do docasneho adresare.
"""
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
TMP = tempfile.mkdtemp(prefix="luxos-gui-kbd-")
LOG = os.path.join(TMP, "setxkbmap.log")
os.makedirs(os.path.join(TMP, "bin"))
with open(os.path.join(TMP, "bin", "setxkbmap"), "w") as f:
    f.write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {shlex.quote(LOG)}\n')
os.chmod(os.path.join(TMP, "bin", "setxkbmap"), stat.S_IRWXU)
os.environ["PATH"] = os.path.join(TMP, "bin") + ":" + os.environ["PATH"]
os.environ["LUXOS_INSTALL_FAKE"] = "1"
os.environ.setdefault("LUXOS_I18N_DIR", I18N)
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)
gui = SourceFileLoader("luxos_install_gui", os.path.join(FILES, "luxos-install-gui")).load_module()
from gi.repository import Gtk  # noqa: E402

FAILS = []


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(desc)


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def last_call():
    try:
        with open(LOG) as f:
            return f.read().splitlines()[-1]
    except (OSError, IndexError):
        return ""


def cfg_values(cfg):
    out = subprocess.run(["bash", "-c", 'eval "$(cat)"; printf "%s|%s|%s" "$XKB_LAYOUT" "$XKB_VARIANT" '
                          '"${XKB_OPTIONS-UNSET}"'], input=cfg, capture_output=True, text=True)
    return out.stdout


def backend(cfg):
    """Konfigurace z GUI -> xkb_normalize (luxos-install) -> setup-chroot.sh -> 00-keyboard.conf."""
    d = tempfile.mkdtemp(dir=TMP)
    script = f'''
set -Eeuo pipefail
T() {{ local f=$1; shift; printf -- "$f" "$@"; }}
fail() {{ echo "FAIL $*"; exit 3; }}
eval "$(sed -n '/^KEYMAPS=(/,/^valid_user() {{/p' {shlex.quote(FILES)}/luxos-install | sed '$d')"
eval "$(cat)"
xkb_normalize
CONSOLE_KEYMAP=$(KBD_MODEL_MAP=/nonexistent x11_to_console "$XKB_LAYOUT" "$XKB_VARIANT")
eval "$(sed -n '/^echo "--> Keyboard/,/^echo "--> Time zone/p' {shlex.quote(FILES)}/setup-chroot.sh | sed '$d' |
        sed -e 's|/etc/X11/xorg.conf.d|{d}|g' -e 's|/etc/vconsole.conf|{d}/vconsole.conf|g')" >/dev/null
cat {d}/00-keyboard.conf
'''
    r = subprocess.run(["bash", "-c", script], input=cfg, capture_output=True, text=True)
    return r.stdout + r.stderr


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    win = gui.Installer()
    win.s.update({"fullname": "Jana Test", "username": "jana", "pw1": "pw", "pw2": "pw", "hostname": "jana-luxos"})
    pump()

    # Vychozi stav podle jazyka
    win.choose_lang("cs_CZ.UTF-8")
    pump()
    check("cs: vychozi cz + us", win.s["xkb"] == [("cz", ""), ("us", "")], str(win.s["xkb"]))
    win.choose_lang("en_US.UTF-8")
    pump()
    check("en: jen us", win.s["xkb"] == [("us", "")], str(win.s["xkb"]))
    win.choose_lang("cs_CZ.UTF-8")
    pump()

    win.idx = win.steps.index("keyboard")
    win.render()
    pump()
    ui = win.kbd_ui
    chips = ui["chips"].get_children()
    check("2 stitky rozlozeni", len(chips) == 2)
    check("prepinani viditelne pro 2 rozlozeni", ui["switch_row"].get_visible())
    check("setxkbmap v live systemu s obema rozlozenimi",
          last_call() == "-layout cz,us -variant , -option  -option grp:alt_shift_toggle", last_call())
    check("tlacitko + u pouziteho rozlozeni neaktivni", not ui["add"][("cz", "")].get_sensitive())
    check("tlacitko + u noveho rozlozeni aktivni", ui["add"][("de", "")].get_sensitive())

    # Klik do seznamu = vychozi rozlozeni (rychla cesta jako driv), + = dalsi
    ui["choose"](("sk", "qwerty"))
    check("klik meni vychozi, US zustane", win.s["xkb"] == [("sk", "qwerty"), ("us", "")], str(win.s["xkb"]))
    ui["choose"](("us", ""))
    check("klik na uz vybrane rozlozeni ho posune na zacatek", win.s["xkb"] == [("us", ""), ("sk", "qwerty")])
    ui["add_fn"](("de", ""))
    ui["add_fn"](("de", ""))
    check("+ prida (bez duplicit)", win.s["xkb"] == [("us", ""), ("sk", "qwerty"), ("de", "")], str(win.s["xkb"]))
    ui["add_fn"](("fr", ""))
    ui["add_fn"](("pl", ""))
    check("nejvyse 4 rozlozeni", len(win.s["xkb"]) == 4, str(win.s["xkb"]))
    check("pri 4 rozlozenich je + neaktivni", not ui["add"][("pl", "")].get_sensitive())
    ui["make_default"](("de", ""))
    check("stitek: nastavit jako vychozi", win.s["xkb"][0] == ("de", ""), str(win.s["xkb"]))
    ui["remove"](("us", ""))
    ui["remove"](("fr", ""))
    check("odebrani", win.s["xkb"] == [("de", ""), ("sk", "qwerty")], str(win.s["xkb"]))
    ui["switch"].set_active_id("grp:ctrl_shift_toggle")
    pump()
    check("volba prepinani", win.s["xkb_switch"] == "grp:ctrl_shift_toggle")
    check("setxkbmap po zmene", last_call() == "-layout de,sk -variant ,qwerty -option  -option grp:ctrl_shift_toggle",
          last_call())

    cfg = win.build_config()
    check("konfigurace: XKB_LAYOUT/VARIANT/OPTIONS", cfg_values(cfg) == "de,sk|,qwerty|grp:ctrl_shift_toggle",
          cfg_values(cfg))
    out = backend(cfg)
    check("backend: 00-keyboard.conf s obema rozlozenimi", '"XkbLayout" "de,sk"' in out and '"XkbVariant" ",qwerty"' in out
          and '"XkbOptions" "grp:ctrl_shift_toggle"' in out, out)

    # Souhrn ukazuje vsechna rozlozeni a prepinani
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    texts = []

    def walk(w):
        if isinstance(w, Gtk.Label):
            texts.append(w.get_text())
        if isinstance(w, Gtk.Container):
            for c in w.get_children():
                walk(c)
    walk(win.scroll)
    names = [win.xkb_name(k) for k in win.s["xkb"]]
    row = next((t for t in texts if "Ctrl + Shift" in t), "")
    check("souhrn: obe rozlozeni a prepinani", row.startswith(", ".join(names)), str(texts))

    # Jedno rozlozeni: bez prepinani, backend nic nepridava
    win.idx = win.steps.index("keyboard")
    win.render()
    pump()
    win.kbd_ui["remove"](("sk", "qwerty"))
    win.kbd_ui["remove"](("de", ""))      # posledni zustane
    check("posledni rozlozeni nelze odebrat", win.s["xkb"] == [("de", "")], str(win.s["xkb"]))
    check("prepinani skryte pro 1 rozlozeni", not win.kbd_ui["switch_row"].get_visible())
    cfg = win.build_config()
    check("jedno rozlozeni: XKB_OPTIONS prazdne (backend neprida US)", cfg_values(cfg) == "de||", cfg_values(cfg))
    out = backend(cfg)
    check("backend: jen de", '"XkbLayout" "de"' in out and "XkbOptions" not in out, out)
    win.destroy()
    print(f"\nVysledek: {len(FAILS)} FAIL")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
