"""Lux Guard - sluzba bez rootu: fanotify nahrazene zaznamem volani, /proc podvrzeny.

Skutecne jadro (fanotify jako root) overuje tests/root-fanotify-test.sh ve VM.
"""
import os
import stat

import pytest

import luxos_guard_core as C
import luxos_guard_rules as R
import luxos_guard_service as S
from test_core import FakeProc, FakeUsers


def ident_fd(fd):
    st = os.fstat(fd)
    return (st.st_dev, st.st_ino)


def ident(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


class FakeFan:
    def __init__(self):
        self.marks = {}          # identita -> maska
        self.mounts = {}
        self.responses = []      # (identita, allow)

    def fileno(self):
        if not hasattr(self, "_pipe"):
            self._pipe = os.pipe()          # nikdy citelne (smycka serve() ho jen hlida)
        return self._pipe[0]

    def mark(self, flags, mask, dirfd=S.AT_FDCWD, path=None):
        if flags & S.FAN_MARK_MOUNT:
            self.mounts[path] = mask
            return
        key = ident(path) if dirfd == S.AT_FDCWD else ident_fd(dirfd)
        if flags & S.FAN_MARK_ADD:
            self.marks[key] = self.marks.get(key, 0) | mask
        else:
            if key not in self.marks:
                raise OSError(2, "no mark")
            self.marks[key] &= ~mask
            if not self.marks[key]:
                del self.marks[key]

    def respond(self, fd, allow):
        self.responses.append((ident_fd(fd), allow))

    def read(self, size=0):
        return []


class FakeClient(S.Client):
    """verified: projde overenim pomocnika (v testech nahrada core.agent_peer_ok - skutecny setgid program
    overuje tests/agent-auth-container-test.sh)."""

    def __init__(self, uid, answer=None, verified=False):
        super().__init__(None, uid, 1)
        self.sent = []
        self.verified = verified

    def send(self, obj):
        self.sent.append(obj)
        return True

    def close(self):
        pass


@pytest.fixture
def g(tmp_path):
    proc_root = FakeProc(str(tmp_path / "proc"))
    home = tmp_path / "home" / "anna"
    (home / "Downloads").mkdir(parents=True)
    (home / "bin").mkdir()
    users = FakeUsers({str(home): 1000})
    fan = FakeFan()
    guard = S.Guard(fan, None, C.State(str(tmp_path / "state.json")), C.Proc(proc_root.root), users,
                    agent_check=lambda c: getattr(c, "verified", False) or c.pid in guard.trusted_pids)
    guard.trusted_pids = set()
    guard.clock = lambda: guard._now
    guard._now = 1000.0
    guard.fan = fan
    guard.fp = proc_root
    guard.home = home
    agent = FakeClient(1000, verified=True)
    assert guard.on_message(agent, {"op": "hello", "role": "agent"})["agent"] is True
    guard.agent = agent
    proc_root.add(50, "/usr/bin/bash", ["bash", "evil.sh"], cwd=str(home / "Downloads"), loginuid=1000)
    proc_root.add(51, "/usr/bin/mousepad", ["mousepad"], loginuid=1000)
    proc_root.add(52, "/usr/lib/firefox/firefox", ["firefox"], loginuid=1000)
    proc_root.add(53, "/usr/bin/cp", ["cp"], loginuid=1000)
    proc_root.add(54, "/usr/bin/thunar", ["thunar"], loginuid=1000)
    return guard


WIPER = b"#!/bin/bash\necho installing\nrm -rf ~/*\n"
GAME = b"#!/bin/bash\ncd \"$(dirname \"$0\")\"\n./game.x86_64\n"


def write(path, data, mode=0o755):
    path.write_bytes(data)
    os.chmod(path, mode)
    return str(path)


def close_write(guard, path, pid):
    """Udalost FAN_CLOSE_WRITE (ctecka) + analyza (vlakno analyzy) synchronne."""
    fd = os.open(path, os.O_RDONLY)
    if guard.on_close_write(fd, pid):
        job = guard.jobs.get_nowait()
        guard.analyze(job)
    else:
        os.close(fd)
    guard.on_results()


def perm(guard, path, mask, pid):
    fd = os.open(path, os.O_RDONLY)
    before = len(guard.fan.responses)
    guard.on_perm(mask, fd, pid)
    new = guard.fan.responses[before:]
    return new[-1][1] if new else None      # True/False, None = drzeno (dotaz/analyza)


def test_critical_download_flagged_and_blocked(g):
    p = write(g.home / "Downloads" / "codec.sh", WIPER)
    close_write(g, p, 52)
    e = g.state.get(ident(p))
    assert e["level"] == C.CRITICAL and R.R_DELETE in e["reasons"] and e["origin"] == "download"
    assert g.fan.marks[ident(p)] == S.PERM_EXEC | S.PERM_OPEN
    assert not os.stat(p).st_mode & 0o111                       # pravo spusteni odebrano
    assert any(m["op"] == "found" for m in g.agent.sent)
    # spusteni (execve) i bash codec.sh: zamitnuto vzdy, okno jen jednou za minutu
    assert perm(g, p, S.PERM_EXEC, 54) is False
    assert perm(g, p, S.PERM_OPEN, 50) is False
    blocked = [m for m in g.agent.sent if m["op"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["path"] == p
    # editor soubor otevrit muze
    assert perm(g, p, S.PERM_OPEN, 51) is True


def test_risky_ask_run_anyway(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    key = ident(p)
    assert g.state.get(key)["level"] == C.RISKY and key in g.fan.marks
    assert perm(g, p, S.PERM_EXEC, 54) is None                  # drzeno, dotaz
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert ask["path"] == p and ask["level"] == C.RISKY
    # druhe spusteni behem dotazu se pripoji ke stejnemu dotazu
    assert perm(g, p, S.PERM_EXEC, 54) is None
    assert len([m for m in g.agent.sent if m["op"] == "ask"]) == 1
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "run"})
    assert g.fan.responses[-2:] == [(key, True), (key, True)]
    assert key not in g.fan.marks                                # znacka zrusena - dalsi spusteni nic nestoji
    assert g.state.get(key)["status"] == C.ALLOWED
    assert g.state.is_allowed(g.state.get(key)["sha256"])
    # kopie povoleneho obsahu se znovu neptá
    q = write(g.home / "bin" / "game-copy.sh", GAME)
    g.fp.add(60, "/usr/bin/cp", ["cp", p, q], fds=[p, q], loginuid=1000)
    close_write(g, q, 60)
    assert ident(q) not in g.fan.marks


def test_risky_deny_and_memory(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    assert perm(g, p, S.PERM_EXEC, 54) is None
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "deny"})
    assert g.fan.responses[-1][1] is False
    assert perm(g, p, S.PERM_EXEC, 54) is False                 # do minuty bez noveho dotazu
    g._now += C.DENY_MEMORY + 1
    g.tick()
    assert perm(g, p, S.PERM_EXEC, 54) is None


def test_sandbox_choice_denies_here(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    perm(g, p, S.PERM_EXEC, 54)
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "sandbox"})
    assert g.fan.responses[-1][1] is False and ident(p) in g.fan.marks


