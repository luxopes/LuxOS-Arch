# NOTICE – third-party components in proprietary LuxOS components

The proprietary LuxOS components (license `LicenseRef-LuxOS-Proprietary`, see
[LicenseRef-LuxOS-Proprietary.md](LicenseRef-LuxOS-Proprietary.md)) contain or use the
third-party software listed below. Each of these components stays under its own license; the
LuxOS proprietary license does not restrict any right those licenses give you. The full license
texts are installed with each package in `/usr/share/licenses/<package>/`.

Status: 2026-11-19. Keep this file in sync with the private repository (`NOTICE.md` there) on
every release of a proprietary package.

## Contained in the package (statically compiled in or shipped as files)

| Package | Component | License | How it is used |
|---|---|---|---|
| `luxai`, `lux-code`, `luxos-domain` | LSL standard library and runtime (Lux Simple Lang, <https://lsl.lux-ai.cz>) | MIT | compiled into the program by the LSL compiler; license text in `/usr/share/licenses/<package>/LSL-LICENSE.txt` |
| `lsl-ide` | pyte – VT100/VT220 terminal emulator (© 2011-2012 Selectel, © 2012-2017 pyte authors and contributors) | LGPL-3.0-only | unmodified Python source in `/usr/lib/lsl-ide/lslide/vendor/pyte/` – it can be replaced by a modified version; license text next to it |
| `lux-code-next` | Oh My Pi (omp, <https://github.com/can1357/oh-my-pi>; © 2025 Mario Zechner, © 2025-2026 Can Bölük, © 2026 Stencil Labs, Inc.) with its bundled npm dependencies | MIT (dependencies: their own permissive licenses, listed in the upstream third-party notices) | patched source compiled into the program with `bun build --compile`; license texts in `/usr/share/licenses/lux-code-next/` (`OMP-LICENSE.txt`, `THIRD-PARTY-NOTICES-*.txt`, `LUX-CODE-NEXT-NOTICE.txt`) |
| `lux-code-next` | pi-natives native addon (`@oh-my-pi/pi-natives-linux-x64`, prebuilt by the Oh My Pi project) | MIT | separate file `/usr/lib/lux-code-next/pi_natives.linux-x64-baseline.node`, loaded at run time |
| `lux-code-next` | Bun runtime (<https://bun.sh>), embedded by `bun build --compile`; contains JavaScriptCore/WebKit | MIT; JavaScriptCore/WebKit LGPL-2.0-or-later / BSD | runtime part of the executable; the same Bun release is available as the Arch Linux package `bun` |
| `luxos-domain` | PAM configuration template `templates/system-auth` (structure follows Arch Linux `pambase`) | GPL-3.0-or-later (as published in LuxOS before the license change) | separate configuration file shipped with the package (aggregation), not part of the program |

## Used at run time (shared libraries and separate programs from LuxOS/Arch Linux packages)

These are not part of the proprietary packages; they are installed as their own packages with
their own licenses and source code available from Arch Linux and LuxOS.

| Package | Component | License | How it is used |
|---|---|---|---|
| `luxai` | GTK 3, GDK, GLib/GIO, GdkPixbuf, Pango, Cairo, librsvg | LGPL-2.1-or-later (Cairo: LGPL-2.1 or MPL-1.1) | dynamic linking (`dlopen` for librsvg) |
| `luxai`, `lux-code` | libcurl | curl (MIT-style) | dynamic linking |
| `luxai` | bash, coreutils, util-linux, xdotool, wmctrl, polkit (`pkexec`) | GPL / LGPL / MIT | separate programs started as processes |
| `lux-code` | git, ripgrep, diffutils, findutils, grep, sed, tar, unzip, xclip | GPL / MIT / Unlicense | separate programs started as processes |
| `lsl-ide` | Python, PySide6 / Qt 6, python-wcwidth | PSF-2.0, LGPL-3.0-only, MIT | interpreter and dynamically loaded modules |
| `luxos-domain` | GTK 3, GDK, GLib/GObject, GdkPixbuf (settings window) | LGPL-2.1-or-later | dynamic linking |
| `luxos-domain` | SSSD, realmd, adcli, Samba (`cifs-utils`, `gvfs-smb`), MIT Kerberos, OpenLDAP, Linux-PAM, polkit, sudo | GPL / LGPL / MIT / OpenLDAP / BSD | separate programs, system services and PAM modules configured and started as processes |

## LGPL notice

Where a proprietary LuxOS component uses a library under the GNU LGPL, you may replace that
library with a modified version (the system packages are shared libraries or plain Python
modules), and the LuxOS proprietary license allows reverse engineering solely to debug such
modifications (point 4 of the license).

## Everything else in LuxOS

The rest of LuxOS (the open `luxos-*` packages, `lux`, the installer, scripts and the patched
upstream packages) is free and open-source software under the licenses stated in each package
(mostly GPL-3.0-or-later, see [LICENSE](../LICENSE) and [README.md](README.md)).
