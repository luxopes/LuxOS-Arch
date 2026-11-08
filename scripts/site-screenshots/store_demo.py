#!/usr/bin/env python3
"""Obchod LuxOS ze zdroju s ukazkovymi daty pro snimky webu (spousti scenes.store pod xvfb).

Katalog aplikaci LuxOS je sestaveny ze zdroju v pracovni kopii (packages/luxos-store/tests/source_catalog.py,
popisy z metainfo) a podavany jako file:// z docasne slozky; snimky aplikaci z packages/luxos-store/screens.
Oblibene aplikace Archu jsou ukazkove komponenty AppStream. Zadna sit, zadna skutecna databaze baliku:
lux, lux-engine a flatpak nahrazuje fake_run (stejne jako tests/test_store_gui.py).

    store_demo.py DATA_DIR [discover|luxos|app:<id>]
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PACKAGES = os.path.join(REPO, "packages")
FILES = os.path.join(PACKAGES, "luxos-store", "files")
SCREENS = os.path.join(PACKAGES, "luxos-store", "screens")
sys.path.insert(0, os.path.join(PACKAGES, "luxos-store", "tests"))
sys.path.insert(0, FILES)
sys.path.insert(0, os.path.join(PACKAGES, "luxos-i18n", "files"))
import luxos_app_catalog  # noqa: E402,F401
import luxos_i18n  # noqa: E402,F401
import source_catalog  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("AppStream", "1.0")
from gi.repository import AppStream, Gdk, GLib, Gtk  # noqa: E402

# aplikace, ktere nejsou ve stabilnim vydani (Posta, Lux Code), na webu nejsou
HIDDEN = {"luxos-mail", "lux-code"}
# oblibene aplikace Archu (ukazkove komponenty AppStream; ikony z motivu WhiteSur)
POPULAR = [
    ("firefox", "Firefox", "Fast, private and safe web browser", "firefox", "Network"),
    ("libreoffice-fresh", "LibreOffice", "Office suite: documents, spreadsheets and presentations", "libreoffice-main", "Office"),
    ("gimp", "GIMP", "Create images and edit photographs", "gimp", "Graphics"),
    ("inkscape", "Inkscape", "Vector graphics editor", "inkscape", "Graphics"),
    ("vlc", "VLC media player", "Play almost any video or music file", "vlc", "AudioVideo"),
    ("obs-studio", "OBS Studio", "Live streaming and screen recording", "com.obsproject.Studio", "AudioVideo"),
    ("thunderbird", "Thunderbird", "Email, calendar and contacts", "thunderbird", "Network"),
    ("blender", "Blender", "3D modeling, animation and rendering", "blender", "Graphics"),
]
NOT_INSTALLED = {"luxai", "lsl-ide", "luxos-safe", "luxos-sandbox", "lsl", "luxos-docs", "luxos-maps",
                 "libreoffice-fresh", "gimp", "inkscape", "vlc", "obs-studio", "thunderbird", "blender"}


def main():
    data_dir, page = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "discover")
    repo = os.path.join(data_dir, "repo")
    apps_dir = os.path.join(data_dir, "applications")
    for d in (os.path.join(repo, "app-icons"), apps_dir):
        os.makedirs(d, exist_ok=True)
    os.environ["LUXOS_STORE_CATALOG_URL"] = "file://" + os.path.join(repo, "apps.json")

    loader = importlib.machinery.SourceFileLoader("luxos_store", os.path.join(FILES, "luxos-store"))
    spec = importlib.util.spec_from_loader("luxos_store", loader)
    store = importlib.util.module_from_spec(spec)
    loader.exec_module(store)
    store.APPLICATIONS_DIR = apps_dir + "/"
    store.LOCAL_CATALOGS = ()

    catalog = source_catalog.source_catalog()
    catalog["apps"] = [a for a in catalog["apps"] if a["id"] not in HIDDEN and a["package"] not in HIDDEN]
    # snimky aplikaci z packages/luxos-store/screens (manifest jako na serveru: app-screens/<id>/...)
    try:
        manifest = json.load(open(os.path.join(SCREENS, "manifest.json"), encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    if os.path.isdir(SCREENS):
        shutil.copytree(SCREENS, os.path.join(repo, "app-screens"), dirs_exist_ok=True)
    for a in catalog["apps"]:
        shots = manifest.get(a["id"]) or []
        if shots:
            a["screenshots"] = [dict({"url": "app-screens/%s/%s" % (a["id"], s["file"]), "width": s["width"],
                                      "height": s["height"]},
                                     **({"dark": "app-screens/%s/%s" % (a["id"], s["dark"])} if s.get("dark") else {}))
                                for s in shots]
    with open(os.path.join(repo, "apps.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False)

    sync = {a["package"]: ("luxos-apps" if a["package"] in ("luxai", "lsl-ide") else "luxos") for a in catalog["apps"]}
    sync["luxos-desktop"] = "luxos"
    rows = [(r, n, "1.0.1-1", "LuxOS package") for n, r in sorted(sync.items())]
    rows += [("extra", p[0], "1.0-1", p[2]) for p in POPULAR]
    installed = sorted({r[1] for r in rows} - NOT_INSTALLED)
    for a in catalog["apps"]:
        if a["package"] in installed:
            with open(os.path.join(apps_dir, a["id"] + ".desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=true\nIcon=%s\n" % (a["name"], a["icon"]))

    def fake_run(*cmd, timeout=60):
        if cmd[0] == store.LUX_ALPM and "list" in cmd:
            return "".join("%s\t%s\t%s\t%d\t%s\n" % (r, n, v, 48 * 1048576, d) for r, n, v, d in rows)
        if cmd[0] == store.ENGINE and cmd[1] == "-Qq":
            return "\n".join(installed) + "\n"
        if cmd[0] == store.ENGINE and cmd[1] == "-Ql":
            return "\n".join("%s %s%s.desktop" % (a["package"], store.APPLICATIONS_DIR, a["id"])
                             for a in catalog["apps"] if a["package"] in cmd[2:]) + "\n"
        if cmd[0] == "curl" and any(str(c).startswith("file://") for c in cmd):
            import subprocess
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
        if cmd[0] == "lux" and cmd[1:] == ("__index",):
            return "{}"
        return ""

    class FakePool:
        def load(self):
            pass

        def get_components_by_kind(self, _kind):
            comps = []
            for pkg, name, summary, icon, cat in POPULAR:
                c = AppStream.Component()
                c.set_kind(AppStream.ComponentKind.DESKTOP_APP)
                c.set_pkgnames([pkg])
                c.set_id(pkg + ".desktop")
                c.set_name(name, "C")
                c.set_summary(summary, "C")
                c.add_category(cat)
                ic = AppStream.Icon()
                ic.set_kind(AppStream.IconKind.STOCK)
                ic.set_name(icon)
                c.add_icon(ic)
                comps.append(c)

            class Box:
                def as_array(self):
                    return comps
            return Box()

    store.run = fake_run
    store.AppStream.Pool = FakePool
    store.Catalog.check_updates = lambda catalog: (setattr(catalog, "update_info", {}),
                                                   setattr(catalog, "updates", [])) and True

    GLib.set_prgname("luxos-store")
    provider = Gtk.CssProvider()
    provider.load_from_data(store.CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win = store.Store()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()

    def open_page():
        if not win.catalog.apps:
            return True
        if page.startswith("app:"):
            app = next((a for a in win.catalog.apps.values() if a.luxos and a.desktop == page[4:]), None)
            if app:
                win.show_detail(app) if hasattr(win, "show_detail") else win.show_page("app", app)
        elif page != "discover":
            win.show_page(page)
        return False
    GLib.timeout_add(400, open_page)
    Gtk.main()


if __name__ == "__main__":
    main()
