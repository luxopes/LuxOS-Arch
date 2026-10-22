#!/usr/bin/env python3
"""LuxOS - doba spusteni aplikaci ve VM (spousti root v hostu pres vmctl.py exec).

  launch-probe.py [USER] [OPAKOVANI]

Pro kazdou aplikaci zmeri cas od spusteni prikazu do zobrazeni jejiho okna
(nove okno v _NET_CLIENT_LIST s WM_CLASS aplikace), pote ji zavre. Kazda
aplikace se spousti OPAKOVANI-krat (vychozi 3): prvni start je "studeny"
(knihovny jeste nejsou v mezipameti), dalsi "teple". Vypise i pocet forku
(/proc/stat) behem startu - kazdy sandbox glycin pro obrazek je dalsi proces.
"""
import os
import pwd
import shutil
import subprocess
import sys
import time

user = sys.argv[1] if len(sys.argv) > 1 else "lux"
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
pw = pwd.getpwnam(user)
ENV = dict(os.environ, DISPLAY=":0", XAUTHORITY=f"{pw.pw_dir}/.Xauthority", HOME=pw.pw_dir, USER=user, LOGNAME=user,
           XDG_RUNTIME_DIR=f"/run/user/{pw.pw_uid}", DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{pw.pw_uid}/bus",
           LANG="cs_CZ.UTF-8")
# aplikace: prikaz, hledany retezec ve WM_CLASS
APPS = [
    (["xfce4-terminal"], "xfce4-terminal"),
    (["thunar"], "thunar"),
    (["mousepad"], "mousepad"),
    (["luxos-control-center"], "luxos-control-center"),
    (["luxos-launchpad"], "rofi"),          # Launchpad = rofi (drun s ikonami)
    (["luxos-settings"], "luxos-settings"),
    (["luxos-calendar"], "luxos-calendar"),
]


def forks():
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("processes "):
                return int(line.split()[1])
    return 0


polls = 0   # vlastni procesy sondy (xprop, xwininfo) - odecitaji se od poctu forku


def xprop(*args):
    global polls
    polls += 1
    try:
        return subprocess.run(["xprop"] + list(args), env=ENV, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def override_window(cls):
    """Okno bez spravce oken (rofi: override-redirect, neni v _NET_CLIENT_LIST): xdotool search."""
    global polls
    polls += 1
    try:
        out = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], env=ENV, capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.split()[0] if out.split() else None


def windows():
    out = xprop("-root", "_NET_CLIENT_LIST")
    return set(w.strip().rstrip(",") for w in out.split("#", 1)[1].split()) if "#" in out else set()


def demote():
    os.setgid(pw.pw_gid)
    os.initgroups(user, pw.pw_gid)
    os.setuid(pw.pw_uid)


for cmd, cls in APPS:
    if not shutil.which(cmd[0]):
        print(f"{' '.join(cmd):26s} not installed")
        continue
    times = []
    for i in range(reps):
        before = windows()
        f0 = forks()
        t0 = time.monotonic()
        p = subprocess.Popen(cmd, env=ENV, preexec_fn=demote, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        win = None
        polls = 0
        while time.monotonic() - t0 < 20:
            if cls == "rofi":
                win = override_window(cls)
            else:
                for w in windows() - before:
                    if cls.lower() in xprop("-id", w, "WM_CLASS").lower():
                        win = w
                        break
            if win:
                break
            time.sleep(0.02)
        dt = time.monotonic() - t0
        nf = forks() - f0 - polls
        times.append(dt if win else None)
        # okno zavrit (aplikace LuxOS se zaviraji Esc, jine pres WM_DELETE)
        if win and cls == "rofi":
            time.sleep(0.5)
            subprocess.run(["pkill", "-u", user, "-x", "rofi"], capture_output=True)
        elif win:
            time.sleep(0.5)
            subprocess.run(["xdotool", "windowclose", win], env=ENV, capture_output=True) if os.path.exists("/usr/bin/xdotool") \
                else subprocess.run(["wmctrl", "-i", "-c", win], env=ENV, capture_output=True)
        time.sleep(1.0)
        if p.poll() is None:
            try:
                os.killpg(p.pid, 15)
            except OSError:
                pass
        time.sleep(0.5)
        print(f"  {' '.join(cmd):24s} run {i + 1}: {'%.2f s' % dt if win else 'NO WINDOW':>10s}  forks {nf}", flush=True)
    ok = [t for t in times if t is not None]
    if ok:
        print(f"{' '.join(cmd):26s} cold {ok[0]:.2f} s, warm {min(ok[1:] or ok):.2f} s")
