# Lux Guard - pomocnik v sezeni uzivatele (automaticke spusteni po prihlaseni).
#
# Drzi spojeni se sluzbou luxos-guard (socket /run/luxos-guard/guard.sock, radky JSON) a teprve kdyz je
# potreba, spusti na chvili pomocnika v Pythonu (luxos-guard-agent-helper): okno luxos-guard-gui (dotaz
# u rizikoveho programu, zprava o zablokovani), upozorneni a volby "Spustit v sandboxu" / "Presunout do
# kose". V klidu bezi jen tento maly program bez Pythonu a GTK (driv Python ~12 MB PSS, ted ~1 MB).
#
#   ask      pomocnik "ask" ukaze dotaz a skonci kodem volby; odpoved {"op": "answer"} jde hned sluzbe,
#            "Spustit v sandboxu" / "Presunout do kose" pak provede pomocnik "act". Bez odpovedi do
#            ASK_TIMEOUT - 2 s (pomocnik zamrzl nebo nejde spustit) se posle "deny" (sluzba by stejne zamitla).
#   blocked  jedno okno pro kazdou cestu najednou (pomocnik "blocked" provede i volbu uzivatele)
#   found    upozorneni jen jednou pro stejny obsah (SHA-256 prvnich 4 MiB; kopie souboru na vic mistech
#            i stejny soubor znovu = bez dalsiho upozorneni, zmeneny soubor = nove upozorneni)
#
# Sluzba nebezi / restart: nove spojeni po 1, 2, 4 ... nejvys 30 s. Konec sezeni: rodic skoncil nebo zmizel
# socket X serveru (kontrola kazdych 20 s). Aktualizace baliku nahradila tento program: po 5 s se spusti
# nova verze (autostart by ho jinak znovu nespustil az do dalsiho prihlaseni). Pomocnik je Python
# spousteny pokazde znovu, jeho aktualizace se projevi hned.
#
# Promenne pro testy: LUXOS_GUARD_SOCKET, LUXOS_GUARD_HELPER, LUXOS_GUARD_ASK_TIMEOUT (s),
# LUXOS_GUARD_AGENT_SESSION_CHECK (s), LUXOS_GUARD_AGENT_UPDATE_CHECK (s), LUXOS_GUARD_AGENT_UPDATE_DELAY (s),
# LUXOS_GUARD_AGENT_XDIR (slozka socketu X serveru misto /tmp/.X11-unix).
load env, json
load luxos_guard_sys as sys

SOCKET = env.get("LUXOS_GUARD_SOCKET", "")
if SOCKET == "":
    SOCKET = "/run/luxos-guard/guard.sock"
end
HELPER = env.get("LUXOS_GUARD_HELPER", "")
if HELPER == "":
    HELPER = "/usr/lib/luxos-guard/luxos-guard-agent-helper"
end
MSG_ENV = "LUXOS_GUARD_MSG"
FOUND_HEAD = 4194304          # 4 MiB jako drive v Pythonu (found_key)
# Kody volby z pomocnika (luxos-guard-agent-helper): 10 run, 11 sandbox, 12 deny, 13 trash, 14 close
CHOICES = ["run", "sandbox", "deny", "trash", "close"]

function seconds(name, default_value):
    value = env.get(name, "")
    if value == "":
        return default_value
    end
    safe:
        return Int(value)
    end
    return default_value
end

ASK_TIMEOUT = seconds("LUXOS_GUARD_ASK_TIMEOUT", 90)
SESSION_CHECK = seconds("LUXOS_GUARD_AGENT_SESSION_CHECK", 20)
UPDATE_CHECK = seconds("LUXOS_GUARD_AGENT_UPDATE_CHECK", 60)
UPDATE_DELAY = seconds("LUXOS_GUARD_AGENT_UPDATE_DELAY", 5)

# Stav: spojeni, rozpracovane dotazy a okna, uz ohlasene soubory
G = {"fd": -1, "delay": 1, "connect_at": 0, "partial": False}
children = {}       # pid -> {"kind": ask|blocked|act|found, "msg": ..., "answered": Bool, "deadline": ms}
showing = {}        # cesta -> True: okno o zablokovani je prave otevrene
found = {}          # klic obsahu -> True

function log(message):
    call sys.eprint("luxos-guard-agent: " + message)
    return 0
end

function send(obj):
    if G["fd"] < 0:
        return False
    end
    return sys.send_text(G["fd"], json.encode(obj) + "\n")
end

function spawn_helper(kind, msg, args):
    argv = [HELPER, kind]
    for a in args:
        call argv.append(a)
    end
    pid = sys.spawn(argv, MSG_ENV, json.encode(msg))
    if pid <= 0:
        call log("cannot start " + HELPER)
        return 0
    end
    children[pid] = {"kind": kind, "msg": msg, "answered": False, "deadline": sys.monotonic_ms() + (ASK_TIMEOUT - 2) * 1000}
    return pid
end

function answer(child, choice):
    if child["answered"]:
        return 0
    end
    child["answered"] = True
    call send({"op": "answer", "id": child["msg"].get("id"), "choice": choice})
    return 0
end

# Stejny obsah = stejne upozorneni, i kdyz je soubor na vic mistech (kopie, pracovni slozky gitu)
function found_key(path):
    digest = ""
    if path != "":
        digest = sys.sha256_head(path, FOUND_HEAD)
    end
    if digest == "":
        return "path:" + path
    end
    return "sha256:" + digest
end

function text_of(value):
    if type(value) == "String":
        return value
    end
    return ""
end

