#!/usr/bin/env python3
# Manualove stranky LuxOS a LSL skladane z offline dokumentace (docs/luxos, docs/lsl).
# Obsah se negeneruje rucne: kazda stranka = hlavicka (NAME, SYNOPSIS podle skutecneho
# --help/usage prikazu) + vybrane soubory/sekce z docs prevedene md2man. Man a docs pro
# LuxAI se tak nikdy nerozejdou. lux(1) je rucne psana v balicku lux - tady jen odkazy.
# Spusteni: python3 manpages.py DOCS_DIR OUT_DIR   (vytvori OUT_DIR/manN/jmeno.N)

import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md2man  # noqa: E402

DOCS_INSTALL = "/usr/share/luxos/docs"

# Zdroje: (soubor, rezim, vyber sekci '##')
#   "body"  - uvod souboru jde do DESCRIPTION, '##' -> .SH, '###' -> .SS
#   "part"  - cely soubor jako jedna .SH (nadpis '#'), '##' -> .SS
#   only=[...] / skip=[...] - presne nazvy sekci '##' (only urcuje i poradi)
#   rename={sekce: nadpis} - napr. sekce jako DESCRIPTION; intro=False - bez uvodu souboru
PAGES = [
    {
        "name": "luxos", "section": 7, "source": "LuxOS",
        "names": ["luxos"],
        "desc": "overview of LuxOS and where everything is documented",
        "sources": [
            ("luxos/overview.md", "body", {}),
            ("luxos/for-ai-assistants.md", "body", {"only": ["Which tool for which task"], "intro": False}),
            ("luxos/troubleshooting.md", "body", {"only": ["First checks"], "intro": False}),
        ],
        "files": [
            ("/usr/share/luxos/docs/", "offline documentation (Markdown) these pages are generated "
             "from; `index.json` lists `luxos/*.md` and `lsl/*.md`"),
            ("/usr/lib/os-release", "LuxOS version (`/etc/os-release` links to it)"),
            ("/etc/lux/lux.conf", "package manager configuration, see lux.conf(5)"),
            ("/etc/xdg/luxos/", "LuxOS desktop defaults"),
            ("~/.config/luxos/", "per-user LuxOS settings"),
        ],
        "see_also": ["lux(1)", "lux.conf(5)", "luxos-care(8)", "luxos-sandbox(1)", "luxos-safe(1)",
                     "luxos-guard(1)", "luxdrop(1)", "lsl(1)", "lsl(7)", "lslc(1)"],
    },
    {
        "name": "lux.conf", "section": 5, "source": "LuxOS",
        "names": ["lux.conf"],
        "desc": "configuration of the LuxOS package manager lux",
        "synopsis": ["`/etc/lux/lux.conf`", "`/etc/lux/conf.d/*.conf`", "`/etc/lux/mirrorlist`",
                     "`~/.config/lux/lux.conf`"],
        "sources": [
            ("luxos/package-management.md", "body",
             {"only": ["Configuration: /etc/lux/lux.conf"], "intro": False,
              "rename": {"Configuration: /etc/lux/lux.conf": "DESCRIPTION"}}),
            ("luxos/lux-engine-and-repos.md", "body",
             {"only": ["Repositories", "Signing and luxos-keyring"], "intro": False,
              "rename": {"Repositories": "Default configuration and repositories"}}),
            ("luxos/package-management.md", "body",
             {"only": ["Files"], "intro": False, "rename": {"Files": "FILES"}}),
        ],
        "see_also": ["lux(1)", "luxos(7)", "luxos-care(8)"],
    },
    {
        "name": "luxos-care", "section": 8, "source": "LuxOS",
        "names": ["luxos-care", "luxos-update"],
        "aliases": [("luxos-update", 8)],
        "desc": "automatic updates, previous-kernel fallback, self-repair, system snapshots and recovery (LuxOS Care)",
        "synopsis": [
            "**luxos-care** [**status**] [**--json**]",
            "**luxos-care history** [*N*]",
            "**luxos-care mode** [**carefree** | **classic**]",
            "**luxos-care update** [**--manual**]",
            "**luxos-care check** [**--updates**]",
            "**luxos-care apply** *ID*-*N*",
            "**luxos-care boot-check** | **kernel-switch** | **kernel-pre** | **kernel-post** | **release-kept**",
            "**luxos-care snapshots** [**--json**] | **snapshot** | **boot-entries**",
            "**luxos-care rollback** *NAME* | **--booted** **--yes**",
            "**luxos-care disk-check** [**--repair**] [**--json**]",
            "**luxos-care reinstall** **--yes**",
            "**luxos-update**",
        ],
        "sources": [("luxos/care-updates.md", "body", {})],
        "see_also": ["lux(1)", "lux.conf(5)", "luxos(7)"],
    },
    {
        "name": "luxos-sandbox", "section": 1, "source": "LuxOS",
        "names": ["luxos-sandbox"],
        "desc": "isolated system for untrusted applications (/dev/sandbox/USER)",
        "synopsis": [
            "**luxos-sandbox create**",
            "**luxos-sandbox status** [**--json**]",
            "**luxos-sandbox shell** [**--net**] [**--shared**]",
            "**luxos-sandbox run** [**--net**] [**--gui**] [**--shared**] [**--**] *COMMAND*|*./FILE* [*ARG*...]",
            "**luxos-sandbox install** *PACKAGE*...",
            "**luxos-sandbox build-install** [**--asdeps**] [**--deps** \"*A B*\"] *NAME* < *DIR.tar*",
            "**luxos-sandbox remove-app** *PACKAGE*...",
            "**luxos-sandbox reset** [**--yes**]",
            "**luxos-sandbox destroy** [**--yes**]",
        ],
        "sources": [("luxos/sandbox.md", "body", {})],
        "see_also": ["luxos-guard(1)", "luxos-safe(1)", "lux(1)", "bwrap(1)", "luxos(7)"],
    },
    {
        "name": "luxos-safe", "section": 1, "source": "LuxOS",
        "names": ["luxos-safe"],
        "desc": "encrypted folder /safe/USER (Safe)",
        "synopsis": [
            "**luxos-safe**",
            "**luxos-safe unlock** [**--open**]",
            "**luxos-safe lock** [**--force** | **--logout**]",
            "**luxos-safe status**",
            "**luxos-safe --watch**",
        ],
        "sources": [("luxos/safe.md", "body", {})],
        "see_also": ["gocryptfs(1)", "luxos-sandbox(1)", "luxos(7)"],
    },
    {
        "name": "luxos-guard", "section": 1, "source": "LuxOS",
        "names": ["luxos-guard"],
        "desc": "Lux Guard: protection against harmful downloaded programs and /home snapshots",
        "synopsis": [
            "**luxos-guard status**",
            "**luxos-guard scan** *FILE*...",
            "**luxos-guard allow** *FILE*",
            "**luxos-guard list** [**--json**]",
            "**luxos-guard snapshots**",
            "**luxos-guard restore** [**--from** *TIME*] [**--overwrite**] [**--dry-run**] *PATH*",
            "**luxos-guard service** | **snapshot**",
        ],
        "sources": [("luxos/guard.md", "body", {})],
        "see_also": ["luxos-sandbox(1)", "luxos-safe(1)", "luxos(7)"],
    },
    {
        "name": "luxdrop", "section": 1, "source": "LuxOS",
        "names": ["luxdrop"],
        "desc": "send files securely to nearby LuxOS computers and LocalSend apps",
        "synopsis": [
            "**luxdrop** [**gui**] [*FILE*...]",
            "**luxdrop send** [**--localsend**] [**--port** *N*] [**--pin** *PIN*] [**--no-remember**] [**-q**] "
            "*TARGET* [*FILE*...] [**--text** *TEXT*]",
            "**luxdrop receive** [**--mode off**|**trusted**|**everyone**] [**--minutes** *N*] [**--dir** *DIR*] "
            "[**--port** *N*] [**--bind** *ADDR*] [**--pin** *PIN*] [**--no-mdns**] [**--no-localsend**] "
            "[**--no-multicast**] [**--ls-port** *N*]",
            "**luxdrop devices** [**--timeout** *SECONDS*] [**--scan**]",
            "**luxdrop trust** [**list** | **remove** *ID*|*NAME*]",
            "**luxdrop id**",
            "**luxdrop mode** [**off**|**trusted**|**everyone**] [**--minutes** *N*]",
        ],
        "sources": [("luxos/luxdrop.md", "body", {})],
        "see_also": ["luxos(7)"],
    },
    {
        "name": "lsl", "section": 1, "source": "LSL",
        "names": ["lsl"],
        "desc": "Lux Simple Lang: run, compile and manage LSL programs",
        "synopsis": [
            "**lsl** [*SOURCE* [*ARG*...]]",
            "**lsl compile** [**--unsafe**] [**--target** *NAME*] *SOURCE* *OUTPUT*",
            "**lsl config** *ENTRY*",
            "**lsl install** *NAME* | **--config** *FILE* | **--tui**",
            "**lsl list**",
            "**lsl search** [*QUERY*]",
            "**lsl check** *NAME*",
            "**lsl man** [**--plain**] [*TOPIC*]",
            "**lsl help** [*TOPIC*]",
            "**lsl about** [*NAME*]",
            "**lsl --tui** [*FILE*]",
            "**lsl update** [*NAME*]",
            "**lsl update** [**--check** | **--rollback**] [**--system**] [**--allow-downgrade**]",
            "**lsl origin** [*NAME*]",
            "**lsl server** [*OPTIONS*]",
            "**lsl sandbox** [*OPTIONS*] *SOURCE* [*ARG*...]",
            "**lsl version** | **--version** | **-h** | **--help**",
        ],
        "sources": [
            ("lsl/overview.md", "body", {"skip": ["Where to go next"]}),
            ("lsl/cli-and-tooling.md", "body", {"skip": ["lslc"]}),
        ],
        "see_also": ["lsl(7)", "lslc(1)", "luxos(7)"],
    },
    {
        "name": "lsl", "section": 7, "source": "LSL",
        "names": ["lsl"],
        "desc": "Lux Simple Lang language reference and standard library",
        "intro": "This page is the LSL language reference: syntax, types, control flow, functions and "
                 "classes, modules, errors, built-in functions and the standard library, followed by "
                 "examples. The command line is described in [lsl(1)](cli-and-tooling.md); `lsl man` "
                 "and `lsl help TOPIC` show the same reference offline.",
        "sources": [(f"lsl/{n}.md", "part", {}) for n in (
            "syntax", "types-and-collections", "control-flow", "functions-and-classes", "modules",
            "errors", "builtins", "stdlib-core", "stdlib-compute", "stdlib-system",
            "stdlib-graphics-io", "stdlib-network-ai", "examples")],
        "see_also": ["lsl(1)", "lslc(1)", "luxos(7)"],
    },
    {
        "name": "lslc", "section": 1, "source": "LSL",
        "names": ["lslc"],
        "desc": "low-level LSL trust-core compiler",
        "synopsis": ["**lslc** [**--safe** | **--unsafe** | **--sandbox**] [**--target** *NAME*] "
                     "*SOURCE* *OUTPUT* [*LSL-QBE*]"],
        "sources": [
            ("lsl/cli-and-tooling.md", "body",
             {"only": ["lslc", "Other tools in the LuxOS package"], "intro": False,
              "rename": {"lslc": "DESCRIPTION"}}),
        ],
        "see_also": ["lsl(1)", "lsl(7)"],
    },
]

