"""Skladani zprav (luxos-mail --test-compose, --test-reply) overene parserem e-mailu Pythonu: hlavicky RFC 5322
(From se jmenem, To/Cc, Bcc jen v konceptu, Subject RFC 2047, Date, Message-ID u domeny odesilatele, In-Reply-To,
References), text UTF-8 (7bit / quoted-printable / base64), prilohy multipart/mixed s nazvy RFC 2231, delka radku,
CRLF, ochrana proti vlozeni hlavicky; predmety a citace odpovedi a preposlani.
"""
import email
import email.utils
import json
import os
import sys
import tempfile
import unittest
from email import policy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="luxos-mail-compose-")
        self.n = 0

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def compose(self, **m):
        m.setdefault("from", ["Jan Novák", "jan@example.cz"])
        m.setdefault("to", [["", "petr@example.com"]])
        m.setdefault("subject", "Test")
        m.setdefault("text", "Ahoj\n")
        atts = []
        for name, data in m.pop("files", []):
            self.n += 1
            path = os.path.join(self.dir, "a%d" % self.n)
            with open(path, "wb") as f:
                f.write(data)
            atts.append({"name": name, "path": path})
        m["attachments"] = atts
        src = os.path.join(self.dir, "m.json")
        with open(src, "w") as f:
            json.dump(m, f)
        out = os.path.join(self.dir, "m.eml")
        r = mt.run_bin(["--test-compose", src, out])
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = open(out, "rb").read()
        return raw, email.message_from_bytes(raw, policy=policy.default)

    def assert_wire(self, raw):
        # jen CRLF, zadna holá LF/CR, radky do 998 bajtu, hlavicky jen ASCII
        self.assertNotIn(b"\r\r", raw)
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        for line in raw.split(b"\r\n"):
            self.assertLessEqual(len(line), 998)
        head = raw.split(b"\r\n\r\n", 1)[0]
        head.decode("ascii")
        for line in head.split(b"\r\n"):
            self.assertLessEqual(len(line), 90, line)

    def body(self, msg):
        return msg.get_body(("plain",)).get_content().replace("\r\n", "\n")

    def test_headers_czech_names_and_subject(self):
        raw, m = self.compose(to=[["Petr \"Pepa\" Dvořák", "petr@example.com"], ["Novák, Jan", "jan2@example.cz"], ["", "x@y.cz"]],
                              cc=[["Žluťoučký kůň úpěl ďábelské ódy a ještě něco navíc, aby to bylo dlouhé", "k@k.cz"]],
                              subject="Příliš žluťoučký kůň úpěl ďábelské ódy — dlouhý předmět s diakritikou 2026 a ještě delší text",
                              date=1762780000, in_reply_to="<abc@x.cz>", references="<r1@x.cz> <abc@x.cz>")
        self.assert_wire(raw)
        self.assertEqual(str(m["subject"]), "Příliš žluťoučký kůň úpěl ďábelské ódy — dlouhý předmět s diakritikou 2026 a ještě delší text")
        self.assertEqual(m["from"].addresses[0].display_name, "Jan Novák")
        self.assertEqual(m["from"].addresses[0].addr_spec, "jan@example.cz")
        to = m["to"].addresses
        self.assertEqual([(a.display_name, a.addr_spec) for a in to],
                         [("Petr \"Pepa\" Dvořák", "petr@example.com"), ("Novák, Jan", "jan2@example.cz"), ("", "x@y.cz")])
        self.assertTrue(m["cc"].addresses[0].display_name.startswith("Žluťoučký kůň"))
        self.assertEqual(email.utils.parsedate_to_datetime(m["date"]).timestamp(), 1762780000)
        self.assertTrue(m["message-id"].endswith("@example.cz>"))
        self.assertEqual(m["in-reply-to"], "<abc@x.cz>")
        self.assertEqual(m["references"], "<r1@x.cz> <abc@x.cz>")
        self.assertEqual(m["mime-version"], "1.0")
        self.assertIsNone(m["bcc"])

    def test_bcc_only_in_draft_and_undisclosed(self):
        raw, m = self.compose(to=[], bcc=[["", "tajny@x.cz"]])
        self.assertNotIn(b"tajny", raw)
        self.assertEqual(m["to"], "undisclosed-recipients:;")
        raw, m = self.compose(bcc=[["Tajný", "tajny@x.cz"]], draft=True, message_id="<draft-1@x.cz>")
        self.assertEqual(m["bcc"].addresses[0].addr_spec, "tajny@x.cz")
        self.assertEqual(m["message-id"], "<draft-1@x.cz>")

    def test_text_encodings(self):
        raw, m = self.compose(text="Hello world\nsecond line\n")
        self.assertEqual(m["content-transfer-encoding"], "7bit")
        self.assertEqual(self.body(m), "Hello world\nsecond line\n")
        cz = "Dobrý den,\n\nžluťoučký kůň úpěl ďábelské ódy.\n.tečka na začátku\nFrom here\nmezera na konci \n"
        raw, m = self.compose(text=cz)
        self.assert_wire(raw)
        self.assertEqual(m["content-transfer-encoding"], "quoted-printable")
        self.assertEqual(self.body(m), cz)
        self.assertEqual(m.get_content_charset(), "utf-8")
        uk = "Добрий день! Зустріч у п'ятницю о 15:00. Ґанок, їжак, є.\n" * 3
        raw, m = self.compose(text=uk)
        self.assertEqual(m["content-transfer-encoding"], "base64")
        self.assertEqual(self.body(m), uk)
        long_line = ("slovo " * 400).strip() + "\n"
        raw, m = self.compose(text=long_line)
        self.assert_wire(raw)
        self.assertEqual(self.body(m), long_line)
        for line in raw.split(b"\r\n\r\n", 1)[1].split(b"\r\n"):
            self.assertLessEqual(len(line), 76)

    def test_attachments_rfc2231(self):
        payload = os.urandom(5000)
        long_name = "příloha č. 1 – velmi dlouhý název souboru s diakritikou a mezerami, který se musí rozdělit.pdf"
        raw, m = self.compose(files=[(long_name, payload), ("poznámky.txt", "čeština\n".encode()), ("photo.JPG", b"\xff\xd8\xff")])
        self.assert_wire(raw)
        self.assertEqual(m.get_content_type(), "multipart/mixed")
        atts = list(m.iter_attachments())
        self.assertEqual([a.get_filename() for a in atts], [long_name, "poznámky.txt", "photo.JPG"])
        self.assertEqual(atts[0].get_content_type(), "application/pdf")
        self.assertEqual(atts[0].get_content(), payload)
        self.assertEqual(atts[1].get_content().replace("\r\n", "\n"), "čeština\n")
        self.assertEqual(atts[2].get_content_type(), "image/jpeg")
        self.assertIn(b"filename*0*=UTF-8''", raw)
        self.assertEqual(self.body(m), "Ahoj\n")

    def test_header_injection(self):
        raw, m = self.compose(subject="Ahoj\r\nBcc: obet@x.cz", to=[["Zlý\r\nX-Evil: 1", "a@b.cz>\r\nBcc: c@d.cz"]])
        self.assertIsNone(m["bcc"])
        self.assertIsNone(m["x-evil"])
        self.assertNotIn(b"\r\nBcc:", raw)
        self.assert_wire(raw)

    def test_reply_and_forward_helpers(self):
        src = os.path.join(self.dir, "orig.eml")
        with open(src, "wb") as f:
            f.write(("From: Petr <petr@example.org>\r\nTo: tester@example.test\r\nSubject: Re: Porada\r\nDate: Mon, 9 Nov 2026 18:02:00 +0100\r\n"
                     "Message-ID: <p3@example.org>\r\nReferences: <p1@example.org>\r\n <p2@example.org>\r\nMIME-Version: 1.0\r\n"
                     "Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\nAhoj,\n> starší\n\nPetr\n").encode())
        r = json.loads(mt.run_bin(["--test-reply", src]).stdout)
        self.assertEqual(r["reply_subject"], "Re: Porada")
        self.assertEqual(r["forward_subject"], "Fwd: Re: Porada")
        self.assertEqual(r["references"], "<p1@example.org> <p2@example.org> <p3@example.org>")
        self.assertEqual(r["in_reply_to"], "<p3@example.org>")
        self.assertEqual(r["quote"], "> Ahoj,\n>> starší\n>\n> Petr")
        self.assertTrue(r["rfc_date"].endswith("+0100") or r["rfc_date"][-5] in "+-")


if __name__ == "__main__":
    unittest.main()
