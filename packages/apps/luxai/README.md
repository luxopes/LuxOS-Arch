# LuxAI (`luxai`) – proprietary component

LuxAI is a **proprietary** part of LuxOS. Its source code is not published in this repository.

- It is shipped as a **signed binary package** `luxai` in the LuxOS repository
  `[luxos-apps]` (<https://luxos.lux-ai.cz/repo>) and is included in the official LuxOS images.
- Use on LuxOS is **free of charge** under the LuxOS proprietary license
  ([LICENSES/LicenseRef-LuxOS-Proprietary.md](../../../LICENSES/LicenseRef-LuxOS-Proprietary.md));
  bundled third-party components and their licenses are listed in
  [LICENSES/NOTICE-proprietary.md](../../../LICENSES/NOTICE-proprietary.md).
- Versions that were published in this repository **before** the change to a proprietary license
  stay available under the license they were published with (see the history of this folder).
- The LuxOS build (`./build.sh`, GitHub Actions) takes this package from the LuxOS repository
  (marker file `PROPRIETARY` in this folder), so this public repository builds without the sources.
- `store/` holds a copy of the package's `.desktop` and metainfo files (what the LuxOS Store shows),
  used by the Store tests here; keep it in sync with the private repository when they change.

Česky: LuxAI je proprietární součást LuxOS. Zdrojový kód v tomto repozitáři není; v LuxOS je
zdarma jako podepsaný binární balík `luxai` z repozitáře LuxOS `[luxos-apps]`.
