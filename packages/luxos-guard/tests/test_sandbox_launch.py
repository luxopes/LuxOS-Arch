"""Lux Guard "Spustit v sandboxu": program s oknem bez terminalu; textovy program v terminalu jen kdyz byl
spusteny z terminalu nebo se zjevne pta (read, input()); jinak bez okna a terminalu s vystupem
zachycenym do souboru a jednim upozornenim (Zobrazit vystup, u dlouheho behu Zastavit).

Klasifikace na skutecnych ELF (male programy X11/GTK/CLI prelozene v testu), AppImage, skriptech
a spoustecich .desktop; spousteni s podvrzenymi luxos-sandbox / luxos-terminal / notify-send, ktere jen
zapisi, jak byly zavolany (zadny skutecny sandbox, pkexec ani okno).

Spusteni: python3 -m pytest -q packages/luxos-guard/tests/test_sandbox_launch.py
"""
import os
import random
import shutil
import subprocess
import time

import pytest

import luxos_guard_core as C
import luxos_guard_rules as R
import luxos_guard_session as S
from test_core import FakeProc

CLI_C = '#include <stdio.h>\nint main(void){puts("hello");return 0;}\n'
X11_C = '#include <X11/Xlib.h>\nint main(void){Display*d=XOpenDisplay(0);return d?0:1;}\n'
GTK_C = '#include <gtk/gtk.h>\nint main(int c,char**v){gtk_init(&c,&v);return 0;}\n'


def cc(tmp, name, src, flags=()):
    if not shutil.which("gcc"):
        pytest.skip("gcc neni k dispozici")
    c = tmp / (name + ".c")
    c.write_text(src)
    out = tmp / name
    r = subprocess.run(["gcc", "-O0", "-o", str(out), str(c), *flags], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"preklad {name} selhal: {r.stderr[-200:]}")
    return str(out)


def pkg_flags(pkg):
    r = subprocess.run(["pkg-config", "--cflags", "--libs", pkg], capture_output=True, text=True) \
        if shutil.which("pkg-config") else None
    if not r or r.returncode != 0:
        pytest.skip(f"{pkg} (pkg-config) neni k dispozici")
    return r.stdout.split()


def kind_of(path):
    with open(path, "rb") as f:
        k = R.detect_kind(f.read(64), os.path.basename(path))
    return k


