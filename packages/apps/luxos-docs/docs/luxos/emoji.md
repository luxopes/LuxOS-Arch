# Emoji & Symbols

Typing emoji works like on Windows (`Win+.`) and macOS (`Ctrl+Cmd+Space`): press **`Super+.`** or
**`Ctrl+Super+Space`** in any app (or open **Emoji & Symbols** from Launchpad or Search) and a small
panel opens next to the mouse pointer.

- **Search** is focused right away. It finds emoji by name and keywords in the **system language**
  and in **English** (Unicode CLDR annotations for all 12 LuxOS languages), with or without
  diacritics and capitals: `srdce`, `usmev` / `úsměv`, `palec`, `smich`, `heart`, `thumbs up`,
  `vlajka cesko`. Best matches first: the exact name, then names starting with the text, then
  whole words of the name, then keywords; recently and frequently used emoji rank a little higher.
- **Tabs**: Recently Used (Frequently Used until you pick something), Smileys, People, Animals &
  Nature, Food & Drink, Activities, Travel & Places, Objects, Symbols, Flags. The grid scrolls with
  the wheel or touchpad; the tab of the visible section lights up.
- **Keys**: arrows move in the grid (Left/Right move the text cursor until you use Up/Down, or when
  the search is empty), Page Up/Down, **Tab** / Shift+Tab next/previous category, **Enter** or click
  inserts the emoji and closes the panel, **Shift+Enter** or Shift+click inserts it and keeps the
  panel open (for several emoji in a row), **Esc** closes. The same shortcut again also closes it.
- **Skin tone**: the six hands at the bottom right choose the tone for emoji that support it (people,
  hands). The choice is remembered. The bottom left shows the name of the selected or hovered emoji.
- **Inserting**: the panel remembers the window you were typing in. After you choose, LuxOS puts
  the emoji on the clipboard, switches back to that window and presses `Ctrl+V` (in terminals
  `Ctrl+Shift+V`, in xterm/rxvt `Shift+Insert`). About a second later the previous clipboard content
  (text or image) comes back, unless something else was copied in the meantime. If inserting is not
  possible (no window had focus, the window closed), the emoji stays on the clipboard and a
  notification says to paste it with `Ctrl+V`.
- Settings: `~/.config/luxos/emoji.conf` (`tone=0-5`, `recent=` up to 27 emoji).
- Command line: `luxos-emoji` (open/close), `luxos-emoji --search TEXT`, `luxos-emoji --close`.
- It is fast because the panel lives in `luxos-hub` with its data already loaded (it opens in a few
  milliseconds). Without `luxos-hub` the same panel starts as its own short-lived process
  (`/usr/lib/luxos/luxos-emoji-ui`, about 150 ms). The data (`/usr/share/luxos/emoji`) comes from
  Unicode Emoji 17.0 and CLDR 49 and is generated when the package is built. Nothing is downloaded
  while it runs. Emoji are drawn with Noto Color Emoji.
- Limits: the clipboard is restored only for text and images. Other clipboard content, such as files
  copied in Files, is replaced by the emoji. The panel opens at the mouse pointer, not at the text
  cursor (X11 has no general way to find the text cursor).

## See also

- [keyboard.md](keyboard.md): all keyboard shortcuts.
- [desktop.md](desktop.md#session-startup-and-luxos-hub): luxos-hub, which keeps the panel preloaded.