def test_ask_and_blocked_say_if_started_from_terminal(g):
    """Spusteni z terminalu (ridici terminal procesu) -> agent spusti sandbox take v terminalu;
    dvojklik ve spravci souboru (bez terminalu) -> program s oknem bez terminalu."""
    g.fp.add(70, "/usr/bin/bash", ["bash"], loginuid=1000, tty=34817)
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    perm(g, p, S.PERM_EXEC, 54)
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert ask["terminal"] is False and ask["kind"] == "script" and ask["interp"] == "bash"
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "deny"})
    g._now += C.DENY_MEMORY + 1
    g.tick()
    perm(g, p, S.PERM_EXEC, 70)
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert ask["terminal"] is True
    w = write(g.home / "Downloads" / "codec.sh", WIPER)
    close_write(g, w, 52)
    assert perm(g, w, S.PERM_EXEC, 70) is False
    blocked = [m for m in g.agent.sent if m["op"] == "blocked"][-1]
    assert blocked["path"] == w and blocked["terminal"] is True


def test_answer_from_other_user_ignored(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    perm(g, p, S.PERM_EXEC, 54)
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    other = FakeClient(1001)
    g.on_message(other, {"op": "hello", "role": "agent"})
    r = g.on_message(other, {"op": "answer", "id": ask["id"], "choice": "run"})
    assert r["op"] == "error" and ask["id"] in g.asks


def test_ask_timeout_denies(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    assert perm(g, p, S.PERM_EXEC, 54) is None
    g._now += C.ASK_TIMEOUT + 1
    g.tick()
    assert g.fan.responses[-1][1] is False and not g.asks


def test_no_agent_denies(g):
    g.drop_client(g.agent)
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    assert perm(g, p, S.PERM_EXEC, 54) is False


def test_exec_then_interpreter_open_allowed_once(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    key = ident(p)
    g.state.get(key)["status"] = C.ALLOWED          # povoleno, znacka zustala (napr. obnovena)
    assert perm(g, p, S.PERM_EXEC, 50) is True
    assert perm(g, p, S.PERM_OPEN, 50) is True


def test_editor_and_cp_can_read_risky(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    assert perm(g, p, S.PERM_OPEN, 51) is True
    assert perm(g, p, S.PERM_OPEN, 53) is True
    assert not [m for m in g.agent.sent if m["op"] == "ask"]


def test_copy_of_flagged_file_is_flagged(g):
    p = write(g.home / "Downloads" / "codec.sh", WIPER)
    close_write(g, p, 52)
    q = write(g.home / "bin" / "innocent.sh", WIPER)
    g.fp.add(61, "/usr/bin/cp", ["cp"], loginuid=1000)        # cp uz skoncil, zadne otevrene soubory
    close_write(g, q, 61)
    e = g.state.get(ident(q))
    assert e and e["origin"] == "copy" and e["level"] == C.CRITICAL and ident(q) in g.fan.marks


def test_empty_download_and_empty_files_not_flagged(g):
    """Prazdny stazeny skript (nepovedene stazeni) se neoznaci a prazdne __init__.py ve venv nejsou jeho kopie."""
    p = write(g.home / "Downloads" / "installer.py", b"", mode=0o644)
    close_write(g, p, 52)
    assert g.state.get(ident(p)) is None
    # oznaceny maly skript: prazdne soubory s nim stejny otisk nemaji, ale i kdyby - pod limitem se neposuzuji
    venv = g.home / "proj" / ".venv" / "lib" / "site-packages" / "pip"
    venv.mkdir(parents=True)
    g.fp.add(62, "/usr/bin/python3.14", ["python3", "-m", "venv", ".venv"], loginuid=1000)
    q = write(venv / "__init__.py", b"", mode=0o644)
    close_write(g, q, 62)
    assert g.state.get(ident(q)) is None and ident(q) not in g.fan.marks


def test_tiny_identical_file_is_not_a_copy(g):
    tiny = b"#!/bin/sh\nrm ~\n"
    assert len(tiny) < S.MIN_COPY_SIZE
    p = write(g.home / "Downloads" / "t.sh", tiny)
    close_write(g, p, 52)
    assert g.state.get(ident(p))                                 # stazeny: posouzen
    q = write(g.home / "bin" / "t2.sh", tiny)
    g.fp.add(63, "/usr/bin/cp", ["cp"], loginuid=1000)
    close_write(g, q, 63)
    assert g.state.get(ident(q)) is None                         # stejny otisk, ale pod limitem kopie


def test_own_build_not_watched(g):
    elf = bytearray(64)
    elf[0:4] = b"\x7fELF"
    elf[4], elf[5] = 2, 1
    elf[16] = 2
    p = write(g.home / "bin" / "a.out", bytes(elf) + b"\0" * 100)
    g.fp.add(62, "/usr/bin/ld", ["ld", "-o", "a.out"], loginuid=1000)
    close_write(g, p, 62)
    assert g.state.get(ident(p)) is None and ident(p) not in g.fan.marks
    # dokumenty ve Stazenych se nehlidaji vubec
    d = write(g.home / "Downloads" / "photo.jpg", b"\xff\xd8\xff\xe0JFIF", 0o644)
    close_write(g, d, 52)
    assert g.state.get(ident(d)) is None


def test_premark_and_pending_until_analysis(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    fd = os.open(p, os.O_RDONLY)
    assert g.on_close_write(fd, 52)
    key = ident(p)
    assert key in g.fan.marks and key in g.analyzing           # predbezna znacka hned ve ctecce
    assert perm(g, p, S.PERM_EXEC, 54) is None                  # spusteni ceka na analyzu
    g.analyze(g.jobs.get_nowait())
    g.on_results()
    assert [m for m in g.agent.sent if m["op"] == "ask"]


def test_desktop_critical_cannot_be_read(g):
    p = write(g.home / "Downloads" / "movie.desktop",
              b"[Desktop Entry]\nType=Application\nName=Movie\nExec=sh -c 'rm -rf ~'\n", 0o644)
    close_write(g, p, 52)
    assert g.state.get(ident(p))["level"] == C.CRITICAL
    assert perm(g, p, S.PERM_OPEN, 54) is False                 # Soubory ho neprectou ani nespusti


def test_allow_command(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    c = write(g.home / "Downloads" / "codec.sh", WIPER)
    close_write(g, p, 52)
    close_write(g, c, 52)
    user = FakeClient(1000)
    fd = os.open(p, os.O_RDONLY)
    user.fds.append(fd)
    # povoleni od uzivatele potvrzuje okno overeneho pomocnika (dotaz), odpoved CLI az po volbe
    assert g.on_message(user, {"op": "allow"}) is None
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert ask["path"] == p and ask["program"] == "luxos-guard allow"
    assert ident(p) in g.fan.marks
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "run"})
    assert user.sent[-1] == {"op": "allow", "ok": True}
    assert ident(p) not in g.fan.marks
    user.fds.append(os.open(c, os.O_RDONLY))
    assert g.on_message(user, {"op": "allow"})["error"] == "critical"
    stranger = FakeClient(1001)
    q = write(g.home / "Downloads" / "game2.sh", GAME + b"#2\n")
    close_write(g, q, 52)
    stranger.fds.append(os.open(q, os.O_RDONLY))
    assert g.on_message(stranger, {"op": "allow"})["error"] == "not yours"
    root = FakeClient(0)
    root.fds.append(os.open(c, os.O_RDONLY))
    assert g.on_message(root, {"op": "allow", "force": True})["ok"]
    assert ident(c) not in g.fan.marks and g.state.get(ident(c)) is None


def test_allow_command_needs_confirmation(g):
    """Program uzivatele si rizikovy soubor nepovoli sam pres "luxos-guard allow"."""
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    user = FakeClient(1000)
    user.fds.append(os.open(p, os.O_RDONLY))
    assert g.on_message(user, {"op": "allow"}) is None
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    # odpoved od neovereneho klienta (i stejneho uzivatele) se nebere
    assert g.on_message(user, {"op": "answer", "id": ask["id"], "choice": "run"})["op"] == "error"
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "deny"})
    assert user.sent[-1] == {"op": "error", "error": "not confirmed"}
    assert g.state.get(ident(p))["status"] == C.FLAGGED and ident(p) in g.fan.marks
    # "Nespoustet" v okne po "luxos-guard allow" neblokuje dalsi spusteni bez dotazu
    assert (1000, ident(p)) not in g.denied
    # bez odpovedi do limitu = nepotvrzeno
    user.fds.append(os.open(p, os.O_RDONLY))
    assert g.on_message(user, {"op": "allow"}) is None
    g._now += C.ASK_TIMEOUT + 1
    g.tick()
    assert user.sent[-1] == {"op": "error", "error": "not confirmed"} and not g.asks
    assert g.state.get(ident(p))["status"] == C.FLAGGED
    # bez pomocnika v sezeni nejde povolit vubec (root ano)
    g.drop_client(g.agent)
    user.fds.append(os.open(p, os.O_RDONLY))
    assert g.on_message(user, {"op": "allow"}) == {"op": "error", "error": "no session"}
    assert g.state.get(ident(p))["status"] == C.FLAGGED
    root = FakeClient(0)
    root.fds.append(os.open(p, os.O_RDONLY))
    assert g.on_message(root, {"op": "allow"})["ok"]
    assert g.state.get(ident(p))["status"] == C.ALLOWED


def test_impostor_agent_refused(g):
    """"hello agent" od programu, ktery neni overeny luxos-guard-agent, nic neda - dotazy dal chodi jen
    skutecnemu pomocnikovi a odpoved podvodnika se ignoruje."""
    fake = FakeClient(1000)
    assert g.on_message(fake, {"op": "hello", "role": "agent"})["agent"] is False
    assert fake.agent is False and g.agents[1000] == [g.agent]
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    assert perm(g, p, S.PERM_EXEC, 54) is None
    assert not [m for m in fake.sent if m["op"] == "ask"]
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert g.on_message(fake, {"op": "answer", "id": ask["id"], "choice": "run"})["op"] == "error"
    assert ask["id"] in g.asks and g.state.get(ident(p))["status"] == C.FLAGGED
    # bez skutecneho pomocnika: podvodnik nedostane dotaz, spusteni se zamitne
    g.drop_client(g.agent)
    g.on_message(fake, {"op": "hello", "role": "agent"})
    q = write(g.home / "Downloads" / "game2.sh", GAME + b"#2\n")
    close_write(g, q, 52)
    assert perm(g, q, S.PERM_EXEC, 54) is False
    assert not [m for m in fake.sent if m["op"] == "ask"]
    assert g.on_message(FakeClient(1000), {"op": "status"})["agent"] is False


def test_agent_check_error_means_refused(g):
    def boom(_c):
        raise OSError("proc gone")
    g.agent_check = boom
    c = FakeClient(1000, verified=True)
    assert g.on_message(c, {"op": "hello", "role": "agent"})["agent"] is False


def test_agents_of_two_users_are_separate(g):
    """Vic uzivatelu: overeny pomocnik dostane jen dotazy sveho uzivatele a odpovi jen na ne."""
    bob = FakeClient(1001, verified=True)
    assert g.on_message(bob, {"op": "hello", "role": "agent"})["agent"] is True
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    perm(g, p, S.PERM_EXEC, 54)
    ask = [m for m in g.agent.sent if m["op"] == "ask"][-1]
    assert not [m for m in bob.sent if m["op"] == "ask"]
    assert g.on_message(bob, {"op": "answer", "id": ask["id"], "choice": "run"})["op"] == "error"
    g.on_message(g.agent, {"op": "answer", "id": ask["id"], "choice": "run"})
    assert g.state.get(ident(p))["status"] == C.ALLOWED


def test_agent_peer_check_real_processes(tmp_path):
    """core.agent_peer_ok proti skutecnym procesum: spravny program + skupina projde, jiny program, jina
    skupina nebo skonceny proces ne (pidfd)."""
    import subprocess
    if os.stat("/usr/bin/sleep").st_uid != 0:
        # user namespace (scripts/wl-test/isolate): root hostitele je nezmapovany, programy patri "nobody"
        pytest.skip("host root is unmapped in this user namespace, the root-owned program check cannot pass")
    gid = os.getegid()
    sleeper = subprocess.Popen(["/usr/bin/sleep", "30"])
    other = subprocess.Popen(["/usr/bin/tail", "-f", "/dev/null"])
    try:
        uid = os.getuid() or 1000
        ok = C.agent_peer_ok(sleeper.pid, uid, gid, exe_path="/usr/bin/sleep", group_gid=gid)
        assert ok is True
        assert C.agent_peer_ok(sleeper.pid, uid, gid + 1, exe_path="/usr/bin/sleep", group_gid=gid) is False
        assert C.agent_peer_ok(other.pid, uid, gid, exe_path="/usr/bin/sleep", group_gid=gid) is False
        assert C.agent_peer_ok(sleeper.pid, uid, gid, exe_path="/usr/bin/sleep", group_gid=None) is (
            C.agent_gid() == gid)
        # vlastni kopie programu (patri uzivateli, ne rootu) neprojde ani se spravnou cestou
        own = tmp_path / "agent"
        own.write_bytes(open("/usr/bin/sleep", "rb").read())
        os.chmod(own, 0o755)
        mine = subprocess.Popen([str(own), "30"])
        try:
            if os.getuid() != 0:
                assert C.agent_peer_ok(mine.pid, uid, gid, exe_path=str(own), group_gid=gid) is False
        finally:
            mine.kill()
            mine.wait()
        pidfd = os.pidfd_open(sleeper.pid)
        try:
            assert C.agent_peer_ok(sleeper.pid, uid, gid, pidfd=pidfd, exe_path="/usr/bin/sleep", group_gid=gid)
            sleeper.kill()
            sleeper.wait()
            assert C.agent_peer_ok(sleeper.pid, uid, gid, pidfd=pidfd, exe_path="/usr/bin/sleep",
                                   group_gid=gid) is False
        finally:
            os.close(pidfd)
        assert C.agent_peer_ok(sleeper.pid, 0, 0) is True            # root smi vse
    finally:
        for pr in (sleeper, other):
            pr.kill()
            pr.wait()


def test_list_and_status_per_user(g):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    r = g.on_message(FakeClient(1000), {"op": "list"})
    assert [e["path"] for e in r["entries"]] == [p]
    assert g.on_message(FakeClient(1001), {"op": "list"})["entries"] == []
    st = g.on_message(FakeClient(1000), {"op": "status"})
    assert st["watched"] == 1 and st["agent"] is True


def test_restore_marks_after_restart(g, tmp_path):
    p = write(g.home / "Downloads" / "codec.sh", WIPER)
    close_write(g, p, 52)
    g.state.save()
    fan2 = FakeFan()
    g2 = S.Guard(fan2, None, C.State(g.state.path), g.proc, g.users)
    n = g2.restore_marks(g2.state.load())
    assert n == 1 and ident(p) in fan2.marks
    # zmeneny soubor se po restartu nepovazuje za stejny
    with open(p, "ab") as f:
        f.write(b"# x\n")
    fan3 = FakeFan()
    g3 = S.Guard(fan3, None, C.State(g.state.path), g.proc, g.users)
    assert g3.restore_marks(g3.state.load()) == 0


def test_removable_exec_classified_on_the_fly(g, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    g.removable = {str(usb)}
    p = write(usb / "setup.sh", WIPER)
    assert perm(g, p, S.PERM_EXEC, 54) is False
    assert g.state.get(ident(p))["origin"] == "removable"
    photo = write(usb / "a.jpg", b"\xff\xd8\xff", 0o644)
    assert perm(g, photo, S.PERM_OPEN, 54) is True            # thunar: neinterpret, hned povoleno
    assert perm(g, photo, S.PERM_OPEN, 50) is True            # interpret, ale ne spustitelny obsah


def test_close_write_filters(g, tmp_path):
    p = write(g.home / "Downloads" / "game.sh", GAME)
    snapdir = tmp_path / "home" / ".luxos-guard-snapshots" / "2026-01-01_10-00"
    snapdir.mkdir(parents=True)
    s = write(snapdir / "x.sh", GAME)
    t = write(g.home / "notes.txt", b"hello", 0o644)
    for path, pid in ((p, g.pid), (s, 52), (t, 52)):
        fd = os.open(path, os.O_RDONLY)
        try:
            assert g.on_close_write(fd, pid) is False, path
        finally:
            os.close(fd)


def test_mounts_parsing(tmp_path):
    mi = tmp_path / "mountinfo"
    mi.write_text(
        "22 1 0:21 /@ / rw - btrfs /dev/vda2 rw\n"
        "23 22 0:21 /@home /home rw - btrfs /dev/vda2 rw\n"
        "24 22 0:30 / /tmp rw - tmpfs tmpfs rw\n"
        "25 22 0:5 / /dev/shm rw - tmpfs tmpfs rw\n"
        "26 22 0:40 / /proc rw - proc proc rw\n"
        "27 22 8:17 / /run/media/anna/MY\\040USB rw - vfat /dev/sdb1 rw\n")
    m = S.read_mounts(str(mi))
    assert S.watch_mounts(m) == ["/home", "/tmp", "/dev/shm"]
    assert S.watch_mounts([("/", "ext4"), ("/tmp", "tmpfs")]) == ["/", "/tmp"]   # /home na korenovem FS
    assert S.removable_mounts(m) == ["/run/media/anna/MY USB"]
    fan = FakeFan()
    guard = S.Guard(fan, None, C.State(str(tmp_path / "s.json")))
    guard.update_mounts(m)
    assert fan.mounts == {"/run/media/anna/MY USB": S.PERM_EXEC | S.PERM_OPEN}
    guard.update_mounts(m[:-1])
    assert guard.removable == set()


def test_fanotify_parse_events():
    import struct
    buf = struct.pack("=IBBHQii", 24, 3, 0, 24, S.FAN_CLOSE_WRITE, 7, 123) + \
        struct.pack("=IBBHQii", 24, 3, 0, 24, S.PERM_EXEC, 8, 124)
    f = S.Fanotify.__new__(S.Fanotify)
    r, w = os.pipe()
    os.write(w, buf)
    f.fd = r
    try:
        assert f.read() == [(S.FAN_CLOSE_WRITE, 7, 123), (S.PERM_EXEC, 8, 124)]
    finally:
        os.close(r)
        os.close(w)


def test_socket_protocol(g, tmp_path):
    """Skutecny socket: prikazy CLI (s predanim deskriptoru) a pomocnik v sezeni (dotaz -> odpoved)."""
    import importlib.machinery
    import importlib.util
    import json
    import socket
    import threading
    import time
    sock = str(tmp_path / "guard.sock")
    g.drop_client(g.agent)
    threading.Thread(target=S.serve, args=(g, sock), daemon=True).start()
    for _ in range(100):
        if os.path.exists(sock):
            break
        time.sleep(0.02)
    loader = importlib.machinery.SourceFileLoader("lg_cli", os.path.join(os.path.dirname(__file__), "..", "files",
                                                                        "luxos-guard"))
    spec = importlib.util.spec_from_loader("lg_cli", loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    assert cli.request({"op": "status"}, sock_path=sock)["active"] is True
    p = write(g.home / "Downloads" / "game.sh", GAME)
    close_write(g, p, 52)
    fd = os.open(p, os.O_RDONLY)
    try:
        r = cli.request({"op": "check"}, fd=fd, sock_path=sock)
    finally:
        os.close(fd)
    assert r["entry"]["path"] == p and r["entry"]["level"] == C.RISKY
    # pomocnik v sezeni: pripoji se, dostane dotaz, odpovi "run"
    # podvodnik (tento proces neni overeny pomocnik): role agent se neprijme
    bad = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bad.connect(sock)
    bad.sendall(b'{"op": "hello", "role": "agent"}\n')
    reply = json.loads(bad.makefile("rb").readline())
    assert reply["op"] == "hello" and reply["agent"] is False and not g.agents
    bad.close()
    a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    a.connect(sock)
    g.trusted_pids.add(os.getpid())         # pomocnik = tento proces (setgid overuje kontejnerovy test)
    a.sendall(b'{"op": "hello", "role": "agent"}\n')
    f = a.makefile("rb")
    assert json.loads(f.readline())["agent"] is True
    g.agents[1000] = g.agents.pop(os.getuid())
    g.agents[1000][0].uid = 1000            # testy bezi pod jinym UID nez 1000
    ev = os.open(p, os.O_RDONLY)
    g.post(("call", None))                  # probudit smycku (zadna akce)
    g.on_perm(S.PERM_EXEC, ev, 54)
    ask = json.loads(f.readline())
    assert ask["op"] == "ask" and ask["path"] == p
    a.sendall((json.dumps({"op": "answer", "id": ask["id"], "choice": "run"}) + "\n").encode())
    for _ in range(100):
        if g.state.get(ident(p))["status"] == C.ALLOWED:
            break
        time.sleep(0.02)
    assert g.state.get(ident(p))["status"] == C.ALLOWED
    a.close()


def test_agent_process_answers(g, tmp_path):
    """Skutecny pomocnik luxos-guard-agent (LSL) + skutecny luxos-guard-agent-helper (Python): dostane dotaz,
    spusti okno (nahrada) a vrati jeho volbu."""
    import subprocess
    import sys
    import threading
    import time
    sock = str(tmp_path / "guard.sock")
    g.drop_client(g.agent)
    threading.Thread(target=S.serve, args=(g, sock), daemon=True).start()
    fake_gui = tmp_path / "fake-gui"
    fake_gui.write_text("#!/bin/sh\ncat > \"$0.in\"\necho run\n")
    os.chmod(fake_gui, 0o755)
    from test_agent_lsl import agent_bin
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "luxos-guard-agent-helper")
    env = dict(os.environ, LUXOS_GUARD_SOCKET=sock, LUXOS_GUARD_GUI=str(fake_gui), PYTHONDONTWRITEBYTECODE="1",
               LUXOS_GUARD_HELPER=os.path.abspath(helper))
    proc = subprocess.Popen([agent_bin()], env=env)
    g.trusted_pids.add(proc.pid)
    try:
        uid = os.getuid()
        for _ in range(200):
            if g.agents.get(uid):
                break
            time.sleep(0.02)
        assert g.agents.get(uid), "agent did not connect"
        p = write(g.home / "Downloads" / "game.sh", GAME)
        close_write(g, p, 52)
        g.state.get(ident(p))["uid"] = uid
        g.fp.add(70, "/usr/bin/thunar", ["thunar"], loginuid=uid)
        g.on_perm(S.PERM_EXEC, os.open(p, os.O_RDONLY), 70)
        for _ in range(200):
            if g.state.get(ident(p))["status"] == C.ALLOWED:
                break
            time.sleep(0.02)
        assert g.state.get(ident(p))["status"] == C.ALLOWED
        assert '"path"' in (tmp_path / "fake-gui.in").read_text()
    finally:
        proc.kill()


# ---- odlozene ulohy (stahovani pod docasnym jmenem): jedno vlakno, omezena fronta -------------------

def test_temp_download_burst_creates_no_threads(g, monkeypatch):
    """Davka zapisu *.part/*.tmp: drive vlakno (threading.Timer) na kazdou udalost -> "can't start new
    thread" a ztracena udalost. Ted fronta v jednom vlakne, zadne nove vlakno pri udalosti."""
    import threading

    def no_thread(*a, **k):
        raise AssertionError("event path must not start a thread")
    monkeypatch.setattr(threading.Thread, "start", no_thread)
    fds = []
    for i in range(300):
        p = write(g.home / "Downloads" / ("file%d.part" % i), b"echo installing\nrm -rf ~/*\n", 0o644)
        fd = os.open(p, os.O_RDONLY)
        assert g.on_close_write(fd, 52) is True
        fds.append(fd)
    assert g.delayed.pending() == 300 and g.jobs.qsize() == 0


def test_temp_download_retried_after_rename(g):
    now = [100.0]
    g.delayed.clock = lambda: now[0]
    part = g.home / "Downloads" / "setup.sh.part"
    write(part, b"echo installing\nrm -rf ~/*\n", 0o644)     # bez #! - druh az podle jmena .sh
    fd = os.open(str(part), os.O_RDONLY)
    assert g.on_close_write(fd, 52)
    assert g.delayed.due() == []                    # jeste ne (3 s)
    final = g.home / "Downloads" / "setup.sh"
    os.rename(str(part), str(final))                # prohlizec prejmenuje po dokonceni
    now[0] += 3.1
    assert g.delayed.run_once(max_wait=0) == 1      # preda se do fronty analyzy
    g.analyze(g.jobs.get_nowait())
    g.on_results()
    e = g.state.get(ident(str(final)))
    assert e and e["level"] == C.CRITICAL and e["path"] == str(final)


def test_delayed_queue_full_counts_overflow(g):
    g.delayed.limit = 2
    taken = []
    for i in range(3):
        p = write(g.home / "Downloads" / ("x%d.tmp" % i), b"echo hi\n", 0o644)
        fd = os.open(p, os.O_RDONLY)
        ok = g.on_close_write(fd, 52)
        taken.append(ok)
        if not ok:
            os.close(fd)                            # volajici (ctecka) fd zavre
    assert taken == [True, True, False]
    assert g.stats["overflows"] == 1 and g.delayed.pending() == 2


def test_delayed_run_once_survives_bad_job():
    seen = []

    def deliver(job):
        if job == "bad":
            raise ValueError("boom")
        seen.append(job)
    d = S.Delayed(deliver, clock=lambda: 10.0)
    d.add(0, "bad")
    d.add(0, "good")
    assert d.run_once(max_wait=0) == 2 and seen == ["good"]


def test_git_hook_samples_not_watched(g):
    """F-13: .git/hooks/*.sample (git je nikdy nespousti) se nehlidaji; skutecny hook ano."""
    hooks = g.home / "Downloads" / "repo" / ".git" / "hooks"
    hooks.mkdir(parents=True)
    for rel in ("repo/.git/hooks/pre-commit.sample", "repo/.git/worktrees/wt/hooks/update.sample",
                "bare.git/hooks/pre-push.sample"):
        path = g.home / "Downloads" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, WIPER)
        fd = os.open(str(path), os.O_RDONLY)
        try:
            assert g.on_close_write(fd, 52) is False, rel
        finally:
            os.close(fd)
    hook = write(hooks / "pre-commit", WIPER)
    fd = os.open(hook, os.O_RDONLY)
    assert g.on_close_write(fd, 52) is True
    g.analyze(g.jobs.get_nowait())
    g.on_results()
    assert g.state.get(ident(hook))["level"] == C.CRITICAL


# ---- odolnost socketu: zadna zprava od uzivatele nesmi sluzbu shodit ani zablokovat -----------------

def _start_serve(g, tmp_path):
    import threading
    import time
    sock = str(tmp_path / "guard.sock")
    g.drop_client(g.agent)
    t = threading.Thread(target=S.serve, args=(g, sock), daemon=True)
    t.start()
    for _ in range(100):
        if os.path.exists(sock):
            break
        time.sleep(0.02)
    return sock, t


def _ask(sock, raw, timeout=5):
    import json
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock)
        s.sendall(raw)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.split(b"\n", 1)[0]) if buf else None
    finally:
        s.close()


