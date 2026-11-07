"""Kalkulacka: zakladni rezim s vypoctem a vedecky rezim (Ctrl+2)."""


def shots(s):
    p = s.launch_python("luxos-desktop/files/bin/luxos-calculator")
    win = s.window(pid=p.pid, size=None)
    s.type("1250*1.21=", win)
    s.capture("1", win)
    s.key("Escape ctrl+2", win)
    s.type("2^10+(3.5*4)=", win)
    s.capture("2", win)
