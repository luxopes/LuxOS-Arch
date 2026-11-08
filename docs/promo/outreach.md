# Where to promote LuxOS 1.0.1 – ranked plan with ready texts

Nothing here has been posted or submitted; all accounts and sending are up to the owner.
Rules change – **re-read each site's current rules right before posting** (the summaries below were
checked on 2026-11-08 where the site allowed it, otherwise they come from the sites' long-standing
guidelines and are marked "verify").

## Ground rules for every channel

- **Say who you are.** "I'm the developer" in the first line. Undisclosed self-promotion (or friends
  posting for you) gets posts removed and accounts banned on Reddit and HN.
- **Say it's beta**, a young one-person project (public repo since 20 Oct 2026). Do not quote user
  numbers beyond what the public usage page shows; do not imply press coverage that does not exist.
- **One channel per day or two**, and stay around for several hours to answer comments. Unanswered
  launch posts die.
- **Expect three recurring questions** – prepare honest answers:
  1. *"Why not just theme Xfce / use Manjaro / EndeavourOS?"* → the custom parts: `lux` (no pacman,
     AUR in a sandbox, Flathub, rollback via Care snapshots), `linux-luxos`, Lux Guard, firewall on by
     default, drivers detection, apps written in LSL.
  2. *"An AI assistant in the OS? Privacy?"* → LuxAI is optional, needs an account, asks before risky
     actions; requests are processed by the third-party model providers listed in the privacy policy
     (<https://luxos.lux-ai.cz/privacy/>). Never claim "local AI".
  3. *"Bus factor / will it be around?"* → be honest: single developer, rolling Arch base, everything
     GPL on GitHub.
- **Name clash:** "LuxOS" is also Luxor's Bitcoin miner firmware. Always write "LuxOS (Linux
  distribution)" or "LuxOS, an Arch-based Linux distro" in titles.
- **Assets to have ready:** 3–5 light-mode screenshots (site gallery), a 30–60 s screen recording
  (Launchpad, Store install, Control Center, rollback), the download link and the changelog link.

Links used below:
- EN home: <https://luxos.lux-ai.cz/> · CS home: <https://luxos.lux-ai.cz/cs/>
- Changelog: <https://luxos.lux-ai.cz/changes/> · <https://luxos.lux-ai.cz/cs/zmeny/>
- Source: <https://github.com/luxopes/LuxOS-Arch>

---

## Ranking (impact × fit × effort)

| # | Channel | Why | When |
|---|---|---|---|
| 1 | AbcLinuxu (zprávička + blog) | Czech Linux audience, users may submit news | day 1 |
| 2 | Root.cz (tip for zprávičky) | biggest Czech Linux news site | day 1 |
| 3 | r/DistroHopping | people actively looking for new distros, tolerant of new projects | day 2 |
| 4 | r/unixporn | design is LuxOS's strength; screenshot format | day 3 |
| 5 | It's FOSS, Linuxiac, 9to5Linux (tips) | English news sites that cover new distro releases | day 2–4 |
| 6 | Show HN | big reach, harsh audience; only when you can answer for hours | week 2 |
| 7 | Mastodon (fosstodon etc.) | low effort, good for screenshots, hashtags | day 1, then ongoing |
| 8 | AlternativeTo listing | long-tail search ("macOS-like Linux") | week 1 |
| 9 | YouTube 5-min tour | evergreen, needed by reviewers | week 1–2 |
| 10 | Czech Facebook/Discord groups, school channels | friendly early testers, Czech localisation is a plus | week 1 |
| 11 | r/linux | strict, high bar; only with a technical angle | later |
| 12 | Product Hunt | weak fit for Linux distros; low priority | optional |
| 13 | Linuxexpres, Lupa.cz, Živě.cz, CzechCrunch | low/odd fit, see notes | optional |
| – | r/archlinux, Phoronix, GamingOnLinux, OMG! Ubuntu, Lobsters, r/opensource | not appropriate now – see "Do not post" | – |

---

## Czech

### 1. AbcLinuxu.cz – zprávička + blog

- **How:** registered users can submit a *zprávička* (news item); it is approved by the editors before
  it is published. Blogs are personal and published immediately. Use your real name (COI is fine when
  disclosed).
