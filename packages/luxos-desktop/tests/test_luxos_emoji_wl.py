#!/usr/bin/env python3
"""Emoji a symboly na Waylandu (files/lsl/luxos_emoji.lsl pres luxos-emoji-ui) proti luxwm headless.

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_emoji_wl.py -v

Vyber emoji se otevre nad GTK oknem s polem (tests/lsl/luxos-wl-window.lsl --entry), Enter vybere prvni
nalezene emoji, vyber se skryje, pole dostane fokus zpet a emoji se do nej napise virtualni klavesnici;
okno vypisuje obsah pole ("text: ..."). Klavesnici harnessu drzi jeden `wlt input` po celou dobu testu
(skutecna klavesnice je pripojena driv nez okna). Privilegovane protokoly dostane jen prelozeny
luxos-emoji-ui a pomocny klient (WLT_PRIVILEGED); kopie emoji-ui mimo allowlist do ciziho okna nenapise nic.
Data emoji: maly vzorek vygenerovany luxos-emoji-data.
"""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
LUXWM = LUXWM_BUILD / "luxwm"
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))

EMOJI_TEST = """# group: Smileys & Emotion
# subgroup: face-smiling
1F600                                      ; fully-qualified     # 😀 E1.0 grinning face
1F602                                      ; fully-qualified     # 😂 E0.6 face with tears of joy
# group: People & Body
1F44D                                      ; fully-qualified     # 👍 E0.6 thumbs up
1F44D 1F3FD                                ; fully-qualified     # 👍🏽 E1.0 thumbs up: medium skin tone
1F9D1 200D 1F91D 200D 1F9D1                ; fully-qualified     # 🧑‍🤝‍🧑 E12.0 people holding hands
# group: Component
1F3FB                                      ; component           # 🏻 E1.0 light skin tone
1F3FC                                      ; component           # 🏼 E1.0 medium-light skin tone
1F3FD                                      ; component           # 🏽 E1.0 medium skin tone
1F3FE                                      ; component           # 🏾 E1.0 medium-dark skin tone
1F3FF                                      ; component           # 🏿 E1.0 dark skin tone
# group: Flags
1F1E8 1F1FF                                ; fully-qualified     # 🇨🇿 E2.0 flag: Czechia
#EOF
"""
ANN = {"😀": "grinning face", "😂": "face with tears of joy", "👍": "thumbs up", "🏻": "light skin tone",
       "🏼": "medium-light skin tone", "🏽": "medium skin tone", "🏾": "medium-dark skin tone", "🏿": "dark skin tone"}
DERIVED = {"🧑‍🤝‍🧑": "people holding hands", "🇨🇿": "flag: Czechia"}


def write_data(root, gen):
    # generator chce aspon jeden dalsi jazyk: cestina se stejnymi (anglickymi) nazvy
    for kind, table, top in (("ann", ANN, "annotations"), ("der", DERIVED, "annotationsDerived")):
        for lang in ("en", "cs"):
            d = root / kind / lang
            d.mkdir(parents=True)
            entries = {e: {"default": name.split(), "tts": [name]} for e, name in table.items()}
            (d / "annotations.json").write_text(json.dumps({top: {"identity": {"language": lang}, "annotations": entries}},
                                                           ensure_ascii=False))
    (root / "emoji-test.txt").write_text(EMOJI_TEST)
    out = root / "data"
    r = subprocess.run([str(gen), str(root / "emoji-test.txt"), str(root / "ann"), str(root / "der"), str(out), "cs"],
                       capture_output=True, text=True, env=dict(os.environ, LUXOS_EMOJI_DATA_MIN="3"))
    if r.returncode != 0:
        raise RuntimeError("luxos-emoji-data: " + r.stdout + r.stderr)
    return out


class Lines:
    """Vystup procesu po radcich (bez vlaken: select s casovym limitem)."""

    def __init__(self, proc):
        self.proc = proc
        self.buf = b""

    def lines(self):
        return self.buf.decode(errors="replace").splitlines()

    def wait(self, text, timeout=10):
        deadline = time.monotonic() + timeout
        fd = self.proc.stdout.fileno()
        while text not in self.lines():
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return False
            chunk = os.read(fd, 65536)
            if not chunk:
                return text in self.lines()
            self.buf += chunk
        return True


@unittest.skipUnless(LSLC and LUXWM.exists() and TOOLS and WLT.exists(),
                     "chybi lslc, luxwm (build-host.sh), harness nebo nastroje sestaveni")
