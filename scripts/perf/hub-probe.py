#!/usr/bin/env python3
"""LuxOS - mereni procesu relace luxos-hub ve VM (spousti root v hostu pres vmctl.py exec).

  hub-probe.py [USER] [IDLE_SECONDS]

Pro bezici luxos-hub uzivatele zmeri:
  - klidovou pamet (RSS, PSS, anonymni PSS) a pocet vlaken,
  - CPU cas od startu procesu a CPU za IDLE_SECONDS klidu, probuzeni za sekundu,
  - cas od kliknuti v liste (luxos-cc-toggle / luxos-calendar-toggle) do viditelneho okna
    (teple: okno uz je predpripravene), medián z 5 opakovani,
  - pamet procesu s obema otevrenymi okny.
Okna se nakonec zavrou. Vysledek: JSON na stdout.
"""
import json
import os
import pwd
import subprocess
import sys
import time

user = sys.argv[1] if len(sys.argv) > 1 else "lux"
idle = float(sys.argv[2]) if len(sys.argv) > 2 else 60
pw = pwd.getpwnam(user)
ENV = dict(os.environ, DISPLAY=":0", XAUTHORITY=f"{pw.pw_dir}/.Xauthority", HOME=pw.pw_dir, USER=user, LOGNAME=user,
           XDG_RUNTIME_DIR=f"/run/user/{pw.pw_uid}", DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{pw.pw_uid}/bus",
           LANG="cs_CZ.UTF-8")
HZ = os.sysconf("SC_CLK_TCK")


def as_user(cmd, **kw):
    return subprocess.run(["runuser", "-u", user, "--"] + cmd, env=ENV, capture_output=True, text=True, timeout=20, **kw)


def hub_pid():
    with open(f"/run/user/{pw.pw_uid}/luxos-hub.pid") as f:
        return int(f.read().strip())


def mem(pid):
    out = {}
    with open(f"/proc/{pid}/smaps_rollup") as f:
        for line in f:
            k = line.split(":")[0]
            if k in ("Rss", "Pss", "Pss_Anon", "Pss_File"):
                out[k] = int(line.split()[1])
    return out


def cpu(pid):
    with open(f"/proc/{pid}/stat") as f:
        st = f.read()
    fl = st[st.rindex(")") + 2:].split()
    return (int(fl[11]) + int(fl[12])) * 1000 / HZ, int(fl[17])


def switches(pid):
    n = 0
    for d in os.listdir(f"/proc/{pid}/task"):
        with open(f"/proc/{pid}/task/{d}/status") as f:
            for line in f:
                if "ctxt_switches:" in line:
                    n += int(line.split()[1])
    return n


def visible_window(cls):
    """Okno s WM_CLASS cls, ktere je mapovane (xdotool search --onlyvisible)."""
    r = as_user(["xdotool", "search", "--onlyvisible", "--class", cls])
    return bool(r.stdout.strip())


def toggle_time(command, cls):
    """ms od spusteni prepinace do viditelneho okna; okno se pak zase zavre."""
    t0 = time.monotonic()
    subprocess.Popen(["runuser", "-u", user, "--", command], env=ENV)
    while time.monotonic() - t0 < 5:
        if visible_window(cls):
            break
        time.sleep(0.005)
    dt = (time.monotonic() - t0) * 1000
    time.sleep(0.4)
    as_user([command])
    time.sleep(0.6)
    return dt


pid = hub_pid()
with open(f"/proc/{pid}/cmdline") as f:
    cmdline = f.read().replace("\0", " ").strip()
res = {"pid": pid, "cmdline": cmdline, "threads": cpu(pid)[1], "idle_mem_kb": mem(pid), "cpu_since_start_ms": cpu(pid)[0]}
c0, s0 = cpu(pid)[0], switches(pid)
time.sleep(idle)
res["idle_seconds"] = idle
res["idle_cpu_ms"] = round(cpu(pid)[0] - c0, 1)
res["idle_wakeups_per_s"] = round((switches(pid) - s0) / idle, 2)
# teple okno: prvni prepnuti vytvori okno az kdyz nebylo predpripravene (po 6 s od startu uz je)
times = {"cc": [], "cal": []}
for _ in range(5):
    times["cc"].append(toggle_time("luxos-cc-toggle", "luxos-control-center"))
    times["cal"].append(toggle_time("luxos-calendar-toggle", "luxos-calendar"))
res["toggle_ms"] = {k: {"median": round(sorted(v)[len(v) // 2], 1), "all": [round(x, 1) for x in v]} for k, v in times.items()}
# pamet s obema otevrenymi okny
as_user(["luxos-cc-toggle"])
time.sleep(0.8)
as_user(["luxos-calendar-toggle"])
time.sleep(1.5)
res["both_open"] = {"cc": visible_window("luxos-control-center"), "cal": visible_window("luxos-calendar")}
res["both_open_mem_kb"] = mem(pid)
as_user(["luxos-cc-toggle"])
as_user(["luxos-calendar-toggle"])
time.sleep(1.0)
res["after_close_mem_kb"] = mem(pid)
res["cpu_total_ms"] = cpu(pid)[0]
print(json.dumps(res, indent=1))