- **Pitfalls (verify):** zprávičky must be news, short, factual, not advertising; editors trim or
  reject promotional wording. Blog posts with only a link get ignored – write real content
  (how lux works, why own kernel build, what failed in beta). The audience is technical and critical;
  answer comments calmly.

**Zprávička (návrh):**

> **Vyšel LuxOS 1.0.1 „Sirius“ – český Linux na Archu s prostředím ve stylu macOS**
>
> Antonín Tomeček vydal verzi 1.0.1 distribuce LuxOS, která stojí na Arch Linuxu a pod povrchem
> používá Xfce upravené do podoby macOS (horní lišta, dock Plank, Launchpad). Místo pacmanu má vlastní
> správce balíků `lux` nad knihovnou libalpm (repozitáře Archu, Flathub, AUR v sandboxu), vlastní
> sestavení neupraveného jádra `linux-luxos`, snímky Btrfs před každou aktualizací s možností návratu
> a nově zapnutý firewall. Verze 1.0.1 je opravné vydání s novým ISO; systém je stále v betě.
> Ke stažení na [luxos.lux-ai.cz/cs](https://luxos.lux-ai.cz/cs/), zdrojový kód je na
> [GitHubu](https://github.com/luxopes/LuxOS-Arch) pod GPL-3.0.

**Blog – osnova:** „Proč jsem v LuxOS vyhodil pacman (a co dělá `lux` jinak)“ – 1) co je libalpm a proč
ho `lux` dál používá, 2) `/etc/lux/lux.conf` v TOML, 3) AUR jen přes sandbox a kontrolu PKGBUILD,
4) snímky před aktualizací a `luxos-care rollback`, 5) co zatím nefunguje (beta), 6) odkazy.
Upřímně napsat, že jde o projekt jednoho člověka a co čekáte od testerů.

### 2. Root.cz – tip do zpráviček

- **How:** zprávičky píše redakce; pošli tip přes kontakt redakce uvedený na webu (stránka
  Kontakt / „Redakce“) – nehádat adresu, zkopírovat ji ze stránky. Krátký e-mail, odkazy, žádné
  přílohy nad pár MB.
- **Pitfalls:** redakce bere novinky, ne reklamu; malé projekty mají šanci hlavně s novým vydáním
  nebo zajímavou technikou. Diskuse pod článkem bývá ostrá – odpovídat věcně, pod svým jménem.

**E-mail (návrh):**

> Předmět: Tip na zprávičku: LuxOS 1.0.1 – český Linux na Archu s vlastním správcem balíků
>
> Dobrý den,
>
> posílám tip na zprávičku. Dnes vyšla verze 1.0.1 „Sirius“ distribuce LuxOS, kterou vyvíjím. Jde
> o systém na Arch Linuxu s prostředím ve stylu macOS postaveným na Xfce. Technicky zajímavé může být:
> vlastní správce balíků `lux` nad libalpm (bez příkazu pacman, AUR jen v sandboxu, Flathub),
> neupravené jádro `linux-luxos` stavěné automaticky v GitHub Actions s testem v QEMU, snímky Btrfs
> před každou aktualizací s návratem zpět, `/usr` jen pro čtení a firewall zapnutý od začátku.
> Systém je zatím beta.
>
> Web a stažení: https://luxos.lux-ai.cz/cs/
> Seznam změn: https://luxos.lux-ai.cz/cs/zmeny/
> Zdrojový kód (GPL-3.0): https://github.com/luxopes/LuxOS-Arch
> Snímky: https://luxos.lux-ai.cz/cs/#gallery
>
> Rád doplním podrobnosti.
> Antonín Tomeček, info@lux-ai.cz

### Linuxexpres.cz

