# Licenses in LuxOS

LuxOS is a free download. Most of it is free and open-source software; a few components that are
the commercial core of LuxOS are proprietary and are shipped as signed binary packages. Both kinds
are free to use on LuxOS.

| What | License | Source code |
|---|---|---|
| LuxOS's own open code: `luxos-*` packages (except `luxos-domain`), `lux`, the installer, `lsh`, scripts, website, documentation | GPL-3.0-or-later ([LICENSE](../LICENSE)) with the [additional permission](LuxOS-GPL-exception.md) | this repository |
| LuxOS Mail, LuxOS Docs, App Studio, Icon Studio | GPL-3.0-or-later | this repository (`packages/apps/`) |
| LuxOS SDK, themes partly | MIT (see each `PKGBUILD`) | this repository |
| Patched upstream packages (`xfwm4`, `plank`, `rofi`, `xfce4-*`, `vte3`, `gdk-pixbuf2`, `libfprint`, `lux-engine`, `adcli`, `realmd`, the `linux-luxos` kernel …) | their upstream licenses (GPL, LGPL, MIT …) | this repository and luxopes/luxos-kernel |
| **Proprietary:** LuxAI (`luxai`), Lux Code (`lux-code`), LSL IDE (`lsl-ide`), LuxOS Organization network / Active Directory (`luxos-domain`) | [LicenseRef-LuxOS-Proprietary](LicenseRef-LuxOS-Proprietary.md); third-party parts in [NOTICE-proprietary.md](NOTICE-proprietary.md) | not public; binary packages in the LuxOS repository |
| LSL (Lux Simple Lang) | MIT | <https://lsl.lux-ai.cz> |

Versions of the proprietary components that were published in this repository before the license
change stay available under the license they were published with; the Git history is not
rewritten.

Folders of proprietary components in `packages/` contain only a `README.md` and a `PROPRIETARY`
marker; the LuxOS build then takes the signed binary package from <https://luxos.lux-ai.cz/repo>.
