# LuxOS Desktop

The desktop of [LuxOS](https://luxos.lux-ai.cz) for your own Linux distribution: menu bar,
Dock, Launchpad, Control Center, widgets, hot corners, Emoji & Symbols, screenshots,
notifications and the LuxOS settings – on top of Xfce, as an extra **"LuxOS Desktop"** session
on your login screen. Most of it is written in [LSL](https://lsl.lux-ai.cz), the Lux Simple
Language.

> **Community edition, best effort.** LuxOS Desktop is tested on Fedora and Arch, but the
> place where everything is fully supported and tested together is LuxOS itself. Bug reports
> are welcome.

## Supported distributions

| Distribution | Status |
|---|---|
| Fedora 43 | ✅ |
| Arch Linux, EndeavourOS, CachyOS and other Arch-based | ✅ |
| Debian / Ubuntu | planned |

x86_64 only. The session runs on X11 (Xfce 4.20).

## Install

```sh
git clone https://github.com/luxopes/LuxOS-Arch.git --depth 1
cd LuxOS-Arch/desktop-standalone
./install.sh
```

Run it as your normal user; it asks for `sudo` only to install packages. It installs the build
tools, builds a native package (`lux-desktop` RPM on Fedora, a pacman package on Arch) and
installs it with your package manager. Then log out and pick **LuxOS Desktop** on the login
screen (the session menu, often a gear icon).

Your other desktops (GNOME, KDE, plain Xfce) are not changed: LuxOS settings apply only inside
the LuxOS Desktop session.

## Uninstall

```sh
sudo dnf remove lux-desktop      # Fedora
sudo pacman -R lux-desktop       # Arch
```

## What is included

- menu bar with the LuxOS menu, clock in the middle, Control Center and Calendar
- Dock (Plank) and Launchpad (all apps, sorting, search)
- Search, Emoji & Symbols, screenshots, notifications
- desktop widgets, wallpapers, light/dark/auto appearance, WhiteSur themes and icons
- hot corners, smooth scrolling, Desktop & Dock and other LuxOS settings
- LuxOS Text Editor and LuxOS Terminal
- touch screen support (the on-screen keyboard needs `onboard`, which Fedora does not package;
  gestures use your distribution's Touchégg – LuxOS ships a fixed build where multi-finger swipes on
  touch screens are not mistaken for pinches, so they are more reliable on LuxOS itself)

Not included – these are parts of the LuxOS system, not of the desktop: LuxOS Care and updates
(your distribution updates itself), firewall, Lux Guard, drivers, the LuxOS installer and login
screen, LuxAI, the LuxOS Store and the first-start tour.

## Shared with your other desktops

The light/dark choice of LuxOS Desktop is also written to the GNOME setting that GTK 4 apps follow
(`color-scheme`), so after switching LuxOS Desktop to light or dark, GNOME follows the same choice.
Xfce itself also stores the cursor size and blinking there. Nothing else in GNOME or KDE is changed.

## If you already use Xfce

Xfce keeps its settings in `~/.config/xfce4`. On the first start of LuxOS Desktop a copy of it is
saved to `~/.config/xfce4.before-luxos-desktop`, and the panel, window manager, keyboard shortcut,
desktop and appearance settings are set aside so LuxOS Desktop can start with its own defaults.
Both sessions then share these settings. To get your old Xfce settings back:

```sh
rm -rf ~/.config/xfce4 && cp -a ~/.config/xfce4.before-luxos-desktop ~/.config/xfce4
```

## How it is built

There is no copy of the desktop here. `build.sh` builds it from the LuxOS packages in
[`packages/`](../packages) – the same `PKGBUILD`s LuxOS uses – with a small makepkg-like runner,
removes the parts that belong to the LuxOS system (`prune.list`), adjusts library paths for the
distribution and adds the session files. A patched `rofi` (needed by Launchpad) is built into
`/usr/lib/lux-desktop` and used only inside the session.

```sh
./build.sh rpm       # Fedora: work/out/lux-desktop-*.rpm
./build.sh pacman    # Arch:   work/out/lux-desktop-*.pkg.tar.zst
```

## License

GPL-3.0-or-later (LuxOS code) with the parts listed in [LICENSES](../LICENSES): WhiteSur themes
(MIT/GPL), rofi (MIT), LSL compiler (MIT, used only to build).
