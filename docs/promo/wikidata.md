# Wikidata item draft for LuxOS + Wikipedia notes

Not created. All QIDs/PIDs below were checked against the Wikidata API on 2026-11-08
(note: **Q19702 is not Arch Linux** – it is the year 1180; Arch Linux is **Q185576**).

## Before creating the item

- Wikidata's notability policy (WD:N) accepts an item if it (1) has a Wikimedia sitelink, **or**
  (2) "refers to an instance of a clearly identifiable conceptual or material entity" that "can be
  described using serious and publicly available references", **or** (3) fulfils a structural need.
  LuxOS can qualify under (2) only with **public references** – the official website and the GitHub
  repository are acceptable as references for basic facts, but items about very new self-published
  software are sometimes nominated for deletion. Wait until at least one independent source (news
  article, DistroWatch entry) exists, then create the item and cite it.
- **Conflict of interest:** you may create the item about your own project, but state the COI on your
  Wikidata user page ("I am the developer of LuxOS"), keep statements neutral and sourced, and don't
  add promotional descriptions.
- **Disambiguation:** "LuxOS" is also Luxor Technologies' Bitcoin miner firmware. Use the
  descriptions below so both can coexist; search Wikidata for "LuxOS" first in case an item already
  exists.

## Labels, descriptions, aliases

| Language | Label | Description | Aliases |
|---|---|---|---|
| en | LuxOS | Arch Linux-based Linux distribution with a macOS-like desktop | LuxOS Linux |
| cs | LuxOS | linuxová distribuce založená na Arch Linuxu s prostředím ve stylu macOS | LuxOS Linux |

(Descriptions must not start with a capital letter or an article and must not be promotional.)

## Statements

| Property | Value | Qualifiers | Reference |
|---|---|---|---|
| instance of (P31) | Linux distribution (Q131669) | | official website |
| based on (P144) | Arch Linux (Q185576) | | official website / docs overview |
| developer (P178) | **omit for now**: there is no item for Antonín Tomeček, and you should not create a person item for yourself (it would fail notability). Add P178 only if such an item ever exists independently. | | |
| official website (P856) | https://luxos.lux-ai.cz/ | language of work or name (P407): English (Q1860), Czech (Q9056) | |
| source code repository URL (P1324) | https://github.com/luxopes/LuxOS-Arch | | |
| issue tracker URL (P1401) | https://github.com/luxopes/LuxOS-Arch/issues | | |
| uses (P2283) (preferred over operating system (P306), which is for software that *runs on* an OS) | Linux kernel (Q14579) | | docs: power-and-performance |
| uses (P2283) | Xfce (Q170821) | | docs overview |
| programmed in (P277) | Python (Q28865) | | GitHub repository |
| programmed in (P277) | shell script (Q959549) | | GitHub repository |
| programmed in (P277) | C (Q15777) | | GitHub repository (patches/tools) |
| programmed in (P277) | *LSL (Lux Simple Lang)* – no item; omit | | |
| copyright license (P275) | GNU General Public License v3.0 or later (Q27016754) | | LICENSE file |
| software version identifier (P348) | 1.0.1 | publication date (P577): 2026-11-08; version type (P548): beta version (Q3295609) | https://luxos.lux-ai.cz/changes/ |
| software version identifier (P348) | 1.0.0 | publication date (P577): 2026-11-04; version type (P548): beta version (Q3295609) | changelog |
| platform (P400) | x86-64 (Q272629) | | hardware docs |
| country of origin (P495) | Czech Republic (Q213) | | privacy page ("developed … by Antonín Tomeček, Czech Republic") |
| inception (P571) | 2026-10 (precision: month) | | GitHub repository first commit (2026-10-20) |
| language of work or name (P407) | English (Q1860), Czech (Q9056) (+ Slovak Q9058, German Q188 … only if you want; the UI has 13 languages) | | docs overview |
| logo image (P154) | *only after upload to Commons* – see below | | |

Mark the newest P348 statement with **preferred rank** and give older ones normal rank.

### QuickStatements (V1)

