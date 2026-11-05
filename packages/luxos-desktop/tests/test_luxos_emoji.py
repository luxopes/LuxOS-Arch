"""Testy Emoji a symbolu v LSL (files/lsl/luxos_emoji*.lsl, luxos-emoji.lsl, luxos-emoji-ui.lsl, luxos-emoji-data.lsl).

Cista logika (skladani bez diakritiky, razeni hledani, naposledy pouzite, odstiny pleti, prepinace, protokol)
pres testovaci program tests/lsl/luxos-emoji-test.lsl nad daty vygenerovanymi generatorem z maleho vzorku
emoji-test.txt a anotaci CLDR (presne ocekavane poradi). S plnymi zdroji (LUXOS_EMOJI_SRC = adresar
s emoji-test.txt a rozbalenymi balicky cldr-annotations-full a cldr-annotations-derived-full jako
x1/package a x2/package) navic cela data: cesky "srdce", "usmev", "palec", rychlost a pokryti pismem.

Pod Xvfb (GUI cast) okno vyberu: otevreni prikazem zkratky, "srdce" + Enter vlozi emoji do GtkEntry,
zastupneho Firefoxu, zastupneho terminalu (Ctrl+Shift+V), zastupneho xterm (Shift+Insert z PRIMARY)
a do skutecneho luxos-terminal; vraceni puvodni schranky, Shift+Enter, Esc, sipky, odstin, bez ciloveho
okna jen schranka + upozorneni, se spravcem oken xfwm4 (ikony okna 16-256 px), cas otevreni.

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_emoji.py -v
GUI cast:  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" dbus-run-session \\
               python3 -m unittest packages/luxos-desktop/tests/test_luxos_emoji.py -v
LUXOS_LSLC: prekladac lslc (jinak se testy preskoci). LUXOS_EMOJI_SHOTS: adresar pro snimky okna
(svetly/tmavy). GUI nikdy na skutecne obrazovce (jen xvfb-run, nebo vyslovne LUXOS_TEST_X=1 ve VM).
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
TARGET = os.path.join(HERE, "emoji", "target.py")
TMP = tempfile.mkdtemp(prefix="luxos-emoji-test-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SRC = os.environ.get("LUXOS_EMOJI_SRC", "")
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) and (
    "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")
LANGS = ["cs", "sk", "de", "fr", "es", "it", "pl", "pt", "nl", "sv", "hu", "uk"]

# ---- maly vzorek dat (struktura jako skutecne soubory) ----------------------------------------------------

EMOJI_TEST = """# emoji-test.txt
# Version: 17.0

# group: Smileys & Emotion
# subgroup: face-smiling
1F600                                      ; fully-qualified     # 😀 E1.0 grinning face
1F604                                      ; fully-qualified     # 😄 E0.6 grinning face with smiling eyes
1F602                                      ; fully-qualified     # 😂 E0.6 face with tears of joy
263A FE0F                                  ; fully-qualified     # ☺️ E0.6 smiling face
263A                                       ; unqualified         # ☺ E0.6 smiling face
# subgroup: heart
2764 FE0F                                  ; fully-qualified     # ❤️ E0.6 red heart
2764                                       ; unqualified         # ❤ E0.6 red heart
1F498                                      ; fully-qualified     # 💘 E0.6 heart with arrow
1F49D                                      ; fully-qualified     # 💝 E0.6 heart with ribbon

# group: People & Body
1F44B                                      ; fully-qualified     # 👋 E0.6 waving hand
1F44B 1F3FB                                ; fully-qualified     # 👋🏻 E1.0 waving hand: light skin tone
1F44B 1F3FC                                ; fully-qualified     # 👋🏼 E1.0 waving hand: medium-light skin tone
1F44B 1F3FD                                ; fully-qualified     # 👋🏽 E1.0 waving hand: medium skin tone
1F44B 1F3FE                                ; fully-qualified     # 👋🏾 E1.0 waving hand: medium-dark skin tone
1F44B 1F3FF                                ; fully-qualified     # 👋🏿 E1.0 waving hand: dark skin tone
1F44D                                      ; fully-qualified     # 👍 E0.6 thumbs up
1F44D 1F3FB                                ; fully-qualified     # 👍🏻 E1.0 thumbs up: light skin tone
1F44D 1F3FC                                ; fully-qualified     # 👍🏼 E1.0 thumbs up: medium-light skin tone
1F44D 1F3FD                                ; fully-qualified     # 👍🏽 E1.0 thumbs up: medium skin tone
1F44D 1F3FE                                ; fully-qualified     # 👍🏾 E1.0 thumbs up: medium-dark skin tone
1F44D 1F3FF                                ; fully-qualified     # 👍🏿 E1.0 thumbs up: dark skin tone
1F9D1 200D 1F91D 200D 1F9D1                ; fully-qualified     # 🧑‍🤝‍🧑 E12.0 people holding hands
1F9D1 1F3FB 200D 1F91D 200D 1F9D1 1F3FB    ; fully-qualified     # 🧑🏻‍🤝‍🧑🏻 E12.0 people holding hands: light skin tone
1F9D1 1F3FB 200D 1F91D 200D 1F9D1 1F3FC    ; fully-qualified     # 🧑🏻‍🤝‍🧑🏼 E12.1 people holding hands: light skin tone, medium-light skin tone
1F9D1 1F3FC 200D 1F91D 200D 1F9D1 1F3FC    ; fully-qualified     # 🧑🏼‍🤝‍🧑🏼 E12.0 people holding hands: medium-light skin tone
1F9D1 1F3FD 200D 1F91D 200D 1F9D1 1F3FD    ; fully-qualified     # 🧑🏽‍🤝‍🧑🏽 E12.0 people holding hands: medium skin tone
1F9D1 1F3FE 200D 1F91D 200D 1F9D1 1F3FE    ; fully-qualified     # 🧑🏾‍🤝‍🧑🏾 E12.0 people holding hands: medium-dark skin tone
1F9D1 1F3FF 200D 1F91D 200D 1F9D1 1F3FF    ; fully-qualified     # 🧑🏿‍🤝‍🧑🏿 E12.0 people holding hands: dark skin tone
261D FE0F                                  ; fully-qualified     # ☝️ E0.6 index pointing up
261D 1F3FB                                 ; fully-qualified     # ☝🏻 E1.0 index pointing up: light skin tone
261D 1F3FC                                 ; fully-qualified     # ☝🏼 E1.0 index pointing up: medium-light skin tone

