#!/usr/bin/env python3
# Prevod Markdownu (podmnozina pouzita v docs/) na roff s makry man(7).
# Bez zavislosti (zadny pandoc): nadpisy, odstavce, odrazky a cislovane seznamy (i vnorene),
# bloky kodu, inline kod/tucne/kurziva, odkazy, jednoduche tabulky a citace.
# Vystup je ciste ASCII (ostatni znaky jako \[uXXXX]), aby nezalezelo na preconv/locale.

import re

# ASCII znaky, ktere groff jinak vysazi typograficky (‘ ’ ˆ ˜) - v prikazech a kodu musi
# zustat kopirovatelne: apostrof, obracena carka, striska, vlnovka
ASCII_SAFE = {"'": "\\(aq", "`": "\\(ga", "^": "\\(ha", "~": "\\(ti"}

# Nekolik beznych znaku ma v roff citelnejsi pojmenovane tvary
NAMED = {
    "\u2013": "\\(en", "\u2014": "\\(em", "\u2192": "\\(->", "\u2190": "\\(<-",
    "\u2265": "\\(>=", "\u2264": "\\(<=", "\u00d7": "\\(mu", "\u2018": "\\(oq",
    "\u2019": "\\(cq", "\u201c": "\\(lq", "\u201d": "\\(rq", "\u2022": "\\(bu",
    "\u00a0": "\\ ",
}

FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
NUMBER_RE = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
LINK_RE = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^()\s]+)(?:\s+\"[^\"]*\")?\)")
AUTOLINK_RE = re.compile(r"<((?:https?|ftp|mailto):[^\s<>]+)>")
MD_ESCAPABLE = set("\\`*_{}[]()#+-.!|<>~\"'")


def escape(text):
    """Text pro roff: zpetne lomitko, spojovniky/minus, ' ` ^ ~ a ne-ASCII znaky."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\e")
        elif ch == "-":
            out.append("\\-")
        elif ch == "\t":
            out.append("    ")
        elif ch in ASCII_SAFE:
            out.append(ASCII_SAFE[ch])
        elif ord(ch) < 128:
            out.append(ch)
        elif ch in NAMED:
            out.append(NAMED[ch])
        else:
            out.append("\\[u%04X]" % ord(ch))
    return "".join(out)


def protect(line):
    """Radek zacinajici '.' nebo '\\'' by roff bral jako makro - predradit \\&."""
    if line[:1] in (".", "'"):
        return "\\&" + line
    return line


# ---------------------------------------------------------------- inline

def _find_closing(s, start, marker):
    """Pozice uzaviraciho znacky `marker` (ne hned za mezerou), jinak -1."""
    i = start
    while True:
        i = s.find(marker, i)
        if i < 0:
            return -1
        if i > start and not s[i - 1].isspace() and s[i - 1] != "\\":
            if marker != "*" or s[i + 1:i + 2] != "*" or s[i - 1] == "*":
                return i
        i += len(marker)


