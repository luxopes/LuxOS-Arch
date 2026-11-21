#!/bin/bash
# LuxOS Desktop - instalace na Fedoru, Arch a odvozene distribuce
#
#   ./install.sh            sestavi balicek lux-desktop a nainstaluje ho spravcem baliku (sudo)
#   ./install.sh --build    jen sestavi balicek (work/out), nic neinstaluje
#
# Spoustet jako bezny uzivatel; sudo se pouzije jen na instalaci zavislosti a hotoveho balicku.
# Odinstalace: sudo dnf remove lux-desktop  /  sudo pacman -R lux-desktop
set -euo pipefail
HERE=$(dirname "$(readlink -f "$0")")
build_only=0
[[ ${1:-} == --build ]] && build_only=1

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'lux-desktop: %s\n' "$*" >&2; exit 1; }
[[ $EUID -ne 0 ]] || die "run as your normal user (sudo is used only to install packages)"
[[ $(uname -m) == x86_64 ]] || die "only x86_64 is supported for now"

. /etc/os-release
family=""
for id in $ID ${ID_LIKE:-}; do
    case $id in
        fedora) family=fedora; break ;;
        arch) family=arch; break ;;
        debian|ubuntu) family=debian; break ;;
    esac
done
case $family in
    fedora|arch) ;;
    debian) die "Debian and Ubuntu are not supported yet (planned next). Fedora and Arch work now." ;;
    *) die "unsupported distribution '$ID' (Fedora and Arch-based for now)" ;;
esac
say "LuxOS Desktop for $PRETTY_NAME"

deps() { grep -v '^#' "$HERE/deps/$1.txt" | tr -s ' \n' ' '; }
if [[ $family == fedora ]]; then
    say "Installing build tools and libraries (dnf)"
    # shellcheck disable=SC2046
    sudo dnf install -y $(deps fedora-build) $(deps fedora-runtime)
    "$HERE/build.sh" rpm
    pkg=$(ls -t "$HERE"/work/out/lux-desktop-*.rpm | head -1)
    ((build_only)) && { say "Package: $pkg"; exit 0; }
    say "Installing $pkg"
    sudo dnf install -y "$pkg"
else
    say "Installing build tools and libraries (pacman)"
    # shellcheck disable=SC2046
    sudo pacman -S --needed --noconfirm $(deps arch-build) $(deps arch-runtime)
    "$HERE/build.sh" pacman
    pkg=$(ls -t "$HERE"/work/out/lux-desktop-*.pkg.tar.* | head -1)
    ((build_only)) && { say "Package: $pkg"; exit 0; }
    say "Installing $pkg"
    sudo pacman -U --noconfirm "$pkg"
fi

cat <<'EOF'

LuxOS Desktop is installed.
Log out and choose "LuxOS Desktop" on the login screen (the session menu, often a gear icon).
Your other desktops (GNOME, KDE, plain Xfce) stay as they are.

Uninstall:  sudo dnf remove lux-desktop   (Fedora)
            sudo pacman -R lux-desktop    (Arch)
EOF
