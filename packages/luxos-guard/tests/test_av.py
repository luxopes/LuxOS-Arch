"""Lux Guard - antivirus (luxos_guard_av): protokol clamd (FILDES), spusteni na vyzadani a zastaveni bez prace,
karantena. Falesny clamd prijima popisovac souboru jako skutecny (SCM_RIGHTS) a hlasi nalez u testovaciho
retezce EICAR. Bez rootu a bez ClamAV."""
import array
import os
import socket
import threading

import pytest

import luxos_guard_av as av

# testovaci retezec EICAR po castech (soubor testu sam neni "virus" pro skenery)
EICAR = (b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")


class FakeClamd:
    def __init__(self, path):
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(8)
        self.commands = []
        self.stopped = False
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while not self.stopped:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                self.handle(conn)

    def handle(self, conn):
        cmd = b""
        while not cmd.endswith(b"\0"):
            c = conn.recv(1)
            if not c:
                return
            cmd += c
        self.commands.append(cmd)
        if cmd == b"zPING\0":
            conn.sendall(b"PONG\0")
        elif cmd == b"zFILDES\0":
            fds = array.array("i")
            _msg, anc, _flags, _addr = conn.recvmsg(1, socket.CMSG_SPACE(fds.itemsize))
            for level, typ, data in anc:
                if level == socket.SOL_SOCKET and typ == socket.SCM_RIGHTS:
                    fds.frombytes(data[:fds.itemsize])
            fd = fds[0]
            data = os.pread(fd, 1 << 20, 0)
            os.close(fd)
            if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
                conn.sendall(b"fd[%d]: Win.Test.EICAR_HDB-1 FOUND\0" % fd)
            else:
                conn.sendall(b"fd[%d]: OK\0" % fd)

    def close(self):
        self.stopped = True
        self.sock.close()
        os.unlink(self.path)


@pytest.fixture
def sock(tmp_path):
    return str(tmp_path / "clamd.sock")


def test_parse_reply():
    assert av.parse_reply("fd[7]: OK\0") == (av.CLEAN, "")
    assert av.parse_reply("fd[7]: Win.Test.EICAR_HDB-1 FOUND\0") == (av.INFECTED, "Win.Test.EICAR_HDB-1")
    assert av.parse_reply("stream: Doc.Macro.Agent-123 FOUND") == (av.INFECTED, "Doc.Macro.Agent-123")
    assert av.parse_reply("fd[7]: Can't open file ERROR\0")[0] == av.ERROR
    assert av.parse_reply("nonsense")[0] == av.ERROR


def test_scan_clean_and_infected(tmp_path, sock):
    fake = FakeClamd(sock)
    try:
        c = av.Clamd(sock, start=lambda: pytest.fail("clamd already runs"), stop=lambda: None)
        good = tmp_path / "report.pdf"
        good.write_bytes(b"%PDF-1.7 nothing")
        bad = tmp_path / "invoice.exe"
        bad.write_bytes(EICAR)
        assert c.scan_path(str(good)) == (av.CLEAN, "")
        assert c.scan_path(str(bad)) == (av.INFECTED, "Win.Test.EICAR_HDB-1")
        # soubor necitelny pro clamd (jen pro vlastnika): popisovac otevira volajici, clamd cestu nedostane
        bad.chmod(0o000)
        if os.geteuid() != 0:
            assert c.scan_path(str(bad))[0] == av.ERROR      # my sami ho neotevreme
        bad.chmod(0o600)
        fd = os.open(str(bad), os.O_RDONLY)
        try:
            assert c.scan_fd(fd)[0] == av.INFECTED
        finally:
            os.close(fd)
        assert not any(b"/" in cmd for cmd in fake.commands), "the path must never be sent to clamd"
        assert c.stats["infected"] == 2
    finally:
        fake.close()


def test_started_on_demand_and_stopped_when_idle(tmp_path, sock):
    now = [1000.0]
    events = []
    holder = {}

    def start():
        events.append("start")
        holder["fake"] = FakeClamd(sock)
        return True

    def stop():
        events.append("stop")
        holder.pop("fake").close()
        return True

    c = av.Clamd(sock, start=start, stop=stop, clock=lambda: now[0], idle=300)
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    # bez kontroly nic nebezi a nic se nespousti
    assert not c.tick() and events == []
    assert c.scan_path(str(f)) == (av.CLEAN, "")
    assert events == ["start"]
    # dalsi kontrola: uz bezi
    assert c.scan_path(str(f)) == (av.CLEAN, "")
    assert events == ["start"]
    now[0] += 299
    assert not c.tick()
    now[0] += 2
    assert c.tick() and events == ["start", "stop"]
    assert not c.tick()
    # dalsi soubor ho spusti znovu
    assert c.scan_path(str(f)) == (av.CLEAN, "")
    assert events == ["start", "stop", "start"]
    holder["fake"].close()


def test_unavailable_clamd_is_an_error_not_clean(tmp_path, sock):
    c = av.Clamd(sock, start=lambda: False, stop=lambda: None)
    f = tmp_path / "a.exe"
    f.write_bytes(EICAR)
    status, detail = c.scan_path(str(f))
    assert status == av.ERROR and "not available" in detail


def test_start_timeout(tmp_path, sock):
    t = [0.0]

    def clock():
        t[0] += 50
        return t[0]

    c = av.Clamd(sock, start=lambda: True, stop=lambda: None, clock=clock, start_timeout=120)
    f = tmp_path / "a"
    f.write_bytes(b"x")
    assert c.scan_path(str(f))[0] == av.ERROR


def test_should_scan_limits(tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"")
    assert not av.should_scan(os.stat(f))           # prazdny
    f.write_bytes(b"x")
    assert av.should_scan(os.stat(f))
    assert not av.should_scan(os.stat(tmp_path))     # adresar


def test_enabled_conf(tmp_path):
    conf = tmp_path / "guard.conf"
    assert av.enabled(str(conf))                     # bez souboru zapnuto
    conf.write_text("# x\nANTIVIRUS=no\n")
    assert not av.enabled(str(conf))
    conf.write_text("ANTIVIRUS='yes'\n")
    assert av.enabled(str(conf))


def test_has_database(tmp_path):
    assert not av.has_database([str(tmp_path)])
    (tmp_path / "daily.cld").write_bytes(b"x")
    assert av.has_database([str(tmp_path)])


# ---- karantena ----

def quarantine(tmp_path):
    return av.Quarantine(str(tmp_path / "q"))


def test_quarantine_moves_file_and_restores(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    bad = home / "Downloads" / "setup.exe"
    bad.write_bytes(EICAR)
    bad.chmod(0o755)
    q = quarantine(tmp_path)
    fd = os.open(str(bad), os.O_RDONLY)
    try:
        e = q.put(fd, str(bad), "Win.Test.EICAR_HDB-1", os.getuid())
    finally:
        os.close(fd)
    assert e["removed"] and not bad.exists()
    qdir = tmp_path / "q"
    assert (qdir.stat().st_mode & 0o777) == 0o700
    stored = qdir / e["id"]
    assert stored.read_bytes() == EICAR and (stored.stat().st_mode & 0o777) == 0o600
    assert [x["id"] for x in q.list(os.getuid())] == [e["id"]]
    assert q.list(os.getuid() + 1) == []                       # cizi uzivatel nevidi
    # obnova: zpet na misto, bez prav spusteni, z karanteny pryc
    assert q.restore(e["id"], os.getuid(), home_of=lambda uid: str(home)) == str(bad)
    assert bad.read_bytes() == EICAR and (bad.stat().st_mode & 0o777) == 0o644   # puvodni prava bez spusteni
    assert bad.stat().st_gid == os.getgid()
    assert q.list() == []


def test_restore_never_overwrites_and_stays_in_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    f = home / "a.doc"
    f.write_bytes(EICAR)
    q = quarantine(tmp_path)
    fd = os.open(str(f), os.O_RDONLY)
    e = q.put(fd, str(f), "Doc.X", os.getuid())
    os.close(fd)
    f.write_bytes(b"new file with the same name")
    assert q.restore(e["id"], os.getuid(), home_of=lambda uid: str(home)) is None
    assert f.read_bytes() == b"new file with the same name"
    # cesta mimo domov vlastnika (podvrzeny zaznam) se neobnovi
    other = tmp_path / "etc"
    other.mkdir()
    assert q.restore(e["id"], os.getuid(), home_of=lambda uid: str(other)) is None
    assert q.get("../../etc/passwd") is None
    assert q.delete(e["id"], os.getuid()) and q.list() == []


def test_quarantine_keeps_file_replaced_meanwhile(tmp_path):
    """Cesta mezitim ukazuje na jiny soubor: ten se nesmaze."""
    f = tmp_path / "x.exe"
    f.write_bytes(EICAR)
    fd = os.open(str(f), os.O_RDONLY)
    os.rename(str(f), str(tmp_path / "moved.exe"))
    f.write_bytes(b"innocent")
    e = quarantine(tmp_path).put(fd, str(f), "Win.Test", os.getuid())
    os.close(fd)
    assert not e["removed"] and f.read_bytes() == b"innocent"


def test_failed_start_backs_off(tmp_path, sock):
    now = [0.0]
    starts = []
    c = av.Clamd(sock, start=lambda: starts.append(1) or False, stop=lambda: None, clock=lambda: now[0])
    f = tmp_path / "a"
    f.write_bytes(b"x")
    for _ in range(5):
        assert c.scan_path(str(f))[0] == av.ERROR
    assert len(starts) == 1                       # bez databaze se clamd nespousti pro kazdy soubor znovu
    now[0] += av.RETRY_AFTER + 1
    c.scan_path(str(f))
    assert len(starts) == 2


def test_clamd_left_from_previous_service_is_stopped(sock):
    """Sluzba se restartovala (aktualizace) a clamd z predchozi instance bezi: po IDLE_STOP ho zastavi."""
    fake = FakeClamd(sock)
    now = [0.0]
    stops = []
    c = av.Clamd(sock, start=lambda: True, stop=lambda: stops.append(1), clock=lambda: now[0], idle=300)
    assert not c.tick()
    now[0] += 301
    assert c.tick() and stops == [1]
    fake.close()
