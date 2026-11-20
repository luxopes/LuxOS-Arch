# Lux Code (`lux-code`) – proprietary component

Lux Code is the LuxAI terminal coding agent. Since LuxOS 1.0.3 (`lux-code` 0.6) it is built on the
open-source [Oh My Pi](https://github.com/can1357/oh-my-pi) (MIT) and replaces both `lux-code-next`
(the test version, same sources) and the original Lux Code 0.1 written in LSL. It is a **proprietary**
part of LuxOS; its source code (the Lux Code layer and the patches to Oh My Pi) is not published in
this repository.

- It is shipped as a **signed binary package** `lux-code` in the LuxOS repository `[luxos-apps]`
  (<https://luxos.lux-ai.cz/repo>). It contains bundled JavaScript run by the system `bun` (Arch Linux
  package, a dependency); the Bun runtime is not built into it. Command `lux-code` (`lux-code-next`
  still works), settings in `~/.config/lux-code` (moved from `~/.config/lux-code-next` on first start).
- Use on LuxOS is **free of charge** under the LuxOS proprietary license
  ([LICENSES/LicenseRef-LuxOS-Proprietary.md](../../../LICENSES/LicenseRef-LuxOS-Proprietary.md)); Oh My
  Pi, its dependencies and the native addon keep their own licenses, listed in
  [LICENSES/NOTICE-proprietary.md](../../../LICENSES/NOTICE-proprietary.md) and installed in
  `/usr/share/licenses/lux-code/`.
- Versions that were published in this repository **before** the change to a proprietary license
  stay available under the license they were published with (see the history of this folder). The
  original Lux Code 0.1 is archived in the private repository (tags `lux-code-0.1.2-6`,
  `lux-code-classic-final`).
- The LuxOS build (`./build.sh`, GitHub Actions) takes this package from the LuxOS repository
  (marker file `PROPRIETARY` in this folder), so this public repository builds without the sources.
- `store/` holds a copy of the package's `.desktop` and metainfo files (what the LuxOS Store shows),
  used by the Store tests here; keep it in sync with the private repository when they change.

Česky: Lux Code je AI agent LuxAI pro programování v terminálu. Od LuxOS 1.0.3 (verze 0.6) je postavený
na otevřeném Oh My Pi a nahrazuje zkušební `lux-code-next` i původní Lux Code 0.1 v LSL. Je to
proprietární součást LuxOS; v LuxOS je zdarma jako podepsaný binární balík `lux-code` z repozitáře
LuxOS `[luxos-apps]`.
