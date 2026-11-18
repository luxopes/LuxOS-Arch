"""Data, velikosti a texty chyb podle jazyka Posty (luxos-mail --test-locale / --test-error-text), ne podle libc
locale: v systemu muze byt vygenerovane jen en_US.UTF-8 (pak strftime ukazal "Sunday" a "11/16/26" v ceske Poste).
Kody odpovedi IMAP (RFC 5530) prelozene, puvodni anglicky text serveru jen v Podrobnostech.
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

I18N = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "luxos-i18n", "files"))
NOW = 1795345200            # ne 22. 11. 2026 12:00 (Europe/Prague)


def run(args, lang):
    env = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": os.environ.get("HOME", "/tmp"), "TZ": "Europe/Prague",
           "LANG": "en_US.UTF-8", "LC_MESSAGES": lang, "LUXOS_I18N_DIR": I18N, "LUXOS_MAIL_NOW": str(NOW)}
    r = subprocess.run([mt.binary()] + args, capture_output=True, env=env, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr.decode())
    return json.loads(r.stdout)


class DateTest(unittest.TestCase):
    def dates(self, lang):
        return [run(["--test-locale", str(t), "1572864"], lang) for t in
                (NOW - 3600, NOW - 86400, NOW - 4 * 86400, NOW - 62 * 86400, NOW - 3 * 365 * 86400)]

    def test_czech_with_only_english_libc_locale(self):
        d = self.dates("cs_CZ.UTF-8")
        self.assertEqual([x["list"] for x in d], ["11:00", "Včera", "středa", "21. 9.", "23. 11. 2023"])
        self.assertEqual(d[0]["long"], "ne 22. 11. 2026 11:00")
        self.assertEqual(d[0]["size"], "1,6\u00a0MB")

    def test_german_and_english(self):
        de = self.dates("de_DE.UTF-8")
        self.assertEqual([x["list"] for x in de][1:4], ["Gestern", "Mittwoch", "21.09."])
        self.assertEqual(de[0]["long"], "So. 22.11.2026 11:00")
        en = self.dates("en_US.UTF-8")
        self.assertEqual([x["list"] for x in en], ["11:00 AM", "Yesterday", "Wednesday", "Sep 21", "Nov 23, 2023"])
        self.assertEqual(en[0]["size"], "1.6\u00a0MB")

    def test_no_english_day_names_in_other_languages(self):
        for lang in ("sk", "pl", "uk", "hu", "fr", "es", "it", "pt", "nl", "sv"):
            for x in self.dates(lang + ".UTF-8"):
                for word in ("Sunday", "Wednesday", "Sun", "Wed", "AM", "PM", "/26"):
                    self.assertNotIn(word, x["list"] + " " + x["long"], (lang, x))


class ErrorTextTest(unittest.TestCase):
    def test_authenticationfailed_without_english_server_text(self):
        r = run(["--test-error-text", "auth", "[AUTHENTICATIONFAILED] Authentication failed."], "cs_CZ.UTF-8")
        self.assertEqual(r["text"], "E-mailová adresa nebo heslo nejsou správné.")
        self.assertNotIn("Server", r["text"])
        self.assertEqual(r["details"], "[AUTHENTICATIONFAILED] Authentication failed.")

    def test_known_codes_are_translated(self):
        r = run(["--test-error-text", "auth", "[EXPIRED] Password expired."], "cs_CZ.UTF-8")
        self.assertNotIn("Password expired", r["text"])
        self.assertIn("vypršel", r["text"])
        r = run(["--test-error-text", "no", "[UNAVAILABLE] Try later"], "de_DE.UTF-8")
        self.assertNotIn("Try later", r["text"])
        self.assertIn("vorübergehend", r["text"])

    def test_keyring_unavailable_is_explained(self):
        raw = "secret-tool: Error calling StartServiceByName for org.freedesktop.secrets: Timeout was reached"
        r = run(["--test-error-text", "keyring", raw], "cs_CZ.UTF-8")
        self.assertNotIn("secret-tool", r["text"])
        self.assertNotIn("StartServiceByName", r["text"])
        self.assertIn("klíčenka", r["text"])
        self.assertEqual(r["details"], raw)


if __name__ == "__main__":
    unittest.main()
