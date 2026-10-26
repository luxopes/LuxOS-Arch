#!/usr/bin/env python3
"""LuxOS installer - krok Firemni sit (domena Active Directory) v GUI bez instalace (virtualni displej):

    env -u DISPLAY xvfb-run -a dbus-run-session -- python3 packages/luxos-installer/tests/gui-domain.py

1) instalator: krok Organization za Account (ne v OEM), volba Ja / Organizace, tlacitko Najit
   (napodoba lux-domain discover), souhrn, konfigurace pro backend (heslo jen ve stdin konfiguraci),
   kontrola v backendu (domain_config), upozorneni @@NOTICE na posledni strance,
2) Pruvodce nastavenim: krok Firemni sit jen s lux-domain, data pro luxos-oem finish, @@WARN pred prihlasenim.
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
TMP = tempfile.mkdtemp(prefix="luxos-gui-domain-")
SECRET = "Domenove heslo 1"

# napodoba lux-domain (discover) a luxos-oem (status, finish s upozornenim o domene)
CLI = os.path.join(TMP, "lux-domain")
with open(CLI, "w") as f:
    f.write('''#!/bin/bash
[[ $1 == discover ]] || exit 2
if [[ $2 == firma.local ]]; then
    echo '{"ok": true, "domain": "firma.local", "realm": "FIRMA.LOCAL", "short": "FIRMA", "type": "active-directory", "controllers": ["dc1.firma.local", "dc2.firma.local"], "clock_skew": 3}'
else
    echo '{"ok": false, "error": "dns", "message": "No domain controller was found for this name (check DNS)."}'
    exit 1
fi
''')
os.chmod(CLI, 0o755)
HELPER = os.path.join(TMP, "helper.sh")
with open(HELPER, "w") as f:
    f.write(f'''#!/bin/bash
case $1 in
    status) printf 'OEM=1\\nARMED=1\\nDONE=0\\nLUKS=none\\nUSER=\\n' ;;
    finish)
        cat >"{TMP}/finish.in"
        echo "@@STEP 1 4 Applying language and region"
        echo "@@STEP 3 4 Joining the organization network"
        grep -q '^DOMAIN=.' "{TMP}/finish.in" && echo "@@WARN The computer could not join the domain firma.local: wrong password. Join it later in Settings > Organization Network."
        echo "@@STEP 4 4 Finishing"
        echo "@@DONE" ;;
esac
''')
os.environ.update({"LUXOS_INSTALL_FAKE": "1", "LANG": "en_US.UTF-8", "LUXOS_SETUP_STATE": os.path.join(TMP, "progress.json"),
                   "LUXOS_INSTALL_GUI": os.path.join(FILES, "luxos-install-gui"), "LUXOS_INSTALL_FAKE_DELAY": "0",
                   "LUXOS_DOMAIN_CLI": CLI, "LUXOS_SETUP_HELPER": "bash " + HELPER, "HOME": TMP})
os.environ.setdefault("LUXOS_I18N_DIR", I18N)
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)

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


def wait_for(cond, sec=10):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        pump(0.05)
        if cond():
            return True
    return False


def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


def labels(w):
    return " | ".join(c.get_text() for c in walk(w) if isinstance(c, Gtk.Label))


def click_card(win, title):
    """Karta volby (EventBox s nadpisem) -> klik."""
    for c in walk(win.scroll):
        if isinstance(c, Gtk.EventBox) and title in labels(c):
            c.emit("button-press-event", None)
            return True
    return False


def installer():
    print("## Instalator: krok Organization")
    win = gui.Installer()
    pump(0.3)
    check("krok Organization hned za Account", win.steps.index("organization") == win.steps.index("account") + 1,
          str(win.steps))
    check("v postrannim panelu", "Organization" in gui.Installer.STEP_NAMES.values())
    win.set_oem(True)
    check("OEM: bez kroku Organization (nastavi majitel)", "organization" not in win.steps)
    win.set_oem(False)
    check("bez OEM: krok zpet za Account", win.steps.index("organization") == win.steps.index("account") + 1)
    win.idx = win.steps.index("organization")
    win.render()
    pump()
    text = labels(win.scroll)
    check("stranka: Ja / Organizace", "Who does this computer belong to?" in text and "Me" in text
          and "An organization (Active Directory domain)" in text, text)
    check("vychozi osobni pocitac: lze pokracovat", win.valid() and not win.s["org"])
    check("osobni pocitac: konfigurace bez DOMAIN", "DOMAIN" not in win.build_config())
    check("klik na Organizace", click_card(win, "An organization (Active Directory domain)"))
    pump(0.1)
    check("organizace: bez udaju nelze pokracovat", win.s["org"] and not win.valid())
    check("organizace: napoveda co chybi", "domain name" in win.nav_hint.get_text(), win.nav_hint.get_text())
    w = win.domain_widgets
    check("pole Domena, Spravce, Heslo (s okem), OU", all(k in w for k in ("domain", "user", "password", "ou"))
          and w["password"].get_icon_name(Gtk.EntryIconPosition.SECONDARY) == "view-reveal-symbolic")
    check("heslo skryte", not w["password"].get_visibility())
    check("Najit: neaktivni bez platne domeny", not w["find"].get_sensitive())
    w["domain"].set_text("Firma.Local")
    pump()
    check("domena malymi pismeny", win.s["domain"] == "firma.local")
    check("Najit: aktivni", w["find"].get_sensitive())
    w["find"].clicked()
    check("Najit: nalezeno (lux-domain discover)",
          wait_for(lambda: "Found: Active Directory FIRMA.LOCAL (domain controllers: 2)" in labels(win.scroll)),
          labels(win.scroll))
    w["domain"].set_text("jina.local")
    pump()
    w["find"].clicked()
    check("Najit: chyba z lux-domain", wait_for(lambda: "No domain controller was found" in labels(win.scroll)),
          labels(win.scroll))
    w["domain"].set_text("firma.local")
    w["user"].set_text("admin")
    pump()
    check("bez hesla nelze pokracovat", not win.valid() and "password" in win.nav_hint.get_text())
    w["password"].set_text(SECRET)
    w["ou"].set_text("OU=PC,DC=firma,DC=local")
    pump()
    check("vyplneno: lze pokracovat", win.valid())
    # Zpet/dal: hodnoty zustanou
    win.idx = win.steps.index("account")
    win.render()
    win.idx = win.steps.index("organization")
    win.render()
    pump()
    check("po navratu: hodnoty zustaly", win.domain_widgets["domain"].get_text() == "firma.local"
          and win.domain_widgets["password"].get_text() == SECRET)
    # bez lux-domain v live systemu: Najit jen vysvetli
    old = gui.oem.DOMAIN_CLI
    gui.oem.DOMAIN_CLI = os.path.join(TMP, "none")
    win.domain_widgets["find"].clicked()
    pump()
    check("bez lux-domain: vysvetleni", "joins it at the end of the installation" in labels(win.scroll))
    gui.oem.DOMAIN_CLI = old
    # souhrn a konfigurace
    win.s.update({"fullname": "Jana", "username": "jana", "pw1": "x", "pw2": "x", "hostname": "jana-luxos"})
    win.disks = gui.fake_disks()
    win.s.update({"disk": win.disks[0]["path"], "mode": "erase", "erase_ok": True})
    win.idx = win.steps.index("summary")
    win.render()
    pump()
    text = labels(win.scroll)
    check("souhrn: radek Organization", "domain firma.local (administrator admin)" in text, text)
    check("souhrn: bez hesla", SECRET not in text)
    cfg = win.build_config()
    check("konfigurace: DOMAIN, DOMAIN_USER, OU", "DOMAIN=firma.local\n" in cfg and "DOMAIN_USER=admin\n" in cfg
          and "OU=OU=PC,DC=firma,DC=local\n" in cfg, cfg)
    check("konfigurace: heslo (shlex)", "DOMAIN_PASSWORD='Domenove heslo 1'\n" in cfg)
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0"), timeout=120)
    check("simulovany backend: domena", "DOMAIN=firma.local DOMAIN_USER=admin OU=OU=PC,DC=firma,DC=local, "
          "domain password length 16" in r.stdout and "@@DONE" in r.stdout, r.stdout[-500:])
    check("simulovany backend: heslo neni ve vystupu", SECRET not in r.stdout)
    # backend luxos-install: kontrola konfigurace z GUI
    script = f'''
T() {{ local f=$1; shift; printf -- "$f" "$@"; }}
fail() {{ echo "FAIL $*"; exit 3; }}
info() {{ :; }}
eval "$(sed -n '/^# --- Firemni sit: pripojeni k domene/,/^# --- OEM: priprava pro jineho cloveka/p' "{FILES}/luxos-install")"
eval "$(cat)"
domain_config
echo "D=$DOMAIN U=$DOMAIN_USER P=${{#DOMAIN_PASSWORD}} OU=$OU"
'''
    r = subprocess.run(["bash", "-c", script], input=cfg, capture_output=True, text=True)
    check("backend domain_config prijme konfiguraci GUI", "D=firma.local U=admin P=16 OU=OU=PC,DC=firma,DC=local"
          in r.stdout, r.stdout + r.stderr)
    # nezdar pripojeni: @@NOTICE -> posledni stranka
    r = subprocess.run(["bash", "-c", gui.FAKE_BACKEND], input=cfg, capture_output=True, text=True,
                       env=dict(os.environ, LUXOS_INSTALL_FAKE_DELAY="0", LUXOS_INSTALL_FAKE_DOMAIN_FAIL="1"),
                       timeout=120)
    notice = [ln for ln in r.stdout.splitlines() if ln.startswith("@@NOTICE ")]
    check("nezdar: @@NOTICE", len(notice) == 1 and "@@DONE" in r.stdout, r.stdout[-400:])
    win.idx = win.steps.index("install")
    win.render()
    pump()
    win.notices = []
    win.handle_line(notice[0])
    check("GUI: upozorneni zapamatovano", len(win.notices) == 1)
    win.result = ("ok",)
    win.idx = win.steps.index("done")
    win.render()
    pump()
    text = labels(win.scroll)
    check("hotovo: instalace OK i s upozornenim", "LuxOS is installed" in text
          and "could not join the domain firma.local" in text, text)
    # zpet na osobni pocitac: domena se neposila
    win.s["org"] = False
    check("osobni pocitac: konfigurace bez hesla domeny", SECRET not in win.build_config())
    win.destroy()


def assistant():
    print("## Pruvodce nastavenim: Firemni sit")
    status = sa.oem.parse_status(sa.run_helper(["status"])[1])
    check("lux-domain je (napodoba)", sa.oem.domain_available())
    win = sa.SetupAssistant(sa.DemoLogin(), status, windowed=True)
    pump(0.2)
    check("kroky: Firemni sit za uctem", win.steps == ["welcome", "keyboard", "network", "timezone", "account",
                                                      "organization", "luxai", "care", "finish"], str(win.steps))
    win.s.update({"fullname": "Jana", "username": "jana", "pw1": "heslo1", "pw2": "heslo1", "hostname": "jana-luxos"})
    win.idx = win.steps.index("organization")
    win.render()
    pump()
    check("stranka z instalatoru", "Who does this computer belong to?" in labels(win.scroll))
    check("klik na Organizace", click_card(win, "An organization (Active Directory domain)"))
    pump(0.1)
    w = win.domain_widgets
    w["domain"].set_text("firma.local")
    w["user"].set_text("admin")
    w["password"].set_text(SECRET)
    pump()
    check("vyplneno: lze pokracovat", win.valid())
    win.go_next()
    pump()
    check("dal: LuxAI", win.current() == "luxai")
    saved = open(os.environ["LUXOS_SETUP_STATE"]).read()
    check("ulozeny prubeh: domena ano, heslo ne", "firma.local" in saved and SECRET not in saved)
    win.go_next()
    pump()
    check("udrzba", win.current() == "care")
    calls = []
    win.login_backend.login = lambda user, pw, done: calls.append(user)
    win.go_next()
    check("dokonceni: upozorneni o domene a tlacitko Prihlasit",
          wait_for(lambda: not win.finishing and "could not join the domain" in labels(win.scroll)),
          labels(win.scroll))
    data = dict(line.split("=", 1) for line in open(os.path.join(TMP, "finish.in")).read().splitlines())
    check("finish: domena pro luxos-oem", data.get("DOMAIN") == "firma.local" and data.get("DOMAIN_USER") == "admin"
          and data.get("DOMAIN_PASSWORD") == SECRET and data.get("DOMAIN_OU") == "", str(data))
    check("pred precteni upozorneni se neprihlasuje", calls == [])
    check("heslo domeny zapomenuto", win.s["domain_pw"] == "")
    win.signin_btn.clicked()
    pump()
    check("Prihlasit: prihlaseni noveho uctu", calls == ["jana"])
    win.destroy()

    # bez luxos-domain: zadny krok Firemni sit
    old = sa.oem.DOMAIN_CLI
    sa.oem.DOMAIN_CLI = os.path.join(TMP, "none")
    os.unlink(os.environ["LUXOS_SETUP_STATE"])
    win = sa.SetupAssistant(sa.DemoLogin(), status, windowed=True)
    pump(0.1)
    check("bez lux-domain: bez kroku Firemni sit", "organization" not in win.steps, str(win.steps))
    win.destroy()
    sa.oem.DOMAIN_CLI = old


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    installer()
    assistant()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("All domain GUI tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
