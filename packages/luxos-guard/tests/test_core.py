"""Lux Guard - puvod souboru, kdo soubor otevira (podvrzeny /proc), stav a rozhodovani."""
import os
import stat

import pytest

import luxos_guard_core as C
import luxos_guard_rules as R


class FakeProc:
    """Strom /proc/<pid> v docasne slozce: exe, cwd (symlinky), cmdline, comm, status, loginuid, fd/."""

    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def add(self, pid, exe, argv, cwd="/", ppid=1, uid=1000, loginuid=None, fds=(), comm=None):
        d = os.path.join(self.root, str(pid))
        os.makedirs(os.path.join(d, "fd"))
        os.symlink(exe, os.path.join(d, "exe"))
        os.symlink(cwd, os.path.join(d, "cwd"))
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"".join(a.encode() + b"\0" for a in argv))
        with open(os.path.join(d, "comm"), "w") as f:
            f.write((comm or os.path.basename(exe))[:15] + "\n")
        with open(os.path.join(d, "status"), "w") as f:
            f.write(f"Name:\t{comm or os.path.basename(exe)}\nPPid:\t{ppid}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        with open(os.path.join(d, "loginuid"), "w") as f:
            f.write(str(loginuid if loginuid is not None else 4294967295))
        for i, t in enumerate(fds):
            os.symlink(t, os.path.join(d, "fd", str(i + 3)))
        return C.Proc(self.root)


@pytest.fixture
def env(tmp_path):
    p = FakeProc(str(tmp_path / "proc"))
    home = tmp_path / "home" / "anna"
    (home / "Downloads").mkdir(parents=True)
    (home / "bin").mkdir()
    return p, tmp_path, home


def ident(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


# ---- program_arg ----------------------------------------------------------------------------
@pytest.mark.parametrize("fam,argv,expect", [
    ("sh", ["bash", "evil.sh"], ("evil.sh", False)),
    ("sh", ["bash", "-x", "evil.sh", "a"], ("evil.sh", False)),
    ("sh", ["bash", "-c", "source evil.sh"], (None, True)),
    ("sh", ["sh", "-ec", "x"], (None, True)),
    ("sh", ["bash", "-o", "pipefail", "evil.sh"], ("evil.sh", False)),
    ("sh", ["bash"], (None, False)),
    ("sh", ["-bash"], (None, False)),
    ("python", ["python3", "-u", "evil.py"], ("evil.py", False)),
    ("python", ["python3", "-c", "exec(open('x').read())"], (None, True)),
    ("python", ["python3", "-W", "ignore", "evil.py"], ("evil.py", False)),
    ("python", ["python3", "-I", "/usr/bin/luxos-sandbox", "run", "./evil.sh"], ("/usr/bin/luxos-sandbox", False)),
    ("python", ["python3", "-m", "pip", "install", "x"], (None, False)),
    ("perl", ["perl", "-Mstrict", "-w", "evil.pl"], ("evil.pl", False)),
    ("perl", ["perl", "-e", "print 1"], (None, True)),
    ("node", ["node", "--require", "x", "app.js"], ("app.js", False)),
    ("node", ["node", "-e", "1"], (None, True)),
    ("java", ["java", "-Xmx1g", "-jar", "app.jar"], ("app.jar", False)),
    ("wine", ["wine", "setup.exe"], ("setup.exe", False)),
])
def test_program_arg(fam, argv, expect):
    assert C.program_arg(fam, argv) == expect


@pytest.mark.parametrize("exe,fam", [
    ("/usr/bin/bash", "sh"), ("/usr/bin/dash", "sh"), ("/usr/bin/lsh", "sh"), ("/usr/bin/lsl", "other"), ("/usr/bin/python3.13", "python"),
    ("/usr/bin/perl5.40.1", "perl"), ("/usr/bin/node", "node"), ("/usr/lib/jvm/java-21/bin/java", "java"),
    ("/usr/bin/wine64-preloader", "wine"), ("/usr/bin/mousepad", None), ("/usr/bin/thunar", None),
    ("/usr/bin/cat", None), ("/usr/bin/cp", None), (None, None),
])
def test_exe_family(exe, fam):
    assert C.exe_family(exe) == fam


# ---- kdo soubor otevira -----------------------------------------------------------------------------
def test_opener_intent(env):
    p, tmp, home = env
    evil = home / "Downloads" / "evil.sh"
    evil.write_text("#!/bin/sh\nrm -rf ~\n")
    other = home / "bin" / "tool.py"
    other.write_text("print(1)\n")
    key = ident(evil)
    d = str(home / "Downloads")
    proc = p.add(100, "/usr/bin/bash", ["bash", "evil.sh"], cwd=d)
    assert C.opener_intent(proc, 100, key) == "exec"
    p.add(101, "/usr/bin/mousepad", ["mousepad", str(evil)])
    assert C.opener_intent(proc, 101, key) == "read"          # editor jen cte
    p.add(102, "/usr/bin/python3", ["python3", str(other), str(evil)], cwd=d)
    assert C.opener_intent(proc, 102, key) == "exec"          # soubor je argumentem interpretu
    p.add(103, "/usr/bin/python3", ["python3", str(other)], cwd=d)
    assert C.opener_intent(proc, 103, key) == "read"          # jiny skript soubor cte
    assert C.opener_intent(proc, 103, key, strict=True) == "exec"   # kriticky: import / exec(open())
    p.add(104, "/usr/bin/bash", ["bash", "-c", ". ./evil.sh"], cwd=d)
    assert C.opener_intent(proc, 104, key) == "exec"
    p.add(105, "/usr/bin/bash", ["-bash"], cwd=d)
    assert C.opener_intent(proc, 105, key) == "exec"          # interaktivni shell: source / < soubor
    p.add(106, "/usr/bin/cp", ["cp", str(evil), "/tmp/x"])
    assert C.opener_intent(proc, 106, key) == "read"
    p.add(107, "/usr/bin/bash", ["bash", "./evil.sh"], cwd=d)
    assert C.opener_intent(proc, 107, key) == "exec"
    # jar jen pres javu, .exe jen pres wine
    assert C.opener_intent(proc, 100, key, kind="jar") == "read"


def test_opener_system_tool_reads(env, tmp_path, monkeypatch):
    p, tmp, home = env
    evil = home / "Downloads" / "evil.sh"
    evil.write_text("#!/bin/sh\n")
    proc = p.add(110, "/usr/bin/python3", ["python3", "-I", "/usr/bin/luxos-sandbox", "run", str(evil)])
    monkeypatch.setattr(C, "is_system_file", lambda path: path == "/usr/bin/luxos-sandbox")
    assert C.opener_intent(proc, 110, ident(evil)) == "read"


def test_in_sandbox(env):
    p, tmp, home = env
    bw = ["bwrap", "--unshare-all", "--die-with-parent", "--hostname", "sandbox", "--clearenv", "--uid", "1000",
          "--seccomp", "9", "--", "/bin/sh"]
    proc = p.add(200, "/usr/bin/bwrap", bw, ppid=1)
    p.add(201, "/usr/bin/bwrap", bw, ppid=200)
    p.add(202, "/usr/bin/bash", ["bash", "x.sh"], ppid=201)
    p.add(203, "/usr/bin/bash", ["bash", "x.sh"], ppid=1)
    # podvrzeny bwrap (cela plocha bez seccomp) neni sandbox
    p.add(204, "/usr/bin/bwrap", ["bwrap", "--bind", "/", "/", "--", "sh"], ppid=1)
    p.add(205, "/usr/bin/bash", ["bash", "x.sh"], ppid=204)
    p.add(206, "/home/anna/bwrap", bw, ppid=1)
    p.add(207, "/usr/bin/bash", ["bash", "x.sh"], ppid=206)
    assert C.in_sandbox(proc, 202)
    assert not C.in_sandbox(proc, 203)
    assert not C.in_sandbox(proc, 205)
    assert not C.in_sandbox(proc, 207)


def test_uid_prefers_loginuid(env):
    p, tmp, home = env
    proc = p.add(300, "/usr/bin/bash", ["bash"], uid=0, loginuid=1000)
    p.add(301, "/usr/bin/bash", ["bash"], uid=1001)
    assert proc.uid(300) == 1000
    assert proc.uid(301) == 1001


# ---- puvod --------------------------------------------------------------------------------------
class FakeUsers(C.Users):
    def __init__(self, homes):
        super().__init__()
        self._homes = homes
        self._homes_t = 1e18


def test_location_origin(env):
    p, tmp, home = env
    users = FakeUsers({str(home): 1000})
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Stažené"\n')
    h = str(home)
    assert C.location_origin(h + "/Downloads/x.sh", users) == ("download", None)
    assert C.location_origin(h + "/Stažené/a/b/x", users) == ("download", None)
    assert C.location_origin(h + "/Sandbox/out.sh", users) == ("sandbox", None)
    assert C.location_origin(h + "/bin/x", users) is None
    assert C.location_origin(h + "/.cache/Downloads/x", users) is None
    assert C.location_origin("/run/media/anna/USB/setup.sh", users) == ("removable", "/run/media/anna/USB")
    assert C.location_origin("/tmp/mozilla_anna0/invoice.sh", users) == ("mail", None)
    assert C.location_origin("/tmp/build/x", users) is None


def test_writer_origin(env):
    p, tmp, home = env
    users = FakeUsers({str(home): 1000})
    state = C.State(str(tmp / "state.json"))
    proc = p.add(400, "/usr/lib/firefox/firefox", ["firefox"])
    info = C.writer_info(proc, 400)
    assert C.writer_origin(info, state, users, str(home / "x")) == ("browser", "firefox")
    # rozbalovani archivu ze Stazenych
    arch = home / "Downloads" / "game.zip"
    arch.write_bytes(b"PK")
    p.add(401, "/usr/bin/bsdtar", ["bsdtar", "xf", str(arch)], fds=[str(arch), str(home / "Games" / "run.sh")])
    info = C.writer_info(proc, 401)
    assert C.writer_origin(info, state, users, str(home / "Games" / "run.sh")) == ("copy", str(arch))
    # program zvenku, ktery zapisuje dalsi soubory (dropper)
    dropper = home / "Downloads" / "drop"
    dropper.write_bytes(b"\x7fELF")
    st = os.stat(dropper)
    state.put((st.st_dev, st.st_ino), {"path": str(dropper), "level": C.RISKY, "status": C.ALLOWED})
    p.add(402, str(dropper), ["./drop"])
    info = C.writer_info(proc, 402)
    assert C.writer_origin(info, state, users, str(home / ".local/bin/x")) == ("program", str(dropper))
    # skript zvenku spusteny interpretem
    s = home / "bin" / "stage1.sh"
    s.write_text("x")
    st = os.stat(s)
    state.put((st.st_dev, st.st_ino), {"path": str(s), "level": C.RISKY, "status": C.ALLOWED})
    p.add(403, "/usr/bin/bash", ["bash", "stage1.sh"], cwd=str(home / "bin"))
    info = C.writer_info(proc, 403)
    assert C.writer_origin(info, state, users, str(home / "x")) == ("program", str(s))
    # bezny prekladac
    p.add(404, "/usr/bin/ld", ["ld", "-o", "a.out", "main.o"], fds=[str(home / "bin" / "main.o")])
    assert C.writer_origin(C.writer_info(proc, 404), state, users, str(home / "bin/a.out")) is None


# ---- stav -------------------------------------------------------------------------------------------
def test_state_roundtrip(tmp_path):
    s = C.State(str(tmp_path / "d" / "state.json"))
    f = tmp_path / "x.sh"
    f.write_text("#!/bin/sh\n")
    st = os.stat(f)
    v = R.classify(f.read_bytes(), "x.sh")
    e = C.make_entry(str(f), st, v, ("download", None), 1000, "abc")
    s.put((st.st_dev, st.st_ino), e)
    s.allow_hash("def", 1000, "/x")
    s.add_log(path=str(f), action="found", uid=1000)
    s.save()
    assert stat.S_IMODE(os.stat(tmp_path / "d" / "state.json").st_mode) == 0o600
    s2 = C.State(str(tmp_path / "d" / "state.json"))
    entries = s2.load()
    assert entries[0]["path"] == str(f) and s2.is_allowed("def") and s2.log
    assert C.entry_matches_file(entries[0], st)
    f.write_text("#!/bin/sh\necho changed\n")
    assert not C.entry_matches_file(entries[0], os.stat(f))
    items, log = s2.for_uid(1001)
    assert items == [] and log == []


def test_state_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert C.State(str(p)).load() == []


def test_decide():
    risky = {"level": C.RISKY, "kind": "script", "status": C.FLAGGED}
    crit = {"level": C.CRITICAL, "kind": "elf", "status": C.FLAGGED}
    desk = {"level": C.CRITICAL, "kind": "desktop", "status": C.FLAGGED}
    assert C.decide(risky, "exec") == C.ASK
    assert C.decide(risky, "read") == C.ALLOW
    assert C.decide({**risky, "status": C.ALLOWED}, "exec") == C.ALLOW
    assert C.decide(crit, "exec") == C.DENY
    assert C.decide({**crit, "status": C.ALLOWED}, "exec") == C.DENY      # kriticky nikdy
    assert C.decide(crit, "read") == C.ALLOW
    assert C.decide(crit, "sandbox") == C.ALLOW
    assert C.decide(desk, "read") == C.DENY
    assert C.mark_mask_for("elf") == (True, False)
    assert C.mark_mask_for("script") == (True, True)
    assert C.mark_mask_for("desktop") == (False, True)


def test_sha256_fd(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"x" * 3000000)
    fd = os.open(f, os.O_RDONLY)
    try:
        import hashlib
        assert C.sha256_fd(fd) == hashlib.sha256(b"x" * 3000000).hexdigest()
    finally:
        os.close(fd)
