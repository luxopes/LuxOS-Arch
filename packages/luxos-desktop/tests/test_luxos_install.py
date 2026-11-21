#!/usr/bin/env python3
"""LuxOS - skript balicku luxos-desktop.install bez Pythonu na cilovem systemu.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_install.py -v

_luxos_own_delay (zamek po aktualizaci: vlastni doba uzivatele v xfconf zustane) dava stejny vysledek jako
drivejsi kontrola v Pythonu (xml.etree) nad souborem xfce4-screensaver.xml.
"""
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(HERE, "..", "luxos-desktop.install")

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n\n<channel name="xfce4-screensaver" version="1.0">\n'
TAIL = '</channel>\n'
CASES = {
    "own-delay": ('  <property name="lock" type="empty">\n'
                  '    <property name="enabled" type="bool" value="true"/>\n'
                  '    <property name="saver-activation" type="empty">\n'
                  '      <property name="enabled" type="bool" value="true"/>\n'
                  '      <property name="delay" type="int" value="5"/>\n'
                  '    </property>\n'
                  '  </property>\n'),
    "zero-delay": ('  <property name="lock" type="empty">\n'
                   '    <property name="saver-activation" type="empty">\n'
                   '      <property name="delay" type="int" value="0"/>\n'
                   '    </property>\n'
                   '  </property>\n'),
    "no-delay": ('  <property name="lock" type="empty">\n'
                 '    <property name="saver-activation" type="empty">\n'
                 '      <property name="enabled" type="bool" value="true"/>\n'
                 '    </property>\n'
                 '  </property>\n'),
    "delay-elsewhere": ('  <property name="saver" type="empty">\n'
                        '    <property name="saver-activation" type="empty">\n'
                        '      <property name="delay" type="int" value="5"/>\n'
                        '    </property>\n'
                        '  </property>\n'
                        '  <property name="lock" type="empty">\n'
                        '    <property name="delay" type="int" value="5"/>\n'
                        '    <property name="saver-activation" type="empty">\n'
                        '      <property name="other" type="empty">\n'
                        '        <property name="delay" type="int" value="5"/>\n'
                        '      </property>\n'
                        '    </property>\n'
                        '  </property>\n'),
    "after-sibling-group": ('  <property name="lock" type="empty">\n'
                            '    <property name="logout" type="empty">\n'
                            '      <property name="enabled" type="bool" value="false"/>\n'
                            '    </property>\n'
                            '    <property name="saver-activation" type="empty">\n'
                            '      <property name="delay" type="uint" value="10"/>\n'
                            '    </property>\n'
                            '  </property>\n'),
    "empty-delay": ('  <property name="lock" type="empty">\n'
                    '    <property name="saver-activation" type="empty">\n'
                    '      <property name="delay" type="empty"/>\n'
                    '    </property>\n'
                    '  </property>\n'),
    "empty-channel": '',
}


def python_check(path):
    """Puvodni kontrola z luxos-desktop.install (python3 -)."""
    try:
        sa = ET.parse(path).getroot().find(
            "./property[@name='lock']/property[@name='saver-activation']/property[@name='delay']")
    except (ET.ParseError, OSError):
        return False
    return sa is not None and sa.get("value") is not None


class OwnDelay(unittest.TestCase):
    def own_delay(self, path):
        r = subprocess.run(["bash", "-c", '. "$1"; _luxos_own_delay "$2"', "x", INSTALL, path],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout + r.stderr, "")
        return r.returncode == 0

    def test_same_as_python(self):
        with tempfile.TemporaryDirectory() as d:
            for name, body in CASES.items():
                path = os.path.join(d, name + ".xml")
                with open(path, "w") as f:
                    f.write(HEAD + body + TAIL)
                with self.subTest(name):
                    self.assertEqual(self.own_delay(path), python_check(path))
            self.assertTrue(self.own_delay(os.path.join(d, "own-delay.xml")))
            self.assertFalse(self.own_delay(os.path.join(d, "no-delay.xml")))
            # poskozeny nebo chybejici soubor: delay se nastavi (jako drive pri chybe Pythonu)
            bad = os.path.join(d, "bad.xml")
            with open(bad, "w") as f:
                f.write("<channel><property name=")
            self.assertFalse(self.own_delay(bad))
            self.assertFalse(self.own_delay(os.path.join(d, "missing.xml")))


if __name__ == "__main__":
    unittest.main()