# Ktery dokument "patri" ke ktere strance - pro prevod relativnich odkazu na NAZEV(N)
DOC_OWNER = {
    "luxos/overview.md": ("luxos", 7),
    "luxos/package-management.md": ("lux", 1),
    "luxos/care-updates.md": ("luxos-care", 8),
    "luxos/sandbox.md": ("luxos-sandbox", 1),
    "luxos/safe.md": ("luxos-safe", 1),
    "luxos/guard.md": ("luxos-guard", 1),
    "luxos/luxdrop.md": ("luxdrop", 1),
    "lsl/overview.md": ("lsl", 1),
    "lsl/cli-and-tooling.md": ("lsl", 1),
}
for _page in PAGES:
    if (_page["name"], _page["section"]) == ("lsl", 7):
        DOC_OWNER.update((src[0], ("lsl", 7)) for src in _page["sources"])

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MAN_REF_RE = re.compile(r"^([\w.+-]+)\((\d)\)$")


def split_sections(text):
    """(nadpis '#', uvod, [(nadpis '##', radky vcetne nadpisu)]) - s ohledem na bloky kodu."""
    title, intro, sections = None, [], []
    fence = None
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if m:
            fence = None if fence and m.group(1)[0] == fence else (fence or m.group(1)[0])
        if not fence and not m:
            if line.startswith("# ") and title is None:
                title = line[2:].strip()
                continue
            if line.startswith("## "):
                sections.append((line[3:].strip(), [line]))
                continue
        (sections[-1][1] if sections else intro).append(line)
    return title, intro, sections


