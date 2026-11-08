"""LuxOS - seznam zmen pro web: cesky CHANGELOG.md (zdroj pravdy) a jeho anglicky preklad
site/content/en/changes/ (jeden soubor na vydani + _intro.md). Pouziva scripts/build-site.py
(sestavi anglickou stranku /changes/) a scripts/check-site.py (overi, ze anglictina nic nevynechava).

Soubor vydani: <verze>-<datum>.md (napr. 1.0.1-2026-11-08.md), sekce „Připravuje se“ = unreleased.md.
Kazdy obsahuje jeden nadpis "## " se stejnou verzi a datem, pak stejne sekce "### " ve stejnem
poradi a v kazde stejny pocet polozek "- " (jedna polozka = jeden radek) jako cesky CHANGELOG.md.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
EN_DIR = os.path.join(ROOT, "site", "content", "en", "changes")
EN_INTRO = "_intro.md"
UNRELEASED_CS = "Připravuje se"
UNRELEASED_EN = "Coming soon"


def split_sections(text):
    """-> (uvod pred prvnim "## ", [(nadpis bez "## ", text sekce vcetne nadpisu), ...])"""
    parts = re.split(r"(?m)^(?=## )", text)
    intro, sections = parts[0], []
    for p in parts[1:]:
        sections.append((p.splitlines()[0][3:].strip(), p))
    return intro, sections


def outline(section_text):
    """[(nadpis "### " nebo None pro polozky pred prvni podsekci, pocet polozek "- "), ...]"""
    out = [[None, 0]]
    for line in section_text.splitlines():
        if line.startswith("### "):
            out.append([line[4:].strip(), 0])
        elif line.startswith(("- ", "* ")):
            out[-1][1] += 1
    if out[0][1] == 0:
        out.pop(0)
    return [tuple(x) for x in out]


def version_date(heading):
    """('1.0.1', '2026-11-08') z nadpisu vydani, (None, None) pro „Připravuje se“/„Coming soon“."""
    m = re.match(r"(\d+\.\d+\.\d+)\b.*?(\d{4}-\d{2}-\d{2})", heading)
    return (m.group(1), m.group(2)) if m else (None, None)


def slug(heading):
    if heading.startswith(UNRELEASED_CS):
        return "unreleased"
    ver, date = version_date(heading)
    if not ver:
        raise ValueError(f"CHANGELOG.md: release heading without version and date: {heading!r}")
    return f"{ver}-{date}"


def cs_releases():
    with open(CHANGELOG, encoding="utf-8") as f:
        return split_sections(f.read())[1]


def en_text():
    """Anglicka stranka zmen (markdown): _intro.md a preklady vydani v poradi CHANGELOG.md."""
    with open(os.path.join(EN_DIR, EN_INTRO), encoding="utf-8") as f:
        parts = [f.read().rstrip("\n")]
    for heading, _text in cs_releases():
        with open(os.path.join(EN_DIR, slug(heading) + ".md"), encoding="utf-8") as f:
            parts.append(f.read().rstrip("\n"))
    return "\n\n".join(parts) + "\n"


def verify():
    """Seznam problemu (prazdny = anglicky preklad odpovida CHANGELOG.md)."""
    problems, expected = [], {EN_INTRO}
    if not os.path.isfile(os.path.join(EN_DIR, EN_INTRO)):
        problems.append(f"changes: missing site/content/en/changes/{EN_INTRO}")
    for heading, text in cs_releases():
        try:
            name = slug(heading) + ".md"
        except ValueError as err:
            problems.append(str(err))
            continue
        expected.add(name)
        path = os.path.join(EN_DIR, name)
        rel = "site/content/en/changes/" + name
        if not os.path.isfile(path):
            problems.append(f"changes: {rel} missing (English translation of CHANGELOG.md '## {heading}')")
            continue
        with open(path, encoding="utf-8") as f:
            en = f.read()
        _pre, en_secs = split_sections(en)
        if _pre.strip() or len(en_secs) != 1:
            problems.append(f"changes: {rel} must start with one '## ' heading and contain no other ('{len(en_secs)}' found)")
            if not en_secs:
                continue
        en_head = en_secs[0][0]
        if heading.startswith(UNRELEASED_CS):
            if en_head != UNRELEASED_EN:
                problems.append(f"changes: {rel} heading is '{en_head}', expected '{UNRELEASED_EN}'")
        elif version_date(en_head) != version_date(heading):
            problems.append(f"changes: {rel} heading '{en_head}' does not match version/date of '{heading}'")
        cs_out, en_out = outline(text), outline(en_secs[0][1])
        if len(cs_out) != len(en_out):
            problems.append(f"changes: {rel} has {len(en_out)} '###' subsections, CHANGELOG.md '{heading}' has {len(cs_out)}")
            continue
        for (cs_sub, cs_n), (en_sub, en_n) in zip(cs_out, en_out):
            if cs_n != en_n:
                problems.append(f"changes: {rel} '### {en_sub}' has {en_n} items, CHANGELOG.md '### {cs_sub}' "
                                f"in '{heading}' has {cs_n}")
        for line in en.splitlines():
            if re.match(r"^[-*]\s*$", line):
                problems.append(f"changes: {rel} has an empty list item")
    if os.path.isdir(EN_DIR):
        for name in sorted(set(os.listdir(EN_DIR)) - expected):
            problems.append(f"changes: site/content/en/changes/{name} matches no section of CHANGELOG.md")
    return problems


def item_counts():
    """{slug: (polozek cesky, polozek anglicky nebo None)} - pro prehled."""
    out = {}
    for heading, text in cs_releases():
        s = slug(heading)
        cs_n = sum(n for _s, n in outline(text))
        path = os.path.join(EN_DIR, s + ".md")
        en_n = None
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                en_n = sum(n for _s, n in outline(f.read()))
        out[s] = (cs_n, en_n)
    return out
