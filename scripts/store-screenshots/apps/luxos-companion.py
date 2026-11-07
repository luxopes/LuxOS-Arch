"""Telefon (LuxOS Companion): pripojeny ukazkovy telefon se sdilenim polohy a dotaz noveho telefonu.
Sluzba je skutecna service.Service ze zdroju bez Bluetooth (apps/_a_companion_service.py, socketpair
misto RFCOMM jako v testech, LuxAI = zastupny tests/fake-luxai)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def shots(s):
    trigger = os.path.join(s.tmp, "second-phone")
    s.env.update({"LUXOS_COMPANION_LUXAI": s.src("luxos-companion/tests/fake-luxai"),
                  "LUXOS_COMPANION_QUIET": "1", "GIO_USE_VFS": "local",
                  # BlueZ: neexistujici sbernice - nikdy skutecny Bluetooth pocitace
                  "LUXOS_COMPANION_BLUEZ_BUS": "unix:path=" + os.path.join(s.tmp, "no-bluez-bus")})
    s.python_env("luxos-companion/files")
    s.launch([sys.executable, os.path.join(HERE, "_a_companion_service.py"), trigger])
    s.sleep(2.5)
    p = _a.run_python(s, "luxos-companion/files/luxos-companion", paths=("luxos-companion/files",),
                      modules=("luxos_i18n",))
    win = s.window(pid=p.pid, size=(560, 620))
    s.sleep(1.5)
    s.capture("1", win)
    open(trigger, "w").close()
    s.sleep(1.5)
    s.capture("2", win)
