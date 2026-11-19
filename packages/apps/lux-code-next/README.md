# Lux Code (next) (`lux-code-next`) – proprietary component

Lux Code (next) is the new version of the Lux Code terminal coding agent, built on the open-source
[Oh My Pi](https://github.com/can1357/oh-my-pi) (MIT). It is a **proprietary** part of LuxOS; its source
code (the Lux Code layer and the patches to Oh My Pi) is not published in this repository.

- It is shipped as a **signed binary package** `lux-code-next` in the LuxOS repository `[luxos-apps]`
  (<https://luxos.lux-ai.cz/repo>, first in the staging channel). It installs next to the older `lux-code`
  without any shared file (command `lux-code-next`, `/usr/lib/lux-code-next`, `~/.config/lux-code-next`,
  desktop id and icon `lux-code-next`). The package contains bundled JavaScript that is run by the system
  `bun` (Arch Linux package, a dependency); the Bun runtime is not built into it.
- Use on LuxOS is **free of charge** under the LuxOS proprietary license
  ([LICENSES/LicenseRef-LuxOS-Proprietary.md](../../../LICENSES/LicenseRef-LuxOS-Proprietary.md)); Oh My Pi,
  its dependencies and the native addon keep their own licenses, listed in
  [LICENSES/NOTICE-proprietary.md](../../../LICENSES/NOTICE-proprietary.md) and installed in
  `/usr/share/licenses/lux-code-next/`.
- The LuxOS build (`./build.sh`, GitHub Actions) takes this package from the LuxOS repository (marker file
  `PROPRIETARY` in this folder), so this public repository builds without the sources.
- `store/` holds a copy of the package's `.desktop` and metainfo files (what the LuxOS Store shows), used by
  the Store tests here; keep it in sync with the private repository when they change.

Česky: Lux Code (next) je nová verze terminálového AI agenta Lux Code postavená na otevřeném Oh My Pi (MIT).
Je to proprietární součást LuxOS; v LuxOS je zdarma jako podepsaný binární balík `lux-code-next` z repozitáře
LuxOS `[luxos-apps]` a instaluje se vedle staršího `lux-code`.
