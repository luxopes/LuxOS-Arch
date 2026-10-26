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
    def __init__(self, uid, answer=None):
        super().__init__(None, uid, 1)
        self.sent = []

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
    guard = S.Guard(fan, None, C.State(str(tmp_path / "state.json")), C.Proc(proc_root.root), users)
    guard.clock = lambda: guard._now
    guard._now = 1000.0
    guard.fan = fan
    guard.fp = proc_root
    guard.home = home
    agent = FakeClient(1000)
    guard.on_message(agent, {"op": "hello", "role": "agent"})
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
    assert g.on_message(user, {"op": "allow"})["ok"]
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
    a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    a.connect(sock)
    a.sendall(b'{"op": "hello", "role": "agent"}\n')
    f = a.makefile("rb")
    assert json.loads(f.readline())["op"] == "hello"
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
    """Skutecny proces luxos-guard-agent: dostane dotaz, spusti okno (nahrada) a vrati jeho volbu."""
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
    agent = os.path.join(os.path.dirname(__file__), "..", "files", "luxos-guard-agent")
    env = dict(os.environ, LUXOS_GUARD_SOCKET=sock, LUXOS_GUARD_GUI=str(fake_gui), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, agent], env=env)
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
