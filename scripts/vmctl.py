#!/usr/bin/env python3
"""LuxOS - ovladani testovaci VM (QMP + QEMU guest agent).

  vmctl.py shot out.png            snimek obrazovky
  vmctl.py exec 'prikaz'           spusti prikaz v hostu (root, bash -c), vypise vystup
  vmctl.py keys 'text'             napise text (US rozlozeni)
  vmctl.py key ctrl-alt-t          stiskne kombinaci klaves (nazvy QEMU qcode)
  vmctl.py click X Y [W H]         klik levym tlacitkem (souradnice obrazovky, vychozi 1280x800)
  vmctl.py move X Y [W H]          presune kurzor
vmctl.py rclick X Y [W H]        klik pravym tlacitkem
vmctl.py scrollup|scrolldown X Y [W H]  jeden zub kolecka mysi
  vmctl.py put SOUBOR CIL          nahraje soubor do hosta
  vmctl.py ping                    ceka na guest agenta
  vmctl.py wakeup                  probudi uspaneho hosta (QMP system_wakeup)
  vmctl.py status                  stav VM (running, suspended...)
"""
import base64, json, os, socket, sys, time

T = os.environ.get("LUXOS_VM_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "test")


def rpc(path, msg, qmp=False, timeout=30):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(path)
    f = s.makefile("rwb")
    if qmp:
        f.readline()
        f.write(b'{"execute":"qmp_capabilities"}\n'); f.flush(); f.readline()
    else:
        # synchronizace guest agenta
        f.write(b'{"execute":"guest-sync","arguments":{"id":4242}}\n'); f.flush()
        while b"4242" not in f.readline():
            pass
    f.write(json.dumps(msg).encode() + b"\n"); f.flush()
    while True:
        line = f.readline()
        if not line:
            raise RuntimeError("connection closed")
        r = json.loads(line)
        if "return" in r or "error" in r:
            s.close()
            if "error" in r:
                raise RuntimeError(r["error"])
            return r["return"]


def qga(cmd, args=None, timeout=30):
    return rpc(os.path.join(T, "qga.sock"), {"execute": cmd, "arguments": args or {}}, timeout=timeout)


def qmp(cmd, args=None):
    return rpc(os.path.join(T, "qmp.sock"), {"execute": cmd, "arguments": args or {}}, qmp=True)


def gexec(command, timeout=600):
    pid = qga("guest-exec", {"path": "/bin/bash", "arg": ["-c", command], "capture-output": True})["pid"]
    end = time.time() + timeout
    while time.time() < end:
        st = qga("guest-exec-status", {"pid": pid})
        if st.get("exited"):
            out = base64.b64decode(st.get("out-data", "")).decode(errors="replace")
            err = base64.b64decode(st.get("err-data", "")).decode(errors="replace")
            return st.get("exitcode", -1), out, err
        time.sleep(1)
    raise TimeoutError(command)


KEYMAP = {" ": "spc", "\n": "ret", "-": "minus", "=": "equal", ".": "dot", ",": "comma", "/": "slash",
          ";": "semicolon", "'": "apostrophe", "[": "bracket_left", "]": "bracket_right", "\\": "backslash"}
SHIFTED = {"_": "minus", "+": "equal", ":": "semicolon", '"': "apostrophe", "?": "slash", "!": "1", "@": "2",
           "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", "<": "comma", ">": "dot",
           "|": "backslash", "~": "grave_accent"}


def send(keys):
    qmp("send-key", {"keys": [{"type": "qcode", "data": k} for k in keys]})
    time.sleep(0.05)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 1
    c = a[0]
    if c == "shot":
        out = os.path.abspath(a[1])
        qmp("screendump", {"filename": out, "format": "png"})
        print(out)
    elif c == "exec":
        rc, out, err = gexec(a[1], timeout=int(a[2]) if len(a) > 2 else 600)
        sys.stdout.write(out); sys.stderr.write(err)
        return rc
    elif c == "put":
        h = qga("guest-file-open", {"path": a[2], "mode": "wb"})
        with open(a[1], "rb") as f:
            while chunk := f.read(48 * 1024):
                qga("guest-file-write", {"handle": h, "buf-b64": base64.b64encode(chunk).decode()})
        qga("guest-file-close", {"handle": h})
    elif c == "ping":
        end = time.time() + (int(a[1]) if len(a) > 1 else 300)
        while time.time() < end:
            try:
                qga("guest-ping", timeout=5); print("ok"); return 0
            except Exception:
                time.sleep(3)
        print("timeout"); return 1
    elif c == "keys":
        for ch in a[1]:
            if ch in SHIFTED: send(["shift", SHIFTED[ch]])
            elif ch.isupper(): send(["shift", ch.lower()])
            else: send([KEYMAP.get(ch, ch)])
    elif c in ("click", "move", "rclick", "scrollup", "scrolldown"):
        x, y = int(a[1]), int(a[2])
        w, h = (int(a[3]), int(a[4])) if len(a) > 4 else (1280, 800)
        ax, ay = x * 32767 // (w - 1), y * 32767 // (h - 1)
        # Pohyb po kouscich jako skutecna mys (GTK potrebuje najeti nad prvek pred klikem)
        for dx in (-3, -1, 0):
            qmp("input-send-event", {"events": [
                {"type": "abs", "data": {"axis": "x", "value": max(ax + dx * 40, 0)}},
                {"type": "abs", "data": {"axis": "y", "value": ay}}]})
            time.sleep(0.05)
        time.sleep(0.15)
        button = {"click": "left", "rclick": "right", "scrollup": "wheel-up", "scrolldown": "wheel-down"}.get(c)
        for down in ((True, False) if button else ()):
            qmp("input-send-event", {"events": [{"type": "btn", "data": {"down": down, "button": button}}]})
            time.sleep(0.08)
    elif c == "key":
        send(a[1].split("-"))
    elif c == "wakeup":
        # probuzeni hosta z uspani (systemctl suspend v hostu)
        qmp("system_wakeup")
    elif c == "status":
        print(qmp("query-status").get("status"))
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
