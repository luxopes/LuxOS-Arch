#!/usr/bin/env python3
"""LuxOS - snimek pameti celeho systemu (spoustet jako root v testovaci VM, viz docs/perf/os-memory.md).

  mem-snapshot.py OUT.json

meminfo (MemTotal - MemAvailable = "pouzito" jako free), PSS/USS/swap kazdeho procesu ze smaps_rollup
seskupene podle jmena programu (uzivatel / system), tmpfs, zram a nejvetsi slab cache. Soucet PSS
nepocita sdilene knihovny vickrat (na rozdil od souctu RSS). Cela data v OUT.json, souhrn na stdout.
"""
import collections, glob, json, os, re, sys


def kv(path):
    d = {}
    for line in open(path):
        k, _, v = line.partition(":")
        d[k.strip()] = int(v.split()[0]) if v.split() else 0
    return d


def name_of(pid):
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        cmd = [c.decode(errors="replace") for c in cmd if c]
    except OSError:
        return None
    if not cmd:
        return None  # kernel thread
    a0 = os.path.basename(cmd[0])
    if a0 in ("python3", "python", "bash", "sh", "env") and len(cmd) > 1:
        for c in cmd[1:]:
            if not c.startswith("-"):
                return os.path.basename(c) + ("" if a0 in ("env",) else f" ({a0})")
    if a0 == "wrapper-2.0" and len(cmd) > 2:
        return "panel:" + os.path.basename(cmd[2]).replace("lib", "").replace(".so", "")
    return a0


def unit_of(pid):
    try:
        cg = open(f"/proc/{pid}/cgroup").read().strip().split("::")[-1]
    except OSError:
        return "?"
    parts = cg.split("/")
    # /user.slice/user-1000.slice/session-2.scope, /user.slice/user-1000.slice/user@1000.service/app.slice/x.service
    for p in reversed(parts):
        if p.endswith((".service", ".scope")) and not p.startswith("user@"):
            return p
    return parts[-1] or "/"


rows = []
for d in glob.glob("/proc/[0-9]*"):
    pid = int(d[6:])
    n = name_of(pid)
    if n is None:
        continue
    try:
        r = kv(f"{d}/smaps_rollup")
        uid = os.stat(d).st_uid
    except (OSError, ValueError):
        continue
    rows.append(dict(pid=pid, name=n, unit=unit_of(pid), uid=uid, pss=r.get("Pss", 0),
                     uss=r.get("Private_Clean", 0) + r.get("Private_Dirty", 0), swap=r.get("Swap", 0),
                     rss=r.get("Rss", 0), anon=r.get("Pss_Anon", 0)))

mi = kv("/proc/meminfo")
zram = {}
for z in glob.glob("/sys/block/zram*/mm_stat"):
    v = open(z).read().split()
    zram[z.split("/")[3]] = dict(orig_kb=int(v[0]) // 1024, compr_kb=int(v[1]) // 1024, mem_used_kb=int(v[2]) // 1024)
shm = {}
for line in open("/proc/mounts"):
    dev, mnt, fs = line.split()[:3]
    if fs == "tmpfs":
        st = os.statvfs(mnt)
        shm[mnt] = (st.f_blocks - st.f_bfree) * st.f_frsize // 1024
slab = []
try:
    for line in open("/proc/slabinfo").readlines()[2:]:
        f = line.split()
        slab.append((int(f[2]) * int(f[3]) // 1024, f[0]))
except OSError:
    pass
slab.sort(reverse=True)

out = dict(meminfo=mi, used_kb=mi["MemTotal"] - mi["MemAvailable"], rows=rows, zram=zram, tmpfs=shm, slab_top=slab[:15])
json.dump(out, open(sys.argv[1], "w"), indent=1)

def mib(k):
    return f"{k / 1024:8.1f}"

print(f"MemTotal-MemAvailable: {mib(out['used_kb'])} MiB   MemFree {mib(mi['MemFree'])}  Cached {mib(mi['Cached'])}"
      f"  AnonPages {mib(mi['AnonPages'])}  Shmem {mib(mi['Shmem'])}  Slab {mib(mi['Slab'])} (unrecl {mib(mi['SUnreclaim'])})"
      f"  KernelStack {mib(mi['KernelStack'])}  PageTables {mib(mi['PageTables'])}  SwapUsed {mib(mi['SwapTotal'] - mi['SwapFree'])}")
tot = sum(r["pss"] for r in rows)
print(f"Sum PSS {mib(tot)}  sum USS {mib(sum(r['uss'] for r in rows))}  swap {mib(sum(r['swap'] for r in rows))}")
g = collections.defaultdict(lambda: [0, 0, 0, 0])
for r in rows:
    key = ("user " if r["uid"] >= 1000 else "sys  ") + r["name"]
    x = g[key]; x[0] += r["pss"]; x[1] += r["uss"]; x[2] += r["swap"]; x[3] += 1
print(f"{'group':48} {'PSS':>8} {'USS':>8} {'swap':>8}  n")
for k, v in sorted(g.items(), key=lambda kv_: -kv_[1][0]):
    print(f"{k[:48]:48} {mib(v[0])} {mib(v[1])} {mib(v[2])} {v[3]:2}")
print("tmpfs:", {k: v for k, v in shm.items() if v})
print("zram:", zram)
print("slab top:", ", ".join(f"{n} {k // 1024}M" for k, n in slab[:8]))
