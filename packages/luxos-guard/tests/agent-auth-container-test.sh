#!/bin/bash
# Lux Guard - overeni pomocnika v sezeni se skutecnym setgid programem. JEN v jednorazovem kontejneru
# (instaluje do /usr/lib/luxos-guard, zaklada uzivatele), jako root:
#   podman run --rm --init --cap-add SYS_PTRACE -v $PWD:/src:ro -v DIR_S_PROGRAMEM:/build:ro IMAGE \
#       bash /src/packages/luxos-guard/tests/agent-auth-container-test.sh /build/luxos-guard-agent
# Obraz: Arch s python, python-gobject, glib2 (program luxos-guard-agent prelozeny lslc na hostiteli).
#
# Sluzba bezi s nahradou fanotify (dotaz se vyvola primo), overeni role "agent" je ale skutecne
# (SO_PEERCRED + SO_PEERPIDFD + /proc/<pid>/exe, skupina luxos-guard). Okno dotazu nahrazuje skript
# /usr/bin/luxos-guard-gui, ktery zapise sve prostredi a odpovi podle /run/lg-test/answer.
set -u
[[ $EUID -eq 0 ]] || { echo "run as root inside a throwaway container"; exit 2; }
[[ -e /run/.containerenv || -e /.dockerenv ]] || { echo "refusing to run outside a container"; exit 2; }
BIN=${1:?usage: agent-auth-container-test.sh PATH/luxos-guard-agent}
SRC=$(cd "$(dirname "$0")/.." && pwd)
pass=0 fail=0
ok() { echo "PASS $*"; pass=$((pass + 1)); }
bad() { echo "FAIL $*"; fail=$((fail + 1)); }

systemd-sysusers - <"$SRC/files/luxos-guard.sysusers" 2>/dev/null || groupadd -r luxos-guard
install -d /usr/lib/luxos-guard /usr/lib/luxos/python /run/lg-test
install -m644 "$SRC"/files/luxos_guard_{core,rules,service,session,snap}.py /usr/lib/luxos/python/
install -m755 "$SRC/files/luxos-guard-agent-helper" /usr/lib/luxos-guard/luxos-guard-agent-helper
# jako po rozbaleni baliku: nejdriv bez setgid (post_install/post_upgrade ho nastavi az pak)
install -m755 "$BIN" /usr/lib/luxos-guard/luxos-guard-agent
cat >/usr/bin/luxos-guard-gui <<'EOF'
#!/bin/sh
# nahrada okna: zapise prostredi a skupiny, odpovi podle souboru (= klik uzivatele)
cat >/dev/null
env >/run/lg-test/gui-env.$(id -u)
grep '^Gid:' /proc/self/status >/run/lg-test/gui-gid.$(id -u)
cat /run/lg-test/answer
EOF
chmod 755 /usr/bin/luxos-guard-gui
chmod 1777 /run/lg-test
echo deny >/run/lg-test/answer
chmod 644 /run/lg-test/answer
for u in alice bob; do
    id "$u" >/dev/null 2>&1 || useradd -m "$u"
    install -d -o "$u" -g "$u" "/home/$u/Downloads" "/home/$u/evil" "/home/$u/evilpy"
done
SITE=$(runuser -u alice -- python3 -c 'import site; print(site.getusersitepackages())')
runuser -u alice -- mkdir -p "$SITE"
echo "import os; open('/run/lg-test/pth-ran', 'w').close()" | runuser -u alice -- tee "$SITE/evil.pth" >/dev/null
printf '#!/bin/sh\ntouch /run/lg-test/evil-helper-ran\nexit 10\n' | runuser -u alice -- tee /home/alice/evil/helper >/dev/null
printf '#!/bin/sh\ntouch /run/lg-test/evil-gui-ran\necho run\n' | runuser -u alice -- tee /home/alice/evil/luxos-guard-gui >/dev/null
chmod 755 /home/alice/evil/helper /home/alice/evil/luxos-guard-gui
printf 'import os\nopen("/run/lg-test/evil-py-ran", "w").close()\nraise SystemExit(10)\n' | \
    runuser -u alice -- tee /home/alice/evilpy/luxos_guard_core.py >/dev/null

