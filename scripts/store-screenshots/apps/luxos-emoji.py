"""Emoji a symboly: panel u ukazatele mysi nad psanym textem (Textovy editor) - hledani a skupina Smajliku.

Panel je samostatny proces luxos-emoji-ui (bez luxos-hub) prelozeny z LSL ze zdroju (jako PKGBUILD).
Data emoji: LUXOS_EMOJI_DATA = /usr/share/luxos/emoji (verejna data Unicode/CLDR z balicku luxos-desktop;
generuji se jen pri sestaveni balicku ze stazenych zdroju, ve zdrojich nejsou). Nic se nevklada
(zadny Enter ani klik do mrizky); notify-send je falesny. Snima se okno editoru, panel lezi v nem.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = "/usr/share/luxos/emoji"

LETTER = """Hi Anna,

thank you so much for the lovely dinner on Saturday! The lemon cake was
amazing and the kids still talk about the garden games.

Next time we are cooking - how about Friday? Bring the whole family.

Happy birthday once again and see you soon """


def text_editor(s):
    spec = importlib.util.spec_from_file_location("_shots_luxos_text_b", os.path.join(HERE, "luxos-text.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build(s)


def shots(s):
    if not os.path.isfile(os.path.join(DATA, "emoji.tsv")):
        raise RuntimeError("emoji data missing: " + DATA + " (package luxos-desktop)")
    ui = s.lslc("luxos-desktop/files/lsl/luxos-emoji-ui.lsl")
    ed = text_editor(s)
    fake = os.path.join(s.tmp, "fakebin")
    os.makedirs(fake, exist_ok=True)
    with open(os.path.join(fake, "notify-send"), "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(fake, "notify-send"), 0o755)
    s.write(".config/luxos/emoji.conf", "# LuxOS Emoji & Symbols\ntone=0\n"
            "recent=🎂 🎉 😍 👍 ❤️ 😂 🍋 🌸 ☀️ 🥳 🙏 😊\n")
    note = s.write("Documents/Thank you.txt", LETTER)
    p = s.launch([ed, note], env={"LUXOS_TEXT_NEW_PROCESS": "1", "LUXOS_TEXT_DATA_DIR": s.src("luxos-text/files"),
                                  "LUXOS_TEXT_ICON": s.src("luxos-branding/files/icons/luxos-notes.png")})
    win = s.window(pid=p.pid, size=(1040, 780))
    s.sleep(1.0)
    s.key("ctrl+End", win)
    env = {"PATH": fake + ":" + s.env.get("PATH", "/usr/bin:/bin"), "LUXOS_EMOJI_DATA": DATA,
           "LUXOS_EMOJI_UI": ui}

    def open_panel(x, y):
        # panel se otevre u ukazatele mysi (souradnice v okne editoru)
        s.xdo("mousemove", "--window", win, x, y)
        s.sleep(0.3)
        e = s.launch([ui], env=env)
        s.sleep(1.5)
        return e

    # 1: hledani "party" (hledani je hned aktivni)
    e = open_panel(430, 236)
    s.type("party", delay=1.0)
    s.capture("1", win)
    s.key("Escape", delay=0.8)
    if e.poll() is None:
        e.wait(5)

    # 2: skupina Smajliku a vyber odstinu pleti dole
    open_panel(430, 236)
    s.key("Tab", delay=0.8)
    s.capture("2", win)
    s.key("Escape", delay=0.5)
