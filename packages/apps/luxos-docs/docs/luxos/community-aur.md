# Community packages (AUR): checking and sandbox

`lux install <name>` uses the community source (AUR) only when the name is not in the LuxOS and
Arch Linux repositories, the LuxOS `.lux` apps or Flathub (order in
[package-management.md](package-management.md)). AUR build scripts are written by other users and
are not checked by LuxOS, so lux checks them itself and builds them isolated by default.

## Checking, sandbox and system installs

- Before building, the PKGBUILD, `.install` files and **every other file in the repository** are
  checked in two layers:
  1. **Fixed rules (offline, deterministic):** downloading and running code (`curl | sh`, download
     straight into `$pkgdir`, download to `/tmp` + `chmod +x`), hidden payloads (base64/hex, text
     reversed with `rev`, `eval` of fetched text), writes outside `$pkgdir`, touching
     accounts/sudo/SSH, persistence (`.bashrc`, per-user autostart/systemd unit), `/etc/hosts`,
     `resolv.conf`, `ld.so.preload`, sudoers/SUID, disabling the firewall or a security service,
     replacing a system binary, data upload / credential, cookie or SSH-key theft, cryptominer
     names, sources from a bare IP or look-alike host, missing checksums (`SKIP`) on a remote
     download, symbolic links pointing outside the package, plain-HTTP sources. A `high` finding is
     by itself a **dangerous** verdict, even if the AI disagrees (this also blocks prompt-injection
     in the files).
  2. **Two independent AI models** when you are signed in to LuxAI: **Lite** and **Flash** (strong
     on security). The stricter answer wins and a verdict is "safe" **only if both models agree**;
     the files are sent as untrusted data and instructions hidden inside them are ignored. Only the
     repository text is sent, never your files.
- Verdict is safe / suspicious / dangerous, always **with reasons** (including why something looks
  safe). Without LuxAI the verdict is "not checked" (`unreviewed`) — never silently "safe".
- **Measured detection** (49-sample evaluation: 22 real AUR packages + 27 synthetic malicious
  variants, built-in corpus in `lux/tests/fixtures/aur-eval`): the full review flagged **27/27
  malicious as dangerous (0 rated safe)**; of the 22 real packages 18 were safe and 4 were
  "suspicious" (needing confirmation), **0 benign rated dangerous**. The offline fixed rules alone
  flagged all 27 malicious at `medium` or higher with **no** `high` finding on a benign package.
- **Default target: your sandbox** ([sandbox.md](sandbox.md)). lux copies the checked directory into
  the sandbox (`luxos-sandbox build-install`), installs `base-devel`/dependencies there, runs
  `makepkg` inside as the sandbox user and installs the result with the sandbox's own `pacman`. The
  build script never runs on your system. lux then says how to start it: a command-line tool by its
  own name (`pi` – a wrapper at the end of `PATH`, a system program of the same name wins), an app
  with a window from Launchpad as "<App> (Sandbox)"; see
  [sandbox.md](sandbox.md#starting-sandbox-apps-commands-and-launchpad). Sandbox apps cannot see your
  files – to use a tool with them, install it with `lux install --system <name>`. `lux remove <name>`
  removes it from the sandbox again.
- **Into the system only with explicit permission**: `--system`, or choose "2 System" and type the
  word `system`. A **dangerous** script is never installed into the system; an unchecked or
  suspicious one only after you confirm without `-y`. System builds use `makepkg -si`
  (`jq`, `git`, `base-devel` are offered), sources in `~/.cache/lux/aur/<pkgbase>`.
- `lux update` rebuilds newer versions of community packages already in the system and checks the
  new build script again (not as root, not with `--repo`).
- **LuxAI never installs community packages**: lux refuses them when run by the LuxAI agent
  (`LUXAI_AGENT=1`) and LuxAI tells you to run `lux install <name>` yourself.
- Hardware drivers people need (printers, scanners) are verified and shipped in the LuxOS
  repository instead — see [drivers.md](drivers.md).

