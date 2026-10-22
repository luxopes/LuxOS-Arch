#!/usr/bin/env python3
"""LuxOS - klidova zatez relace ve VM (spousti root v hostu pres vmctl.py exec).

  idle-probe.py [USER] [SECONDS]

Za SECONDS (vychozi 60) zmeri pro procesy uzivatele: RSS (a PSS), CPU cas,
probuzeni (prepnuti kontextu voluntary+nonvoluntary) a pocet novych procesu
(pravidelne spousteni skriptu). Pro srovnani i soucet za cely system.
"""
import glob
import os
import pwd
import sys
import time

user = sys.argv[1] if len(sys.argv) > 1 else "lux"
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 60
uid = pwd.getpwnam(user).pw_uid
HZ = os.sysconf("SC_CLK_TCK")


def snap(only_uid=None):
    res = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if only_uid is not None and os.stat(d).st_uid != only_uid:
                continue
            with open(d + "/stat") as f:
                st = f.read()
            with open(d + "/status") as f:
                status = f.read()
        except OSError:
            continue
        comm = st[st.index("(") + 1:st.rindex(")")]
        fl = st[st.rindex(")") + 2:].split()
        if fl[0] == "Z":
            continue
        sw = 0
        rss = 0
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
        # probuzeni vsech vlaken procesu
        for t in glob.glob(d + "/task/*/status"):
            try:
                with open(t) as f:
                    for line in f:
                        if "ctxt_switches:" in line:
                            sw += int(line.split()[1])
            except OSError:
                pass
        res[int(d[6:])] = (comm, int(fl[11]) + int(fl[12]), sw, rss)
    return res


def pss(pid):
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def stat():
    """/proc/stat: (CPU jiffies celkem bez idle/iowait, pocet forku od startu)."""
    with open("/proc/stat") as f:
        cpu = forks = 0
        for line in f:
            if line.startswith("cpu "):
                v = [int(x) for x in line.split()[1:]]
                cpu = sum(v) - v[3] - v[4]
            elif line.startswith("processes "):
                forks = int(line.split()[1])
    return cpu, forks


a = snap(uid)
sa = snap()
st_a = stat()
time.sleep(dur)
b = snap(uid)
sb = snap()
st_b = stat()

rows = {}
for pid, (comm, cpu, sw, rss) in b.items():
    r = rows.setdefault(comm, [0, 0, 0, 0, 0])
    r[0] += 1
    r[1] += rss
    r[2] += pss(pid)
    if pid in a:
        r[3] += cpu - a[pid][1]
        r[4] += sw - a[pid][2]
new = [b[p][0] for p in b if p not in a]
print(f"{'process':24s} {'n':>2s} {'RSS MB':>7s} {'PSS MB':>7s} {'CPU ms':>7s} {'wakeups/s':>9s}")
tot = [0, 0, 0, 0]
for comm, r in sorted(rows.items(), key=lambda kv: -kv[1][2]):
    print(f"{comm:24s} {r[0]:2d} {r[1] / 1024:7.1f} {r[2] / 1024:7.1f} {r[3] * 1000 / HZ:7.0f} {r[4] / dur:9.2f}")
    tot = [tot[0] + r[1], tot[1] + r[2], tot[2] + r[3], tot[3] + r[4]]
print(f"{'TOTAL user ' + user:24s}    {tot[0] / 1024:7.1f} {tot[1] / 1024:7.1f} {tot[2] * 1000 / HZ:7.0f} {tot[3] / dur:9.2f}")
sys_cpu = sum(sb[p][1] - sa[p][1] for p in sb if p in sa)
sys_sw = sum(sb[p][2] - sa[p][2] for p in sb if p in sa)
print(f"whole system: CPU {sys_cpu * 1000 / HZ:.0f} ms in {dur:.0f} s ({sys_cpu * 100 / HZ / dur:.2f} % of one core), "
      f"{sys_sw / dur:.1f} wakeups/s (userspace tasks)")
print(f"new user processes during {dur:.0f} s: {len(new)} {sorted(set(new))[:20]}")
print(f"/proc/stat: CPU {(st_b[0] - st_a[0]) * 1000 / HZ:.0f} ms busy in {dur:.0f} s "
      f"({(st_b[0] - st_a[0]) * 100 / HZ / dur:.2f} % of one core incl. kernel), "
      f"forks: {st_b[1] - st_a[1]} ({(st_b[1] - st_a[1]) * 60 / dur:.0f}/min)")
with open("/proc/meminfo") as f:
    mi = {l.split(":")[0]: int(l.split()[1]) for l in f}
print(f"MemTotal-MemAvailable = {(mi['MemTotal'] - mi['MemAvailable']) / 1024:.0f} MB used")
