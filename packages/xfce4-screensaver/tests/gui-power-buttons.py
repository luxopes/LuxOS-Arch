#!/usr/bin/env python3
"""LuxOS - tlacitka Uspat / Restartovat / Vypnout na zamykaci obrazovce (xfce4-screensaver-dialog) v Xvfb.

    gcc -shared -fPIC -o fake-pam.so packages/xfce4-screensaver/tests/fake-pam.c
    python3 packages/xfce4-screensaver/tests/gui-power-buttons.py \\
        --dialog BUILD/src/xfce4-screensaver-dialog --fake-pam fake-pam.so [--shots DIR]

Chyba z 1.0.3: hned po probuzeni z uspani chybela na zamykaci obrazovce spodni tlacitka napajeni.
Dialog vznika pri probouzeni, kdy logind (a polkit) jeste nestihaji - dotaz CanSuspend/CanReboot/
CanPowerOff vyprsel nebo nevratil "yes", a o tlacitkach se rozhodlo jen jednou pri vytvoreni dialogu.
Ted se stav z logind zjistuje znovu (asynchronne) - pri zobrazeni, prijezdu prihlaseni, po probuzeni
(PrepareForSleep) a nekolikrat po sekunde.

Prostredi jako tests/gui-caps-lock.py (vlastni Xvfb, session D-Bus, HOME, napodobeny libpam).
Skutecny systemovy D-Bus ani logind se nikdy nepouzije:
  1. LUXOS_LOCK_DEMO_LOGIND (odpovedi po kolech dotazu): "na,yes" -> tlacitka se objevi; "challenge"
     -> zustanou skryta a opakovani po case prestane; "yes,challenge" -> skryji se (stav se opravdu
     zjistuje znovu); "timeout,timeout,yes" -> vyprseni stav nemeni, pak se objevi; probuzeni (SIGUSR1
     + klavesa) po skonceni opakovani zjisti stav znovu. Snimek: tlacitka jsou opravdu nakreslena.
  2. Napodobeny logind (org.freedesktop.login1) na vlastni sbernici v DBUS_SYSTEM_BUS_ADDRESS, bez
     LUXOS_LOCK_DEMO_USERS, tedy skutecny kod s D-Bus: logind nejdriv odpovida "na" a pak "yes"
     (jako po probuzeni) -> tlacitka se objevi; "challenge" -> skryta, po zmene na "yes" a signalu
     PrepareForSleep(false) se objevi; "yes" -> "challenge" + PrepareForSleep(false) -> skryji se;
     pomaly logind (odpoved az za 3 s) dialog neblokuje; bez logind na sbernici dialog bezi dal.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import argparse
import os
import re
import select
import signal
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader

import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
caps = SourceFileLoader("gui_caps_lock", os.path.join(HERE, "gui-caps-lock.py")).load_module()
REPO = caps.REPO
FAILS = caps.FAILS
check = caps.check
POWER = re.compile(r"luxos-lock: power (\S+) suspend=(\d) restart=(\d) shutdown=(\d)")

# napodobeny logind: CanSuspend/CanReboot/CanPowerOff vraci nastavenou odpoved (volitelne se
# zpozdenim), rozhrani lux.Test meni odpoved a vysle PrepareForSleep; kazdy dotaz na stdout
FAKE_LOGIND = r"""
import sys, gi
from gi.repository import Gio, GLib
XML = '''<node>
 <interface name="org.freedesktop.login1.Manager">
  <method name="CanSuspend"><arg type="s" direction="out"/></method>
  <method name="CanReboot"><arg type="s" direction="out"/></method>
  <method name="CanPowerOff"><arg type="s" direction="out"/></method>
  <signal name="PrepareForSleep"><arg type="b"/></signal>
 </interface>
 <interface name="lux.Test">
  <method name="Set"><arg type="s" direction="in"/><arg type="u" direction="in"/></method>
  <method name="Sleep"><arg type="b" direction="in"/></method>
 </interface>
</node>'''
state = {"answer": sys.argv[1], "delay": int(sys.argv[2])}
loop = GLib.MainLoop()
def call(conn, sender, path, iface, method, params, inv):
    if iface == "lux.Test" and method == "Set":
        state["answer"], state["delay"] = params.unpack()
        inv.return_value(None)
    elif iface == "lux.Test" and method == "Sleep":
        conn.emit_signal(None, "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                         GLib.Variant("(b)", params.unpack()))
        inv.return_value(None)
    else:
        a = state["answer"]
        print("CALL", method, a, flush=True)
        reply = lambda: inv.return_value(GLib.Variant("(s)", (a,))) or False
        if state["delay"]:
            GLib.timeout_add(state["delay"], reply)
        else:
            reply()
def acquired(conn, name):
    print("READY", flush=True)
def bus(conn, name):
    for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces:
        conn.register_object("/org/freedesktop/login1", i, call, None, None)
Gio.bus_own_name(Gio.BusType.SYSTEM, "org.freedesktop.login1", 0, bus, acquired, lambda *a: loop.quit())
loop.run()
"""


def power_lines(d):
    d.pump()
    return [POWER.match(l).groups() for l in d.lines if POWER.match(l)]


def visible(d):
    """(suspend, restart, shutdown) podle posledniho radku "power", nebo None."""
    p = power_lines(d)
    return tuple(int(x) for x in p[-1][1:]) if p else None


def wait_visible(d, want, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if visible(d) == want:
            return time.time() - t0
        time.sleep(0.05)
    return None


def wait_quiet(d, quiet=2.0, timeout=14.0):
    """Ceka, az prestanou dotazy (zadny novy radek "power" po dobu quiet)."""
    t0 = time.time()
    n, last = len(power_lines(d)), time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.1)
        m = len(power_lines(d))
        if m != n:
            n, last = m, time.time()
        elif time.time() - last >= quiet:
            return n
    return None


def bottom_shot(env, path):
    """Snimek a jas spodniho pasu obrazovky (tlacitka napajeni)."""
    caps.shot(env, path)
    s = cairo.ImageSurface.create_from_png(path)
    data, st, w, h = s.get_data(), s.get_stride(), s.get_width(), s.get_height()
    return [data[y * st + x * 4 + 1] for y in range(h - 150, h, 2) for x in range(0, w, 2)]


def demo(env, args, logind, size=(1280, 800)):
    return caps.Dialog(env, args.dialog, args.fake_pam, {"LUXOS_LOCK_DEMO_LOGIND": logind}, size)


def test_demo(args, base):
    env = caps.Env(base, "us")
    try:
        env.wallpaper("/usr/share/backgrounds/luxos/luxos-dark.jpg")

        # nejdriv "na" (logind jeste nestiha), pri dalsim dotazu "yes"
        d = demo(env, args, "na,yes")
        check(d.wid is not None, "dialog window shown")
        p = power_lines(d)
        check(bool(p) and p[0][0] == "na" and p[0][1:] == ("0", "0", "0"),
              f"first logind answer 'na' -> power buttons hidden: {p[:1]}")
        t = wait_visible(d, (1, 1, 1), 3)
        check(t is not None, f"next answer 'yes' -> Sleep, Restart and Shut Down appear: {power_lines(d)[-1:]}")
        n = wait_quiet(d)
        check(n is not None, f"no more logind queries once all buttons are confirmed ({n} rounds)")
        time.sleep(0.6)
        on = bottom_shot(env, os.path.join(env.dir, "power-on.png"))
        if args.shots:
            caps.shot(env, os.path.join(args.shots, "lock-power-after-retry.png"))
        d.close()

        # "challenge" (heslo spravce, napr. prihlaseny dalsi uzivatel): tlacitka skryta
        d = demo(env, args, "challenge")
        n = wait_quiet(d)
        check(n is not None and visible(d) == (0, 0, 0), f"'challenge' keeps the power buttons hidden: {visible(d)}")
        check(n is not None and 3 <= n <= 20, f"'challenge': retries are limited ({n} rounds)")
        time.sleep(0.3)
        off = bottom_shot(env, os.path.join(env.dir, "power-off.png"))
        diff = sum(1 for a, b in zip(on, off) if abs(a - b) > 40)
        check(diff > 300, f"buttons are really drawn after the retry (bottom strip differs in {diff} px)")
        d.close()

        # dalsi dotaz vrati "challenge" -> uz videna tlacitka zmizi (stav se zjistuje znovu)
        d = demo(env, args, "yes,challenge")
        p = power_lines(d)
        check(bool(p) and p[0][1:] == ("1", "1", "1"), f"'yes' first -> buttons shown: {p[:1]}")
        t = wait_visible(d, (0, 0, 0), 3)
        check(t is not None, "later 'challenge' -> buttons hidden again")
        d.close()

        # vyprseni dotazu stav nemeni, dalsi pokus "yes"
        d = demo(env, args, "timeout,timeout,yes")
        p = power_lines(d)
        check(bool(p) and p[0][0] == "timeout" and p[0][1:] == ("0", "0", "0"), f"timeout -> hidden: {p[:1]}")
        t = wait_visible(d, (1, 1, 1), 4)
        check(t is not None, f"after timeouts the next 'yes' shows the buttons ({t})")
        d.close()

        # opakovani skonci se stale "na"; probuzeni (SIGUSR1 + klavesa) zjisti stav znovu
        d = demo(env, args, ",".join(["na"] * 9 + ["yes"]))
        n = wait_quiet(d)
        check(n is not None and visible(d) == (0, 0, 0), f"still 'na' when retries stop ({n} rounds): hidden")
        d.p.send_signal(signal.SIGUSR1)
        time.sleep(0.2)
        d.type("x")
        t = wait_visible(d, (1, 1, 1), 8)
        check(t is not None, f"wake from sleep with the dialog open -> logind asked again, buttons appear ({t})")
        d.close()
    finally:
        env.close()


class FakeLogind:
    """Vlastni sbernice jako DBUS_SYSTEM_BUS_ADDRESS (session dbus-daemon) a napodobeny logind."""

    def __init__(self, env, answer, delay=0, own=True):
        self.procs = []
        r, w = os.pipe()
        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=" + str(w)],
                               pass_fds=(w,), env=env.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(w)
        self.procs.append(bus)
        addr = b""
        while not addr.endswith(b"\n"):
            if not select.select([r], [], [], 10)[0]:
                sys.exit("dbus-daemon (fake system bus) did not start")
            addr += os.read(r, 256)
        os.close(r)
        self.addr = addr.decode().strip()
        self.env = dict(env.env, DBUS_SYSTEM_BUS_ADDRESS=self.addr)
        self.calls = []
        self.p = None
        if own:
            self.p = subprocess.Popen([sys.executable, "-c", FAKE_LOGIND, answer, str(delay)], env=self.env,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            os.set_blocking(self.p.stdout.fileno(), False)
            self.procs.append(self.p)
            t0 = time.time()
            while time.time() - t0 < 10 and "READY" not in self.read():
                time.sleep(0.05)

    def read(self):
        try:
            data = self.p.stdout.read() if self.p else None
        except (OSError, ValueError):
            data = None
        if data:
            self.calls.extend(data.splitlines())
        return self.calls

    def gdbus(self, method, *args):
        r = subprocess.run(["gdbus", "call", "--system", "--dest", "org.freedesktop.login1", "--object-path",
                            "/org/freedesktop/login1", "--method", "lux.Test." + method, *args],
                           env=self.env, capture_output=True, text=True, timeout=10)
        check(r.returncode == 0, f"fake logind {method} {args} {r.stderr.strip()}")

    def close(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()


def real(env, args, fake):
    """Dialog bez LUXOS_LOCK_DEMO_USERS: skutecny dotaz na (napodobeny) logind pres D-Bus."""
    return caps.Dialog(env, args.dialog, args.fake_pam, {"DBUS_SYSTEM_BUS_ADDRESS": fake.addr},
                       drop_env=("LUXOS_LOCK_DEMO_USERS",))


def test_logind(args, base):
    env = caps.Env(base, "us")
    try:
        env.wallpaper("/usr/share/backgrounds/luxos/luxos-dark.jpg")

        # jako po probuzeni: logind nejdriv "na", za chvili "yes"
        fake = FakeLogind(env, "na")
        d = real(env, args, fake)
        check(d.wid is not None, "logind: dialog window shown")
        t = wait_visible(d, (0, 0, 0), 3)
        check(t is not None, "logind 'na' -> buttons hidden")
        fake.gdbus("Set", "yes", "0")
        t = wait_visible(d, (1, 1, 1), 3)
        check(t is not None, f"logind answers 'yes' a moment later -> buttons appear without relocking ({t})")
        check(any(c.startswith("CALL CanSuspend") for c in fake.read())
              and any(c.startswith("CALL CanReboot") for c in fake.calls)
              and any(c.startswith("CALL CanPowerOff") for c in fake.calls), "asked CanSuspend/CanReboot/CanPowerOff")
        n = wait_quiet(d)
        k = len(fake.read())
        time.sleep(2.5)
        check(n is not None and len(fake.read()) == k, f"no polling after all buttons are confirmed ({k} calls)")
        d.close()
        fake.close()

        # "challenge": skryta; opakovani skonci; po zmene na "yes" az PrepareForSleep(false) dotaz zopakuje
        fake = FakeLogind(env, "challenge")
        d = real(env, args, fake)
        n = wait_quiet(d)
        check(n is not None and visible(d) == (0, 0, 0), f"logind 'challenge' -> buttons hidden ({n} answers)")
        fake.gdbus("Set", "yes", "0")
        time.sleep(1.5)
        check(visible(d) == (0, 0, 0), "no endless polling: nothing asked after the retries ended")
        fake.gdbus("Sleep", "true")
        time.sleep(0.5)
        check(visible(d) == (0, 0, 0), "PrepareForSleep(true) (going to sleep) does not ask")
        fake.gdbus("Sleep", "false")
        t = wait_visible(d, (1, 1, 1), 3)
        check(t is not None, f"PrepareForSleep(false) after resume -> logind asked again, buttons appear ({t})")
        # ... a obracene: "challenge" po probuzeni tlacitka skryje
        fake.gdbus("Set", "challenge", "0")
        fake.gdbus("Sleep", "false")
        t = wait_visible(d, (0, 0, 0), 3)
        check(t is not None, "'challenge' after resume hides the buttons again")
        d.close()
        fake.close()

        # pomaly logind (odpoved za 3 s): dialog neblokuje, tlacitka prijdou pozdeji
        fake = FakeLogind(env, "yes", 3000)
        t0 = time.time()
        d = real(env, args, fake)
        ready = time.time() - t0
        check(d.wid is not None and d.state().get("focus") == "1" and ready < 2.5,
              f"slow logind does not delay the dialog ({ready:.1f} s)")
        t = wait_visible(d, (1, 1, 1), 6)
        check(t is not None, f"slow logind: buttons appear once it answers ({t})")
        d.close()
        fake.close()

        # zadny logind na sbernici: tlacitka skryta, dialog bezi a odemkne
        fake = FakeLogind(env, "", own=False)
        d = real(env, args, fake)
        check(d.wid is not None and d.state().get("focus") == "1", "no logind: dialog shown and focused")
        time.sleep(1.5)
        check(visible(d) in (None, (0, 0, 0)), f"no logind: power buttons hidden ({visible(d)})")
        d.type("luxos")
        d.key("Return")
        t0 = time.time()
        while d.alive() and time.time() - t0 < 6:
            d.pump(0.1)
        d.pump(0.2)
        check(not d.alive() and any("RESPONSE=OK" in l for l in d.out), "no logind: correct password still unlocks")
        d.close()
        fake.close()
    finally:
        env.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialog", required=True)
    ap.add_argument("--fake-pam", required=True)
    ap.add_argument("--shots")
    ap.add_argument("--only", choices=("demo", "logind"))
    args = ap.parse_args()
    args.fake_pam = os.path.abspath(args.fake_pam)
    base = os.environ.get("LUXOS_TEST_TMP") or os.path.join(REPO, "out")
    os.makedirs(base, exist_ok=True)
    if os.path.realpath(base).startswith("/tmp"):
        sys.exit("refusing: temporary files must not be in /tmp")
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    if args.only != "logind":
        test_demo(args, base)
    if args.only != "demo":
        test_logind(args, base)
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
