#!/usr/bin/env python3
"""luxos-lock (zamek obrazovky na Waylandu), luxos-lock-session a luxos-auth proti labwc headless (scripts/wl-test).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_lock.py -v

Nikdy skutecny PAM ani skutecne heslo: luxos-auth bezi s napodobenym libpam (tests/lock/fake-pam.c, LD_PRELOAD
v obalovem skriptu), logind je napodobeny (tests/lock/fake_logind.py) na soukrome sbernici dbus-daemon. Kompozitor
jen headless (wlt), klienti bez DISPLAY a bez sbernic skutecne relace. Snimky svetle/tmave tapety jdou do
out/wl-test/lock-shots (LUXOS_LOCK_SHOTS = jiny adresar).
Potrebuje lslc, gcc, libpam (hlavicky), labwc ze sysrootu wlt (scripts/wl-test/fetch-sysroot.sh) a python-dbus.
"""
import os
from pathlib import Path
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
HAVE_LABWC = (OUT / "sysroot/usr/bin/labwc").exists() or shutil.which("labwc")
HAVE_PAM = Path("/usr/include/security/pam_appl.h").exists()
try:
    import dbus  # noqa: F401  (napodobeny logind)
    HAVE_DBUS = shutil.which("dbus-daemon") is not None
except ImportError:
    HAVE_DBUS = False

PASSWORD = "luxos"
BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>system</type>
  <listen>unix:path={path}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def ppm(path):
    data = path.read_bytes()
    magic, size, depth, pixels = data.split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


class Shot:
    def __init__(self, path):
        self.width, self.height, self.data = ppm(path)

    def pixel(self, x, y):
        i = (y * self.width + x) * 3
        return tuple(self.data[i:i + 3])

    def region(self, x0, y0, x1, y1):
        return [self.pixel(x, y) for y in range(y0, y1) for x in range(x0, x1)]


def near(a, b, tol=6):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


@unittest.skipUnless(LSLC and HAVE_LABWC and HAVE_PAM and shutil.which("gcc"),
                     "chybi lslc, labwc (scripts/wl-test/fetch-sysroot.sh), gcc nebo hlavicky PAM")
class LockBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = OUT / f"lock-test-{os.getpid()}"
        shutil.rmtree(cls.tmp, True)
        cls.tmp.mkdir(parents=True)
        build = cls.tmp / "build"
        build.mkdir()
        run = lambda *cmd: subprocess.run(cmd, capture_output=True, text=True)  # noqa: E731
        r = run("make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={build}")
        assert r.returncode == 0, r.stderr
        r = run("gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(build / "luxos-auth"),
                str(PKG / "files/src/luxos-auth.c"), "-lpam")
        assert r.returncode == 0, r.stderr
        r = run("gcc", "-shared", "-fPIC", "-o", str(build / "fake-pam.so"), str(HERE / "lock/fake-pam.c"))
        assert r.returncode == 0, r.stderr
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        for name in ("luxos-lock", "luxos-lock-session"):
            r = run(LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"), str(build / name))
            assert r.returncode == 0, r.stdout + r.stderr
        # obal: napodobeny PAM jen pro luxos-auth (zamek pomocnikovi preda jen par promennych)
        cls.fake_env = cls.tmp / "fake.env"
        auth = build / "auth-fake"
        auth.write_text(f"#!/bin/sh\n[ -f {cls.fake_env} ] && . {cls.fake_env}\n"
                        f"LD_PRELOAD={build}/fake-pam.so exec {build}/luxos-auth \"$@\"\n")
        auth.chmod(0o755)
        cls.build = build
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        self.session = None
        self.log = self.tmp / f"fake-{self.id().rsplit('.', 1)[-1]}.log"
        self.tally = self.tmp / "tally"
        for f in (self.log, self.tally, self.fake_env):
            f.unlink(missing_ok=True)
        self.fake({})

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            if p.stdout:
                p.stdout.close()
        if self.session:
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)

    # ---- prostredi ----

    def fake(self, values):
        values = dict({"FAKE_LOG": str(self.log), "FAKE_TALLY": str(self.tally)}, **values)
        self.fake_env.write_text("".join(f"export {k}='{v}'\n" for k, v in values.items()))

    def start(self, outputs=1, size="1024x640"):
        type(self).counter += 1
        name = f"lock-{os.getpid()}-{self.counter}"
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--outputs", str(outputs), "--size", size,
                            "--name", name, "--timeout", "300"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.session = Path(r.stdout.strip())
        env = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line[len("export "):].partition("=")
            env[key] = value
        self.input_env = dict(env)
        # zamek bez knihoven sysrootu (gdk-pixbuf z nej neumi JPEG tapety)
        env.pop("LD_LIBRARY_PATH", None)
        env.update(LUXOS_WL_LIB=str(self.build / "libluxos-wl.so.0"), LUXOS_LOCK_AUTH=str(self.build / "auth-fake"),
                   LUXOS_LOCK_TRACE="1", LUXOS_LOCK_FPRINT_MODULE="/nonexistent",
                   LUXOS_LOCK_POWER_SUPPLY=str(self.tmp / "power"), LUXOS_LOCK_NOW="9:41", LUXOS_LOCK_DEMO_NAME="Alex Novak")
        self.env = env
        self.home = Path(env["HOME"])
        self.home.mkdir(parents=True, exist_ok=True)
        return self.session

    def spawn(self, argv, env=None):
        p = subprocess.Popen(argv, env=env or self.env, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        p.seen = b""
        self.procs.append(p)
        return p

    def lines(self, p):
        return p.seen.decode(errors="replace").splitlines()

    def wait_line(self, p, want, timeout=10):
        """Ceka na radek, ktery zacina `want`; vraci ho."""
        deadline = time.monotonic() + timeout
        fd = p.stdout.fileno()
        while True:
            for line in self.lines(p):
                if line.startswith(want):
                    return line
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                self.fail(f"{want!r} se neobjevilo: {p.seen.decode(errors='replace')[-3000:]}")
            chunk = os.read(fd, 65536)
            if not chunk:
                self.fail(f"{want!r} se neobjevilo, proces skoncil: {p.seen.decode(errors='replace')[-3000:]}")
            p.seen += chunk

    def drain(self, p, seconds):
        deadline = time.monotonic() + seconds
        fd = p.stdout.fileno()
        while (left := deadline - time.monotonic()) > 0 and select.select([fd], [], [], left)[0]:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            p.seen += chunk

    def locker(self, **extra):
        p = self.spawn([str(self.build / "luxos-lock"), "--notify"], dict(self.env, **extra))
        self.wait_line(p, "ready")
        return p

    def window(self):
        subprocess.run([str(WLT), "run", str(self.session), "--bg", "wlt-client", "--title", "Desk"], check=True,
                       capture_output=True)
        time.sleep(0.5)

    def keys(self, *commands, layout="us", wait=True):
        # nova virtualni klavesnice se zamku ohlasi az za chvili (skutecna klavesnice je tu porad)
        env = dict(self.input_env, WLT_XKB_LAYOUT=layout)
        cmd = [str(OUT / "bin/wlt-input"), "sleep 0.3", *commands]
        if wait:
            subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=60)
            return None
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def shot(self, name="shot.ppm"):
        path = self.session / name
        subprocess.run([str(WLT), "shot", str(self.session), str(path)], check=True, capture_output=True, timeout=20)
        return Shot(path)

    def fake_log(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def passwords(self):
        return [line.split(" ", 2)[2] for line in self.fake_log() if line.startswith("auth luxos-lock ")]

    def pss_kb(self, pid):
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1])
        return 0

    def private_kb(self, pid):
        """Zamek neni dumpable (smaps je jen pro roota): RssAnon + RssShmem ze status (bufery wl_shm jsou memfd)."""
        fields = {}
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            key, _, value = line.partition(":")
            fields[key] = value.split()
        return int(fields["RssAnon"][0]) + int(fields["RssShmem"][0]), int(fields["VmRSS"][0])

    def field(self, p):
        """Pole pro heslo [x, y, w, h] z radku "field" (zamek ho vypise pri configure)."""
        return [int(v) for v in self.wait_line(p, "field ").split()[1:5]]

    def assertCovered(self, shot, window):
        # stred plochy (okno wlt-client) nesmi byt videt
        self.assertFalse(near(shot.pixel(shot.width // 2, shot.height // 2), window, 2), "plocha je videt")


class Auth(LockBase):
    """luxos-auth samotny (bez kompozitoru)."""

    def helper(self, mode="password"):
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        return subprocess.Popen(["sh", str(self.build / "auth-fake"), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                env=env)

    def attempt(self, password):
        p = self.helper()
        prompt = p.stdout.readline()
        data = password.encode()
        rest = p.communicate(struct.pack("=I", len(data)) + data, timeout=10)[0].decode()
        return prompt.decode(), rest, p.returncode

    def test_protocol_ok_and_fail(self):
        self.assertEqual(self.attempt(PASSWORD), ("prompt Password: \n", "result ok 0\n", 0))
        prompt, rest, code = self.attempt("spatne")
        self.assertEqual((rest, code), ("result fail 7\n", 1))
        self.assertEqual(self.passwords(), [PASSWORD, "spatne"])

    def test_unicode_password(self):
        self.fake({"FAKE_PAM_PASSWORD": "žluťoučký kůň"})
        self.assertEqual(self.attempt("žluťoučký kůň")[1:], ("result ok 0\n", 0))

    def test_oversized_or_missing_frame(self):
        p = self.helper()
        p.stdout.readline()
        p.stdin.write(struct.pack("=I", 5000))
        self.assertEqual(p.communicate(timeout=10)[0], b"result fail 19\n")   # PAM_CONV_ERR
        p = self.helper()
        p.stdout.readline()
        self.assertEqual(p.communicate(timeout=10)[0], b"result fail 19\n")

    def test_not_dumpable_and_password_not_in_argv(self):
        p = self.helper()
        p.stdout.readline()
        # skript sh exec-ne pomocnika: PID zustava; bez dumpable patri /proc/PID/{mem,environ} rootovi
        cmdline = Path(f"/proc/{p.pid}/cmdline").read_bytes().split(b"\0")
        self.assertTrue(cmdline[0].endswith(b"luxos-auth"))
        self.assertEqual(cmdline[1], b"password")
        with self.assertRaises(PermissionError):
            Path(f"/proc/{p.pid}/mem").open("rb").read(1)
        with self.assertRaises(PermissionError):
            Path(f"/proc/{p.pid}/environ").read_bytes()
        p.communicate(timeout=10)

    def test_usage(self):
        r = subprocess.run([str(self.build / "luxos-auth"), "root"], capture_output=True)
        self.assertEqual(r.returncode, 2)

    def test_fingerprint_never_answers_prompt(self):
        self.fake({"FAKE_FP": "none"})
        p = self.helper("fingerprint")
        self.assertEqual(p.communicate(timeout=10)[0], b"result fail 7\n")
        self.assertEqual(p.returncode, 1)


class Locker(LockBase):
    def test_correct_password_unlocks(self):
        self.start()
        secret = "kocour7"
        self.fake({"FAKE_PAM_PASSWORD": secret})
        self.window()
        before = self.shot()
        desk = before.pixel(before.width // 2, before.height // 2)
        p = self.locker()
        self.assertIn("locked", self.lines(p))
        self.assertCovered(self.shot(), desk)
        t0 = time.monotonic()
        self.keys(f"type {secret}", "key Return")
        self.assertEqual(p.wait(10), 0)
        took = time.monotonic() - t0
        after = self.shot()
        self.assertEqual(after.pixel(after.width // 2, after.height // 2), desk)
        self.assertEqual(self.passwords(), [secret])
        # heslo jen v napodobenem PAM, nikdy ve vystupu zamku
        self.assertNotIn(secret, p.seen.decode())
        print(f"\n  unlock {took:.2f} s after typing started (incl. 0.3 s keyboard settle)")

    def test_wrong_password_shakes_and_stays_locked(self):
        self.start()
        self.window()
        desk = self.shot().pixel(512, 320)
        p = self.locker()
        fx, fy, fw, fh = self.field(p)
        self.keys("type spatne", "key Return")
        self.wait_line(p, "shake")
        time.sleep(0.12)
        mid = self.shot("mid.ppm")
        time.sleep(0.8)
        rest = self.shot("rest.ppm")
        time.sleep(0.6)
        calm = self.shot("calm.ppm")
        self.assertIsNone(p.poll())
        self.assertCovered(rest, desk)
        # behem zatreseni je pole jinde nez v klidu
        band = (fx - 20, fy + 4, fx + fw + 20, fy + fh - 4)
        self.assertNotEqual(mid.region(*band), rest.region(*band))
        # cerveny okraj pole 1,2 s po chybe, pak zase bily
        def red_rim(shot):
            return sum(1 for px in shot.region(fx + 20, fy - 2, fx + fw - 20, fy) if px[0] > px[1] + 60 and px[0] > px[2] + 60)
        self.assertGreater(red_rim(rest), 50)
        self.assertLess(red_rim(calm), 10)
        # chybova hlaska (svetle cervena error_soft na tmave pilulce) pod polem
        reds = [px for px in calm.region(fx - 60, fy + fh + 6, fx + fw + 60, fy + fh + 30)
                if px[0] > 200 and 150 < px[1] < 200 and 150 < px[2] < 200]
        self.assertGreater(len(reds), 20)
        self.assertEqual(self.passwords(), ["spatne"])
        # prazdny Enter nic neposila (zadny pokus navic pro pam_faillock)
        self.keys("key Return")
        self.drain(p, 0.5)
        self.assertEqual(self.passwords(), ["spatne"])

    def test_typing_during_check_is_a_new_attempt(self):
        self.start()
        self.fake({"FAKE_DELAY_MS": "800"})
        p = self.locker()
        self.keys("type spatne", "key Return", "sleep 0.1", "type lux")
        self.wait_line(p, "shake")
        self.keys(f"type os", "key Return")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.passwords(), ["spatne", PASSWORD])

    def test_caps_lock_indicator(self):
        self.start()
        p = self.locker()
        fx, fy, fw, fh = self.field(p)
        self.keys("type a")
        self.wait_line(p, "keyboard caps=False")
        time.sleep(0.5)
        off = self.shot("off.ppm")
        holder = self.keys("key Caps_Lock", "sleep 3", wait=False)
        self.wait_line(p, "keyboard caps=True")
        time.sleep(0.3)
        on = self.shot("on.ppm")
        holder.wait(10)
        row = (fx - 40, fy + fh + 6, fx + fw + 40, fy + fh + 30)
        changed = sum(a != b for a, b in zip(off.region(*row), on.region(*row)))
        self.assertGreater(changed, 50, "radek Caps Lock se nezmenil")

    def test_czech_layout_password_and_layout_chip(self):
        self.start()
        secret = "ěščřžýáíé"
        self.fake({"FAKE_PAM_PASSWORD": secret})
        p = self.locker()
        names = ["ecaron", "scaron", "ccaron", "rcaron", "zcaron", "yacute", "aacute", "iacute", "eacute"]
        # dve rozlozeni: stitek CZ (aktivni prvni skupina)
        self.keys(*[f"key {n}" for n in names[:4]], layout="cz,us")
        self.wait_line(p, "keyboard caps=False layout=CZ")
        self.keys(*[f"key {n}" for n in names[4:]], "key Return", layout="cz")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.passwords(), [secret])

    def test_dead_keys_compose_and_altgr(self):
        """cz: ť ů ď jen pres mrtve klavesy (Shift+= je hacek, Shift+; krouzek), ě primo, @ pres AltGr+v."""
        self.start()
        secret = "ťůďě@"
        self.fake({"FAKE_PAM_PASSWORD": secret})
        p = self.locker()
        self.keys("key shift+dead_caron", "key t", "key shift+dead_abovering", "key u",
                  # zrusena sekvence (hacek + Backspace) nic neprida ani neubere
                  "key shift+dead_caron", "key BackSpace",
                  "key shift+dead_caron", "key d", "key ecaron", "key ISO_Level3_Shift+v", layout="cz")
        self.drain(p, 0.5)
        lengths = [int(line.split()[2]) for line in self.lines(p) if line.startswith("key ")]
        self.assertEqual(lengths[-1], 5, lengths)
        self.keys("key Return", layout="cz")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.passwords(), [secret])
        out = p.seen.decode()
        for ch in secret:
            self.assertNotIn(ch, out)
        # znaky ani mrtve klavesy nejdou do LSL: keysym 0 za znak, jinak jen ridici klavesy (Shift, AltGr)
        syms = {int(line.split()[1]) for line in self.lines(p) if line.startswith("key ")}
        self.assertFalse([s for s in syms if 0 < s < 0xfe00 or 0xfe50 <= s <= 0xfe93], syms)

    def test_hold_key_repeats(self):
        """Drzena klavesa se opakuje podle repeat_info (labwc testu: prodleva 600 ms, 25/s), Return ne."""
        self.start()
        p = self.locker()
        hold = 1.0
        self.keys("keydown x", f"sleep {hold}", "keyup x")
        self.drain(p, 0.3)
        typed = [int(line.split()[2]) for line in self.lines(p) if line.startswith("key 0 ")]
        expected = 1 + int((hold - 0.6) * 25)
        print(f"\n  x held {hold:.1f} s -> {len(typed)} characters (expected ~{expected})")
        self.assertTrue(expected - 3 <= len(typed) <= expected + 2, typed)
        self.assertEqual(typed, list(range(1, len(typed) + 1)))
        # po uvolneni uz nic
        count = len(self.lines(p))
        self.drain(p, 0.5)
        self.assertEqual(len(self.lines(p)), count)
        # drzeny Backspace smaze vse, pak spravne heslo odemkne
        self.keys("keydown BackSpace", "sleep 1.6", "keyup BackSpace")
        self.drain(p, 0.3)
        backs = [int(line.split()[2]) for line in self.lines(p) if line.startswith("key 65288 ")]
        print(f"  BackSpace held 1.6 s -> {len(backs)} presses, length {backs[-1]}")
        self.assertGreater(len(backs), len(typed))
        self.assertEqual(backs[-1], 0)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.passwords(), [PASSWORD])

    def scaled_lock(self, scale):
        subprocess.run([str(WLT), "run", str(self.session), "wlr-randr", "--output", "HEADLESS-1", "--scale", scale],
                       check=True, capture_output=True, timeout=20)
        time.sleep(0.3)
        return self.locker()

    def test_scale_2_buffer(self):
        """Monitor s meritkem 2: zamek kresli bufer 2x (ostre pismo) pro logickou plochu 1024x640; 1.5 zlomkove."""
        shots = Path(os.environ.get("LUXOS_LOCK_SHOTS") or OUT / "lock-shots")
        shots.mkdir(parents=True, exist_ok=True)
        self.start(size="2048x1280")
        p = self.scaled_lock("2")
        # meritko muze prijit az po prvnim configure (wp_fractional_scale_v1): zamek pak prekresli a vypise ho pozdeji
        self.wait_line(p, "configure 1024x640")
        self.wait_line(p, "scale 2.0")
        subprocess.run([str(WLT), "shot", str(self.session), str(shots / "lock-scale2.png")], check=True,
                       capture_output=True)
        shot = self.shot()
        self.assertEqual((shot.width, shot.height), (2048, 1280))
        # Hodiny: bufer 1x zvetseny kompozitorem je rozmazany (zadna ostra hrana, overeno proti puvodnimu
        # zamku: 0), v buferu 2x ma hrana pisma plny kontrast i mezi pixely jednoho logickeho pixelu (lichy x).
        sharp = odd = 0
        for y in range(100, 420):
            for x in range(640, 1400):
                a, b = shot.pixel(x, y), shot.pixel(x + 1, y)
                if abs(a[0] - b[0]) > 60:
                    sharp += 1
                    odd += x % 2
        print(f"\n  scale 2: {sharp} sharp edges in the clock, {odd} at odd x")
        self.assertGreater(sharp, 300)
        self.assertGreater(odd, sharp // 4)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)
        # zlomkove meritko (wp_fractional_scale_v1 + wp_viewporter)
        p = self.scaled_lock("1.5")
        self.wait_line(p, "configure 1365x853")
        self.wait_line(p, "scale 1.5")
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)

    def test_idle_keeps_one_buffer(self):
        """Po psani (vic snimku za sebou) zustane v klidu jen jeden bufer wl_shm na plochu."""
        self.start(size="1920x1080")
        p = self.locker()
        self.keys("type abcdefgh", "key BackSpace", "key BackSpace")
        time.sleep(2.0)
        shmem = int(next(line.split()[1] for line in Path(f"/proc/{p.pid}/status").read_text().splitlines()
                         if line.startswith("RssShmem:")))
        buffer_kb = 1920 * 1080 * 4 // 1024
        print(f"\n  idle RssShmem {shmem} kB, one 1080p buffer {buffer_kb} kB")
        self.assertLess(shmem, buffer_kb * 3 // 2)

    def test_idle_prompt_and_back(self):
        """Klid bez pole; klavesa i klik ukazou vyzvu (rozmazana tapeta, pole), po LUXOS_LOCK_PROMPT_MS zpet klid."""
        self.start()
        p = self.locker(LUXOS_LOCK_PROMPT_MS="1500")
        fx, fy, fw, fh = self.field(p)
        time.sleep(0.3)
        idle = self.shot("idle.ppm")
        field = (fx + 10, fy + 2, fx + fw - 10, fy + fh - 2)

        def changed(a, b, box):
            return sum(x != y for x, y in zip(a.region(*box), b.region(*box)))
        self.keys("type x")
        self.wait_line(p, "prompt")
        time.sleep(0.6)
        typed = self.shot("typed.ppm")
        self.assertGreater(changed(idle, typed, field), 500, "pole se neukazalo")
        # prvni znak je uz v poli: tecka vlevo
        self.assertIn("key 0 1", self.lines(p))
        # rozmazana tapeta i mimo pole (prolnuti pozadi)
        self.assertGreater(changed(idle, typed, (40, 300, 300, 400)), 2000)
        self.keys("key BackSpace")
        self.wait_line(p, "idle", timeout=5)
        time.sleep(0.7)
        back = self.shot("back.ppm")
        self.assertLess(changed(idle, back, field), 50)
        # klik mysi (ne jen klavesa) ukaze vyzvu znovu
        self.keys("move 100 100", "click")
        self.wait_line(p, "pointer ")
        self.drain(p, 0.6)
        self.assertEqual(sum(line == "prompt" for line in self.lines(p)), 2)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)

    def test_status_cluster_network(self):
        """Stav vpravo nahore: Wi-Fi z napodobeneho /sys/class/net (bez Wi-Fi nic)."""
        self.start()
        net = self.tmp / "net"
        shutil.rmtree(net, True)
        p = self.locker(LUXOS_LOCK_NET=str(net))
        time.sleep(0.3)
        none = self.shot("none.ppm")
        p.terminate()
        p.wait(5)
        (net / "wlan0/wireless").mkdir(parents=True)
        (net / "wlan0/operstate").write_text("up\n")
        (net / "wlan0/type").write_text("1\n")
        p = self.locker(LUXOS_LOCK_NET=str(net))
        time.sleep(0.3)
        wifi = self.shot("wifi.ppm")
        box = (wifi.width - 140, 8, wifi.width - 10, 40)
        self.assertGreater(sum(a != b for a, b in zip(none.region(*box), wifi.region(*box))), 40)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)

    def test_kill_9_keeps_screen_covered_and_new_locker_takes_over(self):
        self.start()
        self.window()
        desk = self.shot().pixel(512, 320)
        p = self.locker()
        os.kill(p.pid, signal.SIGKILL)
        p.wait(5)
        time.sleep(0.3)
        dead = self.shot("dead.ppm")
        self.assertCovered(dead, desk)
        # kompozitor zakryva sam (cerna), nic z plochy
        self.assertTrue(all(px == (0, 0, 0) for px in dead.region(0, 0, dead.width, dead.height)[::997]))
        p2 = self.locker()
        self.assertIn("locked", self.lines(p2))
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p2.wait(10), 0)
        self.assertEqual(self.shot().pixel(512, 320), desk)

    def test_second_locker_is_refused(self):
        self.start()
        self.locker()
        p2 = self.spawn([str(self.build / "luxos-lock"), "--notify"])
        self.assertEqual(p2.wait(10), 3)

    def test_each_output_covered(self):
        self.start(outputs=2, size="800x600")
        layout = (self.session / "layout").read_text().strip()
        self.window()
        p = self.locker()
        sizes = [line for line in self.lines(p) if line.startswith("configure ")]
        self.assertEqual(sizes, ["configure 800x600", "configure 800x600"])
        shot = self.shot()
        self.assertEqual((shot.width, shot.height), tuple(map(int, layout.split("x"))))
        # na kazdem monitoru stejna zamykaci plocha: hodiny nahore a pole dole na obou polovinach
        left = shot.region(300, 40, 500, 200)
        right = shot.region(1100, 40, 1300, 200)
        self.assertGreater(sum(px[0] > 230 and px[1] > 230 for px in left), 100)
        self.assertGreater(sum(px[0] > 230 and px[1] > 230 for px in right), 100)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)

    def test_fingerprint_unlocks(self):
        self.start()
        touch = self.tmp / "touch"
        touch.unlink(missing_ok=True)
        self.fake({"FAKE_FP": "match", "FAKE_FP_TOUCH": str(touch)})
        p = self.locker(LUXOS_LOCK_FPRINT_MODULE=str(self.build / "fake-pam.so"))
        fx, fy, fw, fh = self.field(p)
        self.wait_line(p, "fingerprint: info")
        # klid: jen hodiny, hlaska az s vyzvou (Shift nic nenapise)
        self.keys("key Shift_L")
        self.wait_line(p, "prompt")
        time.sleep(0.6)
        hint = self.shot()
        self.assertGreater(sum(px[0] > 200 and px[1] > 200 and px[2] > 200
                               for px in hint.region(fx - 120, fy + fh + 6, fx + fw + 120, fy + fh + 30)), 30)
        touch.touch()
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.passwords(), [])

    def test_fingerprint_mismatch_then_password(self):
        self.start()
        touch = self.tmp / "touch"
        touch.unlink(missing_ok=True)
        self.fake({"FAKE_FP": "nomatch", "FAKE_FP_TOUCH": str(touch)})
        p = self.locker(LUXOS_LOCK_FPRINT_MODULE=str(self.build / "fake-pam.so"))
        self.wait_line(p, "fingerprint: info")
        touch.touch()
        self.wait_line(p, "shake")
        self.assertIsNone(p.poll())
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)
        # neuspesny otisk se do pam_faillock nepocita
        self.assertFalse(self.tally.exists() and self.tally.read_text().strip())

    def test_no_reader_password_only(self):
        self.start()
        self.fake({"FAKE_FP": "none"})
        p = self.locker(LUXOS_LOCK_FPRINT_MODULE=str(self.build / "fake-pam.so"))
        self.wait_line(p, "fingerprint: ")
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)
        # bez ctecky se otisk po klavesach znovu nespousti
        self.assertEqual(sum(line == "fingerprint start" for line in self.lines(p)), 1)

    def test_faillock_rate(self):
        """pam_faillock LuxOS: 20 chyb za 30 s -> 1 min. 19 chyb nezamyka, 20. ano, pak se pocka."""
        self.start()
        now = int(time.time())
        self.tally.write_text("".join(f"{now}\n" for _ in range(18)))
        self.fake({"FAKE_UNLOCK": "3"})
        p = self.locker()
        self.keys("type spatne", "key Return")         # 19. chyba: jeste nezamceno
        self.wait_line(p, "shake")
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.tally.read_text(), "")    # spravne heslo vynuluje pocitadlo

        self.tally.write_text("".join(f"{now}\n" for _ in range(20)))
        p = self.locker()
        self.keys(f"type {PASSWORD}", "key Return")
        line = self.wait_line(p, "password: error")
        self.wait_line(p, "shake")
        self.assertIsNone(p.poll(), "zamceny ucet nesmi odemknout ani spravnym heslem")
        self.assertEqual(self.passwords().count(PASSWORD), 1, "pri zamceni se heslo PAM nepredava")
        time.sleep(3.2)
        self.keys(f"type {PASSWORD}", "key Return")
        self.assertEqual(p.wait(10), 0)

    def test_screenshots_light_dark_and_idle_pss(self):
        shots = Path(os.environ.get("LUXOS_LOCK_SHOTS") or OUT / "lock-shots")
        shots.mkdir(parents=True, exist_ok=True)
        power = self.tmp / "power/BAT0"
        power.mkdir(parents=True, exist_ok=True)
        for k, v in {"type": "Battery", "capacity": "64", "status": "Discharging", "scope": "System"}.items():
            (power / k).write_text(v + "\n")
        results = {}
        for mode in ("light", "dark"):
            self.start(size="1280x800")
            (self.home / ".config/luxos").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/luxos/appearance").write_text(mode + "\n")
            p = self.locker(XDG_CONFIG_HOME=str(self.home / ".config"))
            self.keys("type abc")
            time.sleep(0.4)
            subprocess.run([str(WLT), "shot", str(self.session), str(shots / f"lock-{mode}.png")], check=True,
                           capture_output=True)
            shot = self.shot()
            # bile hodiny nahore a baterie vpravo nahore
            self.assertGreater(sum(px[0] > 215 and px[1] > 215 and px[2] > 215 for px in shot.region(500, 80, 780, 200)), 100)
            self.assertGreater(sum(px[0] > 220 for px in shot.region(1230, 10, 1270, 30)), 20)
            time.sleep(5)
            results[mode] = self.private_kb(p.pid)
            p.terminate()
            p.wait(5)
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
            self.session = None
        print(f"\n  locker after 5 s idle at 1280x800 [anon+shmem kB, RSS kB]: light {results['light']}, dark {results['dark']}")
        for v in results.values():
            self.assertLess(v[0], 64 * 1024)


