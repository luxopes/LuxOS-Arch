"""Ukladani prijatych souboru na skutecnem disku, bez site a bez oken."""
import errno
import os
import shutil
import sys
import tempfile
import threading
import unicodedata
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.join(HERE, "..", "files", "lib")))
from luxdrop import pathsafe, proto, transfer  # noqa: E402


class FilePlacement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxdrop-placement-")
        self.stage, self.dest = (os.path.join(self.tmp, n) for n in ("stage", "dest"))
        os.mkdir(self.stage)
        os.mkdir(self.dest)
        self.sfd = os.open(self.stage, os.O_RDONLY | os.O_DIRECTORY)
        self.dfd = os.open(self.dest, os.O_RDONLY | os.O_DIRECTORY)

    def tearDown(self):
        os.close(self.sfd)
        os.close(self.dfd)
        shutil.rmtree(self.tmp)

    def write(self, folder, name, data):
        with open(os.path.join(folder, name), "w") as f:
            f.write(data)

    def read(self, folder, name):
        with open(os.path.join(folder, name)) as f:
            return f.read()

    def test_duplicate_maximum_length_names(self):
        for name in ("a" * 251 + ".txt", "ž" * 125 + "x.txt", "x." + "a" * 253):
            with self.subTest(name=name):
                self.write(self.dest, name, "original")
                self.write(self.stage, "incoming", "received")
                saved = transfer._place_file(self.sfd, "incoming", self.dfd, name)
                self.assertNotEqual(saved, name)
                self.assertLessEqual(len(saved.encode("utf-8")), 255)
                self.assertEqual(self.read(self.dest, name), "original")
                self.assertEqual(self.read(self.dest, saved), "received")
                if name.endswith(".txt"):
                    self.assertTrue(saved.endswith(".txt"))

    def test_duplicate_maximum_length_directory(self):
        name = "界" * 85
        os.mkdir(os.path.join(self.dest, name))
        saved = transfer._reserve_dir(self.dfd, name)
        self.assertNotEqual(saved, name)
        self.assertLessEqual(len(saved.encode("utf-8")), 255)
        self.assertTrue(os.path.isdir(os.path.join(self.dest, saved)))

    def test_concurrent_no_hardlink_transfers_keep_both_files(self):
        self.write(self.stage, "one", "first transfer")
        self.write(self.stage, "two", "second transfer")
        barrier = threading.Barrier(2)
        link_barrier = threading.Barrier(2)
        original_rename = os.rename
        saved, errors = [], []

        def racing_rename(*args, **kwargs):
            # Oba stare testy existence musi probehnout pred kterymkoli prejmenovanim.
            barrier.wait(3)
            return original_rename(*args, **kwargs)

        def no_hardlinks(_src, dst, **_kwargs):
            if dst == "report.txt":
                link_barrier.wait(3)
            raise OSError(errno.EOPNOTSUPP, "no hard links")

        def receive(name):
            try:
                saved.append(transfer._place_file(self.sfd, name, self.dfd, "report.txt"))
            except Exception as e:
                errors.append(e)

        with mock.patch.object(transfer.os, "link", side_effect=no_hardlinks), \
                mock.patch.object(transfer.os, "rename", side_effect=racing_rename):
            threads = [threading.Thread(target=receive, args=(n,)) for n in ("one", "two")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(set(saved)), 2)
        self.assertEqual({self.read(self.dest, n) for n in saved}, {"first transfer", "second transfer"})

    def test_failed_partial_cleanup_does_not_create_repeated_copies(self):
        self.write(self.stage, "incoming", "complete file")
        original_link = os.link
        calls = []

        def bounded_link(*args, **kwargs):
            calls.append(args[1])
            if len(calls) > 1:
                raise AssertionError("chyba uklidu nesmi spoustet dalsi pokusy o ulozeni")
            return original_link(*args, **kwargs)

        with mock.patch.object(transfer.os, "link", side_effect=bounded_link), \
                mock.patch.object(transfer.os, "unlink", side_effect=PermissionError(errno.EACCES, "cleanup denied")):
            with self.assertRaises(PermissionError):
                transfer._place_file(self.sfd, "incoming", self.dfd, "report.txt")
        self.assertEqual(calls, ["report.txt"])
        self.assertEqual(os.listdir(self.dest), ["report.txt"])
        self.assertEqual(self.read(self.dest, "report.txt"), "complete file")
        self.assertEqual(self.read(self.stage, "incoming"), "complete file")

    def test_no_hardlink_fallback_preserves_existing_file_and_symlink(self):
        self.write(self.dest, "report.txt", "original")
        os.symlink("report.txt", os.path.join(self.dest, "report (1).txt"))
        self.write(self.stage, "incoming", "received")
        with mock.patch.object(transfer.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "no hard links")):
            saved = transfer._place_file(self.sfd, "incoming", self.dfd, "report.txt")
        self.assertEqual(saved, "report (2).txt")
        self.assertEqual(self.read(self.dest, "report.txt"), "original")
        self.assertTrue(os.path.islink(os.path.join(self.dest, "report (1).txt")))
        self.assertEqual(self.read(self.dest, saved), "received")

    def test_unsupported_atomic_rename_keeps_both_originals(self):
        self.write(self.stage, "incoming", "received")
        self.write(self.dest, "report.txt", "original")
        with mock.patch.object(transfer.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "no hard links")), \
                mock.patch.object(transfer, "_rename_noreplace", side_effect=OSError(errno.EOPNOTSUPP, "unsupported")):
            with self.assertRaises(OSError):
                transfer._place_file(self.sfd, "incoming", self.dfd, "report.txt")
        self.assertEqual(self.read(self.dest, "report.txt"), "original")
        self.assertEqual(self.read(self.stage, "incoming"), "received")

    def test_fixed_destination_conflict_is_rejected_without_overwriting(self):
        self.write(self.stage, "incoming", "received")
        self.write(self.dest, "report.txt", "original")
        with mock.patch.object(transfer.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "no hard links")):
            with self.assertRaises(proto.ProtocolError) as error:
                transfer._place_file(self.sfd, "incoming", self.dfd, "report.txt", unique=False)
        self.assertEqual(error.exception.code, proto.E_INVALID_OFFER)
        self.assertEqual(self.read(self.dest, "report.txt"), "original")
        self.assertEqual(self.read(self.stage, "incoming"), "received")

    def test_many_long_name_collisions_stay_unique(self):
        name = "a" * 255
        saved = []
        for i in range(12):
            self.write(self.stage, "incoming", str(i))
            saved.append(transfer._place_file(self.sfd, "incoming", self.dfd, name))
        self.assertEqual(len(set(saved)), 12)
        for i, final in enumerate(saved):
            self.assertLessEqual(len(final.encode("utf-8")), 255)
            self.assertEqual(self.read(self.dest, final), str(i))

    def test_selecting_two_long_identical_names_can_be_sent(self):
        name = "a" * 251 + ".txt"
        self.write(self.stage, name, "first")
        self.write(self.dest, name, "second")
        items, _dirs = pathsafe.collect([os.path.join(self.stage, name), os.path.join(self.dest, name)])
        self.assertEqual(len({rel for _p, rel, _s, _x in items}), 2)
        self.assertEqual([self.read(os.path.dirname(p), os.path.basename(p)) for p, _r, _s, _x in items],
                         ["first", "second"])

    def test_unicode_normalization_does_not_create_duplicate_offer_paths(self):
        name = "café.txt"
        self.write(self.stage, name, "NFC")
        self.write(self.stage, unicodedata.normalize("NFD", name), "NFD")
        items, dirs = pathsafe.collect([self.stage])
        self.assertEqual(len(items), 2)
        self.assertEqual(len({rel for _p, rel, _s, _x in items}), 2)
        # Prijemce musi nabidku prijmout; obsah obou odlisnych zdrojovych souboru zustava zachovan.
        offer = {"files": [{"path": r, "size": s, "sha256": "00" * 32} for _p, r, s, _x in items], "dirs": dirs}
        pathsafe.check_offer(offer)
        self.assertEqual({self.read(os.path.dirname(p), os.path.basename(p)) for p, _r, _s, _x in items}, {"NFC", "NFD"})


if __name__ == "__main__":
    unittest.main()
