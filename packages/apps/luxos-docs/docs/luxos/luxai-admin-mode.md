# LuxAI administrator mode

How the LuxAI agent runs commands as administrator (root), what administrator mode does since
LuxAI 2.0.2 and why older versions were unsafe.

LuxAI's agent runs root commands only through `pkexec /usr/lib/luxai/luxai-root[-auto]`, never
through `sudo` with a password. LuxAI › Settings › Agent permissions › **Administrator commands**:

| Choice | What happens |
|---|---|
| Ask for the password every time (default) | two confirmations in the card + administrator password for each command |
| Password once for 5 minutes, approve each command | one confirmation per command; password once, then about 5 minutes without it (Flash model only) |
| Password once for 5 minutes, without asking | no card; password once, then about 5 minutes without it (Flash model only) |

The two last choices are **administrator mode** (since LuxAI 2.0.2). It never gives root without a
password to other programs:

- The polkit action `org.luxai.root-auto` is `auth_admin_keep`: polkit remembers the password for
  about 5 minutes only for the process that called `pkexec` – the running LuxAI. Any other program
  of the same user (another terminal, a script, a second LuxAI) gets the password dialog.
- `luxai-root-auto` also refuses (exit code 125) any parent that is not `/usr/bin/luxai`, a LuxAI
  being traced, or one started with `LD_PRELOAD`, `LD_AUDIT` or `LD_LIBRARY_PATH`.
- A request sent to a running LuxAI by another program (`luxai "text"`, Search) always needs the
  card confirmation for administrator commands, even in "without asking".
- No polkit rule is written. LuxAI up to 2.0.1 wrote
  `/etc/polkit-1/rules.d/49-luxai-root-<user>.rules` returning `polkit.Result.YES`, which let **any**
  program of that user run `pkexec /usr/lib/luxai/luxai-root-auto -- COMMAND` as root without a
  password. The 2.0.2 package removes these files on upgrade; the setting itself is kept and now
  means the safe mode. Never recreate such a rule, and never add `Result.YES` rules for actions
  that run arbitrary commands.

Check: `ls /etc/polkit-1/rules.d/49-luxai-root-*.rules` must find nothing;
`pkaction --action-id org.luxai.root-auto --verbose` shows `implicit active: auth_admin_keep`.
Every root command is logged in `~/.local/state/luxai/root-commands.log` and
`journalctl -t luxai-root`.

## Residual risk

While the password is remembered (about 5 minutes), a program running as the same user can still
control the LuxAI window itself – on X11 any program of the user can send keys and clicks to other
windows (for example with `xdotool`), just as it could type into a terminal with a valid `sudo`
timestamp. "Approve each command" keeps a confirmation card for every command; the safest choice is
the default "Ask for the password every time". Destructive commands (deleting the system or home
folder, formatting disks, removing the bootloader, changing accounts, sudo, polkit or PAM) are
refused in every mode by the LuxAI safety rules, but those rules protect against model mistakes,
not against a deliberate attacker.

## Files

| Path | Purpose |
|---|---|
| `/usr/share/polkit-1/actions/org.luxai.root.policy` | actions `org.luxai.root` (`auth_admin`), `org.luxai.root-auto` (`auth_admin_keep`), `org.luxai.root-setup` |
| `/usr/lib/luxai/luxai-root`, `luxai-root-auto` | root helper started by `pkexec` (checks the safety rules again, clean environment, time limit) |
| `/usr/lib/luxai/luxai-root-setup` | only removes the old `49-luxai-root-<user>.rules` (`status` prints `on` while it exists) |
| `~/.config/luxai/settings.json` | the chosen mode (`agent.root_mode`: `password`, `nopass`, `noask`) |
| `~/.local/state/luxai/root-commands.log` | log of every root command (also `journalctl -t luxai-root`) |
