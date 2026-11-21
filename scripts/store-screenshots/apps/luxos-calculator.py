"""Kalkulacka: zakladni rezim s vypoctem a vedecky rezim (Ctrl+2)."""


def shots(s):
    p = s.launch([s.lslc("luxos-desktop/files/lsl/luxos-calculator.lsl")])
    win = s.window(pid=p.pid, size=None)
    s.type("1250*1.21=", win)
    s.capture("1", win)
    s.key("Escape ctrl+2", win)
    s.type("2^10+(3.5*4)=", win)
    s.capture("2", win)