@unittest.skipUnless(HAVE_DBUS, "chybi python-dbus nebo dbus-daemon")
class Session(LockBase):
    def setUp(self):
        super().setUp()
        # cesta soketu ma limit 108 znaku: kratky adresar
        self.bus_dir = Path(tempfile.mkdtemp(prefix="lkbus-"))
        sock = self.bus_dir / "bus"
        conf = self.tmp / "bus.conf"
        conf.write_text(BUS_CONF.format(path=sock))
        self.bus = subprocess.Popen(["dbus-daemon", "--nofork", f"--config-file={conf}"], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        self.address = f"unix:path={sock}"
        self.logind = self.spawn(["python3", str(HERE / "lock/fake_logind.py"), self.address],
                                 {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        self.wait_line(self.logind, "ready")

    def tearDown(self):
        super().tearDown()
        self.bus.terminate()
        self.bus.wait(5)
        shutil.rmtree(self.bus_dir, True)

    def watcher(self, **extra):
        env = dict(self.env, DBUS_SYSTEM_BUS_ADDRESS=self.address, XDG_SESSION_ID="31",
                   LUXOS_LOCK_PROGRAM=str(self.build / "luxos-lock"), **extra)
        p = self.spawn([str(self.build / "luxos-lock-session")], env)
        self.wait_line(p, "started")
        return p

    def command(self, word):
        self.logind.stdin.write((word + "\n").encode())
        self.logind.stdin.flush()
        return int(self.wait_line(self.logind, "sent " + word).split()[-1])

    def test_prepare_for_sleep_locks_before_delay_released(self):
        self.start()
        self.window()
        desk = self.shot().pixel(512, 320)
        w = self.watcher()
        self.wait_line(w, "session /org/freedesktop/login1/session/_31")
        self.wait_line(self.logind, "inhibit sleep delay")
        sent = self.command("sleep")
        released = int(self.wait_line(self.logind, "inhibitor-released").split()[-1])
        # v okamziku uvolneni inhibitoru je obrazovka zamcena a nakreslena (ready drive nez uvolneni)
        self.assertCovered(self.shot(), desk)
        self.wait_line(w, "inhibitor released")
        out = self.lines(w)
        self.assertLess(out.index("locker ready"), out.index("inhibitor released"))
        self.wait_line(self.logind, "locked-hint True")
        print(f"\n  PrepareForSleep -> delay inhibitor released after {released - sent} ms")
        self.assertLess(released - sent, 4000)
        # po probuzeni novy inhibitor, zamek drzi dal
        self.command("resume")
        self.wait_line(w, "resume")
        self.drain(self.logind, 1.0)
        self.assertEqual(sum(line.startswith("inhibit sleep delay") for line in self.lines(self.logind)), 2)
        self.keys(f"type {PASSWORD}", "key Return")
        self.wait_line(w, "locker exit 0")
        self.wait_line(self.logind, "locked-hint False")
        self.assertEqual(self.shot().pixel(512, 320), desk)

    def test_logind_lock_and_unlock(self):
        self.start()
        w = self.watcher()
        self.wait_line(w, "session ")
        self.command("lock")
        self.wait_line(w, "locker ready")
        self.command("unlock")
        self.wait_line(w, "locker exit 0")

    def test_idle_triggers_lock_and_crash_relocks(self):
        self.start()
        self.window()
        desk = self.shot().pixel(512, 320)
        w = self.watcher(LUXOS_LOCK_IDLE_MS="1500")
        self.wait_line(w, "idle 1500")
        t0 = time.monotonic()
        self.wait_line(w, "lock idle", timeout=10)
        self.assertGreater(time.monotonic() - t0, 1.2)
        self.wait_line(w, "locker ready")
        self.assertCovered(self.shot(), desk)
        # pad zamku: nahradni zamek do chvile
        pid = int(subprocess.run(["pgrep", "-f", "-P", str(w.pid), "luxos-lock"], capture_output=True, text=True).stdout.split()[0])
        os.kill(pid, signal.SIGKILL)
        self.wait_line(w, "locker exit 0 signal 9")
        self.wait_line(w, "lock restart")
        self.assertCovered(self.shot(), desk)
        self.drain(w, 1.0)
        self.assertEqual(sum(line == "locker ready" for line in self.lines(w)), 2)
        self.keys(f"type {PASSWORD}", "key Return")
        self.drain(w, 1.5)
        self.assertIn("locker exit 0 signal 0", self.lines(w))
        self.assertEqual(self.shot().pixel(512, 320), desk)
        print(f"\n  lock watcher PSS {self.pss_kb(w.pid)} kB")

    def test_idle_time_from_screensaver_settings(self):
        self.start()
        xml = self.home / ".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="idle-activation" type="empty">
      <property name="enabled" type="bool" value="true"/>
      <property name="delay" type="int" value="5"/>
    </property>
  </property>
  <property name="lock" type="empty">
    <property name="saver-activation" type="empty">
      <property name="delay" type="int" value="2"/>
    </property>
  </property>
</channel>
""")
        w = self.watcher(XDG_CONFIG_HOME=str(self.home / ".config"))
        self.wait_line(w, "idle 420000")
        # vypnuty zamek po sporici: necinnost nezamyka (zmena souboru plati hned)
        xml.write_text(xml.read_text().replace('<property name="delay" type="int" value="2"/>',
                                               '<property name="enabled" type="bool" value="false"/>'))
        self.wait_line(w, "idle 0")


if __name__ == "__main__":
    unittest.main()