def make_resolver(doc, page, docs_dir):
    def resolve(url):
        if re.match(r"^[a-z][a-z0-9+.-]*:", url):
            return ("url", url)
        if MAN_REF_RE.match(url):
            m = MAN_REF_RE.match(url)
            return ("man", m.group(1), m.group(2))
        path, _, _frag = url.partition("#")
        dest = os.path.normpath(os.path.join(os.path.dirname(doc), path)).replace(os.sep, "/") if path else doc
        owner = DOC_OWNER.get(dest)
        if owner == (page["name"], page["section"]):
            if dest == doc or not os.path.isfile(os.path.join(docs_dir, dest)):
                return None                  # odkaz v ramci stejneho dokumentu: jen text
            with open(os.path.join(docs_dir, dest), encoding="utf-8") as f:
                return ("same", split_sections(f.read())[0])   # kapitola teze stranky
        if owner:
            return ("man", owner[0], str(owner[1]))
        if dest.endswith(".md"):
            return ("path", f"{DOCS_INSTALL}/{dest}")
        return None
    return resolve


def select_markdown(page, docs_dir):
    """Vybrany Markdown stranky: (dokument, druh, text); druh je "intro" (uvod souboru do
    DESCRIPTION), "description" (sekce prejmenovana na DESCRIPTION), "sections" nebo "part"."""
    for doc, mode, opts in page["sources"]:
        with open(os.path.join(docs_dir, doc), encoding="utf-8") as f:
            doc_title, intro, sections = split_sections(f.read())
        names = [s[0] for s in sections]
        rename = opts.get("rename", {})
        for want in opts.get("only", []) + opts.get("skip", []) + list(rename):
            if want not in names:
                raise ValueError(f"{doc}: no section '## {want}'")
        if "only" in opts:
            sections = [s for name in opts["only"] for s in sections if s[0] == name]
        sections = [s for s in sections if s[0] not in opts.get("skip", [])]
        if mode == "part":
            yield doc, "part", "\n".join(["# " + doc_title] + intro + [l for _n, ls in sections for l in ls])
            continue
        if opts.get("intro", True) and "".join(intro).strip():
            yield doc, "intro", "\n".join(intro)
        for name, lines in sections:
            if name in rename:
                lines = ["## " + rename[name]] + lines[1:]
            yield doc, "description" if rename.get(name) == "DESCRIPTION" else "sections", "\n".join(lines)


