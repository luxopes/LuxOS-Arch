# E-mail – Thunderbird

The e-mail app of LuxOS is **Mozilla Thunderbird** (package `thunderbird`, command `thunderbird`,
desktop id `org.mozilla.Thunderbird.desktop`). New installations of LuxOS 1.0.3 and later have it
installed, together with its language pack for the system language (for example
`thunderbird-i18n-cs`, `-de`, `-pt-br`). Find it in Launchpad or Search as **Thunderbird**.

Thunderbird is maintained by Mozilla and updated with the system (Software Update). It handles
mail, calendars, contacts and feeds; LuxOS does not change its settings or data
(`~/.thunderbird`).

## Install it on an older installation

Systems installed before 1.0.3 keep what they have – an update does not download Thunderbird
(about 200 MB) for everyone. To install it:

- open the **LuxOS Store**, search for *Thunderbird* (it is also among the *Popular apps*) and press
  **Get**, or
- in the Terminal: `lux install thunderbird thunderbird-i18n-cs` (use your language code: `de`,
  `es-es`, `fr`, `hu`, `it`, `nl`, `pl`, `pt-br` / `pt-pt`, `sk`, `sv-se`, `uk`; English needs no
  language pack).

The Thunderbird app from Flathub (`org.mozilla.Thunderbird`) works the same way.

## Add an account

When Thunderbird starts for the first time it opens **Account Setup** (later: **☰ › Account
Settings › Account Actions › Add Mail Account**):

1. Enter your name, e-mail address and password, then press **Continue**.
2. Thunderbird finds the server settings itself (IMAP/SMTP of your provider) and shows them.
   Press **Done**.

### Gmail and Google Workspace

Enter the Gmail address and press **Continue** – leave the password field empty. Thunderbird
selects **OAuth2** and opens Google's own sign-in window: sign in, approve access for Thunderbird,
done. Thunderbird is verified by Google, so no app password is needed. If you use 2-step
verification, it works as usual in the Google window.

### Outlook.com, Hotmail and Microsoft 365

Enter the address and press **Continue**; Thunderbird uses **OAuth2** with the Microsoft sign-in
window. Some work or school accounts (Microsoft 365) need the administrator to allow IMAP or
Thunderbird – ask your IT department if sign-in is refused.

### Other providers (Seznam, iCloud, your own domain)

Usually the e-mail address and password are enough. Some providers require turning on IMAP access
in their web settings first, or an **app password** instead of the normal password (iCloud: *Sign-In
and Security › App-Specific Passwords* at account.apple.com). If the settings are not found, choose
**Configure manually** and enter the IMAP and SMTP servers from your provider's help page.

## E-mail links and default app

LuxOS sets Thunderbird as the default app for e-mail links (`mailto:`) and saved messages (`.eml`,
`message/rfc822`) in `/etc/xdg/luxos/mimeapps.list`. Your own choice always wins: it is stored in
`~/.config/mimeapps.list` (for example **Open With › Other Application…** in Files, or
`xdg-mime default <app>.desktop x-scheme-handler/mailto`).

E-mail links in Files and `xdg-email` go through `luxos-mail-reader` (see [apps.md](apps.md)): the
app chosen for `mailto` links, otherwise an installed mail app (Thunderbird, also from Flathub,
Evolution, Geary). When no mail app is installed, a notification appears and the LuxOS Store
opens with a search for mail apps – there is never an empty "choose an application" dialog.

## Look

Thunderbird follows the light/dark mode of LuxOS by itself (its default theme is *System theme –
auto*). It draws its own window buttons; they work like in other apps.

## Troubleshooting

- **Thunderbird is in English** – install the language pack for your language (see above) and
  restart Thunderbird.
- **Google says "This app is blocked" / sign-in loops** – make sure the authentication method of
  the account is *OAuth2* (**Account Settings › Server Settings › Authentication method**, and the
  same for the outgoing SMTP server).
- **An e-mail link opens the Store** – no mail app is installed, or the chosen app was removed;
  install Thunderbird or pick another app with **Open With**.

## LuxOS Mail

LuxOS Mail (`luxos-mail`) is a preview app available only in the staging update channel; it is not
part of stable LuxOS. Its documentation is in [mail.md](mail.md).
