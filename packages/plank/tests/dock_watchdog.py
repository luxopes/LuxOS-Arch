#!/usr/bin/env python3
"""LuxOS - hlidac animace Docku: zastavene hodiny snimku behem odkryti/zvetseni.

Spousti se UVNITR izolovane relace (session.sh) s opravenym Plankem. Plank dostane
LUXOS_PLANK_TEST_STALL_AFTER=T: prvni snimek animace po T s se zachova, jako by hodiny snimku
(Gdk.FrameClock) prestaly tikat. Test v te chvili jezdi mysi po ikonach (odkryti + zvetseni).

Ocekavani:
  --no-watchdog (LUXOS_PLANK_TEST_NO_WATCHDOG=1, chovani puvodniho Planku pri ztrate ticku):
      Dock zustane zamrzly - zvetseni nesleduje mys a po odchodu mysi se neschova.
  vychozi (s hlidacem): do ~1.5 s se animace obnovi, zvetseni sleduje mys, Dock se schova,
      v logu je "Animation stalled".

Pouziti: dock_watchdog.py PRACOVNI_ADRESAR PLANK [--no-watchdog]
Navratovy kod: 0 = chovani odpovida ocekavani, 1 = neodpovida.
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dock_stress import COVER_PY, Fb, H, W, gset, mouse  # noqa: E402

APPS = ["firefox", "chromium", "luxai", "luxos-launchpad", "luxos-calculator", "luxos-maps",
        "luxos-mail", "luxos-monitor"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("plank")
    ap.add_argument("--no-watchdog", action="store_true")
    ap.add_argument("--stall-after", type=float, default=6.0)
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    cfg = os.environ["XDG_CONFIG_HOME"]
    assert cfg.startswith(work), "XDG_CONFIG_HOME musi byt v pracovnim adresari"
    launch = os.path.join(cfg, "plank/dock1/launchers")
    os.makedirs(launch, exist_ok=True)
    apps = [p for p in APPS if os.path.exists(f"/usr/share/applications/{p}.desktop")]
    for p in apps:
        with open(os.path.join(launch, f"{p}.dockitem"), "w") as fh:
            fh.write(f"[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/{p}.desktop\n")
    gset("dock-items", "[" + ",".join(f"'{p}.dockitem'" for p in apps) + "]")
    for k, v in [("theme", "'Default'"), ("icon-size", "48"), ("zoom-enabled", "true"),
                 ("zoom-percent", "150"), ("hide-mode", "'window-dodge'"), ("unhide-delay", "0"),
                 ("hide-delay", "300"), ("tooltips-enabled", "false")]:
        gset(k, v)
    cover = subprocess.Popen([sys.executable, "-c", COVER_PY, "cover", "0", "0", str(W), str(H)])
    time.sleep(1.0)
    env = dict(os.environ, LUXOS_PLANK_TEST_STALL_AFTER=str(a.stall_after))
    if a.no_watchdog:
        env["LUXOS_PLANK_TEST_NO_WATCHDOG"] = "1"
    log_path = os.path.join(work, "plank-watchdog.log")
    log = open(log_path, "w")
    t_start = time.monotonic()
    plank = subprocess.Popen([a.plank], stdout=log, stderr=subprocess.STDOUT, env=env)
    fb = Fb(os.path.join(work, "fb", "Xvfb_screen0"))
    time.sleep(3.0)
    # kalibrace
    mouse(W // 2, H - 1)
    time.sleep(1.0)
    cols = fb.dock_columns()
    mouse(W // 2, 150)
    time.sleep(1.5)
    if not cols:
        print("FAIL: Dock se neukazal")
        plank.kill()
        cover.kill()
        return 1
    x0, x1 = cols
    # odkryti + pohyb po ikonach pres okamzik zastaveni hodin
    while time.monotonic() - t_start < a.stall_after - 0.4:
        time.sleep(0.05)
    mouse(x0 + 20, H - 1)
    t_end = t_start + a.stall_after + 2.0
    i = 0
    while time.monotonic() < t_end:
        i += 1
        mouse(x0 + 20 + (i * 17) % max(1, x1 - x0 - 40), H - 1)
        time.sleep(0.01)
    # zvetseni musi sledovat mys
    xa, xb = x0 + (x1 - x0) * 0.2, x0 + (x1 - x0) * 0.8
    mouse(xa, H - 3)
    time.sleep(1.6)
    ca = fb.zoom_center()
    mouse(xb, H - 3)
    time.sleep(1.6)
    cb = fb.zoom_center()
    # spicka zvetsene ikony se musi posunout aspon o polovinu cesty mysi
    zoom_follows = ca is not None and cb is not None and cb - ca > (xb - xa) * 0.5
    # po odchodu se Dock musi schovat (okno pres celou obrazovku)
    mouse(W // 2, 150)
    hidden = False
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3.0:
        if Fb.non_cover(fb.strip(6)) == 0:
            hidden = True
            break
        time.sleep(0.05)
    alive = plank.poll() is None
    plank.terminate()
    try:
        plank.wait(5)
    except subprocess.TimeoutExpired:
        plank.kill()
    cover.terminate()
    log.close()
    text = open(log_path, errors="replace").read()
    simulated = "simulating a stalled frame clock" in text
    recovered_msg = "Animation stalled" in text
    print(f"zoom center {ca} -> {cb} (mouse {xa:.0f} -> {xb:.0f})")
    print(f"stall simulated={simulated} zoom_follows={zoom_follows} hidden_after_leave={hidden} "
          f"watchdog_log={recovered_msg} alive={alive}")
    if not simulated or not alive:
        print("FAIL: zastaveni se nesimulovalo nebo Plank skoncil")
        return 1
    if a.no_watchdog:
        ok = not zoom_follows and not hidden
        print(("OK" if ok else "FAIL") + ": bez hlidace Dock zustal zamrzly (puvodni chovani)"
              if ok else "FAIL: bez hlidace se Dock neocekavane obnovil")
    else:
        ok = zoom_follows and hidden and recovered_msg
        print("OK: hlidac animaci obnovil" if ok else "FAIL: Dock se neobnovil")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
