# LuxAI – the AI assistant for LuxOS

**LuxAI** is the AI assistant of LuxOS: a desktop application (Python 3 and GTK 3, package `luxai`
from the `[luxos-apps]` repository) that chats like any AI assistant and, in **Agent** mode, can
actually work with your computer. It is the same assistant as the terminal agent
[Lux Code](lux-code.html), but with a graphical interface. Install it with `lux install luxai`
and open it from Launchpad or Search.

## Two modes

| Mode | What it does |
|---|---|
| **Chat** | A plain conversation with streamed answers, Markdown (headings, lists, tables, code blocks with a Copy button, links) and a conversation history in the sidebar. Chat has no access to your computer; it can only use the offline manual and the web tools. |
| **Agent** | LuxAI works with the computer through tools: shell commands, reading, writing, editing and deleting files, listing and searching files, opening applications and URLs, screenshots, mouse and keyboard (`xdotool`), listing, activating and closing windows (`wmctrl`), the clipboard and notifications. Every tool call is shown as a card with the result and details. |

You can attach images and text files to a message (the **+** button, or paste with Ctrl+V): up to 4
images and 8 attachments per message; images are shrunk to JPEG, text files are inserted as text
(up to 60,000 characters).

## It knows LuxOS: the offline manual

In both modes the model has the offline LuxOS and [LSL](../lsl/overview.html) manual from the
`luxos-docs` package (the same pages as this documentation). It searches it with `docs_search`
(ranked sections, accent- and case-insensitive) and reads a file or one section with `docs_read`.
These tools only read files inside the manual folder and need no approval. That is why LuxAI can
answer questions such as "how do I add a repository to lux" from the real documentation.

## Web search

In Chat and Agent mode LuxAI can search the web and read pages (`web_search`, `web_fetch`):

- `web_search` returns up to 8 results (title, URL, snippet). It goes through your LuxAI account;
  if the server does not accept it, LuxAI falls back to DuckDuckGo.
- `web_fetch` reads only public `http(s)` addresses, without cookies or credentials, follows at most
  5 redirects, downloads at most 2 MB and extracts readable text (up to 20,000 characters).
- **Private networks are blocked**: every address must be public (no loopback, LAN or link-local
  addresses), also after each redirect.
- Web content is marked as **untrusted data**. The model is told never to follow instructions from a
  web page. As soon as a conversation contains web content, every shell command in Agent mode needs a
  separate confirmation, and a URL that neither you nor a search result supplied is opened only after
  you approve it. This protects against prompt injection and leaking data in URLs.

## Math, code and copying

LaTeX formulas in answers are rendered (fractions, sums, integrals, indices, Greek letters). Code
blocks have syntax highlighting (Python, LSL, Bash, JavaScript, C/C++, Rust, Go, JSON, HTML, CSS, SQL,
YAML and more) in both light and dark theme. Select text with the mouse and press Ctrl+C, or use the
**Copy** buttons under answers and code blocks.

## Agent safety and permissions

LuxAI Agent asks before it acts. Actions are grouped by risk:

| Level | Examples | Behaviour |
|---|---|---|
| Read | read a file, list a folder, find files, list windows | no question |
| Action | shell, write or delete files, mouse and keyboard, open an app or URL, screenshot, clipboard | a card with **Allow once / Always this session / Deny**; an *Auto-approve* switch skips it (and is always off again after a restart) |
| Sensitive | reading `~/.ssh`, `.env` or keys; sending feedback to the LuxOS author | always a one-time confirmation |
| Dangerous | shutting down, `sudo` inside a command, `curl … \| sh`, writing outside the home folder | two confirmations, cannot be allowed permanently |
| Blocked | the LuxAI account token, `rm -rf /`, `mkfs`, writing to disks, boot loader and kernel changes, accounts, sudoers/polkit/PAM, passing passwords to `sudo`/`su` | always refused, in every setting |

In **Settings › Agent permissions** you can set, per category, whether commands run, files are read
or written, the network is used, apps are opened, the mouse and keyboard are controlled, and
screenshots are taken (always ask / ask only when risky / never), plus a working folder, allowed and
forbidden folders and a command time-out (120 s by default). **Stop** (or Esc) interrupts both the
model's answer and a running command.

### Administrator mode

When a task needs root, the agent runs the command through `pkexec`, after the same hard-block check.
By default it needs two confirmations and the administrator password. Optionally (model Flash only)
you can allow root commands without a password. Every root command is logged to
`~/.local/state/luxai/root-commands.log` and the system journal (`journalctl -t luxai-root`).

## LuxAI account and models

LuxAI uses the shared **LuxAI account** of LuxOS – you sign in once in the system and LuxAI, Lux Code
and LSL IDE reuse it. See [LuxAI account](luxai-account.html). The app talks to `https://lux-ai.cz`
with your session and offers two models, **Flash** and **Lite** (the cheapest one, also used for
conversation titles). Monthly usage is shown at the bottom of the sidebar. If you are not signed in,
or the session expired, LuxAI offers **Sign in with LuxAI account**, which runs
`luxos-account login`. The token is read from `~/.config/luxai/account.json`; LuxAI never writes it
and never prints it.

## Privacy and your data

- Conversations are stored locally in `~/.local/share/luxai/conversations/` (files `0600`), images in
  `~/.local/share/luxai/images/`, settings in `~/.config/luxai/settings.json`, screenshots in
  `~/.cache/luxai/screenshots/`.
- **Settings › Privacy and history** lets you turn history off, delete all conversations and delete
  screenshots.
- Messages (and, in Agent mode, the tool results the model needs) are sent to the LuxAI service to
  produce an answer. Images are sent only to models that can see images.
- The tool `send_feedback` sends a bug report or idea to the LuxOS author **only after you
  confirm**: you first see the full text, the account (or anonymous) and the anonymised system data.
  User names, host names, e-mails, IP/MAC addresses and tokens are anonymised.

## Settings

Open **Settings** with Ctrl+, or the ⋮ menu: theme (system, light, dark), Enter or Ctrl+Enter to
send, notifications, default model, answer style (balanced, short, detailed, technical, friendly),
answer length, language, custom instructions, automatic conversation titles, agent permissions and
privacy. Keyboard: Enter send, Esc stop, Ctrl+N new conversation, Ctrl+F search, Ctrl+, settings,
Ctrl+Q quit.

LuxAI is translated into 13 languages and follows the system language of LuxOS.

## See also

- [LuxAI account](luxai-account.html) – signing in and the `luxos-account` command
- [Lux Code](lux-code.html) – the same assistant in the terminal, for programming
- [Guide for AI assistants on LuxOS](for-ai-assistants.html) – how an assistant should do admin tasks safely
- [LuxOS Apps](apps.html)