PYTHONDONTWRITEBYTECODE=1 python3 -I - "$pass" "$fail" <<'PYEOF'
import json
import os
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/luxos/python")
import luxos_guard_core as C      # noqa: E402
import luxos_guard_rules as R     # noqa: E402
import luxos_guard_service as S   # noqa: E402

AGENT = C.AGENT_EXE
results = {"pass": 0, "fail": 0}


def ok(m):
    print("PASS", m, flush=True)
    results["pass"] += 1


def bad(m):
    print("FAIL", m, flush=True)
    results["fail"] += 1


def check(cond, m):
    (ok if cond else bad)(m)


class Fan:
    def __init__(self):
        self.r, self.w = os.pipe()
        self.responses = {}

    def fileno(self):
        return self.r

    def mark(self, *a, **k):
        pass

    def respond(self, fd, allow):
        st = os.fstat(fd)
        self.responses[(st.st_dev, st.st_ino)] = allow

    def read(self, size=0):
        return []


fan = Fan()
os.makedirs("/var/lib/luxos-guard", exist_ok=True)
g = S.Guard(fan, None, C.State("/var/lib/luxos-guard/state.json"), C.Proc(), C.Users())
threading.Thread(target=S.serve, args=(g, C.SOCKET), daemon=True).start()
for _ in range(100):
    if os.path.exists(C.SOCKET):
        break
    time.sleep(0.05)
check(oct(os.stat(C.SOCKET).st_mode & 0o777) == "0o666", "socket for CLI ops")


def uid_of(user):
    import pwd
    return pwd.getpwnam(user).pw_uid


