"""Lux Guard "Spustit v sandboxu": program s oknem bez terminalu, textovy program v terminalu.

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
    assert S.launch_plan(elves["cli"], "elf") == {"argv": [elves["cli"]], "gui": False, "terminal": True}


def test_static_elf(tmp_path):
    p = cc(tmp_path, "static", CLI_C, ["-static"])
    assert S.elf_needed(open(p, "rb").read()) == []
    assert S.launch_plan(p, "elf")["terminal"] is True


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
    assert S.launch_plan(bad, "elf") == {"argv": [bad], "gui": False, "terminal": True}


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
@pytest.mark.parametrize("name,text,gui", [
    ("install.sh", "#!/bin/bash\necho installing\ncp a b\n", False),
    ("ask.sh", "#!/bin/sh\nread -r -p 'Name? ' n\necho $n\n", False),
    ("dlg.sh", "#!/bin/sh\nzenity --info --text=hi\n", True),
    ("dlg-read.sh", "#!/bin/sh\nzenity --info --text=hi\nread x\n", False),
    ("noshebang.sh", "yad --text hi\n", True),
    ("hello.py", "#!/usr/bin/env python3\nprint('hello')\n", False),
    ("tk.py", "#!/usr/bin/env python3\nimport tkinter as tk\ntk.Tk().mainloop()\n", True),
    ("qt.pyw", "from PyQt5.QtWidgets import QApplication\nQApplication([]).exec_()\n", True),
    ("gtk.py", "import gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk\nGtk.main()\n", True),
    ("glib.py", "from gi.repository import GLib\nGLib.MainLoop().run()\n", False),
    ("game.py", "import pygame\npygame.init()\n", True),
    ("tkask.py", "import tkinter\nname = input('Name: ')\n", False),
    ("tool.pl", "#!/usr/bin/perl\nuse Tk;\nMainLoop;\n", True),
    ("ask.pl", "#!/usr/bin/perl\nuse Tk;\nmy $x = <STDIN>;\n", False),
    ("app.rb", "#!/usr/bin/ruby\nputs 1\n", False),
])
def test_script_classification(tmp_path, name, text, gui):
    p = write(tmp_path, name, text, 0o755)
    kind, interp = kind_of(p)
    assert kind == "script"
    plan = S.launch_plan(p, kind, interp)
    assert plan == {"argv": [p], "gui": gui, "terminal": not gui}


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


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    calls.mkdir()
    for name, extra in (("luxos-sandbox", 'echo "Copying into the sandbox..." >&2\n'
                                          'if [ -n "$FAKE_ERR" ]; then echo "$FAKE_ERR" >&2; fi\n'
                                          'exit "${FAKE_RC:-0}"\n'),
                        ("luxos-terminal", ""), ("notify-send", ""), ("luxos-sandbox-gui", "")):
        f = bin_ / name
        f.write_text(FAKE + extra)
        f.chmod(0o755)
    base = tmp_path / "sbx"
    import pwd
    (base / pwd.getpwuid(os.getuid()).pw_name / "usr" / "bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", str(bin_))                     # zadny skutecny terminal ani sandbox
    monkeypatch.setenv("CALLS", str(calls))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setattr(S, "_", lambda text: text)            # texty anglicky bez ohledu na jazyk
    monkeypatch.setattr(S, "SANDBOX_CLI", "luxos-sandbox")
    monkeypatch.setattr(S, "SANDBOX_BASE", str(base))

    class F:
        dir = bin_

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


def test_text_program_in_terminal_kept_open(fakes, elves, tmp_path):
    S.run_in_sandbox(elves["cli"], "elf")
    sh = write(tmp_path, "i.sh", "#!/bin/sh\necho hi\n", 0o755)
    S.run_in_sandbox(sh, "script", "sh")
    calls = fakes.read("luxos-terminal")
    time.sleep(0.3)
    calls = fakes.read()
    term = [c for c in calls if c[0] == "luxos-terminal"]
    assert ["luxos-terminal", "--title", "Sandbox", "--hold", "-x", "luxos-sandbox", "run", "--", elves["cli"]] in term
    assert ["luxos-terminal", "--title", "Sandbox", "--hold", "-x", "luxos-sandbox", "run", "--", sh] in term
    assert not [c for c in calls if c[0] == "luxos-sandbox"]   # sandbox spousti az terminal


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


def test_text_program_without_terminal_app_notifies(fakes, tmp_path):
    os.unlink(fakes.dir / "luxos-terminal")
    sh = write(tmp_path, "i.sh", "#!/bin/sh\necho hi\n", 0o755)
    assert S.run_in_sandbox(sh, "script", "sh") is None
    n = [c for c in fakes.read("notify-send") if c[0] == "notify-send"]
    assert n and n[0][-1] == "No terminal application was found."


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