# group: Component
1F3FB                                      ; component           # 🏻 E1.0 light skin tone
1F3FC                                      ; component           # 🏼 E1.0 medium-light skin tone
1F3FD                                      ; component           # 🏽 E1.0 medium skin tone
1F3FE                                      ; component           # 🏾 E1.0 medium-dark skin tone
1F3FF                                      ; component           # 🏿 E1.0 dark skin tone
1F9B0                                      ; component           # 🦰 E11.0 red hair

# group: Animals & Nature
1F415                                      ; fully-qualified     # 🐕 E0.7 dog

# group: Food & Drink
1F355                                      ; fully-qualified     # 🍕 E0.6 pizza

# group: Travel & Places
1F697                                      ; fully-qualified     # 🚗 E0.6 automobile

# group: Activities
26BD                                       ; fully-qualified     # ⚽ E0.6 soccer ball

# group: Objects
1F4A1                                      ; fully-qualified     # 💡 E0.6 light bulb

# group: Symbols
2665 FE0F                                  ; fully-qualified     # ♥️ E0.6 heart suit
0023 FE0F 20E3                             ; fully-qualified     # #️⃣ E0.6 keycap: #

# group: Flags
1F1E8 1F1FF                                ; fully-qualified     # 🇨🇿 E2.0 flag: Czechia

