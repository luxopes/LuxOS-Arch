"""Terminal: uvitani fastfetch s logem LuxOS jako obrazkem (SIXEL) a panely s ukazkovym projektem v Gitu.

Terminal se preklada ze zdroju do s.tmp (jako build() v PKGBUILD). Shell je bash s vyzvou starship
z konfigurace LuxOS (packages/luxos-shell); fastfetch ma vlastni konfiguraci jen s ukazkovymi
hodnotami (custom), takze snimek neukazuje skutecny pocitac. Projekt je docasny repozitar v s.home.
LUXOS_TERMINAL_NO_SERVICE=1: jeden proces na soukromem D-Bus sezeni (panel --tab), bez sluzby systemd.
"""
import json
import os
import subprocess

DEMO_INFO = [
    ("\U000f0536  OS", "38;2;255;159;90", "LuxOS 1.0 (Sirius) x86_64"),
    ("\U000f0379  Host", "38;2;255;210;90", "Lux Laptop 14"),
    ("  Kernel", "38;2;95;211;141", "Linux 7.2.13-1-luxos"),
    ("\U000f0150  Uptime", "38;2;90;200;250", "2 hours, 14 mins"),
    ("\U000f03d6  Packages", "38;2;180;140;255", "1042 (lux), 6 (flatpak)"),
    ("\U000f018d  Shell", "38;2;255;122;217", "bash 5.3.3"),
    ("\U000f09e8  Desktop", "38;2;91;140;255", "LuxOS Desktop"),
    ("\U000f07b7  Terminal", "38;2;155;140;255", "LuxOS Terminal 1.3.0"),
    ("\U000f0edf  CPU", "38;2;255;107;154", "AMD Ryzen 5 5500U (12) @ 4.06 GHz"),
    ("\U000f08ae  GPU", "38;2;255;107;213", "AMD Radeon Graphics [Integrated]"),
    ("\U000f035b  Memory", "38;2;79;209;197", "3.84 GiB / 15.06 GiB (25%)"),
    ("\U000f02ca  Disk (/)", "38;2;90;200;250", "41.27 GiB / 476.34 GiB (9%) - btrfs"),
]

PROJECT_FILES = {
    "README.md": "# Weather widget\n\nA tiny desktop widget written in LSL.\n",
    "src/main.lsl": "fn main() {\n    print(\"Hello, LuxOS!\")\n}\n",
    "src/forecast.lsl": "// forecast\n",
    "src/icons.lsl": "// icons\n",
    "tests/test_forecast.lsl": "// tests\n",
    "assets/sun.svg": "<svg/>\n",
    "Makefile": "all:\n\tlslc src/main.lsl weather-widget\n",
    "LICENSE": "GPL-3.0-or-later\n",
}

COMMITS = [
    ("Initial project layout", "2026-10-28T09:12:00"),
    ("Add forecast parser", "2026-10-29T14:40:00"),
    ("Draw weather icons", "2026-10-30T11:05:00"),
    ("Add tests for the forecast", "2026-11-02T16:22:00"),
    ("Show the hourly forecast", "2026-11-04T10:31:00"),
    ("Fix the temperature rounding", "2026-11-06T18:03:00"),
]


def build(s):
    out = os.path.join(s.tmp, "luxos-terminal")
    flags = subprocess.run(["pkg-config", "--cflags", "--libs", "vte-2.91", "gtk+-3.0"], capture_output=True,
                           text=True, check=True).stdout.split()
    subprocess.run(["gcc", "-O2", '-DLUXOS_TERMINAL_VERSION="1.3.0"', "-o", out,
                    s.src("luxos-terminal/files/luxos-terminal.c")] + flags, check=True, timeout=300)
    return out