function handle(msg):
    op = msg.get("op")
    if op == "ask":
        if spawn_helper("ask", msg, []) <= 0:
            # pomocnik nejde spustit: zamitnout hned (sluzba by jinak cekala na limit)
            call send({"op": "answer", "id": msg.get("id"), "choice": "deny"})
        end
    elif op == "blocked":
        path = text_of(msg.get("path"))
        if path in showing:
            return 0
        end
        if spawn_helper("blocked", msg, []) > 0:
            showing[path] = True
        end
    elif op == "found":
        # stejny soubor (obsah) jen jednou - dalsi kontroly by jinak ukazovaly stejne upozorneni porad dokola
        key = found_key(text_of(msg.get("path")))
        if key in found:
            return 0
        end
        found[key] = True
        call spawn_helper("found", msg, [])
    end
    return 0
end

function on_exit(pid, code):
    if pid not in children:
        return 0
    end
    child = children.pop(pid)
    kind = child["kind"]
    if kind == "ask":
        choice = "deny"
        if code >= 10 and code < 10 + len(CHOICES) and CHOICES[code - 10] in ["run", "sandbox", "trash"]:
            choice = CHOICES[code - 10]
        end
        if not child["answered"]:
            call answer(child, choice)
            if choice == "sandbox" or choice == "trash":
                call spawn_helper("act", child["msg"], [choice])
            end
        end
    elif kind == "blocked":
        path = text_of(child["msg"].get("path"))
        if path in showing:
            call showing.pop(path)
        end
    end
    return 0
end

function on_lines(text):
    for line in text.split("\n"):
        if line.strip() == "":
            continue
        end
        msg = None
        safe:
            msg = json.decode(line)
        end
        if type(msg) == "Dictionary":
            call handle(msg)
        end
    end
    return 0
end

function disconnect(now):
    call sys.close(G["fd"])
    G["fd"] = -1
    G["partial"] = False
    G["connect_at"] = now + 1000
    G["delay"] = 1
    return 0
end

function try_connect(now):
    fd = sys.unix_connect(SOCKET)
    if fd < 0:
        G["connect_at"] = now + G["delay"] * 1000
        G["delay"] = G["delay"] * 2
        if G["delay"] > 30:
            G["delay"] = 30
        end
        return False
    end
    G["fd"] = fd
    G["delay"] = 1
    G["partial"] = False
    if not send({"op": "hello", "role": "agent"}):
        call disconnect(now)
        return False
    end
    return True
end

# ---- start ------------------------------------------------------------------------------------------------

if sys.getuid() == 0:
    call exit(0)
end
if exists("/run/archiso"):
    call exit(0)                # live system z USB: sluzba nebezi (instalace)
end

self_path = sys.readlink("/proc/self/exe")
self_stamp = sys.stamp(self_path)
parent = sys.getppid()
display = env.get("DISPLAY", "")
xsock = ""
if display.startswith(":"):
    number = display[1:].split(".")[0]
    xdir = env.get("LUXOS_GUARD_AGENT_XDIR", "")
    if xdir == "":
        xdir = "/tmp/.X11-unix"
    end
    xsock = xdir + "/X" + number
    if not exists(xsock):
        xsock = ""
    end
end

now = sys.monotonic_ms()
session_at = now + SESSION_CHECK * 1000
update_at = now + UPDATE_CHECK * 1000
exec_at = 0

while True:
    now = sys.monotonic_ms()
    # skoncene procesy pomocnika
    while True:
        done = sys.reap()
        if done[0] <= 0:
            break
        end
        call on_exit(done[0], done[1])
    end
    # dotaz bez odpovedi pomocnika: zamitnout driv, nez to udela sluzba
    for cpid in children.keys():
        pending = children[cpid]
        if pending["kind"] == "ask" and not pending["answered"] and now >= pending["deadline"]:
            call log("no answer from helper, denying")
            call answer(pending, "deny")
        end
    end
    if G["fd"] < 0 and now >= G["connect_at"]:
        call try_connect(now)
    end
    if now >= session_at:
        session_at = now + SESSION_CHECK * 1000
        if (parent != 1 and sys.getppid() != parent) or (xsock != "" and not exists(xsock)):
            call exit(0)
        end
    end
    if exec_at == 0 and now >= update_at:
        update_at = now + UPDATE_CHECK * 1000
        if self_path != "" and sys.stamp(self_path) != self_stamp:
            exec_at = now + UPDATE_DELAY * 1000      # instalace baliku muze jeste bezet
        end
    end
    if exec_at != 0 and now >= exec_at:
        call sys.close(G["fd"])
        call sys.exec([self_path])
        exec_at = 0
        self_stamp = sys.stamp(self_path)
    end

    # spanek do dalsi udalosti (s bezicim pomocnikem nejvys 200 ms kvuli sberu procesu)
    wake = session_at
    if exec_at == 0 and update_at < wake:
        wake = update_at
    end
    if exec_at != 0 and exec_at < wake:
        wake = exec_at
    end
    if G["fd"] < 0 and G["connect_at"] < wake:
        wake = G["connect_at"]
    end
    timeout = wake - now
    if len(children) > 0 and timeout > 200:
        timeout = 200
    end
    if G["partial"] and timeout > 20:
        timeout = 20
    end
    if timeout < 0:
        timeout = 0
    end
    watch_fd = G["fd"]
    if G["partial"]:
        watch_fd = -1           # cast radku uz je ve fronte: nespinat smycku poll() na stejnych datech
    end
    if sys.wait_readable(watch_fd, timeout) or G["partial"]:
        if G["fd"] >= 0:
            got = sys.read_lines(G["fd"])
            G["partial"] = got[0] == 2
            if got[0] == 0:
                call disconnect(sys.monotonic_ms())
            elif got[0] == 1:
                call on_lines(got[1])
            end
        end
    end
end
