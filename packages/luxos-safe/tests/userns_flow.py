"""Skutecny prubeh ochrany, odemceni a zamceni Trezoru v jednorazovem jmennem prostoru (bez rootu).

Spousti test_userns.py pres:
    unshare -m --propagation private --map-users=0:<uid>:1 --map-users=1000:<subuid>:1 ...
UID 0 v prostoru = volajici uzivatel (pripojuje tmpfs a gocryptfs primo), UID 1000 = "uzivatel Trezoru".
Argumenty: <docasny adresar> <adresar s gocryptfs nebo ->
Omezeni: chattr +i potrebuje CAP_LINUX_IMMUTABLE v hlavnim prostoru, tady proto bezi nahradni
varianta zastupne slozky (bez spoustece, nr_inodes=1).
"""
import atexit
import errno
import importlib.machinery
import importlib.util
import os
import shutil
import signal
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
TMP, GOCRYPTFS_DIR = sys.argv[1], sys.argv[2]
UID = GID = 1000
NAME = "tuser"
PW = "correct horse 1"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def step(msg):
    print(f"  - {msg}", flush=True)


def as_user(fn):
    """fn() pod UID 1000 (bez prav roota); vraci (ok, errno nebo vysledek)."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            os.setgroups([])
            os.setgid(GID)
            os.setuid(UID)
            res = "ok:" + str(fn())
        except OSError as e:
            res = f"err:{e.errno}"
        except BaseException as e:  # noqa: BLE001
            res = f"exc:{e!r}"
        os.write(w, res.encode())
        os._exit(0)
    os.close(w)
    out = b""
    while chunk := os.read(r, 4096):
        out += chunk
    os.close(r)
    os.waitpid(pid, 0)
    return out.decode()


def write_file(path, data="x"):
    def go():
        with open(path, "w") as f:
            f.write(data)
        return "written"
    return go


def cleanup():
    """Soubory s UID 1000 (= podrizene UID) smaze jen root tohoto prostoru."""
    me = os.getpid()
    for m in (os.path.join(TMP, "peek"), os.path.join(TMP, "safe", NAME), os.path.join(TMP, "safe", NAME),
              os.path.join(TMP, "safe", "tuser2")):
        subprocess.run(["umount", "-l", m], capture_output=True)
    if os.getpid() == me:
        for n in os.listdir(TMP):
            p = os.path.join(TMP, n)
            subprocess.run(["chmod", "-R", "u+rwX", p], capture_output=True)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)


atexit.register(cleanup)

helper = load("helper_ns", os.path.join(FILES, "luxos-safe-helper"))
safe = load("safe_ns", os.path.join(FILES, "luxos-safe"))

root = os.path.join(TMP, "safe")
peek = os.path.join(TMP, "peek")
home = os.path.join(TMP, "home")
for d in (root, peek, home):
    os.mkdir(d)
os.chmod(root, 0o755)
os.chmod(TMP, 0o755)
helper.ROOT = root
helper.I18N = I18N
mnt = os.path.join(root, NAME)
vault = os.path.join(root, ".vaults", NAME)

# ---- 1. stara instalace: zamcena slozka je obycejny zapisovatelny adresar ----------------------
print("legacy layout (bug reproduction)")
os.makedirs(vault)
os.chmod(os.path.join(root, ".vaults"), 0o711)
os.chown(vault, UID, GID)
os.chmod(vault, 0o700)
os.mkdir(mnt, 0o700)
os.chown(mnt, UID, GID)
with open(os.path.join(mnt, helper.LAUNCHER), "wb") as f:
    f.write(helper.LEGACY_LAUNCHER)
os.chown(os.path.join(mnt, helper.LAUNCHER), UID, GID)
res = as_user(write_file(os.path.join(mnt, "secret.txt"), "plaintext secret"))
assert res == "ok:written", res
step("user wrote secret.txt into the 'locked' Safe folder (the reported bug)")
as_user(lambda: os.makedirs(os.path.join(mnt, "dir")) or open(os.path.join(mnt, "dir", "a"), "w").write("A"))
as_user(lambda: os.symlink("/etc/passwd", os.path.join(mnt, "link")))

# ---- 2. ochrana (helper guard/protect) -------------------------------------------------------
print("helper protect_user")
st, rec = helper.protect_user(NAME, UID, GID)
assert st == "sealed", st
step(f"sealed, unencrypted files staged in {os.path.relpath(rec, TMP)}")
assert sorted(os.listdir(rec)) == ["dir", "link", "secret.txt"], os.listdir(rec)
assert os.readlink(os.path.join(rec, "link")) == "/etc/passwd"
assert os.stat(rec).st_uid == UID and stat.S_IMODE(os.stat(rec).st_mode) == 0o700
assert os.lstat(os.path.join(rec, "secret.txt")).st_uid == UID
step("legacy launcher removed, user files kept (owner 1000, 0700 folder)")
ms = helper.mounts_at(mnt)
assert ms == [("tmpfs", helper.PLACEHOLDER)], ms
assert helper.protect_user(NAME, UID, GID) == ("protected", None)
step("idempotent: second run reports 'protected'")

# Podkladovy adresar (pohled bez vnorenych pripojeni)
subprocess.run(["mount", "--bind", root, peek], check=True)
under = os.path.join(peek, NAME)
ust = os.lstat(under)
assert ust.st_uid == 0 and stat.S_IMODE(ust.st_mode) == 0 and os.listdir(under) == [], (ust, os.listdir(under))
step("underlying dir is root:root 0000 and empty")

listing = os.listdir(mnt)
pst = os.stat(mnt)
assert pst.st_uid == UID and stat.S_IMODE(pst.st_mode) == 0o700
if listing:
    assert listing == [helper.LAUNCHER]
    step("placeholder has the immutable launcher")
else:
    step("placeholder without launcher (immutable not permitted in a user namespace -> fallback)")

# ---- 3. pohled uzivatele pri zamcenem Trezoru -----------------------------------------------
print("locked Safe as user 1000")
for what, fn in (("create file", write_file(os.path.join(mnt, "new.txt"))),
                 ("mkdir", lambda: os.mkdir(os.path.join(mnt, "d"))),
                 ("symlink", lambda: os.symlink("x", os.path.join(mnt, "l"))),
                 ("read underlying", lambda: os.listdir(under)),
                 ("write underlying", write_file(os.path.join(under, "x"))),
                 ("chmod underlying", lambda: os.chmod(under, 0o777)),
                 ("xattr on placeholder", lambda: os.setxattr(mnt, "user.secret", b"x" * 100))):
    res = as_user(fn)
    assert res.startswith("err:"), (what, res)
    step(f"{what}: refused ({errno.errorcode[int(res[4:])]})")
if listing:
    for what, fn in (("write launcher", write_file(os.path.join(mnt, helper.LAUNCHER))),
                     ("delete launcher", lambda: os.unlink(os.path.join(mnt, helper.LAUNCHER)))):
        res = as_user(fn)
        assert res.startswith("err:"), (what, res)
        step(f"{what}: refused")
res = as_user(write_file(os.path.join(mnt, "root-too.txt")))
try:
    with open(os.path.join(mnt, "root-too.txt"), "w") as f:
        f.write("x")
    raise AssertionError("namespace root could write into the placeholder")
except OSError as e:
    step(f"even (namespace) root cannot store a file there ({errno.errorcode[e.errno]})")
assert os.listdir(under) == []

# ---- 3b. varianta se spoustecem (jadro s chattr +i na tmpfs; tady se priznak jen predstira) -----
print("placeholder layout with launcher (immutable flag simulated)")
real_set_immutable = helper.set_immutable
helper.set_immutable = lambda fd, on: True
try:
    assert helper.protect_user("tuser2", UID, GID) == ("sealed", None)
finally:
    helper.set_immutable = real_set_immutable
mnt2 = os.path.join(root, "tuser2")
assert os.listdir(mnt2) == [helper.LAUNCHER]
lst = os.lstat(os.path.join(mnt2, helper.LAUNCHER))
assert lst.st_uid == UID and stat.S_IMODE(lst.st_mode) == 0o500, lst
with open(os.path.join(mnt2, helper.LAUNCHER), "rb") as f:
    assert f.read() == helper.launcher_text()
assert os.stat(mnt2).st_uid == UID and stat.S_IMODE(os.stat(mnt2).st_mode) == 0o700
res = as_user(write_file(os.path.join(mnt2, "new.txt")))
assert res.startswith("err:"), res
res = as_user(lambda: os.setxattr(mnt2, "user.secret", b"x" * 100))
assert res.startswith("err:"), res
res = as_user(write_file(os.path.join(mnt2, helper.LAUNCHER)))
assert res.startswith("err:"), res
step("launcher owned by user 0500, all languages; no second file, no xattr, launcher not writable")
subprocess.run(["umount", mnt2], check=True)

# ---- 4. odemceni / zamceni se skutecnym gocryptfs ----------------------------------------------
if GOCRYPTFS_DIR == "-":
    print("SKIP gocryptfs flow: no gocryptfs binary")
    sys.exit(0)
print("real gocryptfs flow (luxos-safe functions, namespace root)")
os.environ["PATH"] = GOCRYPTFS_DIR + os.pathsep + os.environ["PATH"]
safe.USER, safe.VAULT, safe.MOUNT = NAME, vault, mnt
safe.RECOVERED = os.path.join(root, ".recovered", NAME)
safe.HOME = home
safe.CONF = os.path.join(TMP, "safe.json")
notes = []
safe.notify = lambda *a: notes.append(a)
safe.trust_launcher = lambda: None          # gio by zapisoval do metadat skutecne relace
safe.add_bookmark = lambda: None
helper_calls = []
safe.run_helper = lambda cmd: helper_calls.append(cmd) or (None if helper.protect_user(NAME, UID, GID)[0] != "busy" else "busy")
assert safe.state() == "none" and safe.protected()

assert safe.create(PW) is None
assert safe.state() == "unlocked", safe.mounts()
assert safe.mounts() == [("tmpfs", helper.PLACEHOLDER), ("fuse.gocryptfs", vault)], safe.mounts()
step("create + unlock: gocryptfs mounted on top of the placeholder")
assert helper_calls == []
rec_home = list(safe.recovered_now)
assert len(rec_home) == 1 and os.path.basename(rec_home[0]).startswith("Safe-unencrypted-recovered-"), rec_home
assert stat.S_IMODE(os.stat(rec_home[0]).st_mode) == 0o700
with open(os.path.join(rec_home[0], "secret.txt")) as f:
    assert f.read() == "plaintext secret"
assert notes and notes[-1][0] == "Unencrypted files found"
assert os.listdir(safe.RECOVERED) == []
step("staged plaintext moved to ~/Safe-unencrypted-recovered-<date> (0700) + notification")

assert safe.import_recovered(rec_home[0]) is None
assert not os.path.exists(rec_home[0])
imported = os.path.join(mnt, os.path.basename(rec_home[0]))
with open(os.path.join(imported, "secret.txt")) as f:
    assert f.read() == "plaintext secret"
step("import moved them into the Safe and removed the plaintext copy")

with open(os.path.join(mnt, "doc.txt"), "w") as f:
    f.write("TOPSECRET-MARKER")
for dp, _dn, fn in os.walk(vault):
    for n in fn:
        try:
            with open(os.path.join(dp, n), "rb") as f:
                blob = f.read()
        except FileNotFoundError:
            continue
        assert b"TOPSECRET-MARKER" not in blob and b"plaintext secret" not in blob
assert os.listdir(under) == []
step("data in the vault is encrypted, underlying dir still empty")

# zaneprazdneno: manualni zamceni odmitne a rekne, kdo soubor drzi
holder = subprocess.Popen(["sleep", "60"], stdin=open(os.path.join(mnt, "doc.txt")))
time.sleep(0.3)
msg = safe.lock()
assert msg and "sleep" in msg and safe.is_unlocked(), msg
step(f"manual lock while busy -> {msg!r}, still mounted (no lazy unmount)")
notes.clear()
msg = safe.lock("auto")
assert msg and "sleep" in msg and safe.is_unlocked() and notes and notes[0][0] == "The Safe could not be locked"
step("auto lock while busy -> notification, still mounted")
holder.kill()
holder.wait()
assert safe.lock() is None and safe.state() == "locked"
assert safe.mounts() == [("tmpfs", helper.PLACEHOLDER)]
assert not os.path.exists(os.path.join(mnt, "doc.txt"))
assert not safe._gocryptfs_pids()
step("lock: gocryptfs unmounted and exited, placeholder visible again")
res = as_user(write_file(os.path.join(mnt, "after-lock.txt")))
assert res.startswith("err:"), res
step("after lock the user still cannot write into the folder")

assert safe.unlock("wrong password") == "Wrong password."
assert safe.state() == "locked"
assert safe.unlock(PW) is None and safe.state() == "unlocked"
with open(os.path.join(mnt, "doc.txt")) as f:
    assert f.read() == "TOPSECRET-MARKER"
assert safe.recovered_now == []
step("wrong password refused; correct password brings the file back; nothing new to recover")

# odhlaseni: aplikace s otevrenym souborem dostane SIGTERM
holder = subprocess.Popen(["sleep", "60"], stdin=open(os.path.join(mnt, "doc.txt")))
time.sleep(0.3)
assert safe.lock("logout") is None and safe.state() == "locked"
assert holder.wait(timeout=5) == -signal.SIGTERM
step("logout lock: holder got SIGTERM, Safe locked")

# odhlaseni: aplikace SIGTERM ignoruje -> gocryptfs se ukonci (klic z pameti), pak teprve odpojeni
assert safe.unlock(PW) is None
stubborn = subprocess.Popen([sys.executable, "-c",
                             "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                             "f=open(sys.argv[1]); print('ready', flush=True); time.sleep(60)",
                             os.path.join(mnt, "doc.txt")], stdout=subprocess.PIPE, text=True)
assert stubborn.stdout.readline().strip() == "ready"
procs = safe._gocryptfs_pids()
assert procs
assert safe.lock("logout") is None
assert safe.state() == "locked" and safe.mounts() == [("tmpfs", helper.PLACEHOLDER)], safe.mounts()
time.sleep(0.3)
assert not any(os.path.exists(f"/proc/{p}") and open(f"/proc/{p}/stat").read().split()[2] != "Z" for p in procs)
try:
    stubborn.kill()
    stubborn.wait()
except OSError:
    pass
step("logout lock with an app ignoring SIGTERM: gocryptfs killed, dead mount detached, placeholder back")
assert os.listdir(under) == []
step("underlying dir still empty after all cycles")
print("ALL OK")
