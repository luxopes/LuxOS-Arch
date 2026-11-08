"""Sceny snimku webu: funkce scena(s) -> GdkPixbuf cele obrazovky (s = SiteSession ze shoot_site.py).

Aplikace ze zdroju pres postupy scripts/store-screenshots/apps/<id>.py (capture() tam bere celou
obrazovku) nebo nainstalovane programy LuxOS s ukazkovymi daty v docasnem HOME sceny. Kazda scena ma
vlastni HOME (s.home); spolecna je jen plocha (tapeta, lista, Dock) sezeni.

Nainstalovane programy, ktere by mohly sahnout na skutecne sezeni, se nespousti primo:
  - luxos-launchpad konci "pkill -x rofi" (zavrel by rofi skutecneho sezeni) -> kopie bez toho radku
  - luxos-dock konci, kdyz bezi plank skutecneho sezeni -> plank primo (shoot_site.Desktop)
  - luxos-hub (sluzby relace) se nespousti; Ovladaci centrum a Kalendar bezi samostatne
Udaje o siti a zvuku (nmcli, pactl) jsou z falesnych programu v PATH: na snimku nesmi byt skutecna
Wi-Fi uzivatele.
"""
import importlib.util
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.join(HERE, "..", "store-screenshots", "apps")
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PACKAGES = os.path.join(REPO, "packages")

# Launchpad a Nastaveni maji ukazat cisty LuxOS, ne aplikace nainstalovane na vyvojovem pocitaci (a ne
# aplikace mimo stabilni vydani: Posta, Lux Code). Aplikace mimo ALLOW_APPS (a nastaveni z DENY_APPS)
# se skryji prekrytim Hidden=true v ~/.local/share/applications sceny.
ALLOW_APPS = ("luxos-", "luxai", "luxdrop", "firefox", "thunar", "org.xfce.ristretto", "org.gnome.Evince",
              "xarchiver", "io.github.celluloid_player.Celluloid", "xfce4-taskmanager", "xfce-settings-manager")
DENY_APPS = ("lux-code", "luxos-mail", "lsl-ide", "nvidia-settings", "cngplp", "cnsetuputil", "xfce4-mail-reader",
             "luxos-mail-background")


