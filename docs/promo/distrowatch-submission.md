# DistroWatch – "Submit a distribution"

Form: <https://distrowatch.com/dwres.php?resource=submit> (the page refuses automated fetching, so the
field list below follows the fields DistroWatch shows on distribution pages; match them to the live
form when submitting). Submit by hand, from the owner's own e-mail. Nothing has been submitted.

## Fields

| Field | Value |
|---|---|
| Distribution name | LuxOS |
| Home page | https://luxos.lux-ai.cz/ |
| Mailing lists | none |
| User forums | none yet (bug reports: GitHub issues; in-system Feedback app) |
| Alternative user forums | – |
| Documentation | https://luxos.lux-ai.cz/docs/ |
| Screenshots | https://luxos.lux-ai.cz/#gallery |
| Screencasts | – (add the YouTube tour once it exists, see outreach.md) |
| Download mirrors | https://luxos.lux-ai.cz/#download (direct: https://luxos.lux-ai.cz/download/luxos-1.0.1-x86_64.iso, SHA256SUMS and .sig next to it) |
| Bug tracker | https://github.com/luxopes/LuxOS-Arch/issues (issues are enabled on the public repository) |
| Related websites | https://github.com/luxopes/LuxOS-Arch (source), https://github.com/luxopes/luxos-kernel (kernel), https://lsl.lux-ai.cz (LSL language), https://luxos.lux-ai.cz/changes/ (changelog) |
| Reviews | – (leave empty; do not list self-written posts as reviews) |
| Where to buy | – (free download) |
| OS type | Linux |
| Based on | Arch |
| Origin | Czech Republic |
| Architecture | x86_64 |
| Desktop | Xfce (customised macOS-like layout: top bar, Plank dock, Launchpad) |
| Category | Desktop, Beginners |
| Status | Active |
| Popularity | – (DistroWatch fills this) |
| Release model | Rolling (numbered ISO snapshots: 1.0.1 "Sirius" on 2026-11-08) |
| Init system | systemd |
| Default file system | Btrfs (zstd compression, optional LUKS2) |
| Package management | lux (libalpm-based; repositories, Flathub, AUR, own .lux format) |
| Price | Free |
| Licence | GPL-3.0-or-later (LuxOS's own code); bundled packages keep their own licences |
| Contact | Antonín Tomeček, info@lux-ai.cz |

## Description (DistroWatch style: third person, factual, 2–4 sentences)

> LuxOS is a desktop Linux distribution based on Arch Linux and developed in the Czech Republic. It
> features a macOS-style desktop built from Xfce components with a top bar, the Plank dock and a
> Launchpad, its own package manager "lux" (based on libalpm, with access to Arch repositories, the
> AUR and Flathub), a self-built vanilla kernel and automatic driver detection. Updates are applied by
> the LuxOS Care service, which takes a Btrfs snapshot before every update so the system can be rolled
> back. The distribution also ships an optional AI assistant (LuxAI), a program checker that runs
> untrusted downloads in a sandbox (Lux Guard) and system tools written in the author's own LSL
> programming language.

Shorter variant (if the form limits length):

> LuxOS is an Arch-based desktop distribution from the Czech Republic with a macOS-like Xfce desktop,
> its own libalpm-based package manager "lux", automatic drivers and snapshot-based rollback of
> updates.

## Waiting-list notes (be realistic)

- New submissions go to the **waiting list**; DistroWatch editors pick projects from it over time,
  there is no guaranteed date. The list is long and waits of many months are common.
- Projects on the waiting list can be **recommended by visitors** (a "Recommend" button on the
  waiting-list entry). Do not organise vote campaigns or ask users to vote repeatedly – it looks bad
  and DistroWatch limits it.
- DistroWatch has historically offered a **paid option to skip the queue**; check the current price
  and terms on the submission page before deciding (not recommended until the project is older).
- Editors look for: a real downloadable ISO, an English website, documentation, an independent
  identity (not a respin with a new wallpaper), and **a track record**. LuxOS's public repository is
  only from **20 October 2026**, so expect editors to wait for more releases. Listing the custom parts
  (lux, linux-luxos, LuxOS Care, Lux Guard, LSL) in the description helps show it is not just a theme.
- Keep the home page, download link and checksums stable; a broken download link is a common reason
  to skip a project.
- After 1–2 more ISO releases, a short follow-up e-mail with the new version is fine. Do not resubmit
  repeatedly.
- **Name clash:** "LuxOS" is also the name of Luxor Technologies' Bitcoin miner firmware. Mention
  "Linux distribution" next to the name everywhere so editors and readers do not confuse them.
