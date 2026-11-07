"""Testovaci server IMAP Posty (packages/apps/luxos-mail/tests/fake_imap.py) pro snimky:
datum prijeti zpravy podle jeji hlavicky Date (seznam ukaze ruzne casy, ne vsude stejny den)
a bez ceske testovaci slozky "Odeslane" (anglicke ukazkove rozhrani).

    python3 _a_fake_imap.py TESTS_DIR [argumenty fake_imap.py]
"""
import email
import email.utils
import sys

sys.path.insert(0, sys.argv[1])
import fake_imap  # noqa: E402

_add = fake_imap.Mailbox.add
_init = fake_imap.State.__init__


def add(self, raw, flags=(), internal=None):
    date = email.message_from_bytes(raw).get("Date")
    if date:
        try:
            internal = email.utils.parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            pass
    return _add(self, raw, flags, internal)


def init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    self.boxes.pop("Odeslan&AOk-", None)


fake_imap.Mailbox.add = add
fake_imap.State.__init__ = init
sys.argv = [fake_imap.__file__] + sys.argv[2:]
fake_imap.main()