def hidden_apps(data_dirs):
    """Id .desktop, ktere se ve scene skryji (viz ALLOW_APPS, DENY_APPS)."""
    hide = set()
    for d in data_dirs.split(":"):
        folder = os.path.join(d, "applications")
        if not d or not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.endswith(".desktop"):
                continue
            app = name[:-8]
            if app.startswith(DENY_APPS):
                hide.add(app)
                continue
            try:
                text = open(os.path.join(folder, name), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            settings = "X-XFCE-SettingsDialog" in text or "X-XFCE-HardwareSettings" in text
            if not settings and not app.startswith(ALLOW_APPS):
                hide.add(app)
    return sorted(hide)


FAKE_NMCLI = r'''#!/bin/sh
# falesny nmcli pro snimky webu: ukazkova Wi-Fi, nic se nemeni
case "$*" in
    "radio wifi") echo enabled ;;
    *"ACTIVE,SSID"*) printf 'yes:Home Wi-Fi\nno:Cafe Corner\nno:Library Guest\n' ;;
    *CONNECTIVITY*) echo full ;;
    *"TYPE,STATE"*) printf 'wifi:connected\nethernet:unavailable\nloopback:connected (externally)\n' ;;
    *) exit 0 ;;
esac
'''
FAKE_PACTL = r'''#!/bin/sh
# falesny pactl pro snimky webu: hlasitost 60 %, bez zvuku se nic nemeni
case "$*" in
    "get-sink-volume"*) echo "Volume: front-left: 39322 /  60% / -13.31 dB,   front-right: 39322 /  60% / -13.31 dB" ;;
    "get-sink-mute"*) echo "Mute: no" ;;
    *) exit 0 ;;
esac
'''


def recipe(name):
    spec = importlib.util.spec_from_file_location("site_recipe_" + name.replace("-", "_"), os.path.join(APPS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prepare_home(s):
    """Spolecne pro vsechny sceny: skryte aplikace, rezim vzhledu, ukazkovy ucet, falesne nmcli/pactl."""
    apps = os.path.join(s.home, ".local", "share", "applications")
    os.makedirs(apps, exist_ok=True)
    for a in hidden_apps(s.env.get("XDG_DATA_DIRS", "/usr/share")):
        with open(os.path.join(apps, a + ".desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=true\nHidden=true\nNoDisplay=true\n" % a)
    s.write(".config/luxos/appearance", ("dark" if s.dark else "light") + "\n")
    bindir = os.path.join(s.tmp, "fake-bin")
    os.makedirs(bindir, exist_ok=True)
    for name, text in (("nmcli", FAKE_NMCLI), ("pactl", FAKE_PACTL)):
        with open(os.path.join(bindir, name), "w") as f:
            f.write(text)
        os.chmod(os.path.join(bindir, name), 0o755)
    s.env["PATH"] = bindir + ":" + s.env.get("PATH", "/usr/bin")
    s.env["LUXOS_ACCOUNTS_FAKE"] = os.path.join(s.tmp, "no-accounts-icon")   # nikdy skutecna fotka uzivatele
    user = {"id": "u-demo", "email": "alex@example.com", "displayName": "Alex Morgan", "username": "alex.morgan"}
    data = {"version": 1, "origin": "http://127.0.0.1:9", "sessionToken": "demo-session-token", "user": user,
            "client": "luxos", "updatedAt": "2026-11-07T10:00:00+0100"}
    path = s.write(".config/luxai/account.json", json.dumps(data, indent=1), 0o600)
    os.chmod(os.path.dirname(path), 0o700)


# slozky uzivatele podle jazyka (jako xdg-user-dirs v LuxOS)
USER_DIRS = {
    "en": {"DESKTOP": "Desktop", "DOCUMENTS": "Documents", "DOWNLOAD": "Downloads", "MUSIC": "Music",
           "PICTURES": "Pictures", "VIDEOS": "Videos"},
    "cs": {"DESKTOP": "Plocha", "DOCUMENTS": "Dokumenty", "DOWNLOAD": "Stažené", "MUSIC": "Hudba",
           "PICTURES": "Obrázky", "VIDEOS": "Videa"},
}
HOLIDAY = {"en": "Holiday 2026", "cs": "Dovolená 2026"}


def user_dir(s, key):
    return os.path.join(s.home, USER_DIRS.get(s.lang, USER_DIRS["en"])[key])


def demo_files(s):
    """Ukazkove slozky a soubory v HOME sceny (Soubory, Terminal) -> slozka s fotkami."""
    from gi.repository import GdkPixbuf
    walls = os.path.join(PACKAGES, "luxos-branding", "files", "wallpapers")
    dirs = USER_DIRS.get(s.lang, USER_DIRS["en"])
    s.write(".config/user-dirs.dirs", "".join('XDG_%s_DIR="$HOME/%s"\n' % kv for kv in dirs.items()))
    for d in dirs.values():
        os.makedirs(os.path.join(s.home, d), exist_ok=True)
    photos = os.path.join(user_dir(s, "PICTURES"), HOLIDAY.get(s.lang, HOLIDAY["en"]))
    os.makedirs(photos, exist_ok=True)
    os.makedirs(os.path.join(s.home, "Projects", "weather-widget"), exist_ok=True)
    docs = user_dir(s, "DOCUMENTS")
    for name, text in (("Trip plan.txt", "Day 1: Prague - Cesky Krumlov\n"), ("Budget 2026.csv", "month,income\n"),
                       ("Notes.md", "# Notes\n")):
        with open(os.path.join(docs, name), "w", encoding="utf-8") as f:
            f.write(text)
    for i, w in enumerate(("luxos-lagoon.jpg", "luxos-sunrise.jpg", "luxos-aurora-blue.jpg", "luxos-citrus.jpg",
                           "luxos-twilight.jpg", "luxos-aurora-orange.jpg")):
        src = os.path.join(walls, w)
        if os.path.exists(src):
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, 1280, 720, True)
            pix.savev(os.path.join(photos, "IMG_%04d.jpg" % (2041 + i)), "jpeg", ["quality"], ["82"])
    shutil.copy(os.path.join(walls, "luxos-lagoon.jpg"), os.path.join(user_dir(s, "PICTURES"), "Lagoon.jpg"))
    return photos


def frame(s, name="shot"):
    s.capture(name)
    return s.frames[name]


# ---- sceny ------------------------------------------------------------------------------------------
def desktop(s):
    """Prazdna plocha: tapeta, horni lista a Dock."""
    s.sleep(1.0)
    return frame(s)


def launchpad(s):
    """Launchpad (rofi s tematem luxos-launchpad) ze zdroju luxos-desktop, bez "pkill -x rofi"."""
    prepare_home(s)
    src = os.path.join(PACKAGES, "luxos-desktop", "files", "bin", "luxos-launchpad")
    text = open(src, encoding="utf-8").read()
    line = "if pkill -x rofi; then exit 0; fi"
    if line not in text:
        raise RuntimeError("luxos-launchpad changed: update the pkill guard in scenes.launchpad")
    text = text.replace(line, ": # snimky webu: rofi skutecneho sezeni se nezavira")
    script = os.path.join(s.tmp, "luxos-launchpad")
    with open(script, "w", encoding="utf-8") as f:
        f.write(text)
    s.write(".config/luxos/launchpad-sort", "category\n")
    env = {"LUXOS_LAUNCHPAD_PY": os.path.join(PACKAGES, "luxos-desktop", "files", "python", "luxos_launchpad.py")}
    s.launch(["bash", script], env=env)
    s.window(cls="rofi", size=None, place=False, timeout=30)
    s.sleep(2.5)
    return frame(s)


def control_center(s):
    """Ovladaci centrum (nainstalovany luxos-control-center, samostatne bez luxos-hub) nad oknem Souboru."""
    prepare_home(s)
    photos = demo_files(s)
    s.launch(["thunar", photos], env={"GIO_USE_VFS": "gvfs"})
    s.window(cls="Thunar", size=(1100, 680))
    s.sleep(4.0)          # nahledy fotek (tumbler)
    s.launch(["luxos-control-center"])
    s.window(cls="luxos-control-center", size=None, place=False, timeout=30)
    s.sleep(2.5)
    return frame(s)


def calendar(s):
    """Kalendar z horni listy (nainstalovany luxos-calendar, samostatne)."""
    prepare_home(s)
    s.launch(["luxos-calendar"])
    win = s.window(cls="luxos-calendar", size=None, place=False, timeout=30)
    s.sleep(1.5)
    # zobrazeni Mesic (prepinac Den | Mesic | Rok nahore vlevo v okne)
    s.click(85, 27, win, delay=1.5)
    return frame(s)


def files(s):
    """Soubory (Thunar s nastavenim LuxOS) s ukazkovymi fotkami."""
    prepare_home(s)
    photos = demo_files(s)
    # GIO s gvfs (Kos v postrannim panelu; FUSE vypnute v shoot_site.prepare)
    s.launch(["thunar", photos], env={"GIO_USE_VFS": "gvfs"})
    s.window(cls="Thunar", size=(1180, 720))
    s.sleep(4.0)          # nahledy fotek (tumbler)
    return frame(s)


def store(s):
    """Obchod LuxOS ze zdroju: stranka Objevovat s aplikacemi LuxOS a popisy."""
    prepare_home(s)
    data = os.path.join(s.tmp, "store-data")
    p = s.launch([sys.executable, os.path.join(HERE, "store_demo.py"), data, "discover"])
    s.window(pid=p.pid, size=(1240, 780))
    s.sleep(5.0)
    return frame(s)


def weather(s):
    """Pocasi (postup store-screenshots: falesny server Open-Meteo s testovacimi daty)."""
    prepare_home(s)
    recipe("luxos-weather").shots(s)
    return s.frames.get("1")


def terminal(s):
    """Terminal (postup store-screenshots: fastfetch s ukazkovymi udaji a projekt v Gitu)."""
    prepare_home(s)
    recipe("luxos-terminal").shots(s)
    return s.frames.get("1")


def luxai(s):
    """LuxAI (nainstalovana aplikace, postup store-screenshots s falesnym serverem LuxAI)."""
    prepare_home(s)
    mod = recipe("luxai")
    if os.path.exists("/usr/bin/luxai"):
        mod.build = lambda _s: "/usr/bin/luxai"
    mod.shots(s)
    return s.frames.get("1")


def settings(s):
    """Nastaveni (xfce4-settings-manager s panely LuxOS)."""
    prepare_home(s)
    s.launch(["xfce4-settings-manager"])
    s.window(cls="Xfce4-settings-manager", size=(1100, 690))
    s.sleep(2.5)
    return frame(s)


SCENES = {
    "desktop": desktop,
    "launchpad": launchpad,
    "control-center": control_center,
    "files": files,
    "store": store,
    "weather": weather,
    "terminal": terminal,
    "luxai": luxai,
    "settings": settings,
    "calendar": calendar,
}
