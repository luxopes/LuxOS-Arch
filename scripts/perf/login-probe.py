#!/usr/bin/env python3
"""LuxOS - mereni prihlaseni ve VM (spousti root v hostu pres vmctl.py exec).

  login-probe.py OUT [USER] [SECONDS]

Kazdych 50 ms zaznamena (cas = /proc/uptime):
  - prvni vyskyt kazdeho procesu uzivatele (jmeno, pid),
  - prvni vyskyt oken v _NET_CLIENT_LIST (WM_CLASS) a vlastnosti _NET_WM_PID,
  - CPU uzivatele (soucet utime+stime) - konec "klidu" = kdy relace prestane pocitat.
Start relace = vznik procesu xfce4-session (nebo prvni proces uzivatele).
Vystup: JSON v OUT; souhrn se vypise na stdout.
"""
import glob
import json
import os
import pwd
import subprocess
import sys
import time

out = sys.argv[1]
user = sys.argv[2] if len(sys.argv) > 2 else "lux"
dur = float(sys.argv[3]) if len(sys.argv) > 3 else 40
uid = pwd.getpwnam(user).pw_uid
HZ = os.sysconf("SC_CLK_TCK")


def uptime():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def xenv():
    env = dict(os.environ, DISPLAY=":0")
    for cand in (f"/home/{user}/.Xauthority", "/run/lightdm/root/:0"):
        if os.path.exists(cand):
            env["XAUTHORITY"] = cand
            break
    return env


procs, wins, cpu = {}, {}, []
series = []
pcpu = {}   # pid -> (comm, posledni CPU v tickach, ppid)
seen_pids = set()
t_end = uptime() + dur
while uptime() < t_end:
    now = uptime()
    total = 0
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if os.stat(d).st_uid != uid:
                continue
            with open(d + "/stat") as f:
                st = f.read()
        except OSError:
            continue
        pid = int(d[6:])
        comm = st[st.index("(") + 1:st.rindex(")")]
        fields = st[st.rindex(")") + 2:].split()
        total += int(fields[11]) + int(fields[12])
        pcpu[pid] = (comm, int(fields[11]) + int(fields[12]), int(fields[1]))
        if pid not in seen_pids:
            seen_pids.add(pid)
            start = int(fields[19]) / HZ
            try:
                with open(d + "/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()[:160]
            except OSError:
                cmd = ""
            procs.setdefault(comm, []).append({"pid": pid, "start": start, "seen": now, "cmd": cmd})
    cpu.append((now, total / HZ))
    if len(cpu) % 20 == 1:   # asi kazdou sekundu: CPU podle jmena procesu (zive procesy)
        agg = {}
        for c, tk, _pp in pcpu.values():
            agg[c] = agg.get(c, 0) + tk
        series.append((now, agg))
    try:
        r = subprocess.run(["xprop", "-root", "_NET_CLIENT_LIST"], env=xenv(), capture_output=True,
                           text=True, timeout=2)
        ids = [w.strip().rstrip(",") for w in r.stdout.split("#", 1)[1].split()] if "#" in r.stdout else []
    except (OSError, subprocess.TimeoutExpired, IndexError):
        ids = []
    for w in ids:
        if w in wins:
            continue
        try:
            r = subprocess.run(["xprop", "-id", w, "WM_CLASS", "_NET_WM_NAME"], env=xenv(),
                               capture_output=True, text=True, timeout=2)
            wins[w] = {"seen": now, "props": r.stdout.strip().replace("\n", " | ")}
        except (OSError, subprocess.TimeoutExpired):
            pass
    time.sleep(0.05)

json.dump({"procs": procs, "wins": wins, "cpu": cpu, "pcpu": pcpu, "series": series}, open(out, "w"), indent=1)

# souhrn
starts = [p["start"] for v in procs.values() for p in v]
sess = [p["start"] for p in procs.get("xfce4-session", [])]
t0 = min(sess) if sess else (min(starts) if starts else 0)
print(f"t0 (session start, uptime) = {t0:.2f}")
for comm, v in sorted(procs.items(), key=lambda kv: kv[1][0]["start"]):
    p = v[0]
    print(f"  proc {p['start'] - t0:7.2f}s  x{len(v):<3d} {comm:22s} {p['cmd'][:70]}")
for w, v in sorted(wins.items(), key=lambda kv: kv[1]["seen"]):
    print(f"  win  {v['seen'] - t0:7.2f}s  {v['props'][:110]}")
# klid: posledni okno 1 s, kdy CPU uzivatele vzrostlo o > 5 % jednoho jadra
quiet = None
for i in range(len(cpu) - 1, 0, -1):
    j = i
    while j > 0 and cpu[i][0] - cpu[j][0] < 1.0:
        j -= 1
    if cpu[i][1] - cpu[j][1] > 0.05 * (cpu[i][0] - cpu[j][0]):
        quiet = cpu[i][0]
        break
by = {}
for comm, ticks, _pp in pcpu.values():
    by[comm] = by.get(comm, 0) + ticks
print("  CPU by process name (s, incl. short-lived, as last seen):")
for comm, ticks in sorted(by.items(), key=lambda kv: -kv[1])[:25]:
    print(f"    {ticks / HZ:6.2f}  {comm}")
if quiet:
    # kdo pocital v obdobi 10 s po startu az do konce
    a = next((x for x in series if x[0] - t0 >= 10), None)
    if a:
        b = series[-1]
        diff = sorted(((b[1].get(c, 0) - a[1].get(c, 0), c) for c in b[1]), reverse=True)[:8]
        print(f"  CPU from {a[0] - t0:.0f}s to {b[0] - t0:.0f}s: " + ", ".join(f"{c} {v / HZ:.2f}" for v, c in diff if v))
    print(f"  user CPU busy until {quiet - t0:.2f}s; CPU seconds used in window: {cpu[-1][1] - cpu[0][1]:.2f}")
