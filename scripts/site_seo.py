"""LuxOS web: pomocne funkce pro SEO a vykon (scripts/build-site.py a scripts/check-site.py).

- image_size(): rozmery obrazku WebP, PNG a JPEG primo z hlavicky souboru (bez Pillow), aby kazdy <img>
  mel width/height a stranka pri nacitani neposkakovala (CLS).
- add_img_dims(): doplni do <img src="/assets/..."> width/height, loading="lazy" a decoding="async".
- faq_pairs(): viditelne otazky a odpovedi z <section class="faq"> (h3 = otazka, text pod ni = odpoved)
  - FAQPage ve strukturovanych datech vznika jen z toho, co je opravdu na strance.
- fit_title(): titulek do TITLE_MAX znaku (Google vic neukaze) - zkrati priponu, pak zavorku, pak podtitul.
"""
import html
import os
import re
import struct

TITLE_MAX = 60
DESC_MAX = 155


def image_size(path):
    """(sirka, vyska) obrazku WebP/PNG/JPEG nebo None."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return None
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        kind = head[12:16]
        if kind == b"VP8X":
            w = int.from_bytes(head[24:27], "little") + 1
            h = int.from_bytes(head[27:30], "little") + 1
            return w, h
        if kind == b"VP8 ":
            # klicovy snimek: 3 B tag, 3 B start code 9d 01 2a, pak 14 bitu sirka a vyska
            i = head.find(b"\x9d\x01\x2a", 20)
            if i > 0:
                w, h = struct.unpack("<HH", head[i + 3:i + 7])
                return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":
            b = head[21:25]
            bits = int.from_bytes(b, "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker = head[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", head[i + 5:i + 9])
                return w, h
            seg = struct.unpack(">H", head[i + 2:i + 4])[0]
            i += 2 + seg
    return None


_IMG = re.compile(r"<img\b([^>]*)>")


def add_img_dims(text, root):
    """<img src="/assets/x.webp" ...> -> s width/height (ze souboru v root), lazy a async, pokud chybi."""
    def fix(m):
        attrs = m.group(1)
        src = re.search(r'\ssrc="(/[^"]+)"', attrs)
        if not src:
            return m.group(0)
        add = ""
        if " width=" not in attrs:
            size = image_size(os.path.join(root, src.group(1).lstrip("/")))
            if size:
                add += f' width="{size[0]}" height="{size[1]}"'
        if " loading=" not in attrs and "fetchpriority" not in attrs:
            add += ' loading="lazy"'
        if " decoding=" not in attrs:
            add += ' decoding="async"'
        if not add:
            return m.group(0)
        end = "/>" if attrs.rstrip().endswith("/") else ">"
        body = attrs.rstrip().rstrip("/") if end == "/>" else attrs
        return f"<img{body}{add}{end}"
    return _IMG.sub(fix, text)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def faq_pairs(text):
    """[(otazka, odpoved)] z <section class="faq"...>: kazde <h3> je otazka, obsah do dalsiho <h3> odpoved."""
    out = []
    for sec in re.findall(r'<section class="faq"[^>]*>(.*?)</section>', text, flags=re.S):
        parts = re.split(r"<h3[^>]*>(.*?)</h3>", sec, flags=re.S)
        for i in range(1, len(parts) - 1, 2):
            q, a = strip_tags(parts[i]), strip_tags(parts[i + 1])
            if q and a:
                out.append((q, a))
    return out


def fit_title(base, suffixes, limit=TITLE_MAX):
    """Titulek 'base + pripona' do limitu: prvni pripona, ktera se vejde; jinak base bez koncove zavorky
    s priponou, pak bez pripony; nakonec jen cast pred ' – ' nebo ': ' (podtitul) s priponou."""
    for s in suffixes:
        if len(base + s) <= limit:
            return base + s
    short = re.sub(r"\s*\([^)]*\)\s*$", "", base).strip()
    for s in suffixes:
        if len(short + s) <= limit:
            return short + s
    if len(short) <= limit:
        return short
    head =re.split(r" – |: ", short)[0].strip()
    for s in suffixes:
        if len(head + s) <= limit:
            return head + s
    return head[:limit]