#EOF
"""


def ann(name, *keywords):
    return {"default": list(keywords), "tts": [name]}


CLDR = {
    "en": {
        "😀": ann("grinning face", "face", "grin", "smile"), "😄": ann("grinning face with smiling eyes", "face", "smile"),
        "😂": ann("face with tears of joy", "laugh", "tears", "joy"), "☺": ann("smiling face", "face", "smile", "relaxed"),
        "❤": ann("red heart", "heart", "love"), "💘": ann("heart with arrow", "cupid", "heart"),
        "💝": ann("heart with ribbon", "valentine", "heart"), "👋": ann("waving hand", "hand", "wave", "hello"),
        "👍": ann("thumbs up", "+1", "hand", "like", "yes"), "☝": ann("index pointing up", "finger", "point"),
        "🐕": ann("dog", "pet"), "🍕": ann("pizza", "cheese", "slice"), "🚗": ann("automobile", "car"),
        "⚽": ann("soccer ball", "ball", "football"), "💡": ann("light bulb", "idea", "electric"),
        "♥": ann("heart suit", "card", "game"), "🏻": ann("light skin tone", "skin tone"),
        "🏼": ann("medium-light skin tone", "skin tone"), "🏽": ann("medium skin tone", "skin tone"),
        "🏾": ann("medium-dark skin tone", "skin tone"), "🏿": ann("dark skin tone", "skin tone"),
    },
    "cs": {
        "😀": ann("zubící se obličej", "obličej", "smích", "úsměv"), "😄": ann("smějící se obličej", "obličej", "veselý"),
        "😂": ann("obličej se slzami smíchu", "smích", "slzy"), "☺": ann("usmívající se obličej", "úsměv", "pohoda"),
        "❤": ann("rudé srdce", "láska", "srdce"), "💘": ann("srdce se šípem", "amor", "srdce"),
        "💝": ann("srdce s mašlí", "valentýn", "srdce"), "👋": ann("mávající ruka", "ahoj", "ruka"),
        "👍": ann("palec nahoru", "palec", "souhlas", "like"), "☝": ann("ukazováček nahoru", "prst"),
        "🐕": ann("pes", "mazlíček"), "🍕": ann("pizza", "sýr"), "🚗": ann("auto", "automobil"),
        "⚽": ann("fotbalový míč", "míč", "fotbal"), "💡": ann("žárovka", "nápad"),
        "♥": ann("srdce", "karta", "hra"), "🏻": ann("světlý odstín pleti", "pleť"),
        "🏼": ann("středně světlý odstín pleti", "pleť"), "🏽": ann("střední odstín pleti", "pleť"),
        "🏾": ann("středně tmavý odstín pleti", "pleť"), "🏿": ann("tmavý odstín pleti", "pleť"),
    },
    "uk": {
        "❤": ann("червоне серце", "кохання", "серце"), "🐕": ann("Собака", "пес", "Їжак"),
    },
}
DERIVED = {
    "en": {"🧑‍🤝‍🧑": ann("people holding hands", "couple", "hand", "hold"), "🇨🇿": ann("flag: Czechia", "flag"),
           "#️⃣": ann("keycap: #", "keycap")},
    "cs": {"🧑‍🤝‍🧑": ann("lidé držící se za ruce", "pár", "ruka"), "🇨🇿": ann("vlajka: Česko", "vlajka")},
    "uk": {},
}


def write_cldr(root):
    for kind, table, top in (("ann", CLDR, "annotations"), ("der", DERIVED, "annotationsDerived")):
        for lang, entries in table.items():
            d = os.path.join(root, kind, lang)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "annotations.json"), "w", encoding="utf-8") as f:
                json.dump({top: {"identity": {"language": lang}, "annotations": entries}}, f, ensure_ascii=False)


def build():
    """Prelozi testovaci program, generator, klienta a samostatny proces; vygeneruje data vzorku."""
    if not LSLC:
        return None
    src = os.path.join(TMP, "src")
    os.makedirs(src, exist_ok=True)
    for f in glob.glob(os.path.join(LSL, "*.lsl")) + [os.path.join(HERE, "lsl", "luxos-emoji-test.lsl")]:
        shutil.copy(f, src)
    out = os.path.join(TMP, "bin")
    os.makedirs(out, exist_ok=True)
    for name in ("luxos-emoji-test", "luxos-emoji-data", "luxos-emoji", "luxos-emoji-ui"):
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, name + ".lsl"), os.path.join(out, name)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return None
    return out


BIN = build()
# ikona okna ze zdroju (motiv hicolor jako po instalaci baliku)
ICONS = os.path.join(TMP, "share")
os.makedirs(os.path.join(ICONS, "icons", "hicolor", "scalable", "apps"), exist_ok=True)
shutil.copy(os.path.join(FILES, "icons", "luxos-emoji.svg"), os.path.join(ICONS, "icons", "hicolor", "scalable", "apps"))
SAMPLE = os.path.join(TMP, "sample-data")
FULL = os.path.join(TMP, "full-data")
GEN_OUT = None


def generate_sample():
    root = os.path.join(TMP, "sample-src")
    write_cldr(root)
    with open(os.path.join(root, "emoji-test.txt"), "w", encoding="utf-8") as f:
        f.write(EMOJI_TEST)
    env = dict(os.environ, LUXOS_EMOJI_DATA_MIN="5")
    return subprocess.run([os.path.join(BIN, "luxos-emoji-data"), os.path.join(root, "emoji-test.txt"),
                           os.path.join(root, "ann"), os.path.join(root, "der"), SAMPLE, "cs", "uk"],
                          capture_output=True, text=True, env=env)


def generate_full():
    """Cela data ze skutecnych zdroju (LUXOS_EMOJI_SRC), jinak nainstalovana /usr/share/luxos/emoji."""
    if SRC and os.path.exists(os.path.join(SRC, "emoji-test.txt")):
        r = subprocess.run([os.path.join(BIN, "luxos-emoji-data"), os.path.join(SRC, "emoji-test.txt"),
                            os.path.join(SRC, "x1", "package", "annotations"),
                            os.path.join(SRC, "x2", "package", "annotationsDerived"), FULL, *LANGS],
                           capture_output=True, text=True)
        return FULL if r.returncode == 0 else None
    if os.path.exists("/usr/share/luxos/emoji/emoji.tsv"):
        return "/usr/share/luxos/emoji"
    return None


if BIN:
    GEN_OUT = generate_sample()
    FULL_DIR = generate_full()
else:
    FULL_DIR = None


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def call(fn, *args, data=None, **env_extra):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LUXOS_EMOJI_DATA": data or SAMPLE, "HOME": TMP}
    env.update(env_extra)
    r = subprocess.run([os.path.join(BIN, "luxos-emoji-test"), fn, *[str(a) for a in args]], capture_output=True,
                       text=True, env=env, timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stdout + r.stderr)
    return json.loads(r.stdout)


def read_tsv(name, data=None):
    with open(os.path.join(data or SAMPLE, name), encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if not line.startswith("# ") and line.strip()]


@unittest.skipUnless(BIN, "needs lslc (LSL >= 0.10.6)")
class DataGeneration(unittest.TestCase):
    def test_generator_output(self):
        self.assertEqual(GEN_OUT.returncode, 0, GEN_OUT.stderr)
        self.assertIn("emoji.tsv: 19 emoji, 3 with skin tones", GEN_OUT.stdout)
        rows = read_tsv("emoji.tsv")
        emojis = [r[0] for r in rows]
        # jen plne kvalifikovana, bez variant s odstinem; neuplne kvalifikovana (☺, ❤) vynechana
        self.assertEqual(emojis.count("☺️"), 1)
        self.assertNotIn("☺", emojis)
        self.assertNotIn("👋🏻", emojis)
        self.assertIn("#️⃣", emojis)                      # klavesa # neni komentar
        self.assertNotIn("🦰", emojis)                     # komponenta vlasu ne
        groups = {r[0]: int(r[1]) for r in rows}
        # poradi zalozek: Aktivity (4) pred Cestovanim (5), i kdyz je emoji-test.txt ma obracene
        self.assertLess(emojis.index("⚽"), emojis.index("🚗"))
        self.assertEqual((groups["⚽"], groups["🚗"], groups["🇨🇿"]), (4, 5, 8))
        self.assertEqual([r[0] for r in rows if r[1] == "-1"], ["🏻", "🏼", "🏽", "🏾", "🏿"])
        tones = {r[0]: r[2] for r in rows}
        self.assertEqual(tones["👋"].split(" "), ["👋🏻", "👋🏼", "👋🏽", "👋🏾", "👋🏿"])
        # skupina: jen stejny odstin u obou osob, smisene varianty ne
        self.assertEqual(tones["🧑‍🤝‍🧑"].split(" ")[0], "🧑🏻‍🤝‍🧑🏻")
        self.assertNotIn("🧑🏻‍🤝‍🧑🏼", tones["🧑‍🤝‍🧑"])
        # neuplna sada odstinu (jen 2 z 5) -> bez nabidky odstinu
        self.assertEqual(tones["☝️"], "")
        self.assertEqual(tones["😀"], "")

    def test_language_files(self):
        cs = {r[0]: r for r in read_tsv("cs.tsv")}
        # nazev CLDR (klic bez FE0F), sloupec pro hledani po fold(): nazev prvni, pak klicova slova
        self.assertEqual(cs["❤️"][1], "rudé srdce")
        self.assertEqual(cs["❤️"][3], "|rude srdce|laska|srdce|")
        self.assertEqual(cs["🇨🇿"][1], "vlajka: Česko")              # odvozene anotace (vlajky, ZWJ)
        self.assertNotIn("#️⃣", cs)                                    # cestina ho nema -> anglicky za behu
        en = {r[0]: r for r in read_tsv("en.tsv")}
        self.assertEqual(en["#️⃣"][1], "keycap: #")
        self.assertEqual(en["☝️"][1], "index pointing up")
        uk = {r[0]: r for r in read_tsv("uk.tsv")}
        self.assertEqual(uk["🐕"][3], "|собака|пес|іжак|")          # cyrilice malymi pismeny, Ї -> і

    def test_runtime_fallback_to_english(self):
        info = call("info", "cs", "#️⃣")
        self.assertEqual(info[:3], ["keycap: #", "keycap: #", 7])
        self.assertEqual(call("info", "cs", "👍")[:2], ["palec nahoru", "thumbs up"])
        summary = call("summary", "cs")
        self.assertEqual(summary["count"], 19)
        self.assertEqual(summary["groups"], [7, 4, 1, 1, 1, 1, 1, 2, 1])
        self.assertEqual(summary["toned"], 3)
        self.assertEqual(summary["tone_names"][2], "střední odstín pleti")

    def test_missing_data(self):
        empty = os.path.join(TMP, "empty-data")
        os.makedirs(empty, exist_ok=True)
        self.assertFalse(call("summary", "cs", data=empty)["ok"])
        self.assertEqual(call("search", "cs", "srdce", 5, data=empty), [])

    def test_truncated_source_rejected(self):
        bad = os.path.join(TMP, "bad-test.txt")
        with open(bad, "w") as f:
            f.write("# group: Smileys & Emotion\n1F600 ; fully-qualified # 😀 E1.0 grinning face\n")
        r = subprocess.run([os.path.join(BIN, "luxos-emoji-data"), bad, "x", "y", os.path.join(TMP, "bad-out"), "cs"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("too few emoji", r.stderr)


@unittest.skipUnless(BIN, "needs lslc (LSL >= 0.10.6)")
class Search(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(call("fold", "Úsměv"), "usmev")
        self.assertEqual(call("fold", "ŽLUŤOUČKÝ kůň"), "zlutoucky kun")
        self.assertEqual(call("fold", "Größe Œuvre"), "grosse oeuvre")
        self.assertEqual(call("fold", "Привіт Їжак Ґанок Йод"), "привіт іжак ганок иод")
        self.assertEqual(call("fold", "Łódź Ősz"), "lodz osz")
        self.assertEqual(call("words", "  Rudé   SRDCE "), ["rude", "srdce"])
        self.assertEqual(call("cap_first", "vlajka: Česko"), "Vlajka: Česko")
        self.assertEqual(call("cap_first", "червоне серце"), "Червоне серце")
        self.assertEqual(call("cap_first", "úsměv"), "Úsměv")

    def test_word_score_levels(self):
        kw = "|laska|srdce|"
        scores = [call("word_score", "rude srdce", "rude srdce", kw),     # presny nazev
                  call("word_score", "rud", "rude srdce", kw),            # zacatek nazvu
                  call("word_score", "srdce", "rude srdce", kw),          # cele slovo nazvu
                  call("word_score", "srd", "rude srdce", kw),            # zacatek slova nazvu
                  call("word_score", "laska", "rude", kw),                # presne klicove slovo
                  call("word_score", "las", "rude", kw),                  # zacatek klicoveho slova
                  call("word_score", "ask", "rude", kw),                  # podretezec
                  call("word_score", "x", "rude", kw)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(set(scores)), len(scores))
        self.assertEqual(scores[-1], 0)
        self.assertEqual(call("word_score", "a", "rude", "|kava|"), 0)   # jeden znak jen jako zacatek

    def test_ranking_exact_prefix_keyword(self):
        # bez posileni: presny nazev "srdce" (♥️) > zacatek nazvu (💘, 💝) > slovo nazvu (❤️ rudé srdce)
        self.assertEqual(call("search", "cs", "srdce", 10), ["♥️", "💘", "💝", "❤️"])
        # klicove slovo jen u ❤️
        self.assertEqual(call("search", "cs", "laska", 10), ["❤️"])
        # posileni casto pouzivanych: ❤️ pred "srdce se šípem", presny nazev porad prvni
        self.assertEqual(call("search", "cs", "srdce", 10, "[]")[:2], ["♥️", "❤️"])

    def test_diacritics_insensitive(self):
        self.assertEqual(call("search", "cs", "usmev", 10), call("search", "cs", "úsměv", 10))
        found = call("search", "cs", "usmev", 10)
        self.assertIn("😀", found)
        self.assertIn("☺️", found)
        self.assertEqual(call("search", "cs", "PALEC", 3), ["👍"])
        self.assertEqual(call("search", "cs", "smich", 3)[0], "😂")       # "smích" v nazvu i slovech
        self.assertEqual(call("search", "uk", "серце", 3)[0], "❤️")
        self.assertEqual(call("search", "uk", "ЇЖАК", 3), ["🐕"])

    def test_english_and_local(self):
        # anglicky nazev i v ceskem systemu, cesky v anglickem ne
        self.assertEqual(call("search", "cs", "thumbs up", 3), ["👍"])
        self.assertEqual(call("search", "cs", "dog", 3), ["🐕"])
        self.assertEqual(call("search", "en", "pes", 3), [])
        self.assertEqual(call("search", "en", "heart", 3, "[]")[0], "❤️")
        # vic slov: kazde musi sedet
        self.assertEqual(call("search", "cs", "vlajka cesko", 3), ["🇨🇿"])
        self.assertEqual(call("search", "cs", "vlajka nemecko", 3), [])
        self.assertEqual(call("search", "cs", "", 3), [])
        self.assertEqual(call("search", "cs", "   ", 3), [])

    def test_limit_and_recent_boost(self):
        self.assertEqual(len(call("search", "en", "face", 2)), 2)
        # naposledy pouzite o stupen vys: 💝 pred 💘
        self.assertEqual(call("search", "cs", "srdce", 10, '["💝"]')[:3], ["♥️", "💝", "❤️"])


@unittest.skipUnless(BIN, "needs lslc (LSL >= 0.10.6)")
class RecentTonesConfig(unittest.TestCase):
    def test_tones(self):
        self.assertEqual(call("with_tone", "👋", 3), "👋🏽")
        self.assertEqual(call("with_tone", "👋", 0), "👋")
        self.assertEqual(call("with_tone", "👋", 9), "👋")
        self.assertEqual(call("with_tone", "😀", 4), "😀")              # bez odstinu
        self.assertEqual(call("with_tone", "🧑‍🤝‍🧑", 5), "🧑🏿‍🤝‍🧑🏿")
        self.assertEqual(call("find_index", "👋🏾"), "👋")
        self.assertEqual(call("find_index", "❤"), "❤️")                  # bez FE0F
        self.assertIsNone(call("find_index", "🦄"))
        self.assertEqual(call("strip_tone", "🧑🏻‍🤝‍🧑🏼"), "🧑‍🤝‍🧑")

    def test_add_recent(self):
        r = call("add_recent", "[]", "😀")
        self.assertEqual(r, ["😀"])
        r = call("add_recent", json.dumps(["😀", "❤️"]), "❤️")
        self.assertEqual(r, ["❤️", "😀"])
        r = call("add_recent", json.dumps(["😀"]), "👋🏽")               # ulozi se bez odstinu
        self.assertEqual(r, ["👋", "😀"])
        many = [chr(0x1F600 + i) for i in range(27)]
        r = call("add_recent", json.dumps(many), "❤️")
        self.assertEqual(len(r), 27)
        self.assertEqual(r[0], "❤️")
        self.assertEqual(r[-1], many[25])

    def test_config_roundtrip(self):
        path = os.path.join(TMP, "cfg", "luxos", "emoji.conf")
        self.assertEqual(call("load_config", path), {"tone": 0, "recent": []})
        self.assertTrue(call("save_config", path, json.dumps({"tone": 3, "recent": ["❤️", "#️⃣", "👋"]})))
        with open(path, encoding="utf-8") as f:
            self.assertIn("tone=3\nrecent=❤️ #️⃣ 👋\n", f.read())
        self.assertEqual(call("load_config", path), {"tone": 3, "recent": ["❤️", "#️⃣", "👋"]})
        self.assertFalse(os.path.exists(path + ".tmp"))
        with open(path, "w") as f:
            f.write("tone=17\nrecent=😀  😀 ❤️\ngarbage\n")
        self.assertEqual(call("load_config", path), {"tone": 0, "recent": ["😀", "❤️"]})

    def test_recent_list(self):
        path = os.path.join(TMP, "recent.conf")
        # bez historie casto pouzivane (jen ta, ktera data maji)
        self.assertEqual(call("recent", path), ["😀", "😂", "❤️", "👍"])
        with open(path, "w") as f:
            f.write("recent=🦄 👋 ♥️\n")
        self.assertEqual(call("recent", path), ["👋", "♥️"])            # nezname vynechane

    def test_paste_method(self):
        self.assertEqual(call("paste_method", "luxos-terminal", "Luxos-terminal"), "ctrl-shift-v")
        self.assertEqual(call("paste_method", "gnome-terminal-server", "Gnome-terminal"), "ctrl-shift-v")
        self.assertEqual(call("paste_method", "kitty", "kitty"), "ctrl-shift-v")
        self.assertEqual(call("paste_method", "xterm", "XTerm"), "shift-insert")
        self.assertEqual(call("paste_method", "urxvt", "URxvt"), "shift-insert")
        self.assertEqual(call("paste_method", "Navigator", "firefox"), "ctrl-v")
        self.assertEqual(call("paste_method", "", ""), "ctrl-v")

    def test_args_and_protocol(self):
        self.assertEqual(call("parse_args"), {"action": "toggle", "search": None, "help": False})
        self.assertEqual(call("parse_args", "--search", "srdce")["search"], "srdce")
        self.assertEqual(call("parse_args", "--search=palec")["action"], "open")
        self.assertEqual(call("parse_args", "--close")["action"], "close")
        self.assertIn("error", call("parse_args", "--bogus"))
        self.assertIn("error", call("parse_args", "--search"))
        self.assertEqual(call("canonical_args", "--search", "a b"), ["--search", "a b"])
        self.assertEqual(call("request_roundtrip", "--search", "rudé srdce"), ["--search", "rudé srdce"])
        self.assertEqual(call("lang", LANG="cs_CZ.UTF-8"), "cs")
        self.assertEqual(call("lang", LANG="pt_BR.UTF-8", LC_ALL="uk_UA"), "uk")
        self.assertEqual(call("lang", LANG="C"), "en")

    def test_client_help_and_errors(self):
        env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": os.path.join(TMP, "norun")}
        r = subprocess.run([os.path.join(BIN, "luxos-emoji"), "--help"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Super+.", r.stdout)
        r = subprocess.run([os.path.join(BIN, "luxos-emoji"), "--nope"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        # --close bez bezici instance nic nespousti
        r = subprocess.run([os.path.join(BIN, "luxos-emoji"), "--close"], capture_output=True, text=True,
                           env=dict(env, LUXOS_EMOJI_UI="/nonexistent"))
        self.assertEqual(r.returncode, 0)


@unittest.skipUnless(BIN and FULL_DIR, "needs full data (LUXOS_EMOJI_SRC or installed /usr/share/luxos/emoji)")
class FullData(unittest.TestCase):
    def test_counts_and_languages(self):
        s = call("summary", "cs", data=FULL_DIR)
        self.assertGreater(s["count"], 1850)
        self.assertGreater(s["toned"], 300)
        self.assertTrue(all(n > 0 for n in s["groups"]), s)
        for lang in LANGS:
            rows = read_tsv(lang + ".tsv", FULL_DIR)
            self.assertGreater(len(rows), 1850, lang)

    def test_czech_queries(self):
        self.assertIn("❤️", call("search", "cs", "srdce", 3, "[]", data=FULL_DIR))
        self.assertEqual(call("search", "cs", "palec", 1, "[]", data=FULL_DIR), ["👍"])
        self.assertIn("😂", call("search", "cs", "smich", 3, "[]", data=FULL_DIR))
        usmev = call("search", "cs", "usmev", 10, "[]", data=FULL_DIR)
        self.assertEqual(usmev, call("search", "cs", "úsměv", 10, "[]", data=FULL_DIR))
        self.assertIn("😊", usmev)
        self.assertEqual(call("search", "cs", "vlajka cesko", 1, data=FULL_DIR), ["🇨🇿"])
        self.assertEqual(call("search", "de", "daumen hoch", 1, data=FULL_DIR), ["👍"])
        self.assertEqual(call("search", "uk", "серце", 3, "[]", data=FULL_DIR)[1], "❤️")

    def test_search_speed(self):
        load_ms, worst_ms, count = call("search_time", "cs", "srdce", "usmev", "thumbs up", "a", "vlajka", data=FULL_DIR)
        print("\nemoji data load %.1f ms, slowest query %.1f ms per keystroke (%d emoji)" % (load_ms, worst_ms, count))
        self.assertLess(worst_ms, 30)
        self.assertLess(load_ms, 400)

    @unittest.skipUnless(shutil.which("fc-query") and os.path.exists("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
                         "needs noto-fonts-emoji")
    def test_font_covers_single_codepoints(self):
        out = subprocess.run(["fc-query", "--format=%{charset}", "/usr/share/fonts/noto/NotoColorEmoji.ttf"],
                             capture_output=True, text=True).stdout
        ranges = []
        for part in out.split():
            a, _, b = part.partition("-")
            ranges.append((int(a, 16), int(b or a, 16)))
        missing = []
        for row in read_tsv("emoji.tsv", FULL_DIR):
            cps = [ord(c) for c in row[0] if ord(c) != 0xFE0F]
            if len(cps) == 1 and not any(a <= cps[0] <= b for a, b in ranges):
                missing.append(row[0])
        self.assertEqual(missing, [])


class Translations(unittest.TestCase):
    def test_strings_in_all_languages(self):
        import re
        with open(os.path.join(LSL, "luxos_emoji.lsl"), encoding="utf-8") as f:
            src = f.read()
        keys = set(re.findall(r'\bT\("((?:[^"\\]|\\.)*)"\)', src))
        with open(os.path.join(LSL, "luxos_emoji_base.lsl"), encoding="utf-8") as f:
            base = f.read()
        groups = re.search(r'^GROUPS = \[(.*)\]$', base, re.M).group(1)
        keys |= set(re.findall(r'"([^"]+)"', groups))
        self.assertGreaterEqual(len(keys), 17)
        for lang in LANGS:
            with open(os.path.join(I18N, lang + ".tsv"), encoding="utf-8") as f:
                table = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            missing = sorted(k for k in keys if not table.get(k, "").strip())
            self.assertEqual(missing, [], lang)

    def test_desktop_entry(self):
        with open(os.path.join(FILES, "applications", "luxos-emoji.desktop"), encoding="utf-8") as f:
            text = f.read()
        for lang in LANGS:
            self.assertIn("Name[%s]=" % lang, text)
            self.assertIn("Comment[%s]=" % lang, text)
        self.assertIn("Exec=luxos-emoji\n", text)
        self.assertIn("Icon=luxos-emoji\n", text)
        self.assertTrue(os.path.exists(os.path.join(FILES, "icons", "luxos-emoji.svg")))

    def test_default_shortcuts(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(FILES, "xdg", "xfce4", "xfconf", "xfce-perchannel-xml",
                                     "xfce4-keyboard-shortcuts.xml")).getroot()
        custom = {}
        for section in root.iter("property"):
            if section.get("name") == "custom":
                for p in section.findall("property"):
                    custom.setdefault(p.get("name"), []).append(p.get("value"))
        self.assertEqual(custom.get("<Super>period"), ["luxos-emoji"])
        self.assertEqual(custom.get("<Primary><Super>space"), ["luxos-emoji"])
        self.assertEqual(custom.get("<Super>space"), ["luxos-search"])          # Hledani zustava
        # zadna zkratka neni prirazena dvakrat (ani v sekci xfwm4)
        for k, v in custom.items():
            if k != "override":
                self.assertEqual(len(v), 1, k)


class SessionMigration(unittest.TestCase):
    """Jednorazove pridani zkratek starsim profilum (blok z luxos-session s falesnym xfconf-query)."""

    def run_block(self, user, home):
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("# Emoji a symboly i u profilu")
        end = src.index("\n# Terminal LuxOS misto", start)
        fake = os.path.join(home, "bin")
        os.makedirs(fake, exist_ok=True)
        shutil.copy(os.path.join(HERE, "fake-shortcuts", "xfconf-query"), fake)
        with open(os.path.join(fake, "luxos-emoji"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(fake, "luxos-emoji"), 0o755)
        state = os.path.join(home, "xfconf.json")
        with open(state, "w") as f:
            json.dump(user, f)
        cfg = os.path.join(home, "cfg")
        os.makedirs(cfg, exist_ok=True)
        script = "cfg=%s\n%s\n" % (cfg, src[start:end])
        env = {"PATH": fake + ":/usr/bin:/bin", "FAKE_XFCONF": state, "HOME": home}
        r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(state) as f:
            return json.load(f), os.path.exists(os.path.join(cfg, "emoji-shortcuts"))

    def test_adds_free_shortcuts_once(self):
        home = tempfile.mkdtemp(dir=TMP)
        user = {"/commands/custom/<Super>period": "firefox", "/commands/custom/<Super>space": "luxos-search"}
        data, marker = self.run_block(user, home)
        self.assertTrue(marker)
        self.assertEqual(data["/commands/custom/<Super>period"], "firefox")      # vlastni prirazeni zustava
        self.assertEqual(data["/commands/custom/<Primary><Super>space"], "luxos-emoji")
        # podruhe (znacka existuje) uz nic - ani kdyz si uzivatel zkratku odebral
        del data["/commands/custom/<Primary><Super>space"]
        with open(os.path.join(home, "xfconf.json"), "w") as f:
            json.dump(data, f)
        data2, _ = self.run_block(data, home)
        self.assertNotIn("/commands/custom/<Primary><Super>space", data2)


# ---- GUI pod Xvfb --------------------------------------------------------------------------------------------

SHOT = ("import sys, gi\ngi.require_version('Gdk', '3.0')\nfrom gi.repository import Gdk\n"
        "r = Gdk.get_default_root_window()\n"
        "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])\n")

# Vlastnik schranky s puvodnim textem (overeni vraceni) a cteni schranky
CLIP_OWNER = ("import sys, gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk, Gdk, GLib\n"
              "c = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)\nc.set_text(sys.argv[1], -1)\n"
              "open(sys.argv[2], 'w').write('ok')\nGtk.main()\n")
CLIP_READ = ("import sys, gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk, Gdk\n"
             "sel = Gdk.SELECTION_PRIMARY if sys.argv[1:] == ['primary'] else Gdk.SELECTION_CLIPBOARD\n"
             "print(Gtk.Clipboard.get(sel).wait_for_text() or '', end='')\n")


@unittest.skipUnless(BIN and HAVE_DISPLAY, "needs lslc and Xvfb (xvfb-run)")
class Gui(unittest.TestCase):
    wm = False

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        self.run_dir = os.path.join(self.home, "run")
        os.makedirs(self.run_dir, mode=0o700)
        os.chmod(self.run_dir, 0o700)
        os.makedirs(os.path.join(self.home, ".config", "luxos"))
        self.fake = os.path.join(self.home, "fakebin")
        os.makedirs(self.fake)
        with open(os.path.join(self.fake, "notify-send"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\n' % os.path.join(self.home, "notify.log"))
        os.chmod(os.path.join(self.fake, "notify-send"), 0o755)
        self.log = os.path.join(self.home, "emoji.log")
        self.procs = []
        if self.wm:
            self.start_wm()

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(3)

    def env(self, **extra):
        env = {"PATH": self.fake + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home,
               "XDG_CONFIG_HOME": os.path.join(self.home, ".config"), "XDG_RUNTIME_DIR": self.run_dir,
               "XDG_CACHE_HOME": os.path.join(self.home, ".cache"), "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
               "LANG": "cs_CZ.UTF-8", "LUXOS_I18N_DIR": I18N, "NO_AT_BRIDGE": "1", "GTK_USE_PORTAL": "0",
               "GIO_USE_VFS": "local", "GTK_THEME": "Adwaita", "LUXOS_EMOJI_DATA": FULL_DIR or SAMPLE,
               "LUXOS_EMOJI_UI": os.path.join(BIN, "luxos-emoji-ui"), "LUXOS_EMOJI_TEST_LOG": self.log,
               "DISPLAY": os.environ["DISPLAY"], "XDG_DATA_DIRS": ICONS + ":/usr/local/share:/usr/share"}
        for k in ("XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
            if k in os.environ:
                env[k] = os.environ[k]
        env.update(extra)
        return env

    def spawn(self, argv, **extra):
        p = subprocess.Popen(argv, env=self.env(**extra), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def start_wm(self):
        if not shutil.which("xfwm4"):
            self.skipTest("xfwm4 not installed")
        self.spawn(["xfwm4", "--compositor=on"])
        ok = self.wait_for(lambda: "_NET_SUPPORTING_WM_CHECK(WINDOW)" in subprocess.run(
            ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], capture_output=True, text=True, env=self.env()).stdout, 8)
        self.assertTrue(ok, "xfwm4 did not start")
        time.sleep(0.5)

    def wait_for(self, cond, timeout=6.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def events(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as f:
            return [line.rsplit(" @", 1)[0] for line in f.read().splitlines()]

    def event_time(self, name):
        with open(self.log, encoding="utf-8") as f:
            for line in f:
                if line.rsplit(" @", 1)[0] == name:
                    return float(line.rsplit(" @", 1)[1])
        return None

    def xdo(self, *args):
        subprocess.run(["xdotool", *args], env=self.env(), check=True, timeout=20)

    def target(self, klass, paste_keys=None):
        out = os.path.join(self.home, "target-" + klass)
        argv = ["python3", TARGET, klass, out]
        if paste_keys:
            argv += ["--paste-keys", paste_keys]
        self.spawn(argv)
        self.assertTrue(self.wait_for(lambda: os.path.exists(out + ".ready"), 10), "target did not start")
        with open(out + ".ready") as f:
            xid = f.read().split()[1]
        self.focus(xid)
        return out

    def focus(self, xid):
        if self.wm:
            self.xdo("windowactivate", "--sync", xid)
        else:
            self.xdo("windowfocus", "--sync", xid)
        time.sleep(0.2)

    def read(self, path):
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def clipboard(self, which="clipboard"):
        return subprocess.run(["python3", "-c", CLIP_READ, which], capture_output=True, text=True, env=self.env(),
                              timeout=10).stdout

    def own_clipboard(self, value):
        flag = os.path.join(self.home, "clip-ready")
        self.spawn(["python3", "-c", CLIP_OWNER, value, flag])
        self.assertTrue(self.wait_for(lambda: os.path.exists(flag), 10))

    def open_picker(self, *args, **extra):
        start = time.monotonic()
        self.spawn([os.path.join(BIN, "luxos-emoji"), *args], **extra)
        self.assertTrue(self.wait_for(lambda: "shown" in self.events(), 10), (self.events(), self.procs[-1].stderr))
        self.assertTrue(self.wait_for(lambda: "drawn" in self.events(), 5), self.events())
        return start

    def type_and_enter(self, text, key="Return"):
        self.xdo("type", "--delay", "30", text)
        time.sleep(0.3)
        self.xdo("key", key)

    def shot(self, name):
        d = os.environ.get("LUXOS_EMOJI_SHOTS")
        if d:
            os.makedirs(d, exist_ok=True)
            subprocess.run(["python3", "-c", SHOT, os.path.join(d, name)], env=self.env(), timeout=20)

    # ---- testy ---------------------------------------------------------------------------------------------
    def test_insert_into_gtk_entry_and_restore_clipboard(self):
        self.own_clipboard("puvodni obsah")
        out = self.target("LuxosTestEntry")
        self.open_picker()
        self.type_and_enter("srdce")
        self.assertTrue(self.wait_for(lambda: self.read(out) != "", 6), (self.events(), self.read(out)))
        heart = self.read(out)
        self.assertIn(heart, ("♥️", "❤️"))
        self.assertIn("pasted ctrl-v", self.events())
        self.assertIn("hidden", self.events())
        # po ~1 s puvodni obsah schranky zpet
        self.assertTrue(self.wait_for(lambda: "restored text" in self.events(), 4), self.events())
        self.assertEqual(self.clipboard(), "puvodni obsah")
        with open(os.path.join(self.home, ".config", "luxos", "emoji.conf"), encoding="utf-8") as f:
            self.assertIn("recent=" + heart, f.read())

    def test_firefox_like_target(self):
        out = self.target("Navigator")
        self.open_picker("--search", "palec")
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) == "👍", 6), (self.events(), self.read(out)))
        self.assertIn("target", " ".join(self.events()))
        self.assertTrue(any(e.startswith("target ") and "navigator/Navigator" in e for e in self.events()), self.events())

    def test_terminal_gets_ctrl_shift_v(self):
        out = self.target("Luxos-terminal", paste_keys="ctrl-shift-v")
        self.open_picker()
        self.type_and_enter("srdce")
        self.assertTrue(self.wait_for(lambda: self.read(out) != "", 6), self.events())
        self.assertIn("pasted ctrl-shift-v", self.events())
        self.assertEqual(self.read(out + ".wrong"), "")

    def test_xterm_gets_shift_insert_from_primary(self):
        out = self.target("XTerm", paste_keys="shift-insert")
        self.open_picker("--search", "palec")
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) == "👍", 6), self.events())
        self.assertIn("pasted shift-insert", self.events())
        self.assertEqual(self.read(out + ".wrong"), "")

    @unittest.skipUnless(shutil.which("luxos-terminal"), "luxos-terminal not installed")
    def test_real_luxos_terminal(self):
        out = os.path.join(self.home, "term-out")
        # vlastni proces bez sluzby D-Bus (jinak by okno patrilo sdilenemu procesu mimo test)
        self.spawn(["luxos-terminal", "--", "sh", "-c", "stty -echo; read line; printf '%s' \"$line\" > " + out + "; sleep 5"],
                   LUXOS_TERMINAL_NEW_PROCESS="1", LUXOS_TERMINAL_NO_SERVICE="1")
        found = self.wait_for(lambda: subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-terminal"],
                                                     capture_output=True, text=True, env=self.env()).stdout.strip() != "", 10)
        if not found:
            self.skipTest("luxos-terminal window did not appear")
        xid = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-terminal"], capture_output=True, text=True,
                             env=self.env()).stdout.split()[-1]
        time.sleep(1.0)
        self.focus(xid)
        self.open_picker()
        self.type_and_enter("srdce")
        self.assertTrue(self.wait_for(lambda: "pasted ctrl-shift-v" in self.events(), 6), self.events())
        time.sleep(0.5)
        self.focus(xid)
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) != "", 6), self.events())
        self.assertIn(self.read(out), ("♥️", "❤️"))

    def test_shift_enter_keeps_open_then_escape(self):
        out = self.target("LuxosTestEntry")
        self.open_picker("--search", "palec")
        self.xdo("key", "shift+Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) == "👍", 6), (self.events(), self.read(out)))
        self.assertTrue(self.wait_for(lambda: "reopened" in self.events(), 4), self.events())
        self.assertNotIn("hidden", self.events())
        time.sleep(0.4)
        # Shift byl drzeny: vlozeni nesmi byt Ctrl+Shift+V, druhe vlozeni jde dal do stejneho pole
        self.xdo("key", "shift+Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) == "👍👍", 6), (self.events(), self.read(out)))
        self.assertTrue(self.wait_for(lambda: self.events().count("reopened") == 2, 4), self.events())
        time.sleep(0.3)
        self.xdo("key", "Escape")
        self.assertTrue(self.wait_for(lambda: "hidden" in self.events(), 4), self.events())
        self.assertEqual(self.read(out), "👍👍")

    def test_escape_inserts_nothing_and_toggle(self):
        out = self.target("LuxosTestEntry")
        self.open_picker()
        self.type_and_enter("srdce", key="Escape")
        self.assertTrue(self.wait_for(lambda: "hidden" in self.events(), 4))
        time.sleep(0.5)
        self.assertEqual(self.read(out), "")
        self.assertNotIn("chose", " ".join(self.events()))
        # stejna zkratka okno otevre a znovu zavre
        self.focus(subprocess.run(["xdotool", "search", "--class", "LuxosTestEntry"], capture_output=True, text=True,
                                  env=self.env()).stdout.split()[0])
        self.spawn([os.path.join(BIN, "luxos-emoji")])
        self.assertTrue(self.wait_for(lambda: self.events().count("shown") == 2, 6), self.events())
        r = subprocess.run([os.path.join(BIN, "luxos-emoji")], env=self.env(), timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.wait_for(lambda: self.events().count("hidden") == 2, 4), self.events())

    def test_arrows_and_skin_tone(self):
        with open(os.path.join(self.home, ".config", "luxos", "emoji.conf"), "w") as f:
            f.write("tone=3\n")
        out = self.target("LuxosTestEntry")
        self.open_picker()
        # prazdne hledani: casto pouzivane 😀 😂 ❤️ 👍 ... -> 3x vpravo = 👍 v odstinu 3
        for _ in range(3):
            self.xdo("key", "Right")
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) == "👍🏽", 6), (self.events(), self.read(out)))
        with open(os.path.join(self.home, ".config", "luxos", "emoji.conf"), encoding="utf-8") as f:
            self.assertIn("recent=👍\n", f.read())                        # naposledy pouzite bez odstinu
        # Down: o radek niz (9 sloupcu): Naposledy pouzite = 👍 + casto pouzivane v dalsich sekcich
        self.focus(subprocess.run(["xdotool", "search", "--class", "LuxosTestEntry"], capture_output=True, text=True,
                                  env=self.env()).stdout.split()[0])
        open(out, "w").close()
        self.open_picker("--search", "srdce")
        self.xdo("key", "Down")      # druhy radek vysledku (nebo posledni polozka, je-li jen jeden)
        self.xdo("key", "Up")
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: self.read(out) != "", 6), self.events())
        self.assertIn(self.read(out), ("👍🏽♥️", "👍🏽❤️"))      # pole uz obsahuje prvni vlozeni

    def test_no_target_copies_and_notifies(self):
        # bez ciloveho okna: zadne okno aplikace nema fokus
        self.open_picker("--search", "palec")
        self.xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: "copied" in self.events(), 6), self.events())
        self.assertEqual(self.clipboard(), "👍")
        self.assertIn("Ctrl+V", self.read(os.path.join(self.home, "notify.log")))
        self.assertIn("Emoji je ve schránce", self.read(os.path.join(self.home, "notify.log")))

    def test_open_time_and_screenshots(self):
        # samostatny proces (bez hubu): start + data + okno
        out = self.target("LuxosTestEntry")
        start = self.open_picker()
        standalone = self.procs[-1]          # luxos-emoji se nahradil (exec) procesem luxos-emoji-ui
        cold = (self.event_time("drawn") - start) * 1000
        self.shot("emoji-light-open.png")
        self.xdo("type", "--delay", "30", "srdce")
        time.sleep(0.4)
        self.shot("emoji-light-search.png")
        self.xdo("key", "Escape")
        self.assertTrue(self.wait_for(lambda: "hidden" in self.events(), 4))
        # samostatny proces skonci sam, jakmile nic nedela
        self.assertTrue(self.wait_for(lambda: standalone.poll() is not None, 5))
        # predpripravene okno jako v luxos-hub (LUXOS_EMOJI_RESIDENT=1)
        os.unlink(self.log)
        resident = self.spawn([os.path.join(BIN, "luxos-emoji-ui")], LUXOS_EMOJI_RESIDENT="1", GTK_THEME="Adwaita:dark")
        time.sleep(1.5)
        self.assertIsNone(resident.poll())
        warm = []
        for _ in range(3):
            if os.path.exists(self.log):
                os.unlink(self.log)
            start = self.open_picker(GTK_THEME="Adwaita:dark")
            warm.append((self.event_time("drawn") - start) * 1000)
            self.assertIsNone(resident.poll())
            if not warm[1:]:
                self.xdo("type", "--delay", "30", "usmev")
                time.sleep(0.4)
                self.shot("emoji-dark-search.png")
            self.xdo("key", "Escape")
            self.assertTrue(self.wait_for(lambda: "hidden" in self.events(), 4))
            time.sleep(0.3)
        print("\nopen time: standalone %.0f ms, prebuilt (hub) %s ms" % (cold, ", ".join("%.0f" % w for w in warm)))
        self.assertLess(min(warm), 100)
        self.assertLess(cold, 1500)
        self.assertEqual(self.read(out), "")


class GuiWithWindowManager(Gui):
    """Stejne testy se spravcem oken xfwm4 (_NET_ACTIVE_WINDOW, kompozitor, ochrana proti kradeni fokusu)."""
    wm = True

    def test_window_icon_sizes(self):
        self.target("LuxosTestEntry")
        self.open_picker()
        xid = subprocess.run(["xdotool", "search", "--class", "luxos-emoji"], capture_output=True, text=True,
                             env=self.env()).stdout.split()
        self.assertTrue(xid)
        prop = subprocess.run(["xprop", "-len", "4000000", "-id", xid[-1], "-notype", "_NET_WM_ICON", "WM_CLASS"], capture_output=True,
                              text=True, env=self.env()).stdout
        self.assertIn('"luxos-emoji", "Luxos-emoji"', prop)
        sizes = set()
        for line in prop.splitlines():
            if "Icon (" in line:
                sizes.add(line.split("(")[1].split(")")[0])
        if not sizes:
            self.skipTest("luxos-emoji icon not installed in the icon theme (xprop: %s)" % prop[:200])
        self.assertIn("256 x 256", sizes)
        self.assertIn("16 x 16", sizes)


if __name__ == "__main__":
    unittest.main()