def demo_project(s):
    proj = os.path.join(s.home, "Projects", "weather-widget")
    for rel, text in PROJECT_FILES.items():
        s.write(os.path.join("Projects", "weather-widget", rel), text)
    genv = dict(s.env, GIT_AUTHOR_NAME="Alex Novak", GIT_AUTHOR_EMAIL="alex@example.com",
                GIT_COMMITTER_NAME="Alex Novak", GIT_COMMITTER_EMAIL="alex@example.com",
                GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")

    def git(*a, date=None):
        e = dict(genv)
        if date:
            e.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        subprocess.run(["git", *a], cwd=proj, env=e, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    for i, (msg, date) in enumerate(COMMITS):
        # kazdy commit neco zmeni
        with open(os.path.join(proj, "CHANGES"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        git("add", "-A")
        git("commit", "-q", "-m", msg, date=date)
    # rozpracovana zmena pro git status
    with open(os.path.join(proj, "src", "forecast.lsl"), "a", encoding="utf-8") as f:
        f.write("// wind speed\n")
    s.write("Projects/weather-widget/src/wind.lsl", "// wind\n")
    return proj


def shots(s):
    term = build(s)
    proj = demo_project(s)
    for d in ("Documents/Invoices", "Music", "Pictures/Holiday 2026"):
        os.makedirs(os.path.join(s.home, d), exist_ok=True)
    s.write("Documents/notes.txt", "Buy milk\n")
    s.write("Documents/Trip plan.odt", "")
    s.write("Pictures/Holiday 2026/beach.jpg", "")

    ff = {
        "logo": {"type": "file-raw", "source": "/dev/null", "width": 31, "height": 12,
                 "padding": {"top": 3, "left": 2, "right": 4}},
        "display": {"separator": "", "disableLinewrap": True, "key": {"width": 13}},
        "modules": [{"type": "custom", "format": "LuxOS", "outputColor": "1;97"},
                    {"type": "custom", "format": "SIMPLE  ·  FAST  ·  SECURE", "outputColor": "90"},
                    "break"]
        + [{"type": "custom", "key": k, "keyColor": c, "format": v} for k, c, v in DEMO_INFO]
        + ["break", {"type": "colors", "symbol": "circle"}],
    }
    ffconf = s.write(".config/demo-fastfetch.jsonc", json.dumps(ff, ensure_ascii=False, indent=1))
    starship = s.src("luxos-shell/files/starship.toml")
    rc = s.write(".demo-bashrc", "\n".join([
        "export STARSHIP_CONFIG=%s" % starship,
        "export STARSHIP_CACHE=$HOME/.cache/starship",
        "_luxos_title() { printf '\\e]0;%s\\a' \"${PWD/#$HOME/\\~}\"; }",
        "starship_precmd_user_func=_luxos_title",
        # /etc/bash.bashrc (Arch) nastavuje titulek user@host - na snimku jen slozka jako v LuxOS
        "unset PROMPT_COMMAND",
        "eval \"$(starship init bash --print-full-init)\"",
        "alias ls='ls --color=auto --group-directories-first'",
        "",
    ]))
    rc_ff = s.write(".demo-bashrc-welcome", ". %s\nfastfetch -c %s --logo-type raw --logo \"$LUXOS_TERMINAL_LOGO\"\n"
                    % (rc, ffconf))
    s.write(".config/luxos/terminal.conf", "[terminal]\ntheme=dark\n\n[state]\ncolumns=100\nrows=30\n")
    env = {"LUXOS_TERMINAL_NO_SERVICE": "1", "SHELL": "/bin/bash", "LANG": "en_US.UTF-8",
           "LUXOS_TERMINAL_LOGO_SOURCE": s.src("luxos-branding/files/logo/luxos-logo.svg")}

    # 1: nove okno s uvitanim fastfetch a vypisem slozky
    p = s.launch([term, "-x", "bash", "--rcfile", rc_ff, "-i"], env=env)
    win = s.window(pid=p.pid, size=(1000, 640))
    s.sleep(2.5)
    s.type("ls\n", win, delay=1.0)
    s.capture("1", win)

    # 2: druhy panel v projektu: historie Gitu a rozpracovane zmeny
    s.launch([term, "--tab", "-w", proj, "-x", "bash", "--rcfile", rc, "-i"], env=env)
    s.sleep(2.0)
    s.type("git log --oneline --graph --decorate\n", win, delay=0.8)
    s.type("git status --short\n", win, delay=0.8)
    s.type("ls src\n", win, delay=1.0)
    s.capture("2", win)
