# GitHub repository settings (to set by hand – not applied)

Repository: <https://github.com/luxopes/LuxOS-Arch> (About ⚙ on the repo page).

**Description** (max ~350 chars, shown in search results):

> LuxOS – fast, lightweight Arch Linux based distribution with a macOS-like Xfce desktop, its own
> package manager (lux), own kernel build, snapshot rollback, automatic drivers and the LuxAI
> assistant. Beta.

**Website:** `https://luxos.lux-ai.cz` (already set)

**Topics** (lowercase, max 20):

```
linux linux-distribution linux-distro archlinux arch-linux arch-based xfce macos-like
desktop-environment rolling-release package-manager btrfs iso operating-system lsl
czech gplv3 bash
```

(Leave out `ai`/`llm` topics unless you want that audience; the AI assistant is optional.)

**Social preview image:** Settings › General › Social preview – upload `site/assets/og-image.jpg`
(1200×630), so links to the repo show the desktop instead of the default card.

**Other quick wins:**
- Releases: create a GitHub Release `v1.0.1` ("LuxOS 1.0.1 Sirius (beta)") with the changelog text
  and a link to the ISO on the website (the ISO is too big for a release asset – 2 GB limit per file
  is close, and the site already hosts it with signatures).
- Pin the repository on the `luxopes` profile; add a profile README with one line and the website.
- Enable Discussions only if you will answer them; otherwise keep issues as the single channel.
- Add `.github/ISSUE_TEMPLATE/bug_report.md` asking for `lux doctor` output, LuxOS version
  (`cat /etc/os-release`) and hardware (`luxos-hwdetect --report`).
