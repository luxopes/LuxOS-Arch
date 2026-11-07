#!/usr/bin/env python3
"""Vytvori testovaci zpravy (tests/fixtures/*.eml) v ruznych kodovanich a znakovych sadach.

Soubory jsou v repozitari; skript je jen pro pripadne obnoveni: python3 make_fixtures.py
"""
import base64
import os
import quopri

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")


def crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def write(name, data):
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(data)


def main():
    os.makedirs(OUT, exist_ok=True)
    cs = "Dobrý den,\npříliš žluťoučký kůň úpěl ďábelské ódy.\nS pozdravem\nJana"
    # 1) cestina v ISO-8859-2, quoted-printable, predmet RFC 2047 Q
    body = quopri.encodestring(cs.encode("iso-8859-2")).decode()
    write("cs-iso88592-qp.eml", crlf(
        "From: =?ISO-8859-2?Q?Jana_Dvo=F8=E1kov=E1?= <jana@example.cz>\n"
        "To: info@example.test\n"
        "Subject: =?ISO-8859-2?Q?P=F8=EDli=B9_=BElu=BBou=E8k=FD_k=F9=F2?=\n"
        "Date: Tue, 03 Nov 2026 09:15:00 +0100\n"
        "Message-ID: <cs1@example.cz>\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=ISO-8859-2\n"
        "Content-Transfer-Encoding: quoted-printable\n\n" + body).encode("ascii"))
    # 2) cestina windows-1250 8bit, predmet RFC 2047 B rozdeleny do dvou slov (vicebajtovy znak v UTF-8 na hranici)
    subj = "Faktura č. 2026/118 – říjen".encode("utf-8")
    w1 = base64.b64encode(subj[:13]).decode()
    w2 = base64.b64encode(subj[13:]).decode()
    write("cs-cp1250-8bit.eml", crlf(
        "From: \"Účtárna s.r.o.\" <uctarna@example.cz>\n"
        "To: info@example.test\n"
        "Subject: =?UTF-8?B?" + w1 + "?=\n =?UTF-8?B?" + w2 + "?=\n"
        "Date: Mon, 2 Nov 2026 16:40:12 +0100\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=windows-1250\n"
        "Content-Transfer-Encoding: 8bit\n\n").encode("cp1250") + crlf("Částka: 12 500 Kč\nSplatnost: 14 dní").encode("cp1250"))
    # 3) nemcina: multipart/alternative, text/plain iso-8859-1 QP + HTML
    de_plain = "Grüße aus München!\nÜbermorgen um 10 Uhr – passt das?"
    de_html = "<html><head><style>p{color:red}</style><script>alert(1)</script></head><body><p>Gr&uuml;&szlig;e aus <b>M&uuml;nchen</b>!</p></body></html>"
    write("de-alternative.eml", crlf(
        "From: =?utf-8?q?J=C3=BCrgen_M=C3=BCller?= <juergen@example.de>\n"
        "To: Info <info@example.test>, \"Novák, Jan\" <jan@example.cz>\n"
        "Cc: team@example.de\n"
        "Subject: =?iso-8859-1?Q?Gr=FC=DFe?= aus =?utf-8?B?TcO8bmNoZW4=?=\n"
        "Date: Sun, 1 Nov 2026 08:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        "Content-Type: multipart/alternative; boundary=\"ALT-123\"\n\n"
        "This is a multi-part message in MIME format.\n"
        "--ALT-123\n"
        "Content-Type: text/plain; charset=iso-8859-1\n"
        "Content-Transfer-Encoding: quoted-printable\n\n" + quopri.encodestring(de_plain.encode("cp1252")).decode() + "\n"
        "--ALT-123\n"
        "Content-Type: text/html; charset=us-ascii\n\n" + de_html + "\n"
        "--ALT-123--\n").encode("utf-8"))
    # 4) ukrajinstina: KOI8-U base64 a predmet windows-1251
    uk = "Добрий день! Зустріч у п'ятницю о 15:00. Ґанок, їжак, є."
    write("uk-koi8u-base64.eml", crlf(
        "From: =?windows-1251?B?" + base64.b64encode("Олена Ковальчук".encode("cp1251")).decode() + "?= <olena@example.ua>\n"
        "To: info@example.test\n"
        "Subject: =?KOI8-U?B?" + base64.b64encode("Зустріч у п'ятницю".encode("koi8_u")).decode() + "?=\n"
        "Date: Fri, 30 Oct 2026 12:00:00 +0200\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=\"koi8-u\"\n"
        "Content-Transfer-Encoding: base64\n\n" + base64.encodebytes(uk.encode("koi8_u")).decode()).encode("ascii"))
    # 5) multipart/mixed s prilohou PDF (RFC 2231 nazev v UTF-8) a vlozenou textovou prilohou
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    write("mixed-attachment.eml", crlf(
        "From: Jan Novák <jan@example.cz>\n"
        "To: info@example.test\n"
        "Subject: Smlouva k podpisu\n"
        "Date: Thu, 29 Oct 2026 10:30:00 +0100\n"
        "MIME-Version: 1.0\n"
        "Content-Type: multipart/mixed; boundary=\"MIX\"\n\n"
        "--MIX\n"
        "Content-Type: multipart/alternative; boundary=\"ALT\"\n\n"
        "--ALT\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "Content-Transfer-Encoding: 8bit\n\n"
        "V příloze posílám smlouvu.\n"
        "--ALT\n"
        "Content-Type: text/html; charset=utf-8\n\n"
        "<p>V příloze posílám <i>smlouvu</i>.</p>\n"
        "--ALT--\n"
        "--MIX\n"
        "Content-Type: application/pdf; name=\"smlouva.pdf\"\n"
        "Content-Disposition: attachment;\n filename*0*=UTF-8''smlouva%20%C4%8D.;\n filename*1=\"2026.pdf\"\n"
        "Content-Transfer-Encoding: base64\n\n" + base64.encodebytes(pdf).decode() +
        "--MIX\n"
        "Content-Type: text/plain; charset=utf-8; name=\"poznamka.txt\"\n"
        "Content-Disposition: attachment; filename=\"=?UTF-8?Q?pozn=C3=A1mka.txt?=\"\n\n"
        "Poznámka\n"
        "--MIX--\n").encode("utf-8"))
    with open(os.path.join(OUT, "mixed-attachment.pdf"), "wb") as f:
        f.write(pdf)
    # 6) jen HTML (newsletter) s odkazy, entitami, tabulkou, obrazkem s alt a vzdalenym obrazkem
    html = ("<!DOCTYPE html><html><head><title>Novinky</title><style>.x{}</style></head><body>"
            "<!-- komentar --><h1>Novinky&nbsp;v&nbsp;listopadu</h1><p>Ahoj,<br>m&aacute;me pro tebe <a href=\"https://example.cz/akce?id=1\">akci</a> &ndash; 20&nbsp;% sleva.</p>"
            "<ul><li>Prvn&iacute;</li><li>Druh&aacute; &amp; t&#345;et&iacute;</li></ul>"
            "<table><tr><td>Cena</td><td>1&nbsp;200&nbsp;K&#269;</td></tr></table>"
            "<img src=\"https://tracker.example/pixel.gif\" width=1 height=1><img src=\"cid:logo\" alt=\"Logo\">"
            "<pre>  zachovat   mezery</pre><p>&#x1F600; &euro;</p></body></html>")
    write("html-only.eml", crlf(
        "From: Obchod <news@shop.example>\n"
        "To: info@example.test\n"
        "Subject: Novinky\n"
        "Date: Wed, 28 Oct 2026 07:00:00 GMT\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "Content-Transfer-Encoding: quoted-printable\n\n" + quopri.encodestring(html.encode("utf-8")).decode()).encode("ascii"))
    # 7) format=flowed
    write("flowed.eml", crlf(
        "From: a@example.test\n"
        "To: info@example.test\n"
        "Subject: flowed\n"
        "Date: 27 Oct 2026 22:10 +0100\n"
        "Content-Type: text/plain; charset=utf-8; format=flowed\n\n"
        "Tohle je dlouhy odstavec, ktery \nse zalomil na vice \nradku.\n\n> citace\n-- \npodpis\n").encode("utf-8"))
    # 8) bez Content-Type, 8bit bez oznaceni sady (UTF-8 a cp1250)
    write("no-charset-utf8.eml", crlf("From: x@example.test\nSubject: Žádná sada\n\nText v UTF-8: čeština\n").encode("utf-8"))
    write("no-charset-cp1250.eml", crlf("From: x@example.test\nSubject: test\n\n").encode("ascii") + "Text: čeština".encode("cp1250"))
    # 9) seznam IMAP odpovedi pro test parseru
    lit = "Příloha {x}".encode("utf-8")
    resp = (b"* LIST (\\HasNoChildren \\Sent) \"/\" \"Odeslan&AOk- po&AWE-ta\"\r\n"
            b"* LIST (\\Noselect) \".\" {7}\r\nArchiv.\r\n"
            b"* 12 FETCH (UID 34 FLAGS (\\Seen $Forwarded) INTERNALDATE \"05-Nov-2026 14:03:22 +0100\" RFC822.SIZE 2048 "
            b"ENVELOPE (\"Tue, 5 Nov 2026 14:03:22 +0100\" {" + str(len(lit)).encode() + b"}\r\n" + lit +
            b" ((\"=?utf-8?Q?Jan_Nov=C3=A1k?=\" NIL \"jan\" \"example.cz\")) NIL NIL "
            b"((\"Info\" NIL \"info\" \"lux-ai.cz\")(NIL NIL \"team\" NIL)(NIL NIL \"a\" \"b.cz\")(NIL NIL NIL NIL)) NIL NIL NIL \"<a@b>\") "
            b"BODYSTRUCTURE ((\"text\" \"plain\" (\"charset\" \"utf-8\") NIL NIL \"quoted-printable\" 120 4 NIL NIL NIL)"
            b"((\"text\" \"html\" (\"charset\" \"utf-8\") NIL NIL \"7bit\" 300 9 NIL NIL NIL)(\"image\" \"png\" (\"name\" \"logo.png\") \"<logo>\" NIL \"base64\" 900 NIL (\"inline\" NIL) NIL) \"related\" (\"boundary\" \"r\") NIL NIL)"
            b"(\"application\" \"pdf\" (\"name\" \"f.pdf\") NIL NIL \"base64\" 5000 NIL (\"attachment\" (\"filename*\" \"utf-8''faktura%20%C4%8D.pdf\")) NIL) "
            b"\"mixed\" (\"boundary\" \"xx\") NIL NIL) BODY[1]<0> {12}\r\nAhoj (svete))\r\n"
            b"* 13 FETCH (UID 35 FLAGS () BODYSTRUCTURE (\"TEXT\" \"PLAIN\" (\"CHARSET\" \"iso-8859-2\") NIL NIL \"8BIT\" 10 1 NIL NIL NIL NIL))\r\n"
            b"* VANISHED (EARLIER) 1:3,7\r\n"
            b"L5 OK [HIGHESTMODSEQ 99] done\r\n")
    write("imap-responses.txt", resp)


if __name__ == "__main__":
    main()
