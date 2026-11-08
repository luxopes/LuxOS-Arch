"""Testovaci server IMAP pro ukazkove video Posty (overeni u Googlu): fake_imap.py z testu Posty
v podobe Gmailu (--personality gmail: [Gmail]/..., XOAUTH2/OAUTHBEARER), s anglickymi stitky misto
ceskych testovacich slozek a datem prijeti podle hlavicky Date. Jen ukazkova data, jen 127.0.0.1.

    python3 demo_imap.py TESTS_DIR [argumenty fake_imap.py]
"""
import email
import email.utils
import sys

sys.path.insert(0, sys.argv[1])
import fake_imap  # noqa: E402

RENAME = {"Faktury": "Receipts", "Faktury/2026": "Travel"}
_add = fake_imap.Mailbox.add


def add(self, raw, flags=(), internal=None):
    date = email.message_from_bytes(raw).get("Date")
    if date:
        try:
            internal = email.utils.parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            pass
    return _add(self, raw, flags, internal)


def _get_boxes(self):
    return self._boxes


def _set_boxes(self, boxes):
    out = {}
    for name, box in boxes.items():
        new = RENAME.get(name, name)
        box.name = new
        out[new] = box
    self._boxes = out


fake_imap.Mailbox.add = add
fake_imap.State.boxes = property(_get_boxes, _set_boxes)
sys.argv = [fake_imap.__file__] + sys.argv[2:]
fake_imap.main()
