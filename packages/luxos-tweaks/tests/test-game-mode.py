#!/usr/bin/env python3
"""LuxOS - testy Herniho rezimu (luxos-game-mode) bez roota: falesny /proc, cgroupfs, systemctl,
powerprofilesctl a busctl; priority vlaken se nemeni doopravdy (get/set nice a ioprio nahrazene).

    python3 packages/luxos-tweaks/tests/test-game-mode.py -v
"""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAEMON = HERE.parent / "files/game/luxos-game-mode"
USER_APPS = "/user.slice/user-1000.slice/user@1000.service/app.slice"


def load(env):
    os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader("luxos_game_mode", str(DAEMON))
    spec = importlib.util.spec_from_loader("luxos_game_mode", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class World:
    """Falesny system: procesy, cgroup, prikazy (zapisuji do log)."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="gamemode-"))
        self.proc = self.root / "proc"
        self.cg = self.root / "cgroup"
        self.bin = self.root / "bin"
        self.log = self.root / "log"
        for d in (self.proc, self.cg, self.bin, self.root / "run"):
            d.mkdir(parents=True)
        (self.proc / "sys/vm").mkdir(parents=True)
        self.meminfo = self.root / "meminfo"
        self.meminfo.write_text("MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\n")
        self.conf = self.root / "game-mode.conf"
        self.conf.write_text("")
        self.active_units = "luxos-care-update.service loaded active running LuxOS Care update\n" \
                            "luxos-guard.service loaded active running Lux Guard\n"
        self.profile = "balanced"
        self.dnd = "false"
        self.write_fakes()

    def write_fakes(self):
        L = f'echo "$(basename "$0") $*" >>"{self.log}"\n'
        (self.bin / "systemctl").write_text("#!/bin/sh\n" + L + f'''case "$1" in
  list-units) cat "{self.root}/units";;
  is-active) exit 3;;
esac
exit 0
''')
        (self.root / "units").write_text(self.active_units)
        (self.bin / "powerprofilesctl").write_text("#!/bin/sh\n" + L + f'''[ "$1" = get ] && cat "{self.root}/profile"
[ "$1" = set ] && echo "$2" >"{self.root}/profile"
exit 0
''')
        (self.root / "profile").write_text(self.profile + "\n")
        (self.bin / "busctl").write_text("#!/bin/sh\n" + L + f'''case "$*" in
  *GetDoNotDisturb*) echo "b $(cat "{self.root}/dnd")";;
esac
exit 0
''')
        (self.root / "dnd").write_text(self.dnd)
        for f in self.bin.iterdir():
            f.chmod(0o755)

    def env(self):
        return {"LUXOS_PROC": str(self.proc), "LUXOS_CGROUP": str(self.cg), "LUXOS_RUN": str(self.root / "run"),
                "LUXOS_GAME_CONF": str(self.conf), "LUXOS_MEMINFO": str(self.meminfo),
                "LUXOS_SYSTEMCTL": str(self.bin / "systemctl"), "LUXOS_BUSCTL": str(self.bin / "busctl"),
                "LUXOS_POWERPROFILESCTL": str(self.bin / "powerprofilesctl")}

    def add(self, pid, comm, ppid=1, uid=1000, cgroup=USER_APPS + "/app-luxos-x.scope", argv0=None, env=None,
            threads=1, policy=0, start=100):
        d = self.proc / str(pid)
        (d / "task").mkdir(parents=True)
        for i in range(threads):
            (d / "task" / str(pid + i)).mkdir()
        fields = ["S", str(ppid)] + ["0"] * 17 + [str(start)] + ["0"] * 18 + [str(policy)] + ["0"] * 10
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
        (d / "status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (d / "cgroup").write_text(f"0::{cgroup}\n")
        (d / "cmdline").write_text((argv0 or comm) + "\0")
        (d / "environ").write_text("".join(f"{k}={v}\0" for k, v in (env or {}).items()))
        cgd = self.cg / cgroup.lstrip("/")
        cgd.mkdir(parents=True, exist_ok=True)
        if not (cgd / "memory.current").exists():
            (cgd / "memory.current").write_text(str(1 << 30))
        return pid

    def remove(self, pid):
        import shutil
        shutil.rmtree(self.proc / str(pid))

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class GameModeTest(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.m = load(self.w.env())
        self.nice = {}
        self.io = {}
        self.m.get_nice = lambda tid: self.nice.get(tid, 0)
        self.m.set_nice = lambda tid, v: self.nice.__setitem__(tid, v) or True
        self.m.get_ioprio = lambda tid: self.io.get(tid, 0)
        self.m.set_ioprio = lambda tid, v: self.io.__setitem__(tid, v) or True
        self.aff = {}
        self.m.get_affinity = lambda tid: self.aff.get(tid, list(range(12)))
        self.m.set_affinity = lambda tid, cpus: self.aff.__setitem__(tid, sorted(cpus)) or True
        self.m.online_cpus = lambda: list(range(12))
        self.m.core_siblings = lambda c: [c - c % 2, c - c % 2 + 1]

    def desktop(self):
        w = self.w
        w.add(10, "luxwm", cgroup="/user.slice/user-1000.slice/session-3.scope")
        w.add(11, "pipewire", cgroup="/user.slice/user-1000.slice/user@1000.service/session.slice/pipewire.service")
        w.add(12, "wireplumber", cgroup=USER_APPS + "/wireplumber.service")
        w.add(20, "firefox", cgroup=USER_APPS + "/app-luxos-firefox.scope", threads=3)
        w.add(30, "steam", cgroup=USER_APPS + "/app-luxos-steam.scope")
        w.add(31, "steamwebhelper", ppid=30, cgroup=USER_APPS + "/app-luxos-steam.scope")
        w.add(40, "nicejob", cgroup=USER_APPS + "/app-luxos-y.scope")
        self.nice[40] = 5                                   # uzivatel sam nastavil nice
        w.add(41, "rtapp", cgroup=USER_APPS + "/app-luxos-z.scope", policy=1)
        w.add(50, "clamd", uid=0, cgroup="/system.slice/luxos-guard-clamd.service")

    def gm(self):
        g = self.m.GameMode()
        return g

    def test_no_game_does_nothing(self):
        self.desktop()
        g = self.gm()
        g.tick()
        self.assertFalse(g.active)
        self.assertEqual(self.nice.get(20, 0), 0)
        self.assertEqual(self.w.calls(), [])

    def test_steam_game_detection(self):
        self.desktop()
        w = self.w
        w.add(60, "reaper", ppid=30, cgroup=USER_APPS + "/app-luxos-steam.scope", env={"SteamAppId": "570"})
        w.add(61, "dota2", ppid=60, cgroup=USER_APPS + "/app-luxos-steam.scope", env={"SteamAppId": "570"},
              threads=4)
        procs = self.m.all_procs()
        roots, games = self.m.find_games(procs, set())
        self.assertEqual(roots, [61])
        self.assertEqual(games, {61})
        self.assertNotIn(30, games)                          # klient Steamu neni hra
        self.assertNotIn(50, procs)                          # systemove procesy se neprochazi

    def test_wine_game_and_helpers(self):
        w = self.w
        w.add(70, "wineserver", argv0="/usr/bin/wineserver")
        w.add(71, "services.exe", argv0="C:\\windows\\system32\\services.exe")
        w.add(72, "Game-Win64-Shi", argv0="Z:\\games\\Game\\Game-Win64-Shipping.exe")
        w.add(73, "child", ppid=72)
        roots, games = self.m.find_games(self.m.all_procs(), set())
        self.assertEqual(roots, [72])
        self.assertEqual(games, {72, 73})

    def test_explicit_and_configured(self):
        w = self.w
        w.add(80, "supertuxkart")
        w.add(81, "mygame", env={"LUXOS_GAME": "1"})
        roots, _ = self.m.find_games(self.m.all_procs(), {"supertuxkart"})
        self.assertEqual(sorted(roots), [80, 81])

    def test_game_on_and_off(self):
        self.desktop()
        self.w.add(61, "dota2", ppid=30, cgroup=USER_APPS + "/app-luxos-steam.scope", env={"SteamAppId": "570"})
        g = self.gm()
        g.tick()
        for t in __import__("threading").enumerate():
            if t.daemon:
                t.join(5)
        self.assertTrue(g.active)
        # pozadi zpomalene: Firefox (vsechna vlakna), klient Steamu
        for tid in (20, 21, 22, 30, 31):
            self.assertEqual(self.nice.get(tid), 10, tid)
            self.assertEqual(self.io.get(tid), 3 << 13, tid)
            self.assertEqual(self.aff.get(tid), [10, 11], tid)         # pozadi na poslednim jadru
        self.assertNotIn(61, self.aff)                                  # hra smi vsude
        self.assertNotIn(11, self.aff)                                  # zvuk taky
        # hra, kompozitor, zvuk, nice uzivatele, realtime: beze zmeny
        for tid in (61, 10, 11, 12, 41):
            self.assertEqual(self.nice.get(tid, 0), 0, tid)
        self.assertEqual(self.nice[40], 5)
        calls = self.w.calls()
        self.assertIn("systemctl freeze luxos-care-update.service", calls)
        self.assertFalse(any("freeze luxos-guard.service" in c for c in calls), "Lux Guard must never be paused")
        self.assertIn("powerprofilesctl set performance", calls)
        self.assertTrue(any("SetDoNotDisturb b true" in c and "--machine=1000@.host" in c for c in calls), calls)
        state = json.loads((self.w.root / "run/game-mode.json").read_text())
        self.assertTrue(state["active"])
        self.assertEqual(state["games"], [{"pid": 61, "name": "dota2"}])
        # komprese pameti: hra (scope Steamu) ne, Firefox ano
        firefox = self.w.cg / USER_APPS.lstrip("/") / "app-luxos-firefox.scope/memory.reclaim"
        steam = self.w.cg / USER_APPS.lstrip("/") / "app-luxos-steam.scope/memory.reclaim"
        self.assertTrue(firefox.exists())
        self.assertFalse(steam.exists())

        # hra skoncila: rezim drzi END_DELAY, pak vse vrati
        self.w.remove(61)
        self.m.END_DELAY = 0
        g.tick()
        self.assertFalse(g.active)
        for tid in (20, 21, 22, 30, 31):
            self.assertEqual(self.nice.get(tid), 0, tid)
            self.assertEqual(self.io.get(tid), 0, tid)
            self.assertEqual(self.aff.get(tid), list(range(12)), tid)
        calls = self.w.calls()
        self.assertIn("systemctl thaw luxos-care-update.service", calls)
        self.assertIn("powerprofilesctl set balanced", calls)
        self.assertTrue(any("SetDoNotDisturb b false" in c for c in calls))

    def test_respects_user_choices(self):
        self.desktop()
        self.w.dnd = "true"                                  # uzivatel ma Nerusit sam
        self.w.profile = "performance"
        self.w.write_fakes()
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        self.w.remove(61)
        self.m.END_DELAY = 0
        g.tick()
        calls = self.w.calls()
        self.assertFalse(any("SetDoNotDisturb" in c for c in calls), calls)
        self.assertFalse(any("powerprofilesctl set" in c for c in calls), calls)

    def test_disabled(self):
        self.desktop()
        self.w.conf.write_text("ENABLED=no\n")
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        self.assertFalse(g.active)
        self.assertEqual(self.nice.get(20, 0), 0)

    def test_restores_after_crash(self):
        self.desktop()
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        self.assertEqual(self.nice.get(20), 10)
        # sluzba spadla (zadny stop); nova instance obnovi ze stavu v /run
        self.w.remove(61)
        g2 = self.gm()
        g2.load_stale()
        self.assertEqual(self.nice.get(20), 0)
        self.assertIn("systemctl thaw luxos-care-update.service", self.w.calls())

    def test_own_affinity_kept(self):
        """Program s vlastni affinitou (napr. omezeny uzivatelem) zustane, kde je."""
        self.desktop()
        self.aff[20] = [0, 1]
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        self.assertEqual(self.aff[20], [0, 1])
        self.assertEqual(self.aff[21], [10, 11])
        self.w.remove(61)
        self.m.END_DELAY = 0
        g.tick()
        self.assertEqual(self.aff[20], [0, 1])
        self.assertEqual(self.aff[21], list(range(12)))

    def test_inherited_threads_and_children_restored(self):
        """Vlakno a proces vznikle behem hry ze zpomaleneho programu zdedi nice, I/O i procesory - po hre zpet."""
        self.desktop()
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        # Firefox vytvoril nove vlakno 23 a podproces 90 (zdedeny stav od rodice)
        (self.w.proc / "20/task/23").mkdir()
        self.w.add(90, "firefox-child", ppid=20, cgroup=USER_APPS + "/app-luxos-firefox.scope")
        for tid in (23, 90):
            self.nice[tid], self.io[tid], self.aff[tid] = 10, 3 << 13, [10, 11]
        # jiny program s nice 10 od uzivatele (bez I/O idle) neni nas
        self.w.add(95, "userjob", cgroup=USER_APPS + "/app-luxos-q.scope")
        self.nice[95] = 10
        g.tick()
        # vlakno 24 vzniklo az po posledni kontrole (neni v zaznamu)
        (self.w.proc / "20/task/24").mkdir()
        self.nice[24], self.io[24], self.aff[24] = 10, 3 << 13, [10, 11]
        self.w.remove(61)
        self.m.END_DELAY = 0
        g.tick()
        for tid in (23, 24, 90):
            self.assertEqual(self.nice[tid], 0, tid)
            self.assertEqual(self.io[tid], 0, tid)
            self.assertEqual(self.aff[tid], list(range(12)), tid)
        self.assertEqual(self.nice[95], 10)

    def test_background_cpus(self):
        sib = lambda c: [c - c % 2, c - c % 2 + 1]           # noqa: E731
        one = lambda c: [c]                                  # noqa: E731
        cases = {1: [0], 2: [1], 4: [3], 8: [7], 12: [10, 11], 16: [14, 15], 32: [28, 29, 30, 31]}
        for n, want in cases.items():
            self.assertEqual(self.m.background_cpus(list(range(n)), sib), want, n)
        self.assertEqual(self.m.background_cpus(list(range(8)), one), [7])

    def test_pid_reuse_not_restored(self):
        self.desktop()
        self.w.add(61, "game", env={"LUXOS_GAME": "1"})
        g = self.gm()
        g.tick()
        # Firefox skoncil a jeho PID dostal jiny proces s nice 10 od uzivatele
        self.w.remove(20)
        self.w.add(20, "other", start=999)
        self.nice[20], self.io[20], self.aff[20] = 10, 0, list(range(12))   # vlastni stav noveho procesu
        self.w.remove(61)
        self.m.END_DELAY = 0
        g.tick()
        self.assertEqual(self.nice[20], 10)


if __name__ == "__main__":
    unittest.main()