class EmojiWayland(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-emoji-wl-", dir=OUT))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        for name in ("luxos-wl-window", "luxos-shot-wl-probe"):
            shutil.copy(HERE / "lsl" / f"{name}.lsl", src)
        for name in ("luxos-emoji-ui", "luxos-emoji-data", "luxos-wl-window", "luxos-shot-wl-probe"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"),
                                str(cls.tmp / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        cls.data = write_data(cls.tmp / "sample", cls.tmp / "luxos-emoji-data")
        (cls.tmp / "other").mkdir()
        shutil.copy(cls.tmp / "luxos-emoji-ui", cls.tmp / "other/luxos-emoji-ui")
        conf = cls.tmp / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        cls.conf = conf
        cls.times = []

    @classmethod
    def tearDownClass(cls):
        if cls.times:
            print(f"\n  vyber -> napsano: {min(cls.times):.0f}-{max(cls.times):.0f} ms ({len(cls.times)}x)")
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        name = f"e{os.getpid() % 10000}-{self._testMethodName[5:17]}"
        env = dict(os.environ, WLT_PRIVILEGED=f"{self.tmp / 'luxos-emoji-ui'} {self.tmp / 'luxos-shot-wl-probe'}",
                   WLT_COMPOSITOR_ENV=f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                                      f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "600",
                            "--name", name, "--", str(LUXWM)], env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.log = self.session / "emoji.log"
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", GTK_THEME="Adwaita",
                        LUXOS_WL_LIB=str(self.tmp / "libluxos-wl.so.0"), LUXOS_EMOJI_DATA=str(self.data),
                        LUXOS_EMOJI_TEST_LOG=str(self.log))
        # jedna klavesnice po cely test (jinak luxwm vezme fokus pri odpojeni a GTK ztrati prvni klavesu)
        self.kb = subprocess.Popen([str(WLT), "input", str(self.session)], stdin=subprocess.PIPE, text=True)
        self.procs.append(self.kb)
        time.sleep(0.3)

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for pipe in (p.stdin, p.stdout, p.stderr):
                if pipe:
                    pipe.close()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    # ---- pomucky ----

    def keys(self, *commands):
        for c in commands:
            self.kb.stdin.write(c + "\n")
        self.kb.stdin.flush()

    def entry_window(self):
        p = subprocess.Popen([str(self.tmp / "luxos-wl-window"), "test.entry", "Psani", "--entry"], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        out = Lines(p)
        self.assertTrue(out.wait("shown"), "okno s polem se neukazalo")
        time.sleep(0.3)
        self.keys("move 640 420", "click")
        time.sleep(0.3)
        return out

    def picker(self, *args, program=None):
        shown = sum(1 for line in self.tlog() if line.startswith("shown "))
        p = subprocess.Popen([str(program or self.tmp / "luxos-emoji-ui"), *args], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.wait_log("shown", count=shown + 1)
        time.sleep(0.3)
        return p

    def tlog(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def wait_log(self, word, timeout=10, count=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = [line for line in self.tlog() if line.split(" @")[0] == word or line.startswith(word + " ")]
            if len(found) >= count:
                return found[count - 1]
            time.sleep(0.05)
        self.fail(f"{word!r} neni v logu: {self.tlog()}")

    def stamp(self, line):
        return float(line.rsplit("@", 1)[1])

    def typed(self, entry, text, count=1):
        self.assertTrue(entry.wait("text: " + text), f"pole: {entry.lines()} log: {self.tlog()}")
        self.times.append((self.stamp(self.wait_log("typed", count=count)) - self.stamp(self.wait_log("chose", count=count))) * 1000)

    # ---- testy ----

    def test_enter_types_into_previous_window(self):
        entry = self.entry_window()
        p = self.picker("--search", "grinning")
        self.assertIn("target", self.wait_log("target"))
        self.assertIn("test.entry/Psani", self.wait_log("target"))
        self.keys("key Return")
        self.typed(entry, "😀")
        self.assertIn("hidden", [line.split(" @")[0] for line in self.tlog()])
        # samostatny proces po vlozeni skonci
        self.assertEqual(p.wait(5), 0)

    def test_multi_codepoint_sequences(self):
        entry = self.entry_window()
        self.picker("--search", "people holding")
        self.keys("key Return")
        self.typed(entry, "🧑‍🤝‍🧑")
        self.picker("--search", "czechia")
        self.keys("key Return")
        self.typed(entry, "🧑‍🤝‍🧑🇨🇿", count=2)

    def test_shift_enter_keeps_picker_open(self):
        entry = self.entry_window()
        p = self.picker("--search", "thumbs")
        self.keys("key shift+Return")
        self.typed(entry, "👍")
        self.wait_log("reopened")
        # fokus je zpet ve vyberu: dalsi Enter napise druhe emoji a vyber zavre
        time.sleep(0.3)
        self.keys("key Return")
        self.typed(entry, "👍👍", count=2)
        self.assertEqual(p.wait(5), 0)

    def test_without_target_copies_to_clipboard(self):
        p = self.picker("--search", "grinning")
        self.assertIn("target 0", self.wait_log("target"))
        self.keys("key Return")
        self.wait_log("copied")
        probe = subprocess.run([str(self.tmp / "luxos-shot-wl-probe"), "text"], env=self.env, capture_output=True,
                               text=True, timeout=15)
        self.assertIn("text 😀", probe.stdout.splitlines())
        # schranku prevzal jiny klient: proces uz nic nedrzi a skonci
        self.assertEqual(p.wait(5), 0)

    def test_not_allowlisted_cannot_type_into_other_window(self):
        entry = self.entry_window()
        self.picker("--search", "grinning", program=self.tmp / "other/luxos-emoji-ui")
        # seznam oken (wlr-foreign-toplevel) je privilegovany: cil neni, emoji jen do vlastni schranky GTK
        self.assertIn("target 0", self.wait_log("target"))
        self.keys("key Return")
        self.wait_log("copied")
        self.assertFalse(entry.wait("text: 😀", timeout=1.0), entry.lines())


if __name__ == "__main__":
    unittest.main()
