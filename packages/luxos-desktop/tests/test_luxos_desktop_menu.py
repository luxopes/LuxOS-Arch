#!/usr/bin/env python3
"""LuxOS - nabidka plochy s "Upravit widgety..." (GTK modul files/src/luxos-desktop-menu.c).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_desktop_menu.py -v

Vlastni Xvfb a docasny domov. Testovaci program napodobi nabidku plochy xfdesktop (podnabidka
Aplikace = GarconGtkMenu) a nabidku ikony, nacte modul jako GTK_MODULES a vypise polozky.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-desktop-menu.c")
WRAPPER = os.path.join(HERE, "..", "files", "override-bin", "xfdesktop")
I18N = os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

PROG = r'''
#include <gtk/gtk.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { GtkMenu parent; } Fake;
typedef struct { GtkMenuClass parent; } FakeClass;
G_DEFINE_TYPE (Fake, fake, GTK_TYPE_MENU)
static void fake_class_init (FakeClass *c) { (void) c; }
static void fake_init (Fake *f) { (void) f; }
static GtkWidget *item (GtkWidget *menu, const char *label) {
    GtkWidget *i = label ? gtk_menu_item_new_with_label (label) : gtk_separator_menu_item_new ();
    gtk_menu_shell_append (GTK_MENU_SHELL (menu), i);
    return i;
}
static void dump (const char *name, GtkWidget *menu) {
    /* jako pri otevreni nabidky: show_all ukaze jen polozky, "show" nabidky az zobrazeni */
    gtk_widget_show_all (menu);
    gtk_widget_show (menu);
    GList *kids = gtk_container_get_children (GTK_CONTAINER (menu));
    printf ("%s", name);
    for (GList *k = kids; k; k = k->next)
        printf ("|%s", GTK_IS_SEPARATOR_MENU_ITEM (k->data) ? "-" : gtk_menu_item_get_label (k->data));
    printf ("\n");
    g_list_free (kids);
}
int main (int argc, char **argv) {
    g_set_prgname (argv[2]);
    gtk_init (&argc, &argv);
    /* GarconGtkMenu az po gtk_init (jako ve xfdesktop knihovna garcon-gtk) */
    GType t = g_type_register_static_simple (GTK_TYPE_MENU, "GarconGtkMenu", sizeof (GtkMenuClass), NULL,
                                             sizeof (GtkMenu), NULL, 0);
    void *h = dlopen (argv[1], RTLD_NOW);
    void (*init) (gint *, gchar ***) = h ? (void (*) (gint *, gchar ***)) dlsym (h, "gtk_module_init") : NULL;
    if (!init)
        return 3;
    init (&argc, &argv);
    printf ("env|%s\n", g_getenv ("GTK_MODULES") ? g_getenv ("GTK_MODULES") : "");
    GtkWidget *desk = gtk_menu_new ();
    item (desk, "Paste"); item (desk, NULL); item (desk, "Open in New Window"); item (desk, NULL);
    item (desk, "Desktop Settings..."); item (desk, NULL);
    gtk_menu_item_set_submenu (GTK_MENU_ITEM (item (desk, "Applications")), g_object_new (t, NULL));
    dump ("desktop", desk);
    gtk_widget_hide (desk);
    dump ("again", desk);
    GtkWidget *icon = gtk_menu_new ();
    item (icon, "Open"); item (icon, NULL); item (icon, "Rename...");
    gtk_widget_hide (desk);
    dump ("icon", icon);
    (void) fake_get_type;
    return 0;
}
'''


def have():
    return all(shutil.which(t) for t in ("gcc", "pkg-config", "Xvfb")) and \
        subprocess.run(["pkg-config", "--exists", "gtk+-3.0"]).returncode == 0


@unittest.skipUnless(have(), "needs gcc, GTK 3 headers and Xvfb")
class DesktopMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-desktop-menu-")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True,
                               check=True).stdout.split()
        cls.mod = os.path.join(cls.t, "libluxos-desktop-menu.so")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-o", cls.mod, SRC, *flags], check=True)
        prog = os.path.join(cls.t, "prog.c")
        with open(prog, "w") as f:
            f.write(PROG)
        cls.bin = os.path.join(cls.t, "prog")
        subprocess.run(["gcc", "-O2", "-Wall", "-o", cls.bin, prog, *flags, "-ldl"], check=True)
        cls.fake = os.path.join(cls.t, "bin")
        os.makedirs(cls.fake)
        with open(os.path.join(cls.fake, "luxos-widgets"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(cls.fake, "luxos-widgets"), 0o755)
        os.makedirs(os.path.join(cls.t, "home"))
        cls.xvfb = subprocess.Popen(["Xvfb", ":86", "-screen", "0", "800x600x24", "-nolisten", "tcp"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["sleep", "1"])

    @classmethod
    def tearDownClass(cls):
        cls.xvfb.terminate()
        cls.xvfb.wait(timeout=10)
        shutil.rmtree(cls.t, True)

    def run_prog(self, prgname="xfdesktop", lang="C", widgets=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DBUS_", "XDG_", "LC_"))}
        env.update(DISPLAY=":86", HOME=os.path.join(self.t, "home"), LANG=lang, LUXOS_I18N_DIR=I18N,
                   GTK_MODULES="foo:luxos-desktop-menu", NO_AT_BRIDGE="1", GTK_THEME="Adwaita",
                   PATH=self.fake if widgets else os.path.join(self.t, "home"))
        r = subprocess.run([self.bin, self.mod, prgname], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(line.split("|", 1) for line in r.stdout.splitlines())

    def test_item_after_desktop_settings(self):
        out = self.run_prog()
        self.assertEqual(out["desktop"], "Paste|-|Open in New Window|-|Desktop Settings...|Edit Widgets…|-|Applications")
        self.assertEqual(out["again"], out["desktop"], "pri dalsim zobrazeni jen jednou")

    def test_icon_menu_untouched(self):
        self.assertEqual(self.run_prog()["icon"], "Open|-|Rename...")

    def test_translated(self):
        self.assertIn("Upravit widgety…", self.run_prog(lang="cs_CZ.UTF-8")["desktop"])

    def test_only_in_xfdesktop_and_with_widgets(self):
        self.assertNotIn("Edit Widgets", self.run_prog(prgname="thunar")["desktop"])
        self.assertNotIn("Edit Widgets", self.run_prog(widgets=False)["desktop"])

    def test_children_do_not_inherit_module(self):
        """Aplikace spustene z plochy modul nenacitaji (GTK_MODULES bez luxos-desktop-menu)."""
        self.assertEqual(self.run_prog()["env"], "foo")

    def test_wrapper_adds_module_once(self):
        with open(WRAPPER) as f:
            body = f.read()
        self.assertIn("exec /usr/bin/xfdesktop", body)
        fake = os.path.join(self.t, "wrap")
        with open(fake, "w") as f:
            f.write(body.replace("exec /usr/bin/xfdesktop \"$@\"", "echo \"$GTK_MODULES\""))
        for start, want in (("", "luxos-desktop-menu"), ("a", "a:luxos-desktop-menu"),
                            ("luxos-desktop-menu", "luxos-desktop-menu")):
            r = subprocess.run(["sh", fake], env={"GTK_MODULES": start, "PATH": "/usr/bin"},
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), want)


if __name__ == "__main__":
    unittest.main()
