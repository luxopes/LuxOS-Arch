"""Spoustec jako Dock: klik do okna spusti aplikaci z .desktop pres g_app_info_launch s GdkAppLaunchContext
(GTK si na Waylandu vyzada token xdg-activation, StartupNotify=true).

  gtk-launcher.py SOUBOR.desktop
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

info = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])
win = Gtk.Window(title="Launcher")
win.set_default_size(300, 200)
win.connect("destroy", Gtk.main_quit)
box = Gtk.EventBox()
win.add(box)


def launch(*args):
    info.launch([], Gdk.Display.get_default().get_app_launch_context())
    print("launched", flush=True)


box.connect("button-press-event", launch)
win.show_all()
Gtk.main()
