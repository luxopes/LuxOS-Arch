#!/usr/bin/env python3
"""LuxOS installer - OEM v GUI bez instalace a bez LightDM (potrebuje virtualni displej):

    env -u DISPLAY xvfb-run -a python3 packages/luxos-installer/tests/gui-oem.py

1) instalator: volba "Pripravit pro jineho cloveka (OEM)" - kroky, sifrovani bez hesla, ucet oem,
   souhrn a konfigurace pro backend (FAKE_BACKEND),
2) Pruvodce nastavenim (luxos-setup-assistant, ukazkove prihlaseni): vsechny stranky, ulozeny prubeh
   po "vypadku proudu", data pro luxos-oem finish (napodoba), chyba a novy pokus, cela obrazovka,
3) okno Zapecetit pro zakaznika.
"""
import os
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
TMP = tempfile.mkdtemp(prefix="luxos-gui-oem-")
os.environ.update({"LUXOS_INSTALL_FAKE": "1", "LANG": "en_US.UTF-8", "LUXOS_SETUP_STATE": os.path.join(TMP, "progress.json"),
                   "LUXOS_INSTALL_GUI": os.path.join(FILES, "luxos-install-gui"), "LUXOS_INSTALL_FAKE_DELAY": "0"})
os.environ.setdefault("LUXOS_I18N_DIR", I18N)
# krok Firemni sit jen s luxos-domain: tady bez nej (pevne poradi kroku), viz gui-domain.py
os.environ["LUXOS_DOMAIN_CLI"] = os.path.join(TMP, "no-lux-domain")
os.environ["HOME"] = TMP
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)

# napodoba luxos-oem: status (sifrovany disk) a finish (vstup do souboru)
HELPER = os.path.join(TMP, "helper.sh")
with open(HELPER, "w") as f:
    f.write(f'''#!/bin/bash
case $1 in
    status) printf 'OEM=1\\nARMED=1\\nDONE=0\\nLUKS=pending\\nUSER=\\n' ;;
    finish)
        cat >"{TMP}/finish.in"
        echo "@@STEP 1 5 Applying language and region"
        if [[ -e "{TMP}/fail" ]]; then echo "@@ERROR The user name jana is already taken."; exit 1; fi
        echo "@@STEP 5 5 Finishing"
        echo "@@DONE" ;;
esac
''')
os.environ["LUXOS_SETUP_HELPER"] = "bash " + HELPER

loader = SourceFileLoader("luxos_setup_assistant", os.path.join(FILES, "luxos-setup-assistant"))
sa = module_from_spec(spec_from_loader("luxos_setup_assistant", loader))
loader.exec_module(sa)
gui = sa.gui
Gtk = gui.Gtk

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
            break
        time.sleep(0.02)


def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


def labels(w):
    return " | ".join(c.get_text() for c in walk(w) if isinstance(c, Gtk.Label))


def installer():
    print("## Instalator: OEM")
    win = gui.Installer()
    pump(0.3)
    check("bez OEM je krok LuxAI", "luxai" in win.steps)
    win.render()
    pump()
    oem_btn = next((c for c in walk(win.scroll) if isinstance(c, Gtk.CheckButton)
                    and c.get_label() == "Prepare for another person (OEM)"), None)
    check("uvod: volba Prepare for another person (OEM)", oem_btn is not None)
    oem_btn.set_active(True)
    pump()
    check("OEM: bez kroku LuxAI", "luxai" not in win.steps)
    # disk: sifrovani bez hesla
    win.disks = gui.fake_disks()
    win.s.update({"disk": win.disks[0]["path"], "mode": "erase", "erase_ok": True, "encrypt": True})
    win.idx = win.steps.index("disk")
    win.render()
    pump()
    check("OEM + sifrovani: Continue bez hesla", win.valid())
    check("OEM: heslo disku zvoli majitel", "The owner chooses the disk password" in labels(win.scroll))
    # ucet: zapecetit hned / pripravit
    win.idx = win.steps.index("account")
    win.render()
    pump()
    check("OEM ucet: Seal now / Prepare first", "Seal now" in labels(win.scroll) and "Prepare first" in labels(win.scroll))
    check("seal now: platne bez hesla", win.valid())
    win.pick_oem_prepare(True)
    pump()
    check("prepare: bez hesla oem neplatne", not win.valid())
    win.s.update(oem_pw1="adm", oem_pw2="adm")
    win.render()
    pump()
    check("prepare: s heslem platne", win.valid())
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    text = labels(win.scroll)
    check("souhrn: ucet zalozi majitel", "the owner creates it at the first start (OEM)" in text, text)
    check("souhrn: bez radku LuxAI", "| LuxAI |" not in text)
    cfg = win.build_config()
    check("konfigurace: OEM=1 OEM_SEAL=0", "OEM=1\n" in cfg and "OEM_SEAL=0\n" in cfg, cfg)
    check("konfigurace: bez LUKS_PASS a uctu", "LUKS_PASS=''\n" in cfg and "USERNAME=''\n" in cfg, cfg)
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0"), timeout=120)
    check("simulovany backend: @@DONE", "@@DONE" in r.stdout, r.stdout[-400:] + r.stderr)
    check("simulovany backend vidi OEM", "OEM=1 OEM_SEAL=0, password length 3" in r.stdout)
    # backend: konfigurace projde oem_config (bez USERNAME/PASSWORD chyb)
    script = f'''
T() {{ local f=$1; shift; printf -- "$f" "$@"; }}
fail() {{ echo "FAIL $*"; exit 3; }}
info() {{ :; }}
eval "$(sed -n '/^# --- OEM: priprava pro jineho cloveka/,/^# Bezpecne smazani (WIPE)/p' "{FILES}/luxos-install")"
eval "$(cat)"
oem_config
echo "U=$USERNAME P=${{#PASSWORD}} K=${{#LUKS_PASS}}"
'''
    r = subprocess.run(["bash", "-c", script], input=cfg, capture_output=True, text=True)
    check("backend oem_config: ucet oem, docasny klic disku", "U=oem P=3 K=64" in r.stdout, r.stdout + r.stderr)
    win.pick_oem_prepare(False)
    pump()
    cfg = win.build_config()
    check("seal now: OEM_SEAL=1 bez hesla", "OEM_SEAL=1\n" in cfg and "PASSWORD=''\n" in cfg)
    oem_btn = None
    win.idx = 0
    win.render()
    pump()
    next(c for c in walk(win.scroll) if isinstance(c, Gtk.CheckButton)).set_active(False)
    pump()
    check("OEM vypnuto: krok LuxAI zpet pred souhrnem",
          "luxai" in win.steps and win.steps.index("luxai") == win.steps.index("summary") - 1)
    win.destroy()