```
CREATE
LAST	Len	"LuxOS"
LAST	Lcs	"LuxOS"
LAST	Den	"Arch Linux-based Linux distribution with a macOS-like desktop"
LAST	Dcs	"linuxová distribuce založená na Arch Linuxu s prostředím ve stylu macOS"
LAST	P31	Q131669	S854	"https://luxos.lux-ai.cz/"
LAST	P144	Q185576	S854	"https://luxos.lux-ai.cz/docs/luxos/overview.html"
LAST	P856	"https://luxos.lux-ai.cz/"
LAST	P1324	"https://github.com/luxopes/LuxOS-Arch"
LAST	P1401	"https://github.com/luxopes/LuxOS-Arch/issues"
LAST	P2283	Q14579	S854	"https://luxos.lux-ai.cz/docs/luxos/power-and-performance.html"
LAST	P2283	Q170821	S854	"https://luxos.lux-ai.cz/docs/luxos/overview.html"
LAST	P277	Q28865	S854	"https://github.com/luxopes/LuxOS-Arch"
LAST	P277	Q959549	S854	"https://github.com/luxopes/LuxOS-Arch"
LAST	P275	Q27016754	S854	"https://github.com/luxopes/LuxOS-Arch/blob/main/LICENSE"
LAST	P348	"1.0.1"	P577	+2026-11-08T00:00:00Z/11	P548	Q3295609	S854	"https://luxos.lux-ai.cz/changes/"
LAST	P400	Q272629	S854	"https://luxos.lux-ai.cz/docs/luxos/hardware.html"
LAST	P495	Q213	S854	"https://luxos.lux-ai.cz/privacy/"
LAST	P571	+2026-10-00T00:00:00Z/10	S854	"https://github.com/luxopes/LuxOS-Arch"
```

Check the docs URLs above resolve on the live site before running; QuickStatements needs a logged-in
Wikidata account and should be run by the owner.

## Logo on Wikimedia Commons

- Only upload a logo you own: the LuxOS logo is your own work (`packages/luxos-branding/files/logo`,
  `site/assets/luxos-logo.svg`). It must **not** contain Apple elements.
- Commons accepts only **free licences** (e.g. CC BY-SA 4.0, CC0) or {{PD-textlogo}} for simple
  text-only logos. Uploading it means anyone may reuse it under that licence (trademark rights stay
  separate – add the {{Trademarked}} template).
- Upload as SVG via Special:UploadWizard as "own work", file name e.g. `LuxOS logo.svg`, category
  "Linux distribution logos". Then add `P154 logo image = LuxOS logo.svg`.
- If you don't want to free-license the logo, skip P154 (Wikidata cannot use non-free files).

## Wikipedia – honest notes

- **Do not create the article yourself.** You have a conflict of interest (WP:COI); English Wikipedia
  expects COI editors to disclose it and to propose articles through **Articles for Creation (AfC)**
  (WP:AFC) instead of publishing directly. Czech Wikipedia has a similar expectation (Wikipedie:Střet
  zájmů) and no AfC queue – a draft would go to the article discussion or a request to experienced
  editors.
- **Notability today: not met.** Software needs *significant coverage in multiple reliable sources
  independent of the subject* (WP:GNG, WP:NSOFT). The website, GitHub, the changelog, DistroWatch's
  waiting list, Reddit/HN posts, YouTube videos you make, forum posts and press releases do **not**
  count. A draft submitted now would be declined, and a deleted article makes later attempts harder.
- **Timeline:** wait until there are at least 2–3 independent in-depth articles, ideally months apart.
  Then either a neutral editor writes it, or you submit a neutral draft via AfC with the COI disclosed.

### Sources that would establish notability (examples)

| Kind | Counts? |
|---|---|
| Review or news article written by editors at Root.cz, AbcLinuxu (editorial article, not a user blog/zprávička), Linuxexpres, Živě.cz | yes, if in-depth |
| Review or news at It's FOSS, Linuxiac, 9to5Linux, LWN.net, Phoronix, The Register, Ars Technica, Heise/c't, Linux Magazine, Linux Format | yes, if in-depth and editorial (not sponsored) |
| DistroWatch Weekly **review** (not just the database entry) | yes, generally accepted |
| Academic paper or thesis that discusses LuxOS | yes |
| Book chapter / magazine print coverage | yes |
| User-submitted zprávička, your own blog, Reddit, HN, YouTube by you, press release reprints, app-store listings, sponsored posts, AI-generated "listicles" | no |
| DistroWatch database entry alone, AlternativeTo, GitHub stars | no (fine as Wikidata references for facts) |
