"""luxos_glib.lsl: zachyceny vystup procesu (spawn_capture, spawn_stream) s vicebajtovymi znaky UTF-8
rozdelenymi na hranici kusu cteni (4096 B) dorazi beze zmeny; zaznam obsluhy signalu (connect_data) se uvolni
se zanikem objektu; signal UNIXu (unix_signal_add) ma prioritu DEFAULT, ne HIGH.

Spusteni: python3 -m unittest packages/luxos-desktop/tests/test_luxos_glib_lsl.py -v
LUXOS_LSLC: prekladac lslc (jinak lslc z PATH).
"""
import glob
import os
import shutil
import signal
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")


@unittest.skipUnless(LSLC, "chybi lslc (LUXOS_LSLC)")
class GlibCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-glib-")
        for f in glob.glob(os.path.join(LSL, "*.lsl")):
            shutil.copy(f, cls.tmp)
        cls.prog = os.path.join(cls.tmp, "glib-test")
        cls.signal_prog = os.path.join(cls.tmp, "signal-test")
        cls.priority_prog = os.path.join(cls.tmp, "signal-priority-test")
        for name, prog in (("luxos-glib-test", cls.prog), ("luxos-signal-test", cls.signal_prog),
                           ("luxos-signal-priority-test", cls.priority_prog)):
            shutil.copy(os.path.join(HERE, "lsl", name + ".lsl"), cls.tmp)
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", cls.tmp,
                                os.path.join(cls.tmp, name + ".lsl"), prog], capture_output=True, text=True)
            if r.returncode != 0:
                raise unittest.SkipTest(r.stdout + r.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_without_command_exits(self):
        r = subprocess.run([self.prog], capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 2)

    def test_utf8_across_read_boundary(self):
        # "č" (2 B) zacina na bajtu 4095, "𝄞" (4 B) prekracuje dalsi hranici; pomaly zapis po kusech
        text = "a" * 4095 + "čšž" + "b" * 4090 + "𝄞" + "konec"
        path = os.path.join(self.tmp, "out.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        cmd = "head -c 4096 %s; sleep 0.2; tail -c +4097 %s | head -c 4100; sleep 0.2; tail -c +8197 %s" % (path, path, path)
        # vlastni skupina procesu: po testu se ukonci vse, co by po programu zustalo
        p = subprocess.Popen([self.prog, cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = p.communicate(timeout=20)
        finally:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.assertEqual(p.returncode, 0, err)
        r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
        self.assertEqual(r.stdout.decode("utf-8").split("\n")[:2], [text, text])

    def test_signal_records_freed_with_object(self):
        r = subprocess.run([self.signal_prog], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split("\n")[:2], ["fired 1001", "alive 0 0"])

    def test_unix_signal_default_priority(self):
        # HIGH by v kole se signalem preskocil kontrolu zdroje Waylandu s rozectenym spojenim (zamrznuti hubu)
        r = subprocess.run([self.priority_prog], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split("\n")[:2], ["priority 0", "handled"])


if __name__ == "__main__":
    unittest.main()
