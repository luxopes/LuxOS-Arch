"""Pomocnik v sezeni luxos-guard-agent (LSL): spojeni se sluzbou, dotazy, okna, upozorneni, restart.

Skutecny prelozeny program proti nahradni sluzbe (socket UNIX v docasne slozce) a nahradnimu pomocnikovi
(sh skript misto luxos-guard-agent-helper: zapise volani a skonci zadanym kodem). Program: LUXOS_GUARD_AGENT_BIN
(build() v PKGBUILD), jinak se prelozi pres lslc.

Spusteni: python3 -m pytest packages/luxos-guard/tests/test_agent_lsl.py (nebo unittest)
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
_BIN = None


def agent_bin():
    global _BIN
    if _BIN:
        return _BIN
    path = os.environ.get("LUXOS_GUARD_AGENT_BIN")
    if not path:
        if not shutil.which("lslc"):
            raise unittest.SkipTest("lslc is not installed")
        out = tempfile.mkdtemp(prefix="luxos-guard-agent-bin-")
        for name in ("luxos-guard-agent.lsl", "luxos_guard_sys.lsl"):
            shutil.copy(os.path.join(FILES, name), out)
        path = os.path.join(out, "luxos-guard-agent")
        subprocess.run(["lslc", "--target", "linux-x86_64-gnu", os.path.join(out, "luxos-guard-agent.lsl"), path],
                       check=True, cwd=out, capture_output=True)
    _BIN = path
    return path


def wait_for(cond, timeout=5.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class FakeService:
    """Nahrada sluzby luxos-guard: prijima spojeni, sbira radky JSON a umi poslat zpravu."""

    def __init__(self, path):
        self.path = path
        self.lines = []           # (cislo spojeni, zprava)
        self.conns = []
        self.lock = threading.Lock()
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with self.lock:
                self.conns.append(c)
                n = len(self.conns)
            threading.Thread(target=self._read, args=(c, n), daemon=True).start()

    def _read(self, c, n):
        buf = b""
        while True:
            try:
                chunk = c.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                with self.lock:
                    self.lines.append((n, json.loads(line)))

    def send(self, obj, conn=-1, raw=None):
        data = raw if raw is not None else (json.dumps(obj) + "\n").encode()
        with self.lock:
            c = self.conns[conn]
        c.sendall(data)

    def messages(self, op=None):
        with self.lock:
            return [m for _n, m in self.lines if op is None or m.get("op") == op]

    def hellos(self):
        with self.lock:
            return [n for n, m in self.lines if m.get("op") == "hello" and m.get("role") == "agent"]

    def drop(self):
        with self.lock:
            for c in self.conns:
                try:
                    c.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                c.close()

    def close(self):
        self.drop()
        self.srv.close()


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="guard-agent-")
        self.sock = os.path.join(self.tmp, "guard.sock")
        self.log = os.path.join(self.tmp, "helper.log")
        self.codefile = os.path.join(self.tmp, "code")
        self.sleepfile = os.path.join(self.tmp, "sleep")
        self.helper = os.path.join(self.tmp, "helper")
        with open(self.helper, "w") as f:
            f.write('#!/bin/sh\n'
                    'printf "%s|%s|%s\\n" "$1" "$2" "$LUXOS_GUARD_MSG" >>"' + self.log + '"\n'
                    '[ -f "' + self.sleepfile + '" ] && sleep "$(cat "' + self.sleepfile + '")"\n'
                    '[ "$1" = ask ] && [ -f "' + self.codefile + '" ] && exit "$(cat "' + self.codefile + '")"\n'
                    'exit 0\n')
        os.chmod(self.helper, 0o755)
        self.svc = None
        self.procs = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)
        if self.svc:
            self.svc.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **extra):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp, "LUXOS_GUARD_SOCKET": self.sock,
               "LUXOS_GUARD_HELPER": self.helper, "LUXOS_GUARD_AGENT_SESSION_CHECK": "1"}
        env.update(extra)
        return env

    def start(self, binary=None, service=True, **extra):
        if service and not self.svc:
            self.svc = FakeService(self.sock)
        p = subprocess.Popen([binary or agent_bin()], env=self.env(**extra), stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
        self.procs.append(p)
        if service:
            self.assertTrue(wait_for(lambda: self.svc.hellos()), "agent did not say hello")
        return p

    def calls(self):
        try:
            with open(self.log) as f:
                return [line.split("|", 2) for line in f.read().splitlines()]
        except OSError:
            return []

    def set_code(self, code):
        with open(self.codefile, "w") as f:
            f.write(str(code))

    # ---- dotaz ------------------------------------------------------------------------------------------------

    def test_ask_run(self):
        self.set_code(10)
        self.start()
        self.svc.send({"op": "ask", "id": 7, "path": "/home/u/Stazene/hra.sh", "program": "bash"})
        self.assertTrue(wait_for(lambda: self.svc.messages("answer")))
        self.assertEqual(self.svc.messages("answer"), [{"op": "answer", "id": 7, "choice": "run"}])
        kinds = [c[0] for c in self.calls()]
        self.assertEqual(kinds, ["ask"])
        msg = json.loads(self.calls()[0][2])
        self.assertEqual(msg["path"], "/home/u/Stazene/hra.sh")      # cela zprava sluzby pro okno

    def test_ask_sandbox_answers_then_acts(self):
        self.set_code(11)
        self.start()
        self.svc.send({"op": "ask", "id": "r-1", "path": "/tmp/x.AppImage", "kind": "elf"})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 2))
        self.assertEqual(self.svc.messages("answer"), [{"op": "answer", "id": "r-1", "choice": "sandbox"}])
        self.assertEqual([c[:2] for c in self.calls()], [["ask", ""], ["act", "sandbox"]])
        self.assertEqual(json.loads(self.calls()[1][2])["path"], "/tmp/x.AppImage")

    def test_ask_trash(self):
        self.set_code(13)
        self.start()
        self.svc.send({"op": "ask", "id": 3, "path": "/tmp/y.sh"})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 2))
        self.assertEqual(self.svc.messages("answer")[0]["choice"], "trash")
        self.assertEqual(self.calls()[1][:2], ["act", "trash"])

    def test_ask_unknown_result_denies(self):
        for code in (12, 14, 1, 99):           # deny, zavrene okno, chyba Pythonu, nesmysl
            with self.subTest(code=code):
                self.set_code(code)
                if not self.svc:
                    self.start()
                before = len(self.svc.messages("answer"))
                self.svc.send({"op": "ask", "id": code, "path": "/tmp/z"})
                self.assertTrue(wait_for(lambda: len(self.svc.messages("answer")) == before + 1))
                self.assertEqual(self.svc.messages("answer")[-1], {"op": "answer", "id": code, "choice": "deny"})
        self.assertNotIn("act", [c[0] for c in self.calls()])

    def test_ask_missing_helper_denies(self):
        self.start(LUXOS_GUARD_HELPER=os.path.join(self.tmp, "nonexistent"))
        self.svc.send({"op": "ask", "id": 5, "path": "/tmp/z"})
        self.assertTrue(wait_for(lambda: self.svc.messages("answer")))
        self.assertEqual(self.svc.messages("answer"), [{"op": "answer", "id": 5, "choice": "deny"}])

    def test_ask_timeout_denies_once(self):
        """Pomocnik neodpovi (zamrzle okno): zamitnuti pred limitem sluzby, pozdejsi volba se uz neposle."""
        self.set_code(10)
        with open(self.sleepfile, "w") as f:
            f.write("3")
        self.start(LUXOS_GUARD_ASK_TIMEOUT="3")      # agent ceka ASK_TIMEOUT - 2 = 1 s
        t0 = time.time()
        self.svc.send({"op": "ask", "id": 9, "path": "/tmp/slow"})
        self.assertTrue(wait_for(lambda: self.svc.messages("answer"), 2.5))
        self.assertLess(time.time() - t0, 2.5)
        self.assertEqual(self.svc.messages("answer"), [{"op": "answer", "id": 9, "choice": "deny"}])
        time.sleep(3)                                  # pomocnik skonci s "run": zadna druha odpoved
        self.assertEqual(len(self.svc.messages("answer")), 1)
        self.assertNotIn("act", [c[0] for c in self.calls()])

    def test_two_asks_at_once(self):
        """Dva dotazy soucasne (dve okna): kazdy dostane svou odpoved, okna se navzajem neblokuji."""
        self.set_code(10)
        with open(self.sleepfile, "w") as f:
            f.write("0.5")
        self.start()
        self.svc.send({"op": "ask", "id": 1, "path": "/tmp/a"})
        self.svc.send({"op": "ask", "id": 2, "path": "/tmp/b"})
        self.assertTrue(wait_for(lambda: len(self.svc.messages("answer")) == 2, 3))
        self.assertEqual(sorted(m["id"] for m in self.svc.messages("answer")), [1, 2])
        self.assertEqual(len(self.calls()), 2)

    # ---- zablokovano a nalezeno -------------------------------------------------------------------------------

    def test_blocked_one_window_per_path(self):
        with open(self.sleepfile, "w") as f:
            f.write("1")
        self.start()
        msg = {"op": "blocked", "path": "/home/u/Stazene/wipe.sh", "level": "critical"}
        self.svc.send(msg)
        self.svc.send(msg)                              # okno uz je otevrene
        self.svc.send({**msg, "path": "/home/u/Stazene/other.sh"})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 2))
        time.sleep(0.3)
        self.assertEqual(sorted(json.loads(c[2])["path"] for c in self.calls()),
                         ["/home/u/Stazene/other.sh", "/home/u/Stazene/wipe.sh"])
        os.unlink(self.sleepfile)
        time.sleep(1.5)                                 # okna zavrena: stejna zprava = nove okno
        self.svc.send(msg)
        self.assertTrue(wait_for(lambda: len(self.calls()) == 3))
        self.assertEqual(self.svc.messages("answer"), [])

    def test_found_once_per_content(self):
        f1 = os.path.join(self.tmp, "helper.sh")
        with open(f1, "w") as f:
            f.write("echo hi\n")
        copy = os.path.join(self.tmp, "copy", "helper.sh")
        os.makedirs(os.path.dirname(copy))
        shutil.copy(f1, copy)
        self.start()
        reasons = ["changes sudo, polkit or login (PAM) security"]
        self.svc.send({"op": "found", "path": f1, "reasons": reasons})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 1))
        self.svc.send({"op": "found", "path": f1, "reasons": reasons})        # stejny soubor znovu
        self.svc.send({"op": "found", "path": copy, "reasons": reasons})      # kopie jinde
        time.sleep(0.5)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0][0], "found")
        self.assertEqual(json.loads(self.calls()[0][2])["reasons"], reasons)
        with open(f1, "a") as f:                                                # zmeneny soubor
            f.write("echo changed\n")
        self.svc.send({"op": "found", "path": f1, "reasons": reasons})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 2))

    def test_found_unreadable_by_path(self):
        self.start()
        for p in ("/nonexistent/a", "/nonexistent/a", "/nonexistent/b"):
            self.svc.send({"op": "found", "path": p, "reasons": []})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 2))
        time.sleep(0.3)
        self.assertEqual(len(self.calls()), 2)

    def test_found_hashes_only_first_4_mib(self):
        """Stejny zacatek (4 MiB) = stejny obsah jako drive v Pythonu (found_key)."""
        a = os.path.join(self.tmp, "a.bin")
        b = os.path.join(self.tmp, "b.bin")
        head = os.urandom(4 << 20)
        for path, tail in ((a, b"x"), (b, b"y")):
            with open(path, "wb") as f:
                f.write(head + tail)
        self.start()
        self.svc.send({"op": "found", "path": a, "reasons": []})
        self.svc.send({"op": "found", "path": b, "reasons": []})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 1))
        time.sleep(0.4)
        self.assertEqual(len(self.calls()), 1)

    def test_ignores_garbage_and_split_lines(self):
        self.set_code(10)
        self.start()
        self.svc.send(None, raw=b"not json\n[1,2]\n\n{\"op\": \"unknown\"}\n")
        # zprava rozdelena uprostred znaku UTF-8 (cesta s diakritikou)
        data = (json.dumps({"op": "ask", "id": 11, "path": "/home/u/Stažené/hra.sh"}, ensure_ascii=False) + "\n").encode()
        cut = data.index("ž".encode()) + 1
        self.svc.send(None, raw=data[:cut])
        time.sleep(0.2)
        self.svc.send(None, raw=data[cut:])
        self.assertTrue(wait_for(lambda: self.svc.messages("answer")))
        self.assertEqual(self.svc.messages("answer"), [{"op": "answer", "id": 11, "choice": "run"}])
        self.assertEqual(json.loads(self.calls()[0][2])["path"], "/home/u/Stažené/hra.sh")

    # ---- spojeni, konec sezeni, aktualizace -----------------------------------------------------------------

    def test_reconnects_after_service_restart(self):
        p = self.start()
        self.svc.close()
        os.unlink(self.sock)
        time.sleep(1.5)                                 # sluzba nebezi: agent zkousi dal
        self.assertIsNone(p.poll())
        self.svc = FakeService(self.sock)
        self.assertTrue(wait_for(lambda: self.svc.hellos(), 6), "no reconnect")
        self.set_code(10)
        self.svc.send({"op": "ask", "id": 1, "path": "/tmp/a"})
        self.assertTrue(wait_for(lambda: self.svc.messages("answer")))

    def test_waits_for_service(self):
        p = self.start(service=False)
        time.sleep(1.2)
        self.assertIsNone(p.poll())
        self.svc = FakeService(self.sock)
        self.assertTrue(wait_for(lambda: self.svc.hellos(), 6))

    def test_exits_when_session_parent_ends(self):
        self.svc = FakeService(self.sock)
        pidfile = os.path.join(self.tmp, "pid")
        env = self.env()
        # rodic (jako xfce4-session) skonci: agent to pozna nejpozdeji po LUXOS_GUARD_AGENT_SESSION_CHECK
        parent = subprocess.Popen(["/bin/sh", "-c", '"$0" & echo $! >"$1"; sleep 1.5', agent_bin(), pidfile],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(wait_for(lambda: self.svc.hellos()))
        pid = int(open(pidfile).read())
        parent.wait(5)

        def gone():
            try:
                with open("/proc/%d/stat" % pid) as f:
                    return f.read().split(")")[-1].split()[0] == "Z"
            except OSError:
                return True
        self.assertTrue(wait_for(gone, 5), "agent still running after the session ended")

    def test_exits_when_x_server_socket_disappears(self):
        xdir = os.path.join(self.tmp, "X11-unix")         # misto /tmp/.X11-unix (skutecny X server se nemeni)
        os.makedirs(xdir)
        fake = os.path.join(xdir, "X7")
        open(fake, "w").close()
        p = self.start(DISPLAY=":7.0", LUXOS_GUARD_AGENT_XDIR=xdir)
        time.sleep(1.3)
        self.assertIsNone(p.poll())
        os.unlink(fake)
        self.assertEqual(p.wait(5), 0)

    def test_no_x_server_socket_keeps_running(self):
        """DISPLAY bez socketu (vzdaleny X, Xwayland jinde): kontrola X se vypne, agent bezi dal."""
        p = self.start(DISPLAY=":8", LUXOS_GUARD_AGENT_XDIR=os.path.join(self.tmp, "none"))
        time.sleep(1.5)
        self.assertIsNone(p.poll())

    def test_restarts_new_version_after_update(self):
        """Balik nahradil program (novy inode): agent se spusti znovu ze stejne cesty a znovu se pripoji."""
        copy = os.path.join(self.tmp, "luxos-guard-agent")
        shutil.copy(agent_bin(), copy)
        p = self.start(binary=copy, LUXOS_GUARD_AGENT_UPDATE_CHECK="1", LUXOS_GUARD_AGENT_UPDATE_DELAY="0")
        time.sleep(1.5)
        self.assertEqual(len(self.svc.hellos()), 1)     # bez zmeny zadny restart
        new = copy + ".new"
        shutil.copy(agent_bin(), new)
        os.replace(new, copy)
        self.assertTrue(wait_for(lambda: len(self.svc.hellos()) == 2, 5), "no restart after update")
        self.assertIsNone(p.poll())                     # stejny proces (exec), jen nova verze
        self.assertNotEqual(self.svc.hellos()[0], self.svc.hellos()[1])   # nove spojeni
        self.set_code(10)
        self.svc.send({"op": "ask", "id": 2, "path": "/tmp/a"})
        self.assertTrue(wait_for(lambda: self.svc.messages("answer")))

    def test_idle_without_wakeups(self):
        """V klidu (bez udalosti) nespotrebuje procesor: probouzi se jen kvuli kontrolam za 20/60 s."""
        p = self.start(LUXOS_GUARD_AGENT_SESSION_CHECK="20")
        time.sleep(0.3)

        def cpu():
            with open("/proc/%d/stat" % p.pid) as f:
                fields = f.read().split(")")[-1].split()
            return int(fields[11]) + int(fields[12])
        c0 = cpu()
        time.sleep(1.5)
        self.assertLessEqual(cpu() - c0, 1)

    def test_small_memory(self):
        p = self.start()
        time.sleep(0.3)
        with open("/proc/%d/smaps_rollup" % p.pid) as f:
            pss = next(int(line.split()[1]) for line in f if line.startswith("Pss:"))
        self.assertLess(pss, 4096, "PSS %d kB" % pss)      # Python verze ~12 MB


if __name__ == "__main__":
    unittest.main()
