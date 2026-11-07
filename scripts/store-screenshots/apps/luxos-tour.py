"""Prohlidka LuxOS: uvitani, horni lista a instalace aplikaci (stranky 1, 2 a 6, tlacitko Pokracovat = Enter).

Tlacitka prohlidky spousteji aplikace a luxos-appearance (cteni i zmena vzhledu) - v PATH jsou proto
falesne prikazy bez ucinku (luxos-appearance mode vypise "light"), aby se nic skutecneho nespustilo.
"""
import os

COMMANDS = ("luxos-cc-toggle", "luxos-launchpad", "luxos-search", "thunar", "luxos-safe", "luxos-store",
            "luxos-terminal", "luxos-settings", "luxdrop", "luxos-printers", "luxos-shortcuts", "luxos-feedback")


def shots(s):
    fake = os.path.join(s.tmp, "fakebin")
    os.makedirs(fake, exist_ok=True)
    for name in COMMANDS + ("luxos-appearance",):
        with open(os.path.join(fake, name), "w") as f:
            f.write('#!/bin/sh\n[ "$1" = mode ] && echo light\nexit 0\n' if name == "luxos-appearance"
                    else "#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(fake, name), 0o755)
    p = s.launch_python("luxos-desktop/files/bin/luxos-tour",
                        env={"PATH": fake + ":" + s.env.get("PATH", "/usr/bin:/bin")})
    win = s.window(pid=p.pid, size=None)
    s.sleep(1.0)
    s.capture("1", win)
    s.key("Return", win, delay=1.0)
    s.capture("2", win)
    for _ in range(4):
        s.key("Return", win, delay=0.6)
    s.sleep(0.6)
    s.capture("3", win)
