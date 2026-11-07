"""LSL IDE: maly ukazkovy projekt (nakupni seznam ve dvou souborech), vystup programu po F5
a kontrola chyb prekladacem. IDE ze zdrojoveho archivu packages/apps/lsl-ide (rozbaleny do s.tmp,
spusteny jako /usr/bin/lsl-ide z balicku), prekladac = nainstalovany lsl (zavislost balicku).
Svetly motiv One Light (vychozi Neon je tmavy), anglicke rozhrani."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402


# Spoustec IDE: jako lslide/__main__.py, jen po zobrazeni okna zvetsi panel Vystup (jako kdyby uzivatel
# pretahl delic - v xvfb tazeni mysi delic nechyti); rozlozeni si IDE samo pamatuje v ui/state.
LAUNCHER = r'''
import sys
sys.path.insert(0, %(src)r)
from PySide6 import QtCore
from lslide import app as A

_show = A.MainWindow.show


def show(self):
    _show(self)

    def layout():
        # panely Agent a Cloud LuxAI (bez uctu prazdne) zavrene - jinak urcuji nejmensi vysku okna
        for dock in (self.agent_dock, self.cloud_dock, self.outline_dock):
            dock.hide()
        self.resizeDocks([self.bottom_dock], [%(panel)d], QtCore.Qt.Orientation.Vertical)
        self.resizeDocks([self.project_dock], [200], QtCore.Qt.Orientation.Horizontal)
    QtCore.QTimer.singleShot(800, layout)


A.MainWindow.show = show
sys.exit(A.main(sys.argv))
'''


def shots(s):
    src = _a.extract(s, "apps/lsl-ide/lsl-ide-1.0.0.tar.gz", "lsl-ide")
    project = os.path.join(s.home, "Projects", "shopping-list")
    main = _a.demo_lsl_project(s)
    s.write(".config/lsl-ide/lsl-ide.conf",
            "[check]\nenabled=true\n\n"
            "[editor]\nfont_size=11\n\n"
            "[project]\nfolder=%s\n\n"
            "[session]\nrestore=false\n\n"
            "[ui]\nlang=en\ntheme=one-light\n" % project)
    s.env.update({"LSL_IDE_LANG": "en", "QT_QPA_PLATFORM": "xcb", "QT_ACCESSIBILITY": "0"})
    launcher = os.path.join(s.tmp, "lsl-ide-launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"src": src, "panel": 330})
    p = s.launch([sys.executable, launcher, project, main], cwd=project)
    win = s.window(pid=p.pid, size=(1180, 740))
    s.sleep(3.0)
    # vychozi okno 1280x820 je vyssi nez obrazovka: cela obrazovka (F11) = presne 1280x800
    s.key("F11", win, delay=1.5)
    s.key("F5", win, delay=3.0)
    # kurzor na promenne items (radek 5): panel Symbol pod kurzorem ukaze prirazeni a vyskyty
    # (u klicovych slov odkazuje na kapitoly manualu LSL, ktery je jen cesky)
    s.click(318, 245, win, delay=1.0)
    s.capture("1", win)
    # preklep: kontrola na pozadi ukaze chybu prekladace (tecka u radku, vlnovka, "1 error");
    # panel Problemy ne - zahlavi sloupcu Zavaznost/Kod neni prelozene
    s.click(700, 392, win)
    s.key("End", win)
    s.type(" +", win, delay=3.0)
    s.capture("2", win)