def build_date():
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    t = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc) if epoch else \
        datetime.datetime.now(datetime.timezone.utc)
    return t.strftime("%Y-%m-%d")


def render_page(page, docs_dir, date=None):
    sec = page["section"]
    title = page["name"].upper()
    manual = {1: "LuxOS User Commands", 5: "LuxOS File Formats", 7: "LuxOS Miscellaneous",
              8: "LuxOS Administration"}[sec]
    out = [
        '.\\" Generovano z %s (luxos-docs, man/manpages.py) - neupravovat rucne.' % DOCS_INSTALL,
        '.TH "%s" "%d" "%s" "%s" "%s"' % (md2man.escape(title), sec, date or build_date(),
                                          page["source"], manual),
        # zarovnani vlevo (groff man cte retezec AD pri kazdem odstavci): dlouhe cesty
        # a prikazy pak nevytvari velke mezery
        ".ds AD l",
        ".ad l",
        # bez deleni slov (groff man cte registr HY pri kazdem odstavci): prikazy a cesty
        # v textu musi zustat kopirovatelne
        ".nr HY 0",
        ".nh",
        ".SH NAME",
        "%s \\- %s" % (", ".join(md2man.escape(n) for n in page["names"]), md2man.escape(page["desc"])),
    ]
    if page.get("synopsis"):
        out.append(".SH SYNOPSIS")
        r = md2man.Renderer()
        for k, line in enumerate(page["synopsis"]):
            out.append(".PP" if k == 0 else ".br")
            out.append(md2man.protect(r.inline(line)))
    described = False
    if page.get("intro"):
        out.append(".SH DESCRIPTION")
        r = md2man.Renderer(make_resolver("lsl/overview.md", page, docs_dir))
        out.append(r.convert(page["intro"]).rstrip("\n"))
        described = True
    for doc, kind, md in select_markdown(page, docs_dir):
        if kind == "intro" and not described:
            out.append(".SH DESCRIPTION")
        if kind in ("intro", "description"):
            described = True
        offset = 0 if kind == "part" else 1
        out.append(md2man.convert(md, make_resolver(doc, page, docs_dir), offset).rstrip("\n"))
    if page.get("files"):
        out.append(".SH FILES")
        r = md2man.Renderer()
        for path, what in page["files"]:
            out.append(".TP")
            out.append(md2man.protect("\\fI" + md2man.escape(path) + "\\fR"))
            out.append(md2man.protect(r.inline(what)))
    out.append(".SH SEE ALSO")
    refs = []
    for ref in page["see_also"]:
        m = MAN_REF_RE.match(ref)
        refs.append("\\fB%s\\fR(%s)" % (md2man.escape(m.group(1)), m.group(2)))
    out.append(",\n".join(refs))
    out.append(".PP")
    out.append(md2man.protect(md2man.Renderer().inline(
        "Full offline documentation (Markdown, also read by LuxAI): `%s/` "
        "(`index.json`, `luxos/*.md`, `lsl/*.md`)." % DOCS_INSTALL)))
    return "\n".join(out) + "\n"


def build(docs_dir, out_dir, date=None):
    written = []
    for page in PAGES:
        sec = page["section"]
        d = os.path.join(out_dir, f"man{sec}")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{page['name']}.{sec}")
        with open(path, "w", encoding="ascii") as f:
            f.write(render_page(page, docs_dir, date))
        written.append(path)
        for alias, asec in page.get("aliases", []):
            ad = os.path.join(out_dir, f"man{asec}")
            os.makedirs(ad, exist_ok=True)
            apath = os.path.join(ad, f"{alias}.{asec}")
            with open(apath, "w", encoding="ascii") as f:
                f.write(f".so man{sec}/{page['name']}.{sec}\n")
            written.append(apath)
    return written


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: manpages.py DOCS_DIR OUT_DIR")
    for p in build(sys.argv[1], sys.argv[2]):
        print(p)
