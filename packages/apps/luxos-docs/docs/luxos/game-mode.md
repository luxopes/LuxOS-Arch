# Game Mode

While a game runs, the game gets almost the whole computer. It switches on by itself, like Game Mode
in Windows; no `gamemoderun` needed. `luxos-game-mode.service` (package `luxos-tweaks`, root) checks
the processes every 2 s.

## What counts as a game

 a game started by Steam (`SteamGameId`/`SteamAppId`, not the Steam client),
a Windows program under Wine/Proton (`*.exe`, not Wine's helpers), `gamescope`, programs listed in
`GAMES=` and anything started with `luxos-game run PROGRAM` (in Steam: launch option
`luxos-game run %command%`). The game includes all its child processes.

## While it runs

1. Your other apps (Firefox, Steam client, chat, mail, …) run only on the last physical CPU core
   (about a sixth of the CPU, at least one logical CPU), with nice +10 and idle I/O priority. Sound
   (PipeWire), the compositor, portals and input methods are never slowed. Threads with their own CPU
   affinity, nice or real-time scheduling are left alone. CPU affinity works with every scheduler;
   scx_lavd mostly ignores nice and cgroup CPU limits.
2. Heavy system jobs pause (`systemctl freeze`) until the game ends: LuxOS Care updates and checks,
   virus scan and database update, snapshots, backups, man-db, fstrim, reflector, … Lux Guard itself is
   never paused (it checks the files the game opens).
3. Once, at the start: memory of background apps is compressed into zram (`memory.reclaim` of their
   cgroups) until `RECLAIM_TARGET` % of RAM is free, then memory is compacted (huge pages for the game).
4. Power profile Performance (not while Battery Saver is on), Do Not Disturb (unless you already had it).

## After the game

10 s after the last game process ends everything is restored: CPU cores, priorities, paused jobs, power
profile and Do Not Disturb. After a crash of the service the next start restores it from
`/run/luxos/game-mode.json`.

## Measurement

Measured on a Ryzen 5 5500U (12 threads, scx_lavd): a test "game" with 6 threads and fixed work per
frame made 125 FPS on an idle system and 76 FPS (1 % low 52) while 12 busy background threads ran.
With Game Mode it made 126 FPS (1 % low 101).

## Settings and status

- Settings: `/etc/luxos/game-mode.conf` (`ENABLED`, `RECLAIM`, `RECLAIM_TARGET`, `PERFORMANCE`,
  `QUIET`, `GAMES`, `FREEZE`), then `sudo systemctl reload luxos-game-mode`.
- Status: `luxos-game status`; log: `journalctl -u luxos-game-mode`.

## Always on for games

- `kernel.split_lock_mitigate = 0` (in `/usr/lib/sysctl.d/99-luxos.conf`): a split lock is only logged, the process is not slowed down
  (some games under Wine stuttered: the kernel put them to sleep for 10 ms; as on SteamOS / CachyOS).
- The `ntsync` module is loaded at boot (fast thread synchronisation for Wine/Proton, `/dev/ntsync`).
- Bigger shader cache, less stutter the first time a place in a game is drawn:
  `__GL_SHADER_DISK_CACHE_SIZE` and `MESA_SHADER_CACHE_MAX_SIZE` in `/etc/profile.d/luxos-games.sh` and
  `/usr/lib/environment.d/60-luxos-games.conf` (your own value wins).
- Games run on the discrete GPU ([luxos-gpu](power-and-performance.md)); the compositor shows a
  full-screen game directly (scanout), with VRR and tearing on request.

See also [Power, performance and memory](power-and-performance.md) (CPU scheduler, zram, sysctl).
