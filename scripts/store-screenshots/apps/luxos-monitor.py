"""Monitor systemu: karty Procesor/Pamet/Disk/Sit s grafem a seznam otevrenych aplikaci.

Seznam aplikaci ukazuje jen okna na virtualnim displeji xvfb - proto se nejdriv spusti nekolik
ukazkovych aplikaci LuxOS ze zdroju (Kalkulacka, Firewall s falesnym stavem, Sprava site s falesnou
siti). Prepinac "Vsechny procesy" (technicky vypis skutecnych procesu pocitace) se nezapina, nic se
neukoncuje. Karty ukazuji skutecne vytizeni pocitace, na kterem snimek vznika."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _recipe(name):
    spec = importlib.util.spec_from_file_location("shots_" + name.replace("-", "_"), os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shots(s):
    # ukazkove otevrene aplikace
    s.launch_python("luxos-desktop/files/bin/luxos-calculator")
    s.window(name="^Calculator$", size=None)
    router = _recipe("luxos-router")
    s.launch_python("luxos-desktop/files/bin/luxos-router", env=router.net_env(s, "net.json", "192.168.1.1"))
    s.window(cls="luxos-router", size=None)
    fw = _recipe("luxos-firewall-settings")
    fw.launch_demo(s)
    s.window(cls="luxos-firewall-settings", size=None)

    p = s.launch_python("luxos-desktop/files/bin/luxos-monitor")
    win = s.window(pid=p.pid, size=(1070, 640))
    s.sleep(62)                       # graf za posledni minutu se cely naplni
    s.capture("1", win)