- Fit: medium-low (articles/reviews more than news). Offer a guest article ("Jak funguje návrat
  systému po aktualizaci na Btrfs") via their contact page, not a press release.

### Lupa.cz, Živě.cz, CzechCrunch

- **Lupa.cz:** internet/telco/business news – fit only with a business or privacy angle. Skip now.
- **Živě.cz:** general tech; a tip via the redakce contact may work if framed as "český student/vývojář
  udělal vlastní Linux". Only after Root/Abclinuxu, and only if you are comfortable with a personal
  story angle. Keep it honest: beta, small user base.
- **CzechCrunch:** startup/business – no fit (LuxOS is not a company). Skip.

### Czech Facebook groups, Discord servers, school channels

- Targets: Czech Linux groups on Facebook (search "Linux CZ/SK"), Czech Linux/IT Discord servers,
  your school's IT club or student chat, local hackerspaces (e.g. Brmlab-type spaces – check if they
  have a public channel).
- **Rules:** read each group's rules; many groups forbid self-promotion except on certain days or in a
  dedicated channel (e.g. `#projekty`/`#showcase`). Ask an admin first. Post once.

**Krátký příspěvek:**

> Ahoj, vyvíjím český Linux LuxOS (na Archu, vzhled jako macOS, vlastní správce balíků `lux`,
> čeština v celém systému). Právě vyšla verze 1.0.1 – je to ještě beta, takže hledám lidi, kteří ho
> vyzkouší (ideálně ve virtuálu nebo na záložním počítači) a řeknou mi, co nefunguje.
> 👉 https://luxos.lux-ai.cz/cs/ · chyby: https://github.com/luxopes/LuxOS-Arch/issues
> Díky!

---

## English news sites

### It's FOSS – news tip

- **How:** contact form / tip page on itsfoss.com (Contact → news tip). Short, link-rich, one
  paragraph on why it is interesting.
- **Pitfalls:** they receive many "new distro" tips; they cover what is distinctive. They also run
  paid sponsored posts – do **not** mistake that for coverage, and do not pay.

### Linuxiac – news tip

- Linuxiac regularly covers new distro releases, including small ones. Use the contact/tip address on
  the site. Same text as below.

### 9to5Linux – news tip

- Covers releases, mostly established distros; a tip with the ISO link and changelog is fine. Low
  chance for a first contact; better after 2–3 releases.

**Tip text (all three):**

> Subject: News tip: LuxOS 1.0.1 "Sirius" – Arch-based distro with a macOS-like desktop and its own package manager
>
> Hi,
>
> I'm the developer of LuxOS, an independent Arch-based distribution from the Czech Republic. Version
> 1.0.1 "Sirius" (beta) came out today with a new ISO.
>
> What is different from other Arch derivatives:
> - its own package manager `lux` on top of libalpm – no pacman command, AUR builds in a sandbox,
>   Flathub, own signed repositories;
> - a vanilla `linux-luxos` kernel built automatically in GitHub Actions and smoke-tested in QEMU;
> - LuxOS Care: background updates, a Btrfs snapshot before every update and one-command rollback,
>   read-only /usr;
> - a macOS-like Xfce desktop (top bar, Plank dock, Launchpad, Control Center), firewall on by default,
>   automatic driver detection, an optional AI assistant (LuxAI).
>
> 1.0.1 adds the default firewall, moves /tmp to disk, adds Store screenshots and fixes printing,
> scanning and security issues. It is still beta.
>
> Download: https://luxos.lux-ai.cz/ · Changelog: https://luxos.lux-ai.cz/changes/
> Screenshots: https://luxos.lux-ai.cz/#gallery · Source (GPL-3.0): https://github.com/luxopes/LuxOS-Arch
>
> Happy to answer questions or provide more screenshots.
> Antonín Tomeček – info@lux-ai.cz

### OMG! Ubuntu

- Ubuntu-centric; an Arch derivative is off-topic. **Skip.** (Their sister site for general Linux, if
  still active, is a better target – check.)

### Phoronix

- Only for a **technical** story (e.g. "distro defaults to sched_ext scx_lavd", kernel CI with QEMU
  driver tests, benchmarks with data). A release announcement alone is not Phoronix material.
  Tip only when there is such an angle.

### GamingOnLinux

- Only with a **gaming angle**: e.g. Performance mode routing games to the discrete GPU on hybrid
  laptops (including Flatpak Steam overrides). Even then, a forum/news tip at most. Not now.

---

## Communities

### r/DistroHopping (rank 3)

- **Rules (verify sidebar):** new-distro posts are welcome; be transparent that you are the developer;
  no repeated reposts. Flair if required.
- **Post:**