def _runs(s, bold, italic, code, links, out):
    """Rozlozi inline Markdown na useky (text, tucne, kurziva, kod)."""
    i, buf = 0, []

    def flush():
        if buf:
            out.append(("".join(buf), bold, italic, code))
            buf.clear()

    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in MD_ESCAPABLE:
            buf.append(s[i + 1])
            i += 2
            continue
        if c == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            ticks = s[i:j]
            k = s.find(ticks, j)
            while k >= 0 and k + len(ticks) < n and s[k + len(ticks)] == "`":
                k = s.find(ticks, k + len(ticks) + 1)
            if k >= 0:
                flush()
                body = s[j:k]
                if body.startswith(" ") and body.endswith(" ") and body.strip():
                    body = body[1:-1]
                out.append((body, bold, italic, True))
                i = k + len(ticks)
                continue
            buf.append(ticks)
            i = j
            continue
        if c == "[":
            m = LINK_RE.match(s, i)
            if m:
                flush()
                label, url = m.group(1), m.group(2)
                sub = []
                _runs(label, bold, italic, code, links, sub)
                out.extend(links(label, url, sub, (bold, italic, code)))
                i = m.end()
                continue
        if c == "<":
            m = AUTOLINK_RE.match(s, i)
            if m:
                flush()
                out.append((m.group(1), bold, italic, code))
                i = m.end()
                continue
        if s.startswith("**", i) or s.startswith("__", i):
            mark = s[i:i + 2]
            if i + 2 < n and not s[i + 2].isspace() and (mark == "**" or i == 0 or not s[i - 1].isalnum()):
                k = _find_closing(s, i + 2, mark)
                if k > 0 and (mark == "**" or k + 2 >= n or not s[k + 2].isalnum()):
                    flush()
                    _runs(s[i + 2:k], True, italic, code, links, out)
                    i = k + 2
                    continue
        if c in "*_" and not s.startswith(c * 2, i):
            if i + 1 < n and not s[i + 1].isspace() and (c == "*" or i == 0 or not s[i - 1].isalnum()):
                k = _find_closing(s, i + 1, c)
                if k > 0 and (c == "*" or k + 1 >= n or not s[k + 1].isalnum()):
                    flush()
                    _runs(s[i + 1:k], bold, True, code, links, out)
                    i = k + 1
                    continue
        buf.append(c)
        i += 1
    flush()


def plain(s):
    """Inline Markdown bez formatovani (nadpisy, porovnani popisku odkazu)."""
    out = []
    _runs(s, False, False, False, lambda label, url, sub, st: sub, out)
    return "".join(r[0] for r in out)


def _font(bold, italic, code):
    b = bold or code
    if b and italic:
        return "\\f(BI"
    if b:
        return "\\fB"
    if italic:
        return "\\fI"
    return "\\fR"


def render_runs(runs):
    out, cur, prev = [], "\\fR", " "
    for text, bold, italic, code in runs:
        if not text:
            continue
        f = _font(bold, italic, code)
        if f != cur:
            out.append(f)
            cur = f
        if code:
            # kod, cesty a prikazy se nedeli spojovnikem: \% na zacatku slova vypne deleni;
            # uprostred slova (napr. hned za '(') by naopak pridal misto deleni, tam se nevklada
            esc = escape(text)
            esc = re.sub(r"(\s)(?=\S)", lambda m: m.group(1) + "\\%", esc)
            out.append("\\%" + esc if prev.isspace() and not text[0].isspace() else esc)
        else:
            out.append(escape(text))
        prev = text[-1]
    if cur != "\\fR":
        out.append("\\fR")
    return "".join(out)