def test_malformed_messages_do_not_kill_service(g, tmp_path):
    """Neplatne typy (id jako seznam/slovnik), hluboce vnoreny JSON, nesmyslne op: sluzba odpovi chybou nebo
    zpravu zahodi a dal bezi (drive TypeError/RecursionError ukoncil smycku a po 5 padech Guard zustal vypnuty)."""
    import json
    sock, t = _start_serve(g, tmp_path)
    bad = [b'{"op": "answer", "id": []}\n', b'{"op": "answer", "id": {"a": 1}}\n',
           b'{"op": "answer", "id": 1.5, "choice": ["run"]}\n', b'{"op": ["hello"]}\n', b'{"op": {"x": 1}}\n',
           b'{"op": "hello", "role": ["agent"]}\n', b'{"op": "allow"}\n',
           b"[" * 100000 + b"]" * 100000 + b"\n", b'{"a":' * 50000 + b"1" + b"}" * 50000 + b"\n"]
    for raw in bad:
        try:
            _ask(sock, raw, timeout=2)
        except OSError:
            pass
        assert t.is_alive(), raw[:40]
        assert _ask(sock, b'{"op": "status"}\n')["active"] is True, raw[:40]
    # jedna spojena zprava: spatny radek a hned za nim platny - platny se stale zpracuje
    assert _ask(sock, b'{"op": "answer", "id": []}\n{"op": "status"}\n')["op"] in ("error", "status")
    assert json.dumps(g.stats)       # stav sluzby porad citelny