> **Title:** I made LuxOS, an Arch-based distro with a macOS-like Xfce desktop and its own package manager – 1.0.1 beta is out
>
> Hi! I'm the developer (one person, from Czechia). LuxOS is Arch underneath, Xfce under a macOS-style
> layout (top bar, Plank dock, Launchpad, Control Center) and a few things of its own:
>
> - `lux` instead of pacman (libalpm underneath; repos + Flathub + AUR built in a sandbox)
> - Btrfs snapshot before every update, `luxos-care rollback` to go back, read-only /usr
> - vanilla `linux-luxos` kernel with scx_lavd scheduler
> - firewall on by default, automatic drivers incl. legacy NVIDIA
> - optional AI assistant (needs an account – you can ignore it)
>
> It's beta – please try it in a VM or a spare machine first. I'd love bug reports and honest
> criticism. Screenshots: https://luxos.lux-ai.cz/#gallery · ISO: https://luxos.lux-ai.cz/ ·
> Source: https://github.com/luxopes/LuxOS-Arch

### r/unixporn (rank 4)

- **Rules (from the sub's FAQ; verify the current sidebar – rules were updated in Oct 2024):**
  - title must start with the **WM/DE tag in brackets**, e.g. `[Xfce]`; no other tags;
  - a **details comment** (theme, icons, fonts, bar, dock, wallpaper…) is required, posted right after
    the image;
  - the post is about the *rice*, not an ad for a distro – a distro release post can be removed as
    off-topic. Show the setup and make the details useful for people who want to recreate it.
- **Title:** `[Xfce] LuxOS – light macOS-style layout: Plank dock, top bar Control Center, Launchpad`
- **Image:** one clean light-mode screenshot (desktop + Launchpad or Control Center), no personal
  data, 1080p or higher; optionally a gallery with dark mode.
- **Details comment:**

> **Details**
> - OS: LuxOS 1.0.1 (Arch-based; I'm the developer)
> - WM: xfwm4 (built-in compositor), window buttons left
> - Bar: xfce4-panel as a top bar (app menu, active app name, tray, clock + calendar)
> - Dock: Plank (zoom on hover)
> - Launcher: Launchpad (`Super+A`) and Search (`Super+Space`)
> - GTK theme / icons / cursors: WhiteSur (LuxOS redraws a set of its own icons; no Apple logos)
> - Font: Inter
> - Wallpaper: LuxOS default
> - Dotfiles: defaults are in `/etc/xdg/luxos` – https://github.com/luxopes/LuxOS-Arch (packages/luxos-desktop, packages/luxos-themes)

### r/linux (rank 11 – be careful)

- **Rules (verify at reddit.com/r/linux/about/rules):** a general news/discussion sub with strict
  moderation of low-effort and self-promotional posts. Reddit's old "10% / 9:1" self-promotion
  guideline is no longer an official sitewide rule, but **many moderators still apply it**: if most of
  your account's posts link to your own project, you'll be treated as a spammer. Build history first
  (comment genuinely in other threads).
- Only post with a substantial, technical angle (a write-up on the lux design or the kernel CI), as a
  text post or blog link, not "check out my distro".

### r/archlinux – **do not post**

- Arch derivatives are off-topic and support for them is not given; promotion is removed. The same
  applies to the Arch forums and Arch wiki. Never ask Arch channels for help with LuxOS-specific
  problems.

### r/opensource – **not now**

- Reported in 2026: the sub restricts promotion of AI-related projects and requires about a year of
  maintenance for project promotion (verify). LuxOS ships an AI assistant and is weeks old.

### Hacker News – Show HN (rank 6)

- **Rules (news.ycombinator.com/showhn.html, verify):** Show HN is for something people can **try**
  (an ISO qualifies); title starts with `Show HN:`; post the link to the project (site or GitHub), add
  a first comment with background; **don't ask for upvotes** or have friends upvote (voting rings are
  detected and penalised); no marketing language; be there to answer. One retry after a few weeks is
  tolerated if it got no attention, not more.
- HN dislikes hype and is sceptical of AI features and of "macOS clones"; lead with the technical
  parts and be frank about limitations.
- **Title:** `Show HN: LuxOS – Arch-based Linux with its own package manager and snapshot rollback`
  (URL: https://luxos.lux-ai.cz/ or the GitHub repo)
- **First comment:**

> I'm the developer of LuxOS. It started as "Arch, but set up so that I never have to fix it by hand",
> and grew into a distro:
>
> - `lux` replaces the pacman command but keeps libalpm, so it's binary compatible with Arch repos.
>   Config is TOML (/etc/lux/lux.conf); it also handles Flathub, AUR (built in a bubblewrap sandbox after
>   a PKGBUILD review) and a small own package format (.lux).
> - Every transaction takes a read-only Btrfs snapshot first; `luxos-care rollback` boots back into it,
>   with the matching kernel kept on the ESP. /usr is read-only except during transactions, and a weekly
>   check compares every system file with the package database's mtree.
> - The kernel is vanilla stable from kernel.org with Arch's config plus a few settings, built by
>   GitHub Actions, booted in QEMU and checked for ~50 common drivers before publishing.
> - Desktop is Xfce (xfwm4, panel, Plank) arranged like macOS. Several tools are written in LSL, a
>   small compiled language I also made.
> - There is an optional AI assistant that needs an account; the OS works fine without it.
>
> It's beta, a one-person project, and the public repo is only a few weeks old – expect rough edges.
> I'd appreciate criticism of the design, especially the update/rollback path.

### Lobsters – **invite-only**

- You need an invitation from an existing member. Self-promotion is accepted only from people who
  participate otherwise (guideline: own content should be a small fraction of your activity). Don't ask
  strangers for invites just to post this. Skip unless someone you know invites you.

### Mastodon / Fosstodon (rank 7)

- **Rules:** fosstodon.org is FOSS-focused and requires English posts; self-promotion of FOSS projects
  is fine in moderation. Use **content warnings** only if your instance asks for them; add **alt text to
  every image** (the community expects it). Hashtags in CamelCase: `#Linux #ArchLinux #FOSS #OpenSource
  #LinuxDistro #Xfce`. Consider an official project account (e.g. @luxos) – check instance rules for
  project accounts.
- **Post:**

> LuxOS 1.0.1 "Sirius" is out 🎉 – an Arch-based Linux with a macOS-like Xfce desktop, its own package
> manager (lux), Btrfs snapshot before every update with rollback, and a firewall on by default.
> Still beta – testers welcome!
>
> https://luxos.lux-ai.cz
>
> #Linux #ArchLinux #FOSS #LinuxDistro #Xfce
>
> [alt text: LuxOS desktop in light mode with a top bar, a dock at the bottom and the Launchpad grid of apps]

### X (Twitter)

- Low organic reach for new accounts; post the same screenshot + link, tag nobody uninvited. Do not
  buy promotion.

> LuxOS 1.0.1 "Sirius" (beta) is out: Arch-based Linux with a macOS-like desktop, its own package
> manager, snapshot rollback and a default firewall. Free, GPL-3.0. https://luxos.lux-ai.cz #Linux

### AlternativeTo listing (rank 8)

- Create the app as **LuxOS**; set "Alternative to": macOS, Zorin OS, elementary OS, Linux Mint,
  Manjaro, EndeavourOS. Platforms: Linux. License: Free, Open Source. Tags: linux-distribution,
  arch-based, macos-like, rolling-release, xfce. Do not upvote your own listing with extra accounts.
- **Description:**

> LuxOS is a free, open-source Linux distribution based on Arch Linux with a macOS-like desktop built
> on Xfce: a top bar with Control Center, the Plank dock, Launchpad and Search. It has its own package
> manager, lux (Arch repositories, Flathub and sandboxed AUR builds), a graphical app store, automatic
> driver detection, background updates with a Btrfs snapshot before every update and one-command
> rollback, a firewall on by default and Lux Guard, which runs untrusted downloaded programs in a
> sandbox. An optional AI assistant, LuxAI, is included. LuxOS is in beta.

### Product Hunt (rank 12, optional)

- Fit is weak (consumer apps/SaaS). If you do it: launch at 00:01 PT, have the maker comment ready,
  do **not** ask for upvotes (against PH rules).
- **Tagline (60 chars):** `Arch-based Linux with a macOS-like desktop – free, beta`
- **Description:**

> LuxOS is a free Linux distribution that looks and feels like a Mac: top bar, dock, Launchpad and a
> Control Center. Under the hood it is Arch Linux with its own package manager, automatic drivers and
> updates you can undo. Optional LuxAI assistant. Beta – feedback welcome.

- **Maker comment:** short version of the Show HN comment, less technical.

### YouTube – 5-minute tour (rank 9)

Record in a VM or on real hardware at 1080p, light mode, no personal data, system language English
(record a Czech version separately or add subtitles). No music with copyright issues.

| Time | Scene | Script (voice-over) |
|---|---|---|
| 0:00–0:20 | Desktop after login | "This is LuxOS 1.0.1 'Sirius', a free Linux distribution based on Arch with a macOS-style desktop. It's still beta – here's a five-minute tour." |
| 0:20–0:50 | Boot ISO → live desktop → "Install LuxOS" | "You boot the ISO and can try it without installing. The installer asks for language, keyboard, disk and optional encryption; it takes about ten minutes and needs internet." (speed up the install) |
| 0:50–1:40 | Top bar, Dock, Launchpad (`Super+A`), Search (`Super+Space`), Control Center | "The top bar shows the current app and a Control Center with Wi‑Fi, Bluetooth, brightness, Do Not Disturb and dark mode. Launchpad and Search work like on a Mac." |
| 1:40–2:30 | LuxOS Store: install an app; terminal `lux install`, `lux search ^vim` | "Apps come from the LuxOS Store or the `lux` command – Arch repositories, Flathub, and AUR packages that are built in a sandbox. There's no pacman; if you type it, the shell shows the lux equivalent." |
| 2:30–3:15 | Software Update, snapshot list, `luxos-care rollback` explanation | "Updates install in the background. Before each update LuxOS takes a Btrfs snapshot, so a bad update can be rolled back with one command, and the previous kernel stays in the boot menu." |
| 3:15–3:50 | Download a script → Lux Guard dialog → Run in Sandbox; Settings › Firewall | "Programs from the internet are checked by Lux Guard when you start them and can be run in a sandbox. The firewall is on by default and asks before a program accepts connections." |
| 3:50–4:25 | LuxAI chat asking "How much disk space do I have?" (agent asks for approval) | "LuxAI is an optional assistant – it needs a LuxAI account and asks before doing anything risky." |
| 4:25–4:50 | Weather, Maps, emoji panel `Super+.`, Alt+` | "A few of the built-in apps: Weather with a live sky, Maps with OpenStreetMap, and an emoji picker." |
| 4:50–5:00 | Website | "LuxOS is free and GPL-licensed. Download it at luxos.lux-ai.cz, and please report bugs on GitHub." |

- **Title:** `LuxOS 1.0.1 tour – Arch-based Linux with a macOS-like desktop (beta)`
- **Description:** two sentences + links (site, changelog, GitHub issues) + chapters with the times
  above. Tags: linux, arch linux, linux distro, macos like linux, xfce.
- Thumbnail: the light desktop with "LuxOS 1.0.1" – no Apple logo.

### School/student channels

- Your school's IT teacher, student IT club, or a Czech student hackathon Discord. Pitch it as "a
  project I built – looking for testers", not as a product. Offer a short demo or talk. Respect
  school IT rules (do not install on school computers without permission).

---

## Do not post (now)

| Channel | Why |
|---|---|
| r/archlinux, Arch forums, Arch wiki | derivatives are off-topic; promotion removed |
| Phoronix | only for a concrete technical story with data |
| GamingOnLinux | only with a real gaming feature story |
| OMG! Ubuntu | Ubuntu-focused |
| Lobsters | invite-only, no drive-by promotion |
| r/opensource | reported rules against AI-related and very young projects |
| CzechCrunch, Lupa.cz | not a business/telco story |
| Wikipedia | no article until independent sources exist – see wikidata.md |

## After posting

- Note each post's URL, date and outcome in a private list (not in the repo).
- Turn real questions into FAQ entries on the site (phase 2).
- If an outlet writes about LuxOS, save the link – these are the independent sources needed for
  Wikipedia notability later (see wikidata.md).
