#!/usr/bin/env python3
"""A/B kontrola rezerv pameti v testovaci 4GB VM, nikoli na pracovnim pocitaci.

    watermark-probe.py USER [PRESSURE_MIB [FACTOR ...]]

Docasne meni watermark_scale_factor (125/10), puvodni hodnotu nakonec obnovi.
Behem tlaku meri dostupnou pamet, PSI, direct reclaim a odezvu serveru X.
"""
import json
import os
from pathlib import Path
import pwd
import statistics
import subprocess
import sys
import time


def meminfo():
    return {s.split(":")[0]: int(s.split()[1]) for s in Path("/proc/meminfo").read_text().splitlines()}


def vmstat():
    return {s.split()[0]: int(s.split()[1]) for s in Path("/proc/vmstat").read_text().splitlines()}


def psi():
    return {s.split()[0]: int(s.split("total=")[1])
            for s in Path("/proc/pressure/memory").read_text().splitlines()}


def main():
    if os.geteuid() != 0 or not 3000 <= meminfo()["MemTotal"] // 1024 <= 4500:
        raise SystemExit("Run only as root inside the disposable 4GB VM")
    if subprocess.run(["systemd-detect-virt", "--vm", "--quiet"]).returncode:
        raise SystemExit("Refusing to run on a physical machine")
    user = sys.argv[1]
    account = pwd.getpwnam(user)
    pressure = int(sys.argv[2]) if len(sys.argv) > 2 else 2600
    if not 0 < pressure <= 3000:
        raise SystemExit("PRESSURE_MIB must be between 1 and 3000")
    factors = list(map(int, sys.argv[3:])) or [125, 10]
    if any(factor not in (10, 125) for factor in factors):
        raise SystemExit("FACTOR must be 10 or 125")
    env = dict(os.environ, DISPLAY=":0", XAUTHORITY=account.pw_dir + "/.Xauthority")
    setting = Path("/proc/sys/vm/watermark_scale_factor")
    original = setting.read_text()
    workload = """
import mmap, os, sys, time
size = int(sys.argv[1]) * 1024 * 1024
m = mmap.mmap(-1, size)
for offset in range(0, size, 1024 * 1024):
    m[offset:offset+1024*1024] = os.urandom(1024*1024)
print('ready', flush=True)
time.sleep(30)
"""
    try:
        for factor in factors:
            setting.write_text(str(factor))
            time.sleep(2)
            before = meminfo()
            start_vm, start_psi = vmstat(), psi()
            start = time.monotonic()
            child = subprocess.Popen(["runuser", "-u", user, "--", sys.executable,
                                      "-c", workload, str(pressure)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                if child.stdout.readline().strip() != "ready":
                    raise RuntimeError("Memory workload failed before becoming ready: " + child.stderr.read())
                allocation_s = time.monotonic() - start
                samples = []
                for _ in range(10):
                    t = time.monotonic()
                    subprocess.run(["runuser", "-u", user, "--", "xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=5)
                    samples.append((time.monotonic() - t) * 1000)
                    time.sleep(0.3)
                after, end_vm, end_psi = meminfo(), vmstat(), psi()
                print(json.dumps({"factor": factor, "pressure_mib": pressure,
                      "idle_used_mib": round((before["MemTotal"]-before["MemAvailable"])/1024, 1),
                      "available_under_load_mib": round(after["MemAvailable"]/1024, 1),
                      "swap_used_mib": round((after["SwapTotal"]-after["SwapFree"])/1024, 1),
                      "allocation_s": round(allocation_s, 2), "x_roundtrip_median_ms": round(statistics.median(samples), 2),
                      "x_roundtrip_max_ms": round(max(samples), 2),
                      "allocstall": sum(end_vm[k]-v for k, v in start_vm.items() if k.startswith("allocstall_")),
                      "psi_some_ms": round((end_psi["some"]-start_psi["some"])/1000, 1),
                      "psi_full_ms": round((end_psi["full"]-start_psi["full"])/1000, 1)}), flush=True)
            finally:
                # Ukoncit konkretni zatezovy proces, ne uzivatelske aplikace ani sluzby.
                child.terminate()
                child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()
    finally:
        setting.write_text(original)


if __name__ == "__main__":
    main()