def assistant():
    print("## Pruvodce nastavenim")
    status = sa.oem.parse_status(sa.run_helper(["status"])[1])
    check("status z napodoby: disk ceka na heslo", status["LUKS"] == "pending")
    login = sa.DemoLogin()
    win = sa.SetupAssistant(login, status, windowed=True)
    pump(0.3)
    check("kroky vcetne hesla disku", win.steps == ["welcome", "keyboard", "network", "timezone", "account", "luxai",
                                                   "diskpass", "care", "finish"], str(win.steps))
    check("okno s titulkem a zavrenim (ukazka)", win.header is not None and win.header.get_show_close_button())
    check("prvni stranka: bez Zpet", not win.btn_back.get_visible())
    win.choose_lang("cs_CZ.UTF-8")
    pump(0.2)
    check("cestina: preklad stranky", "Vítejte" in labels(win.scroll), labels(win.scroll)[:200])
    check("cestina: klavesnice us + cz", win.s["xkb"] == [("us", ""), ("cz", "")])
    win.go_next()
    pump()
    check("klavesnice: stranka z instalatoru", win.current() == "keyboard" and hasattr(win, "kbd_ui"))
    check("Zpet na kazde dalsi strance", win.btn_back.get_visible())
    win.go_next()
    pump(0.3)
    check("Wi-Fi: lze pokracovat", win.current() == "network" and win.valid())
    win.go_next()
    pump()
    check("casove pasmo", win.current() == "timezone")
    win.go_next()
    pump()
    check("ucet: bez udaju nelze pokracovat", win.current() == "account" and not win.valid())
    check("ucet: fotka (nepovinna)", "Choose Photo…" in [c.get_label() for c in walk(win.scroll)
                                                       if isinstance(c, Gtk.Button)] or
          "Vybrat fotku…" in [c.get_label() for c in walk(win.scroll) if isinstance(c, Gtk.Button)])
    eyes = [c for c in walk(win.scroll) if isinstance(c, Gtk.Entry)
            and c.get_icon_name(Gtk.EntryIconPosition.SECONDARY) == "view-reveal-symbolic"]
    check("heslo s ikonou oka", len(eyes) >= 2)
    full = next(c for c in walk(win.scroll) if isinstance(c, Gtk.Entry)
                and c.get_placeholder_text() == gui._("Jane Doe"))
    full.set_text("Jana Nováková")
    pump()
    check("uzivatelske jmeno podle jmena", win.s["username"] == "jana" and win.s["hostname"] == "jana-luxos")
    eyes[0].set_text("heslo1")
    eyes[1].set_text("heslo1")
    pump()
    check("ucet platny", win.valid())
    # fotka: PNG 256 px
    from gi.repository import GdkPixbuf
    src = os.path.join(TMP, "me.jpg")
    GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 800, 600).savev(src, "jpeg", [], [])
    win.set_photo(src)
    check("fotka zmensena na PNG", win.photo and open(win.photo, "rb").read(8) == b"\x89PNG\r\n\x1a\n")
    check("fotka max 256 px", GdkPixbuf.Pixbuf.get_file_info(win.photo)[1] <= 256)
    win.go_next()
    pump()
    check("LuxAI: krok lze preskocit", win.current() == "luxai" and win.btn_next.get_label() in ("Skip", "Přeskočit"))

    # "vypadek proudu": novy Pruvodce pokracuje na ulozenem kroku, hesla se neukladaji
    win2 = sa.SetupAssistant(sa.DemoLogin(), status, windowed=True)
    pump(0.2)
    check("po vypadku: pokracuje na kroku LuxAI", win2.current() == "luxai", win2.current())
    check("po vypadku: jmeno a jazyk zustaly", win2.s["username"] == "jana" and win2.s["locale"] == "cs_CZ.UTF-8")
    check("po vypadku: heslo se neulozilo", win2.s["pw1"] == "")
    check("ulozeny soubor bez hesla", "heslo1" not in open(os.environ["LUXOS_SETUP_STATE"]).read())
    win2.destroy()

    win.go_next()
    pump()
    check("heslo disku: vychozi = heslo uctu", win.current() == "diskpass" and win.valid())
    same = next(c for c in walk(win.scroll) if isinstance(c, Gtk.CheckButton))
    same.set_active(False)
    pump()
    check("vlastni heslo disku: prazdne nelze", not win.valid())
    win.s.update(disk1="disk-heslo", disk2="jine")
    check("vlastni heslo disku: neshoda", not win.valid())
    win.s["disk2"] = "disk-heslo"
    check("vlastni heslo disku: shoda", win.valid())
    win.go_next()
    pump()
    check("udrzba (stranka z instalatoru)", win.current() == "care")
    win.pick_care("classic")
    pump()
    # chyba z luxos-oem: novy pokus a Zpet
    open(os.path.join(TMP, "fail"), "w").close()
    win.go_next()
    for _i in range(100):
        pump(0.05)
        if not win.finishing:
            break
    check("chyba dokonceni: zobrazena", "already taken" in labels(win.scroll), labels(win.scroll))
    check("chyba: Zkusit znovu a Zpet", win.btn_next.get_visible() and win.btn_back.get_visible())
    os.unlink(os.path.join(TMP, "fail"))
    got = []
    win.logged_in = lambda ok: got.append(ok)
    win.go_next()
    for _i in range(100):
        pump(0.05)
        if got:
            break
    data = dict(line.split("=", 1) for line in open(os.path.join(TMP, "finish.in")).read().splitlines())
    check("finish: data pro luxos-oem", data["USERNAME"] == "jana" and data["LOCALE"] == "cs_CZ.UTF-8"
          and data["CARE_MODE"] == "classic" and data["DISK_PASS"] == "disk-heslo" and data["PASSWORD"] == "heslo1",
          str(data))
    check("finish: fotka predana", data["PHOTO"].endswith("photo.png"))
    check("finish: klavesnice", data["XKB_LAYOUT"] == "us,cz")
    check("po dokonceni prihlaseni noveho uctu", login.calls == [("login", "jana")] and got == [True], str(login.calls))
    check("po dokonceni bez Zpet", not win.btn_back.get_visible())
    win.destroy()

    # cela obrazovka (pod LightDM): bez dekorace, zavreni okna nejde, Zpet ano
    full = sa.SetupAssistant(sa.DemoLogin(), {"LUKS": "none"}, windowed=False)
    pump(0.2)
    check("cela obrazovka: bez dekorace", not full.get_decorated() and full.header is None)
    check("cela obrazovka: bez stranky disku", "diskpass" not in full.steps)
    check("cela obrazovka: zavreni se odmitne", full.on_delete() is True)
    check("cela obrazovka: Zpet na ulozenem kroku", full.idx > 0 and full.btn_back.get_visible())
    full.power_btn.get_popup().get_children()[1].activate()
    check("vypnuti z nabidky", full.login_backend.calls == [("shutdown",)])
    full.destroy()


def seal_dialog():
    print("## Zapecetit pro zakaznika")
    d = sa.SealDialog(reminder=True)
    pump()
    hb = d.get_titlebar()
    check("okno s titulkem a zavrenim", isinstance(hb, Gtk.HeaderBar) and hb.get_show_close_button())
    check("prikaz: pkexec luxos-oem seal --yes --poweroff", d.command() == ["pkexec", "/usr/bin/luxos-oem", "seal",
                                                                         "--yes", "--poweroff"])
    d.keep_wifi.set_active(True)
    check("ponechat Wi-Fi: --keep-wifi", d.command()[-1] == "--keep-wifi")
    d.destroy()


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    installer()
    assistant()
    seal_dialog()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("All OEM GUI tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