@pytest.fixture(scope="module")
def elves(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("elf")
    out = {"cli": cc(tmp, "cli", CLI_C), "x11": cc(tmp, "x11", X11_C, ["-lX11"]),
           "gtk": cc(tmp, "gtk", GTK_C, pkg_flags("gtk+-3.0"))}
    # AppImage: ELF s magickym "AI\x02" na bajtu 8 (runtime typu 2)
    data = bytearray(open(out["cli"], "rb").read())
    data[8:11] = b"AI\x02"
    ai = tmp / "Tool-x86_64.AppImage"
    ai.write_bytes(bytes(data))
    out["appimage"] = str(ai)
    return out


def write(tmp, name, text, mode=0o644):
    p = tmp / name
    p.write_text(text) if isinstance(text, str) else p.write_bytes(text)
    os.chmod(p, mode)
    return str(p)


# ---- ELF ---------------------------------------------------------------------------------------
def test_elf_needed_reads_real_binaries(elves):
    libs = S.elf_needed(open(elves["x11"], "rb").read())
    assert "libX11.so.6" in libs and "libc.so.6" in libs
    assert "libX11.so.6" not in S.elf_needed(open(elves["cli"], "rb").read())
    assert any(x.startswith("libgtk-3") for x in S.elf_needed(open(elves["gtk"], "rb").read()))


def test_elf_gui_vs_cli(elves):
    assert S.elf_is_gui(elves["x11"]) and S.elf_is_gui(elves["gtk"])
    assert not S.elf_is_gui(elves["cli"])
    assert kind_of(elves["cli"])[0] == "elf"
    assert S.launch_plan(elves["gtk"], "elf") == {"argv": [elves["gtk"]], "gui": True, "terminal": False}
    assert S.launch_plan(elves["x11"], "elf")["terminal"] is False
    # bez terminalu u zablokovaneho procesu: bez okna i bez terminalu (vystup do upozorneni)
    assert S.launch_plan(elves["cli"], "elf") == {"argv": [elves["cli"]], "gui": False, "terminal": False}
    assert S.launch_plan(elves["cli"], "elf", terminal=True)["terminal"] is True


def test_static_elf(tmp_path):
    p = cc(tmp_path, "static", CLI_C, ["-static"])
    assert S.elf_needed(open(p, "rb").read()) == []
    assert S.launch_plan(p, "elf")["terminal"] is False


def test_damaged_elf_never_raises(elves, tmp_path):
    good = open(elves["gtk"], "rb").read()
    assert S.elf_needed(good[:40]) is None                    # useknuta hlavicka
    assert S.elf_needed(b"\x7fELF" + b"\xff" * 60) is None
    assert S.elf_needed(b"not an elf") is None
    rnd = random.Random(7)
    for _ in range(300):
        d = bytearray(good[:8192])
        for _k in range(rnd.randint(1, 20)):
            d[rnd.randrange(16, 128)] = rnd.randrange(256)
        r = S.elf_needed(bytes(d))
        assert r is None or isinstance(r, list)
    bad = write(tmp_path, "bad", b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x03\x00" + b"\xff" * 100, 0o755)
    assert S.launch_plan(bad, "elf") == {"argv": [bad], "gui": False, "terminal": False}


def test_appimage_is_gui(elves):
    assert kind_of(elves["appimage"])[0] == "appimage"
    assert S.launch_plan(elves["appimage"], "appimage") == {"argv": [elves["appimage"]], "gui": True,
                                                             "terminal": False}


def test_symlink_and_missing_file_not_followed(elves, tmp_path):
    link = tmp_path / "link"
    os.symlink(elves["gtk"], link)
    assert not S.elf_is_gui(str(link))
    assert not S.elf_is_gui(str(tmp_path / "missing"))


# ---- skripty -----------------------------------------------------------------------------------
@pytest.mark.parametrize("name,text,gui,asks", [
    ("install.sh", "#!/bin/bash\necho installing\ncp a b\n", False, False),
    ("usage.sh", "#!/bin/sh\necho 'usage: tool [-h] FILE' >&2\nexit 1\n", False, False),
    ("ask.sh", "#!/bin/sh\nread -r -p 'Name? ' n\necho $n\n", False, True),
    ("confirm.sh", "#!/bin/bash\nif true; then read -n1 ans; fi\n", False, True),
    ("tty.sh", "#!/bin/sh\nread pw < /dev/tty\n", False, True),
    ("menu.sh", "#!/bin/bash\nselect x in a b; do break; done\n", False, True),
    ("whip.sh", "#!/bin/sh\nwhiptail --yesno Go 8 40\n", False, True),
    ("loop.sh", "#!/bin/sh\nwhile read -r line; do echo $line; done < list.txt\n", False, False),
    ("pipe.sh", "#!/bin/sh\nls | while read f; do echo $f; done\n", False, False),
    ("herestr.sh", "#!/bin/bash\nread -r a b <<< \"$X\"\n", False, False),
    ("comment.sh", "#!/bin/sh\necho 'please read the README'\n", False, False),
    ("dlg.sh", "#!/bin/sh\nzenity --info --text=hi\n", True, False),
    ("dlg-read.sh", "#!/bin/sh\nzenity --info --text=hi\nread x\n", False, True),
    ("dlg-loop.sh", "#!/bin/sh\nwhile read l; do zenity --info --text=\"$l\"; done < f\n", True, False),
    ("noshebang.sh", "yad --text hi\n", True, False),
    ("hello.py", "#!/usr/bin/env python3\nprint('hello')\n", False, False),
    ("filter.py", "#!/usr/bin/env python3\nimport sys\nprint(sys.stdin.read().upper())\n", False, False),
    ("ask.py", "#!/usr/bin/env python3\nname = input('Name: ')\n", False, True),
    ("pw.py", "#!/usr/bin/env python3\nimport getpass\ngetpass.getpass()\n", False, True),
    ("tk.py", "#!/usr/bin/env python3\nimport tkinter as tk\ntk.Tk().mainloop()\n", True, False),
    ("qt.pyw", "from PyQt5.QtWidgets import QApplication\nQApplication([]).exec_()\n", True, False),
    ("gtk.py", "import gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk\nGtk.main()\n",
     True, False),
    ("glib.py", "from gi.repository import GLib\nGLib.MainLoop().run()\n", False, False),
    ("game.py", "import pygame\npygame.init()\n", True, False),
    ("tkask.py", "import tkinter\nname = input('Name: ')\n", False, True),
    ("tool.pl", "#!/usr/bin/perl\nuse Tk;\nMainLoop;\n", True, False),
    ("ask.pl", "#!/usr/bin/perl\nuse Tk;\nmy $x = <STDIN>;\n", False, True),
    ("cat.pl", "#!/usr/bin/perl\nwhile (<>) { print }\n", False, False),
    ("app.rb", "#!/usr/bin/ruby\nputs 1\n", False, False),
    ("ask.rb", "#!/usr/bin/ruby\nname = gets\n", False, True),
    ("ask.js", "#!/usr/bin/env node\nconst rl = require('readline').createInterface({input: process.stdin});\n",
     False, True),
])
def test_script_classification(tmp_path, name, text, gui, asks):
    p = write(tmp_path, name, text, 0o755)
    kind, interp = kind_of(p)
    assert kind == "script"
    plan = S.launch_plan(p, kind, interp)
    # terminal jen pro skript, ktery se zjevne pta; ostatni bez okna (vystup do upozorneni)
    assert plan == {"argv": [p], "gui": gui, "terminal": asks}
    assert S.launch_plan(p, kind, interp, terminal=True)["terminal"] is True


def test_self_extracting_script_text_part_only(tmp_path):
    p = write(tmp_path, "setup.run", b"#!/bin/sh\nzenity --info\nexit 0\n\x00\x01" + b"read x " * 10, 0o755)
    assert S.launch_plan(p, "script", "sh")["gui"] is True


# ---- spoustece .desktop ------------------------------------------------------------------------
def test_desktop_gui_launcher(tmp_path):
    p = write(tmp_path, "app.desktop", "[Desktop Entry]\nType=Application\nName=App\n"
              "Exec=\"/home/anna/Downloads/My App.AppImage\" --flag %U\nTerminal=false\n"
              "[Desktop Action new]\nExec=other\n")
    assert kind_of(p)[0] == "desktop"
    assert S.launch_plan(p, "desktop") == {"argv": ["/home/anna/Downloads/My App.AppImage", "--flag"],
                                           "gui": True, "terminal": False}


def test_desktop_default_terminal_false_and_escapes(tmp_path):
    p = write(tmp_path, "x.desktop", "[Desktop Entry]\nName=X\nExec=sh -c \"echo 100%%\\sdone\" %f\n")
    assert S.launch_plan(p, "desktop") == {"argv": ["sh", "-c", "echo 100% done"], "gui": True,
                                           "terminal": False}


def test_desktop_terminal_true(tmp_path):
    p = write(tmp_path, "t.desktop", "[Desktop Entry]\nType=Application\nExec=htop\nTerminal=true\n")
    assert S.launch_plan(p, "desktop") == {"argv": ["htop"], "gui": False, "terminal": True}


def test_desktop_relative_exec_uses_path_key(tmp_path):
    p = write(tmp_path, "r.desktop", "[Desktop Entry]\nExec=./game.x86_64\nPath=/opt/game\n")
    assert S.launch_plan(p, "desktop")["argv"] == ["/opt/game/game.x86_64"]
    q = write(tmp_path, "r2.desktop", "[Desktop Entry]\nExec=bin/run\n")
    assert S.launch_plan(q, "desktop")["argv"] == [str(tmp_path / "bin" / "run")]


@pytest.mark.parametrize("text", [
    "[Desktop Entry]\nType=Link\nURL=https://example.com\n",
    "[Desktop Entry]\nType=Application\nName=No exec\n",
    "[Desktop Entry]\nExec=\"unterminated\n",
    "[Other]\nExec=foo\n",
    "[Desktop Entry]\nExec=%U\n",
])
def test_desktop_nothing_to_run(tmp_path, text):
    assert S.launch_plan(write(tmp_path, "n.desktop", text), "desktop") is None


# ---- vyslovna volba uzivatele --------------------------------------------------------------------
def test_explicit_terminal_choice_wins(elves, tmp_path):
    assert S.launch_plan(elves["gtk"], "elf", terminal=True) == {"argv": [elves["gtk"]], "gui": True,
                                                                  "terminal": True}
    sh = write(tmp_path, "a.sh", "#!/bin/sh\necho hi\n", 0o755)
    assert S.launch_plan(sh, "script", "sh", terminal=False)["terminal"] is False


def test_proc_has_tty(tmp_path):
    fp = FakeProc(str(tmp_path / "proc"))
    p = fp.add(10, "/usr/bin/bash", ["bash"])
    assert p.has_tty(10) is False                              # bez souboru stat
    with open(tmp_path / "proc" / "10" / "stat", "w") as f:
        f.write("10 (we ird) name) S 1 10 10 34817 10 4194560 0 0\n")
    assert p.has_tty(10) is True
    with open(tmp_path / "proc" / "10" / "stat", "w") as f:
        f.write("10 (thunar) S 1 10 10 0 -1 4194560 0 0\n")
    assert p.has_tty(10) is False
    assert C.Proc().has_tty(os.getpid()) in (True, False)


# ---- spousteni s podvrzenymi programy ----------------------------------------------------------
FAKE = """#!/bin/sh
# kazde volani do vlastniho souboru: nazev a argumenty oddelene znakem NUL (i s novymi radky)
printf '%s\\0' "${0##*/}" "$@" >"$CALLS/$$"
"""
# notify-send: -p vypise id (PID), -w vezme dalsi akci z fronty $ACTIONS (radek; "hang" = ceka, dokud
# ho hlidac neukonci; prazdny = zavreno bez volby)
NOTIFY = """
case " $* " in *" -p "*) echo $$ ;; esac
case " $* " in
  *" -w "*)
    a=$(/usr/bin/head -n 1 "$ACTIONS" 2>/dev/null); /usr/bin/tail -n +2 "$ACTIONS" > "$ACTIONS.t" 2>/dev/null
    /usr/bin/mv "$ACTIONS.t" "$ACTIONS" 2>/dev/null
    if [ "$a" = hang ]; then exec /usr/bin/sleep 30; fi
    [ -n "$a" ] && echo "$a" ;;
esac
exit 0
"""
SANDBOX = """echo "Copying into the sandbox..." >&2
if [ -n "$FAKE_OUT" ]; then printf '%b' "$FAKE_OUT"; fi
if [ -n "$FAKE_ERR" ]; then echo "$FAKE_ERR" >&2; fi
if [ -n "$FAKE_BIG" ]; then i=0; while [ $i -lt "$FAKE_BIG" ]; do echo "line $i ......................................"; i=$((i+1)); done; fi
if [ -n "$FAKE_SLEEP" ]; then echo $$ > "$CALLS/../sandbox.pid"; /usr/bin/sleep "$FAKE_SLEEP"; echo "woke up"; fi
exit "${FAKE_RC:-0}"
"""


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    calls.mkdir()
    for name, extra in (("luxos-sandbox", SANDBOX), ("luxos-terminal", ""), ("notify-send", NOTIFY),
                        ("luxos-sandbox-gui", ""), ("luxos-guard-gui", "")):
        f = bin_ / name
        f.write_text(FAKE + extra)
        f.chmod(0o755)
    base = tmp_path / "sbx"
    import pwd
    (base / pwd.getpwuid(os.getuid()).pw_name / "usr" / "bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", str(bin_))                     # zadny skutecny terminal ani sandbox
    monkeypatch.setenv("CALLS", str(calls))
    monkeypatch.setenv("ACTIONS", str(tmp_path / "actions"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))           # soukroma, ne /run/user skutecne relace
    monkeypatch.delenv("LUXOS_GUARD_GUI", raising=False)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setattr(S, "_", lambda text: text)            # texty anglicky bez ohledu na jazyk
    monkeypatch.setattr(S, "SANDBOX_CLI", "luxos-sandbox")
    monkeypatch.setattr(S, "SANDBOX_BASE", str(base))

    class F:
        dir = bin_
        tmp = tmp_path
        out_dir = run / "luxos-guard"

        def actions(self, *items):
            (tmp_path / "actions").write_text("".join(a + "\n" for a in items))

        def read(self, wait_for=None, timeout=5.0):
            end = time.time() + timeout
            while True:
                out = []
                for f in sorted(calls.iterdir()):
                    raw = f.read_bytes()
                    if raw.endswith(b"\0"):
                        out.append(raw[:-1].decode().split("\0"))
                if wait_for is None or any(c[0] == wait_for for c in out) or time.time() > end:
                    return out
                time.sleep(0.05)

        def settle(self, proc):
            if proc is not None and hasattr(proc, "wait"):
                proc.wait(5)
            time.sleep(0.4)                                     # vlakno _watch / notify-send
    return F()


def test_gui_program_runs_without_terminal(fakes, elves):
    p = S.run_in_sandbox(elves["gtk"], "elf", None)
    fakes.settle(p)
    calls = fakes.read()
    assert ["luxos-sandbox", "run", "--gui", "--", elves["gtk"]] in calls
    assert not [c for c in calls if c[0] in ("luxos-terminal", "notify-send")]


def test_appimage_and_desktop_without_terminal(fakes, elves, tmp_path):
    fakes.settle(S.run_in_sandbox(elves["appimage"], "appimage"))
    d = write(tmp_path, "a.desktop", "[Desktop Entry]\nExec=/home/anna/app --x %u\nTerminal=false\n")
    fakes.settle(S.run_in_sandbox(d, "desktop"))
    calls = fakes.read()
    assert ["luxos-sandbox", "run", "--gui", "--", elves["appimage"]] in calls
    assert ["luxos-sandbox", "run", "--gui", "--", "/home/anna/app", "--x"] in calls
    assert not [c for c in calls if c[0] == "luxos-terminal"]


def test_text_program_started_from_terminal_in_terminal_kept_open(fakes, elves, tmp_path):
    """Zablokovany proces mel terminal (uzivatel psal prikaz) -> terminal, ktery zustane otevreny."""
    S.run_in_sandbox(elves["cli"], "elf", None, terminal=True)
    sh = write(tmp_path, "i.sh", "#!/bin/sh\necho hi\n", 0o755)
    S.run_in_sandbox(sh, "script", "sh", terminal=True)
    calls = fakes.read("luxos-terminal")
    time.sleep(0.3)
    calls = fakes.read()
    term = [c for c in calls if c[0] == "luxos-terminal"]
    assert ["luxos-terminal", "--title", "Sandbox", "--hold", "-x", "luxos-sandbox", "run", "--", elves["cli"]] in term
    assert ["luxos-terminal", "--title", "Sandbox", "--hold", "-x", "luxos-sandbox", "run", "--", sh] in term
    assert not [c for c in calls if c[0] == "luxos-sandbox"]   # sandbox spousti az terminal


def test_script_that_asks_gets_terminal_without_tty(fakes, tmp_path):
    sh = write(tmp_path, "ask.sh", "#!/bin/sh\nread -r -p 'Continue? ' a\n", 0o755)
    S.run_in_sandbox(sh, "script", "sh")
    t = [c for c in fakes.read("luxos-terminal") if c[0] == "luxos-terminal"]
    assert t and t[0][-4:] == ["luxos-sandbox", "run", "--", sh]


def notifications(calls):
    return [c for c in calls if c[0] == "notify-send"]


def actions_of(call):
    return [call[i + 1] for i, a in enumerate(call) if a == "-A"]


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        r = cond()
        if r:
            return r
        time.sleep(0.05)
    return cond()


def test_no_tty_text_program_runs_without_terminal(fakes, tmp_path, monkeypatch):
    """Skutecny pripad: proces na pozadi spustil skript z AUR, ten vypise napovedu.
    Bez terminalu: bezi v sandboxu bez okna, vystup do souboru, jedno klidne upozorneni."""
    monkeypatch.setenv("FAKE_OUT", "usage: tool [-h] FILE\\n\\033[1mbold\\033[0m <b>x</b>\\n")
    monkeypatch.setenv("LC_ALL", "C")
    fakes.actions("")                                          # upozorneni zavreno bez volby
    sh = write(tmp_path, "tool.sh", "#!/bin/sh\necho 'usage: tool [-h] FILE'\n", 0o755)
    sup = S.run_in_sandbox(sh, "script", "sh")
    assert sup is not None and sup.wait(15) == 0               # hlidaci proces (samostatne sezeni)
    calls = fakes.read()
    assert ["luxos-sandbox", "run", "--", sh] in calls
    assert not [c for c in calls if c[0] in ("luxos-terminal", "luxos-guard-gui")]
    n = notifications(calls)
    assert len(n) == 1, n
    title, body = n[0][-2], n[0][-1]
    assert title == "tool.sh ran safely in the sandbox"
    assert "-u" in n[0] and n[0][n[0].index("-u") + 1] == "normal"
    assert actions_of(n[0]) == ["output=Show Output"] and "-w" in n[0]
    outs = list(fakes.out_dir.iterdir())
    assert len(outs) == 1
    st = os.stat(outs[0])
    assert oct(st.st_mode & 0o777) == "0o600" and oct(os.stat(fakes.out_dir).st_mode & 0o777) == "0o700"
    text = outs[0].read_text()
    assert "usage: tool [-h] FILE" in text and "bold <b>x</b>" in text and "\x1b" not in text


def test_show_output_opens_viewer(fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_OUT", "hello from the sandbox\\n")
    fakes.actions("output")
    sup = S.run_in_sandbox(write(tmp_path, "t.sh", "#!/bin/sh\necho x\n", 0o755), "script", "sh")
    sup.wait(15)
    g = [c for c in fakes.read("luxos-guard-gui") if c[0] == "luxos-guard-gui"]
    assert g and g[0][1] == "output" and g[0][3] == "t.sh"
    assert open(g[0][2]).read().endswith("\nhello from the sandbox\n")
    assert os.path.dirname(g[0][2]) == str(fakes.out_dir)


def test_error_exit_is_calm(fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "2")
    monkeypatch.setenv("FAKE_OUT", "missing argument\\n")
    fakes.actions("")
    S.run_in_sandbox(write(tmp_path, "t.sh", "#!/bin/sh\nexit 2\n", 0o755), "script", "sh").wait(15)
    n = notifications(fakes.read())
    assert len(n) == 1
    assert n[0][-2] == "t.sh finished with an error"
    assert "error code 2" in n[0][-1] and "not affected" in n[0][-1]
    assert n[0][n[0].index("-u") + 1] == "normal"


def test_crash_is_critical(fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "139")                       # SIGSEGV uvnitr sandboxu (128 + 11)
    fakes.actions("")
    S.run_in_sandbox(write(tmp_path, "t.sh", "#!/bin/sh\n", 0o755), "script", "sh").wait(15)
    n = notifications(fakes.read())
    assert n[0][-2] == "t.sh crashed in the sandbox" and n[0][n[0].index("-u") + 1] == "critical"


def test_no_output_no_button(fakes, tmp_path, monkeypatch):
    (fakes.dir / "luxos-sandbox").write_text(FAKE + "exit 0\n")
    S.run_in_sandbox(write(tmp_path, "q.sh", "#!/bin/sh\n", 0o755), "script", "sh").wait(15)
    n = notifications(fakes.read())
    assert len(n) == 1 and actions_of(n[0]) == [] and "-w" not in n[0]
    assert "did not print anything" in n[0][-1]
    assert list(fakes.out_dir.iterdir()) == []


def test_no_terminal_app_falls_back_to_headless(fakes, tmp_path):
    """Uzivatel chtel terminal, ale zadna aplikace terminalu neni: radeji bez okna nez nic."""
    os.unlink(fakes.dir / "luxos-terminal")
    fakes.actions("")
    sh = write(tmp_path, "i.sh", "#!/bin/sh\necho hi\n", 0o755)
    sup = S.run_in_sandbox(sh, "script", "sh", terminal=True)
    assert sup is not None and sup.wait(15) == 0
    calls = fakes.read()
    assert ["luxos-sandbox", "run", "--", sh] in calls
    assert notifications(calls)[0][-2] == "i.sh ran safely in the sandbox"


# ---- dlouhy beh (v procesu testu: kratsi casy) ----------------------------------------------------
def run_headless_thread(name, cmd):
    import threading
    h = S.HeadlessRun(name, cmd)
    t = threading.Thread(target=h.run, daemon=True)
    t.start()
    return h, t


def gone(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def test_long_running_stop(fakes, monkeypatch):
    monkeypatch.setattr(S, "RUNNING_NOTICE", 0.3)
    monkeypatch.setenv("FAKE_SLEEP", "30")
    fakes.actions("stop", "")
    h, t = run_headless_thread("server", ["luxos-sandbox", "run", "--", "/x/server"])
    t.join(15)
    assert not t.is_alive()
    assert h.proc.returncode is not None and h.stopped
    assert wait_for(lambda: gone(h.proc.pid), 5)               # cela skupina vlastniho behu skoncila
    n = notifications(fakes.read())
    assert n[0][-2] == "server is running in the sandbox"
    assert actions_of(n[0]) == ["output=Show Output", "stop=Stop"] and n[0][n[0].index("-t") + 1] == "0"
    assert n[-1][-2] == "server was stopped"
    assert "woke up" not in open(h.out_path).read()


def test_long_running_finish_replaces_running_notice(fakes, monkeypatch):
    monkeypatch.setattr(S, "RUNNING_NOTICE", 0.3)
    monkeypatch.setenv("FAKE_SLEEP", "1")
    fakes.actions("hang", "")                                  # "bezi" ceka, dokud ho hlidac nezavre
    h, t = run_headless_thread("job", ["luxos-sandbox", "run", "--", "/x/job"])
    t.join(15)
    assert not t.is_alive() and h.proc.returncode == 0 and not h.stopped
    n = notifications(fakes.read())
    running = [c for c in n if c[-2] == "job is running in the sandbox"]
    final = [c for c in n if c[-2] == "job ran safely in the sandbox"]
    assert len(running) == 1 and len(final) == 1
    rid = h.nid
    assert rid and final[0][final[0].index("-r") + 1] == str(rid)
    assert "woke up" in open(h.out_path).read()


def test_long_running_show_output_then_reshown(fakes, monkeypatch):
    monkeypatch.setattr(S, "RUNNING_NOTICE", 0.3)
    monkeypatch.setenv("FAKE_SLEEP", "30")
    monkeypatch.setenv("FAKE_OUT", "started\\n")
    fakes.actions("output", "stop", "")
    h, t = run_headless_thread("srv", ["luxos-sandbox", "run", "--", "/x/srv"])
    t.join(15)
    calls = fakes.read()
    g = [c for c in calls if c[0] == "luxos-guard-gui"]
    assert g and g[0][1] == "output"
    running = [c for c in notifications(calls) if c[-2] == "srv is running in the sandbox"]
    assert len(running) == 2
    assert "-r" in running[1]                                  # stejne upozorneni znovu, ne nove
    assert h.stopped


# ---- vystup: omezeni a cisteni ---------------------------------------------------------------------
def test_capture_keeps_only_last_bytes(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_BIG", "3000")                     # ~150 KB
    h = S.HeadlessRun("big", ["luxos-sandbox", "run", "--", "/x/big"])
    fakes.actions("")
    h.run()
    text = open(h.out_path).read()
    assert len(text.encode()) <= S.OUTPUT_LIMIT + 200
    first, second = text.split("\n")[:2]
    assert first.startswith("… (only the last 64 KB")
    assert second.startswith("line ") and second.endswith(".")   # zadny useknuty radek
    assert "line 2999 " in text and "line 0 " not in text


def test_clean_output_strips_control_sequences():
    raw = (b"\x1b]0;evil title\x07\x1b[31mred\x1b[0m\n"
           b"progress 10%\rprogress 50%\rprogress 100%\n"
           b"bell\x07 nul\x00 back\x08 c1\xc2\x9b\n"
           b"\xe2\x80\xaeevil\xe2\x80\xac rtl\n"
           b"bad utf8 \xff\xfe\n\x1bP+q\x1b\\done\r\n\n\n")
    out = S.clean_output(raw)
    assert out.split("\n") == ["red", "progress 100%", "bell nul back c1", "evil rtl",
                               "bad utf8 ��", "done"]
    assert not any(ord(c) < 32 and c != "\n" for c in out)
    assert S.clean_output(b"") == ""
    assert S.clean_output(b"cut-line\nfull\n", truncated=True).endswith("\nfull")


def test_output_dir_private(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    d = S.output_dir()
    assert d == str(run / "luxos-guard") and oct(os.stat(d).st_mode & 0o777) == "0o700"
    # podvrzeny odkaz misto slozky se nepouzije
    run2 = tmp_path / "run2"
    run2.mkdir()
    os.symlink(tmp_path, run2 / "luxos-guard")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run2))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert S.output_dir() == str(tmp_path / "cache" / "luxos-guard")
    # stare vystupy se uklidi
    old = os.path.join(d, "output-1-1.txt")
    open(old, "w").close()
    os.utime(old, (1, 1))
    new = os.path.join(d, "output-2-2.txt")
    open(new, "w").close()
    S._cleanup_outputs(d)
    assert not os.path.exists(old) and os.path.exists(new)


def test_write_output_does_not_follow_symlink(tmp_path):
    target = tmp_path / "victim"
    target.write_text("keep")
    os.symlink(target, tmp_path / "out.txt")
    assert S.write_output(str(tmp_path / "out.txt"), "x") is None
    assert target.read_text() == "keep"


def test_desktop_terminal_true_in_terminal(fakes, tmp_path):
    d = write(tmp_path, "t.desktop", "[Desktop Entry]\nExec=htop\nTerminal=true\n")
    S.run_in_sandbox(d, "desktop")
    calls = fakes.read("luxos-terminal")
    assert ["luxos-terminal", "--title", "Sandbox", "--hold", "-x", "luxos-sandbox", "run", "--", "htop"] in calls


def test_gui_in_terminal_by_user_choice_not_held(fakes, elves):
    S.run_in_sandbox(elves["gtk"], "elf", None, terminal=True)
    t = [c for c in fakes.read("luxos-terminal") if c[0] == "luxos-terminal"][0]
    assert "--hold" not in t
    assert t[t.index("-x") + 1:t.index("-x") + 3] == ["/bin/sh", "-c"]
    assert t[-5:] == ["luxos-sandbox", "run", "--gui", "--", elves["gtk"]]


def test_hold_on_error_wrapper(fakes, elves):
    """Obal terminalu pro program s oknem: pri uspechu se zavre hned, pri chybe ceka na Enter a vrati kod."""
    cmd = S._terminal_cmd(["/bin/sh", "-c", "exit 0"], hold_always=False)
    inner = cmd[cmd.index("-x") + 1:]
    r = subprocess.run(inner, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    assert r.returncode == 0 and r.stdout == ""
    inner_fail = inner[:-3] + ["/bin/sh", "-c", "exit 3"]
    r = subprocess.run(inner_fail, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    assert r.returncode == 3 and "Press Enter to close" in r.stdout


def test_failed_gui_launch_notifies(fakes, elves, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_ERR", "luxos-sandbox: Xephyr is not installed <b>x</b>\x1b[31m")
    p = S.run_in_sandbox(elves["gtk"], "elf")
    fakes.settle(p)
    calls = fakes.read("notify-send")
    n = [c for c in calls if c[0] == "notify-send"]
    assert n, calls
    title, body = n[0][-2], n[0][-1]
    assert title == "Could not start gtk in the sandbox"
    assert "Xephyr is not installed &lt;b&gt;x&lt;/b&gt;" in body and "\x1b" not in body
    assert "-u" in n[0]


def test_failed_without_output_shows_code(fakes, tmp_path, monkeypatch):
    (fakes.dir / "luxos-sandbox").write_text(FAKE + "exit 7\n")
    monkeypatch.setenv("FAKE_RC", "7")
    p = S.run_in_sandbox(write(tmp_path, "t.py", "import tkinter\n", 0o755), "script", "python3")
    fakes.settle(p)
    n = [c for c in fakes.read("notify-send") if c[0] == "notify-send"]
    assert n and n[0][-1] == "The program ended with error code 7."


def test_late_exit_with_error_is_quiet(fakes, elves, monkeypatch):
    """Zavreni okna Xephyr po dlouhem behu (nenulovy kod) neni chyba spusteni."""
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setattr(S, "LAUNCH_FAIL_WINDOW", 0)
    fakes.settle(S.run_in_sandbox(elves["gtk"], "elf"))
    assert not [c for c in fakes.read() if c[0] == "notify-send"]


def test_desktop_without_exec_notifies(fakes, tmp_path):
    d = write(tmp_path, "l.desktop", "[Desktop Entry]\nType=Link\nURL=https://x\n")
    assert S.run_in_sandbox(d, "desktop") is None
    n = [c for c in fakes.read("notify-send") if c[0] == "notify-send"]
    assert n and n[0][-1] == "The launcher does not contain a program to run."
    assert not [c for c in fakes.read() if c[0] == "luxos-sandbox"]


def test_agent_passes_kind_interp_and_terminal(fakes, elves, tmp_path, monkeypatch):
    from test_agent_notify import load_agent
    mod = load_agent()
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    agent = mod.Agent(sock_path=str(tmp_path / "none"))
    tk = write(tmp_path, "tk.py", "import tkinter\ntkinter.Tk().mainloop()\n", 0o755)
    agent.act("sandbox", {"path": tk, "kind": "script", "interp": "python3", "terminal": False})
    calls = fakes.read("luxos-sandbox")
    assert ["luxos-sandbox", "run", "--gui", "--", tk] in calls
    assert not [c for c in calls if c[0] == "luxos-terminal"]
    # spusteno z terminalu -> terminal i pro program s oknem
    agent.act("sandbox", {"path": elves["gtk"], "kind": "elf", "terminal": True})
    t = [c for c in fakes.read("luxos-terminal") if c[0] == "luxos-terminal"]
    assert t and t[0][-5:] == ["luxos-sandbox", "run", "--gui", "--", elves["gtk"]]
    time.sleep(0.3)


def test_no_sandbox_yet_opens_sandbox_window(fakes, elves, monkeypatch, tmp_path):
    monkeypatch.setattr(S, "SANDBOX_BASE", str(tmp_path / "none"))
    fakes.settle(S.run_in_sandbox(elves["gtk"], "elf"))
    calls = fakes.read()
    assert ["luxos-sandbox-gui"] in calls
    assert not [c for c in calls if c[0] == "luxos-sandbox"]