def test_client_that_never_reads_does_not_block_service(g, tmp_path):
    """Klient posila dotazy a odpovedi necte: sluzba nesmi cekat na jeho socket (drive blokujici sendall
    s limitem 2 s v hlavni smycce = zdrzene odpovedi na spousteni programu v celem systemu)."""
    import socket
    import time
    sock, t = _start_serve(g, tmp_path)
    hog = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    hog.connect(sock)
    hog.setblocking(False)
    line = b'{"op": "status"}\n' * 2000
    sent = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3:
        try:
            sent += hog.send(line)
        except BlockingIOError:
            time.sleep(0.01)
        except OSError:
            break                    # sluzba zahltiveho klienta odpojila - v poradku
    start = time.monotonic()
    assert _ask(sock, b'{"op": "status"}\n', timeout=5)["active"] is True
    assert time.monotonic() - start < 1.0
    assert t.is_alive()
    hog.close()


def test_passed_descriptors_are_bounded(g, tmp_path):
    """Deskriptory predane pres SCM_RIGHTS bez prikazu, ktery je pouzije, se nesmi hromadit (vycerpani fd)."""
    import socket
    import time
    sock, t = _start_serve(g, tmp_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock)
    r, w = os.pipe()
    try:
        for _ in range(300):
            socket.send_fds(s, [b" "], [r, w, r, w])
        s.sendall(b'{"op": "status"}\n')
        s.settimeout(5)
        assert b"status" in s.recv(65536)
        time.sleep(0.1)
        held = [c for c in getattr(g, "_clients", {}).values()] if hasattr(g, "_clients") else []
        for c in held:
            assert len(c.fds) <= S.MAX_CLIENT_FDS
        assert t.is_alive()
    finally:
        s.close()
        os.close(r)
        os.close(w)