class Renderer:
    """Prevod jednoho Markdown dokumentu na roff.

    heading_offset: o kolik snizit uroven nadpisu ('##' s offsetem 1 -> .SH).
    resolve(url) -> None (jen text), ("man", jmeno, sekce), ("path", cesta), ("url", adresa)
    nebo ("same", nadpis) pro jinou kapitolu teze stranky.
    """

    def __init__(self, resolve=None, heading_offset=0):
        self.resolve = resolve or (lambda url: ("url", url))
        self.offset = heading_offset

    # ---- odkazy
    def _link(self, label, url, sub, style):
        bold, italic, code = style
        target = self.resolve(url)
        if target is None:
            return sub
        text = plain(label).strip()
        base = url.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if target[0] == "same":
            # jina kapitola teze stranky: misto nazvu souboru jeji nadpis
            if target[1] and text in (base, url):
                return [("\u201c%s\u201d" % target[1], bold, italic, False)]
            return sub
        if target[0] == "man":
            ref = [(target[1], True, False, False), ("(%s)" % target[2], bold, italic, code)]
        else:
            ref = [(target[1], bold, italic, True if target[0] == "path" else code)]
        if not text or text in (url, base, target[1]) or (
                target[0] == "man" and text == "%s(%s)" % (target[1], target[2])):
            return ref
        return sub + [(" (", bold, italic, code)] + ref + [(")", bold, italic, code)]

    def inline(self, s):
        out = []
        _runs(s, False, False, False, self._link, out)
        return render_runs(out)

    # ---- bloky
    def convert(self, text):
        lines = text.replace("\r\n", "\n").split("\n")
        out = []
        self._blocks(lines, out, top=True)
        return "\n".join(out) + ("\n" if out else "")

    def _blocks(self, lines, out, top=False, first_para=None):
        """first_para: pri renderovani polozky seznamu - vlozit prvni odstavec bez .PP."""
        i, n = 0, len(lines)
        started = False
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = FENCE_RE.match(line)
            if m:
                i = self._code(lines, i, m, out)
                started = True
                continue
            m = HEADING_RE.match(line)
            if m:
                self._heading(len(m.group(1)), m.group(2), out)
                i += 1
                started = True
                continue
            if HR_RE.match(line):
                out.append(".sp")
                i += 1
                continue
            if line.lstrip().startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
                i = self._table(lines, i, out)
                started = True
                continue
            if BULLET_RE.match(line) or NUMBER_RE.match(line):
                i = self._list(lines, i, out)
                started = True
                continue
            if line.lstrip().startswith(">"):
                j = i
                quote = []
                while j < n and lines[j].lstrip().startswith(">"):
                    quote.append(re.sub(r"^\s*>\s?", "", lines[j]))
                    j += 1
                out.append(".RS 4")
                self._blocks(quote, out)
                out.append(".RE")
                i = j
                started = True
                continue
            # odstavec: az do prazdneho radku nebo zacatku jineho bloku
            para = [line.strip()]
            j = i + 1
            while j < n and lines[j].strip() and not self._starts_block(lines, j):
                para.append(lines[j].strip())
                j += 1
            if first_para is not None and not started:
                first_para.append(self._para_text(para))
            else:
                out.append(".PP")
                out.append(self._para_text(para))
            started = True
            i = j

    def _starts_block(self, lines, j):
        line = lines[j]
        return bool(FENCE_RE.match(line) or HEADING_RE.match(line) or BULLET_RE.match(line)
                    or NUMBER_RE.match(line) or line.lstrip().startswith(">")
                    or (line.lstrip().startswith("|") and j + 1 < len(lines)
                        and TABLE_SEP_RE.match(lines[j + 1])))

    def _para_text(self, para):
        # tvrde zalomeni: dve mezery nebo '\' na konci radku
        parts, chunk = [], []
        for raw in para:
            chunk.append(raw.rstrip("\\").rstrip())
            if raw.endswith("\\"):
                parts.append(" ".join(chunk))
                chunk = []
        if chunk:
            parts.append(" ".join(chunk))
        return "\n.br\n".join(protect(self.inline(p)) for p in parts)

    def _heading(self, level, text, out):
        level -= self.offset
        title = escape(plain(text).strip())
        if level <= 1:
            out.append(".SH")
            out.append(protect(title))
        elif level == 2:
            out.append(".SS")
            out.append(protect(title))
        else:
            out.append(".PP")
            out.append("\\fB" + title + "\\fR")

    def _code(self, lines, i, m, out):
        indent, fence = len(m.group(1)), m.group(2)
        body = []
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped.startswith(fence[0] * len(fence)) and set(stripped) == {fence[0]}:
                j += 1
                break
            raw = lines[j]
            # odsazeni plotu (blok uvnitr polozky seznamu) se z obsahu odebere
            k = 0
            while k < indent and k < len(raw) and raw[k] == " ":
                k += 1
            body.append(raw[k:].expandtabs(4).rstrip())
            j += 1
        while body and not body[-1]:
            body.pop()
        out.append(".PP")
        out.append(".RS 4")
        out.append(".EX")
        for b in body:
            out.append(protect(escape(b)) if b else "")
        out.append(".EE")
        out.append(".RE")
        return j

    @staticmethod
    def _cells(line):
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|") and not s.endswith("\\|"):
            s = s[:-1]
        cells, cur, i, code = [], [], 0, 0
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
                cur.append("|" if code else "\\|")
                i += 2
                continue
            if c == "`":
                code ^= 1
            if c == "|" and not code:
                cells.append("".join(cur).strip())
                cur = []
            else:
                cur.append(c)
            i += 1
        cells.append("".join(cur).strip())
        return cells

    def _table(self, lines, i, out):
        """Tabulka jako odsazene polozky: prvni sloupec je stitek (.TP), dalsi sloupce
        pod nim (u 3+ sloupcu s nazvem sloupce). Citelne na 80 sloupcich bez tbl."""
        header = self._cells(lines[i])
        j = i + 2
        rows = []
        while j < len(lines) and lines[j].strip().startswith("|"):
            rows.append(self._cells(lines[j]))
            j += 1
        out.append(".PP")
        for row in rows:
            row = row + [""] * (len(header) - len(row))
            out.append(".TP")
            out.append(protect(self.inline(row[0])) if row[0] else "\\&")
            body = []
            for h, cell in zip(header[1:], row[1:]):
                if not cell:
                    continue
                if len(header) > 2:
                    body.append(protect(self.inline("*%s:* " % plain(h) if h else "") + self.inline(cell)))
                else:
                    body.append(protect(self.inline(cell)))
            out.append("\n.br\n".join(body) if body else "\\&")
        return j

    def _list(self, lines, i, out):
        n = len(lines)
        first = BULLET_RE.match(lines[i]) or NUMBER_RE.match(lines[i])
        base = len(first.group(1))
        numbered = NUMBER_RE.match(lines[i]) is not None
        number = int(first.group(2)) if numbered else 0
        width = 4 if numbered else 2
        while i < n:
            m = BULLET_RE.match(lines[i]) or NUMBER_RE.match(lines[i])
            if not m or len(m.group(1)) != base or (NUMBER_RE.match(lines[i]) is not None) != numbered:
                break
            content_indent = len(lines[i]) - len(m.group(3))
            item = [m.group(3)]
            j = i + 1
            in_fence = False
            while j < n:
                l = lines[j]
                if FENCE_RE.match(l):
                    in_fence = not in_fence
                if in_fence or (l.strip() and len(l) - len(l.lstrip()) >= content_indent):
                    item.append(l[content_indent:] if l[:content_indent].strip() == "" else l.lstrip())
                    j += 1
                    continue
                if not l.strip():
                    # prazdny radek: polozka pokracuje jen odsazenym obsahem
                    k = j
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n and len(lines[k]) - len(lines[k].lstrip()) >= content_indent:
                        item.extend([""] * (k - j))
                        j = k
                        continue
                    break
                lm = BULLET_RE.match(l) or NUMBER_RE.match(l)
                if lm or self._starts_block(lines, j):
                    break
                item.append(l.strip())   # line pokracovani bez odsazeni
                j += 1
            tag = "%d." % number if numbered else "\\(bu"
            number += 1
            first_para, rest = [], []
            self._blocks(item, rest, first_para=first_para)
            out.append(".IP %s %d" % (tag, width))
            if first_para:
                out.append(first_para[0])
            if rest:
                out.append(".RS %d" % width)
                out.extend(rest)
                out.append(".RE")
            i = j
            while i < n and not lines[i].strip():
                k = i
                while k < n and not lines[k].strip():
                    k += 1
                if k < n and (BULLET_RE.match(lines[k]) or NUMBER_RE.match(lines[k])):
                    i = k
                break
        return i


def convert(text, resolve=None, heading_offset=0):
    return Renderer(resolve, heading_offset).convert(text)