def wait(cond, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def start_agent(user, extra_env=None):
    env = {"PATH": "/usr/bin", "HOME": "/home/" + user, "LANG": "C.UTF-8",
           "LUXOS_GUARD_AGENT_UPDATE_CHECK": "1", "LUXOS_GUARD_AGENT_UPDATE_DELAY": "1"}
    env.update(extra_env or {})
    return subprocess.Popen(["setpriv", "--reuid", user, "--regid", user, "--init-groups", AGENT], env=env,
                            stderr=subprocess.PIPE, text=True)


def agents(user):
    return [c for c in g.agents.get(uid_of(user), [])]


def risky(user, name):
    path = f"/home/{user}/Downloads/{name}"
    with open(path, "w") as f:
        f.write("#!/bin/sh\necho game %s\n" % name)
    os.chown(path, uid_of(user), uid_of(user))
    fd = os.open(path, os.O_RDONLY)
    st = os.fstat(fd)
    verdict = R.classify(open(path, "rb").read(), name)
    entry = C.make_entry(path, st, verdict, ("download", None), uid_of(user), C.sha256_fd(fd))
    key = (st.st_dev, st.st_ino)
    g.state.put(key, entry)
    return path, fd, key, entry


def ask(user, name, answer):
    with open("/run/lg-test/answer", "w") as f:
        f.write(answer + "\n")
    path, fd, key, entry = risky(user, name)
    g._ask(entry, key, uid_of(user), S.PERM_EXEC, fd, os.getpid())
    wait(lambda: key in fan.responses, 20)
    return fan.responses.get(key)


def impostor(user, code):
    return subprocess.run(["setpriv", "--reuid", user, "--regid", user, "--init-groups", "python3", "-c", code],
                          capture_output=True, text=True, timeout=20)


HELLO = ("import json,socket;s=socket.socket(socket.AF_UNIX);s.connect('%s');"
         "s.sendall(b'{\"op\":\"hello\",\"role\":\"agent\"}\\n');print(s.makefile().readline())" % C.SOCKET)

# 1. podvodnik: obycejny program uzivatele se prohlasi za agenta
r = impostor("alice", HELLO)
check('"agent": false' in r.stdout and not agents("alice"), "impostor hello refused")
check(ask("alice", "a1.sh", "run") is False, "no verified agent -> denied without asking")

# 2. podvodnik s pripojenim zdedenym setgid programem (fork + exec): skupinu urcuje jadro pri connect()
code = ("import os,socket,time;s=socket.socket(socket.AF_UNIX);s.connect('%s');os.set_inheritable(s.fileno(),True);"
        "pid=os.fork()\n"
        "if pid==0:\n time.sleep(0.5);s.sendall(b'{\"op\":\"hello\",\"role\":\"agent\"}\\n');"
        "print(s.makefile().readline(),flush=True);os._exit(0)\n"
        "else:\n os.execv('%s',['%s'])\n" % (C.SOCKET, AGENT, AGENT))
p = subprocess.Popen(["setpriv", "--reuid", "alice", "--regid", "alice", "--init-groups", "python3", "-c", code],
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
time.sleep(1.5)
p.kill()
check(not agents("alice"), "inherited-connection impostor refused (agent not setgid yet)")

# 3. program jeste bez setgid (rozbaleny balik pred post_install): sluzba ho neprijme ...
a = start_agent("alice")
time.sleep(1.5)
check(not agents("alice"), "agent without setgid refused")
# ... po nastaveni setgid (post_install/post_upgrade) prejde sam na novou verzi (razitko vcetne prav)
subprocess.run(["chgrp", "luxos-guard", AGENT], check=True)
os.chmod(AGENT, 0o2755)
check(wait(lambda: agents("alice"), 15), "agent re-execs after setgid is set and is accepted")
check(ask("alice", "a2.sh", "run") is True, "verified agent: user clicked Run -> allowed")
check(ask("alice", "a3.sh", "deny") is False, "verified agent: user clicked Don't run -> denied")
gid_line = open("/run/lg-test/gui-gid.%d" % uid_of("alice")).read().split()
check(str(C.agent_gid()) not in gid_line[1:], "helper/GUI run without the luxos-guard group (%s)" % " ".join(gid_line))

# 4. fork trick po setgid: podvodnik se pripoji sam a pak spusti skutecny program se zdedenym spojenim
p = subprocess.Popen(["setpriv", "--reuid", "alice", "--regid", "alice", "--init-groups", "python3", "-c", code],
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
time.sleep(2)
p.kill()
out = p.stdout.read() if p.stdout else ""
check('"agent": false' in out, "inherited connection of the real setgid program still refused (%s)" % out.strip())

# 5. restart / nove prihlaseni: pomocnik skonci a spusti se znovu
a.kill()
a.wait()
check(wait(lambda: not agents("alice"), 5), "agent gone after logout")
a = start_agent("alice")
check(wait(lambda: agents("alice"), 10), "agent accepted again after relogin")
check(ask("alice", "a4.sh", "run") is True, "after relogin: Run -> allowed")

# 6. restart sluzby: pomocnik se pripoji znovu (novy socket) - simulace: zavrit spojeni ze strany sluzby
old = set(map(id, agents("alice")))
for c in list(agents("alice")):
    c.sock.shutdown(socket.SHUT_RDWR)
check(wait(lambda: any(id(c) not in old for c in agents("alice")), 15),
      "agent reconnects after service-side disconnect")

# 7. skutecny program spusteny podvodnikem s podvrzenym prostredim: pomocnik a okno jsou porad ty systemove,
#    bez PYTHON*/LD_*/LUXOS_GUARD_*, s pevnou PATH, bez uzivatelskych site-packages
a.kill()
a.wait()
wait(lambda: not agents("alice"), 5)
a = start_agent("alice", {"LUXOS_GUARD_HELPER": "/home/alice/evil/helper", "PYTHONPATH": "/home/alice/evilpy",
                          "PATH": "/home/alice/evil:/usr/bin", "LUXOS_GUARD_GUI": "/home/alice/evil/luxos-guard-gui",
                          "GTK_MODULES": "/home/alice/evil/x.so", "LD_LIBRARY_PATH": "/home/alice/evil",
                          "LUXOS_GUARD_SOCKET": "/home/alice/evil/sock"})
check(wait(lambda: agents("alice"), 10), "agent with tampered env still connects to the real socket")
check(ask("alice", "a5.sh", "deny") is False, "tampered env: user's Don't run respected")
for marker in ("evil-helper-ran", "evil-gui-ran", "evil-py-ran", "pth-ran"):
    check(not os.path.exists("/run/lg-test/" + marker), "not executed: " + marker)
env = dict(line.split("=", 1) for line in open("/run/lg-test/gui-env.%d" % uid_of("alice")).read().splitlines()
           if "=" in line)
check(env.get("PATH") == "/usr/local/sbin:/usr/local/bin:/usr/bin", "helper PATH fixed (%s)" % env.get("PATH"))
leaked = [k for k in env if k.startswith(("PYTHON", "LD_", "GTK_MODULES")) or
          (k.startswith("LUXOS_GUARD_") and k != "LUXOS_GUARD_MSG")]
check(not leaked, "no dangerous variables in helper env %s" % leaked)

# 8. druhy uzivatel: vlastni pomocnik, dotazy oddelene
b = start_agent("bob")
check(wait(lambda: agents("bob"), 10), "second user's agent accepted")
check(ask("bob", "b1.sh", "run") is True, "bob: Run -> allowed")
rid = g.next_id
path, fd, key, entry = risky("alice", "a6.sh")
with open("/run/lg-test/answer", "w") as f:
    f.write("deny\n")
g._ask(entry, key, uid_of("alice"), S.PERM_EXEC, fd, os.getpid())
r = g.on_message(agents("bob")[0], {"op": "answer", "id": rid, "choice": "run"})
check(r and r.get("op") == "error", "bob's agent cannot answer alice's question")
wait(lambda: key in fan.responses, 20)
check(fan.responses.get(key) is False, "alice's own answer used")

# 9. CLI allow uzivatele: potvrzeni v okne
with open("/run/lg-test/answer", "w") as f:
    f.write("deny\n")
path, fd, key, entry = risky("alice", "a7.sh")
os.close(fd)
r = subprocess.run(["setpriv", "--reuid", "alice", "--regid", "alice", "--init-groups", "python3",
                    os.environ.get("LG_CLI", "/src/packages/luxos-guard/files/luxos-guard"), "allow", path],
                   capture_output=True, text=True, timeout=120,
                   env={"PATH": "/usr/bin", "LANG": "C.UTF-8", "PYTHONPATH": "/usr/lib/luxos/python"})
check(r.returncode != 0 and "not confirmed" in r.stderr, "CLI allow + Don't run in window -> refused")
check(g.state.get(key)["status"] == C.FLAGGED, "file still flagged")
with open("/run/lg-test/answer", "w") as f:
    f.write("run\n")
r = subprocess.run(["setpriv", "--reuid", "alice", "--regid", "alice", "--init-groups", "python3",
                    "/src/packages/luxos-guard/files/luxos-guard", "allow", path],
                   capture_output=True, text=True, timeout=120,
                   env={"PATH": "/usr/bin", "LANG": "C.UTF-8", "PYTHONPATH": "/usr/lib/luxos/python"})
check(r.returncode == 0 and g.state.get(key)["status"] == C.ALLOWED, "CLI allow + Run in window -> allowed")

for pr in (a, b):
    pr.kill()
print("python: %d passed, %d failed" % (results["pass"], results["fail"]))
sys.exit(1 if results["fail"] else 0)
PYEOF
rc=$?
echo "== result: $([[ $rc -eq 0 ]] && echo OK || echo FAILED)"
exit $rc