def test_connections_per_user_are_bounded(g, tmp_path):
    """Mnoho otevrenych spojeni jednoho uzivatele: nad limit se dalsi hned zavrou, sluzba dal odpovida."""
    import socket
    sock, t = _start_serve(g, tmp_path)
    conns = []
    try:
        for _ in range(S.MAX_CLIENTS_PER_UID + 20):
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.connect(sock)
            conns.append(c)
        import time
        time.sleep(0.3)
        assert len(g._clients) <= S.MAX_CLIENTS_PER_UID
        # stara necinna spojeni zavrit -> nove zase projde
        for c in conns:
            c.close()
        conns = []
        time.sleep(0.3)
        assert _ask(sock, b'{"op": "status"}\n')["active"] is True
    finally:
        for c in conns:
            c.close()


def test_mounts_octal_escapes(tmp_path):
    """mountinfo koduje mezeru, tabulator, novy radek i zpetne lomitko (\\040 \\011 \\012 \\134)."""
    mi = tmp_path / "mountinfo"
    mi.write_text("27 22 8:17 / /run/media/anna/A\\134B\\011C\\012D\\040E rw - vfat /dev/sdb1 rw\n")
    assert S.read_mounts(str(mi)) == [("/run/media/anna/A\\B\tC\nD E", "vfat")]


def test_big_single_reply_is_delivered(g, tmp_path):
    """Jedna velka odpoved (seznam tisicu hlidanych souboru) se pomalu ctoucimu klientovi doruci cela."""
    import json
    import socket
    import time
    for i in range(3000):
        g.state.entries[(1, i)] = {"path": f"/home/anna/Downloads/{'x' * 200}-{i}.sh", "uid": os.getuid(),
                                   "level": C.RISKY, "status": C.FLAGGED, "t": i}
    sock, t = _start_serve(g, tmp_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock)
    s.sendall(b'{"op": "list"}\n')
    time.sleep(0.5)                  # klient chvili necte
    s.settimeout(5)
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        assert chunk
        buf += chunk
    assert len(buf) > S.MAX_CLIENT_OUT and len(json.loads(buf)["entries"]) == 3000
    s.close()
