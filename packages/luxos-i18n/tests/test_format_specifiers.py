#!/usr/bin/env python3
"""Formatovaci znacky prekladu: kazdy preklad ma presne stejne znacky jako anglicky text (klic).

    python3 packages/luxos-i18n/tests/test_format_specifiers.py

Preklad s chybejici, navic nebo jinou znackou shodi program: C (printf, g_strdup_printf) cte argument
spatneho typu, Python "%" vyhodi TypeError a str.format KeyError. Kontroluje se:
- printf: %s %d %i %u %f %.1f %5.2f %ld %lu %lld %zu %x %c %e %g %% a pozicni %1$s,
- Python: %(nazev)s a {nazev} / {nazev:.1f} / {} / {0},
- poradi znacek bez nazvu (printf bere argumenty postupne; prehozeni %s a %d = spatny typ).
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
I18N = os.path.join(HERE, "..", "files")
LANGS = ["cs", "de", "es", "fr", "hu", "it", "nl", "pl", "pt", "sk", "sv", "uk"]

# printf (vcetne pozicniho %1$s a Pythonu %(nazev)s): priznaky, sirka, presnost, delka, typ.
# Bez priznaku " " (mezera): doslovne "20 % automatisch" by se jinak cetlo jako "% a".
PRINTF = re.compile(r"%(?:(?P<pos>\d+)\$)?(?:\((?P<name>[A-Za-z_][A-Za-z0-9_]*)\))?"
                    r"(?P<flags>[-+#0']*)(?P<width>\*|\d+)?(?:\.(?P<prec>\*|\d+))?"
                    r"(?P<len>hh|h|ll|l|L|q|j|z|t)?(?P<conv>[diouxXeEfFgGcsaAp%])")
# str.format: {}, {0}, {nazev}, {nazev:.1f}, {nazev!r}; {{ a }} jsou doslovne zavorky
BRACE = re.compile(r"\{\{|\}\}|\{(?P<field>[A-Za-z_][A-Za-z0-9_]*|\d*)(?P<conv>![rsa])?(?::(?P<spec>[^{}]*))?\}")


def specs(text):
    """-> (pozicni printf v poradi, pojmenovane/pozicni printf jako mnozina, str.format jako mnozina)"""
    ordered, named, braces = [], [], []
    for m in PRINTF.finditer(text):
        if m.group("conv") == "%":
            continue
        # sirka/presnost/typ, bez priznaku zarovnani (ty nemeni typ argumentu)
        sig = f"%{m.group('width') or ''}{'.' + m.group('prec') if m.group('prec') else ''}" \
              f"{m.group('len') or ''}{m.group('conv')}"
        if m.group("name"):
            named.append(f"%({m.group('name')}){sig[1:]}")
        elif m.group("pos"):
            named.append(f"%{m.group('pos')}${sig[1:]}")
        else:
            ordered.append(sig)
    for m in BRACE.finditer(text):
        if m.group(0) in ("{{", "}}"):
            continue
        braces.append("{" + m.group("field") + (m.group("conv") or "") + (":" + m.group("spec") if m.group("spec")
                                                                           is not None else "") + "}")
    return ordered, sorted(named), sorted(braces)


def compatible(en, tr):
    """Preklad se smi lisit jen tim, ze postupne znacky prepise na pozicni (%1$s %2$d) se stejnymi typy."""
    eo, en_named, eb = specs(en)
    to, tr_named, tb = specs(tr)
    if eb != tb:
        return False
    if eo == to and en_named == tr_named:
        return True
    # anglicky postupne, preklad pozicne
    if eo and not to and not en_named:
        want = sorted(f"%{i}${s[1:]}" for i, s in enumerate(eo, 1))
        return want == tr_named
    return False


def load(lang):
    out = []
    with open(os.path.join(I18N, lang + ".tsv"), encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "\t" not in line:
                continue
            k, v = line.split("\t", 1)
            out.append((n, k, v))
    return out


class FormatSpecifiers(unittest.TestCase):
    def test_translations_keep_format_specifiers(self):
        bad = []
        for lang in LANGS:
            for n, k, v in load(lang):
                # klic "|few" je tvar mnozneho cisla - anglicky text je cast pred "|"
                en = k.rsplit("|", 1)[0] if k.endswith("|few") else k
                if not compatible(en, v):
                    bad.append(f"{lang}.tsv:{n}: {en!r} -> {v!r}")
        self.assertEqual(bad, [], f"{len(bad)} translations with different format specifiers:\n" + "\n".join(bad))

    def test_checker(self):
        # kontrola kontroly: zachyti chybejici, navic, jiny typ, prehozene poradi, jine nazvy a presnost
        ok = [("%s of %d", "%s z %d"), ("%.1f MB", "%.1f MB"), ("%(n)s/%(m)d", "%(m)d/%(n)s"), ("{a} {b}", "{b} {a}"),
              ("%s and %d", "%2$d a %1$s"), ("100%% %s", "%s 100 %%"), ("{n:.1f} s", "{n:.1f} s"),
              ("{{x}} %s", "%s {{y}}"), ("%5.2f", "%5.2f"), ("%ld", "%ld"), ("Size: %'d", "Velikost: %d"),
              ("at 20 %", "Bei 20 % automatisch")]
        bad = [("%s of %d", "%s z"), ("%s", "%s %s"), ("%d files", "%s souboru"), ("%s and %d", "%d a %s"),
               ("%.1f MB", "%.2f MB"), ("%.1f MB", "%f MB"), ("%(n)s", "%(m)s"), ("{name}", "{nazev}"),
               ("{n:.1f}", "{n}"), ("%ld", "%d"), ("%s", "{s}"), ("Hi", "Ahoj %s"), ("%s and %d", "%1$d a %2$s"),
               ("%u", "%d"), ("{}", "{0}")]
        for en, tr in ok:
            self.assertTrue(compatible(en, tr), (en, tr))
        for en, tr in bad:
            self.assertFalse(compatible(en, tr), (en, tr))


if __name__ == "__main__":
    unittest.main()
