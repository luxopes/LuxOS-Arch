#!/usr/bin/env python3
"""LuxOS - lupa Hledani v horni liste: luxos-search --panel a --add-to-panel (starsi profily).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_search_panel.py -v

xfconf-query, pgrep a xfce4-panel jsou falesne programy v PATH (kanal xfce4-panel v JSON),
domov v docasne slozce - nic se nemeni na skutecnem systemu.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = os.path.normpath(os.path.join(HERE, "..", "files", "bin", "luxos-search"))
PANEL_XML = os.path.normpath(os.path.join(HERE, "..", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml",
                                          "xfce4-panel.xml"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

# Falesny xfconf-query: vlastnosti kanalu v $FAKE_XFCONF (JSON {cesta: hodnota nebo [pole]})
FAKE_XFCONF = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_XFCONF"]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_XFCONF_DOWN"):
    sys.exit(1)
data = json.load(open(path))
a = sys.argv[1:]
prop, values, lst, force_array, i = None, [], False, False, 0
while i < len(a):
    if a[i] == "-c": i += 1
    elif a[i] == "-p": prop = a[i + 1]; i += 1
    elif a[i] == "-l": lst = True
    elif a[i] == "-s": values.append(a[i + 1]); i += 1
    elif a[i] == "-t": i += 1
    elif a[i] == "--force-array": force_array = True
    i += 1
if lst:
    for k in sorted(data):
        if prop is None or k == prop or k.startswith(prop + "/"):
            print(k)
    sys.exit(0)
if values:
    data[prop] = values if (force_array or len(values) > 1) else values[0]
    json.dump(data, open(path, "w"))
    sys.exit(0)
if prop not in data:
    print('Property "%s" does not exist on channel "xfce4-panel".' % prop, file=sys.stderr)
    sys.exit(1)
v = data[prop]
if isinstance(v, list):
    print("Value is an array with %d items:\n" % len(v))
    for x in v:
        print(x)
else:
    print(v)
'''


def channel_from_xml(path):
    """Vychozi kanal xfce4-panel z LuxOS jako slovnik vlastnosti (jako xfconfd)."""
    out = {}

    def walk(el, base):
        for p in el.findall("property"):
            name = base + "/" + p.get("name")
            vals = [v.get("value") for v in p.findall("value")]
            if p.get("type") == "array":
                out[name] = vals
            elif p.get("type") != "empty":
                out[name] = p.get("value")
            walk(p, name)
    walk(ET.parse(path).getroot(), "")
    return out


class SearchPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-search-")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(fake)
        progs = {"xfconf-query": FAKE_XFCONF,
                 "pgrep": "#!/bin/sh\nexit 0\n",
                 "xfce4-panel": '#!/bin/sh\necho "xfce4-panel $*" >>"$FAKE_LOG"\n'}
        for name, body in progs.items():
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.xfconf = os.path.join(self.tmp, "panel.json")
        self.log = os.path.join(self.tmp, "calls.log")
        self.cfg = os.path.join(self.tmp, "config")
        self.env = {"PATH": fake + ":/usr/bin:/bin", "HOME": self.tmp, "XDG_CONFIG_HOME": self.cfg, "USER": "test",
                    "LANG": "C", "FAKE_XFCONF": self.xfconf, "FAKE_LOG": self.log, "LUXOS_I18N_DIR": I18N}

    def write_channel(self, data):
        with open(self.xfconf, "w") as f:
            json.dump(data, f)

    def channel(self):
        with open(self.xfconf) as f:
            return json.load(f)

    def run_search(self, *args, **env):
        return subprocess.run([SEARCH, *args], env={**self.env, **env}, capture_output=True, text=True, timeout=20)

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def old_profile(self):
        """Profil z LuxOS 0.9.12: vychozi lista bez lupy (plugin-15)."""
        data = channel_from_xml(PANEL_XML)
        for k in [k for k in data if k.startswith("/plugins/plugin-15")]:
            del data[k]
        data["/panels/panel-1/plugin-ids"] = [v for v in data["/panels/panel-1/plugin-ids"] if v != "15"]
        return data

    def test_panel_output(self):
        out = self.run_search("--panel")
        self.assertEqual(out.stdout, "<icon>luxos-search-symbolic</icon><iconclick>luxos-search</iconclick>"
                         "<tool>Search</tool>\n")
        cs = self.run_search("--panel", LANG="cs_CZ.UTF-8").stdout
        self.assertIn("<tool>Hledat</tool>", cs)

    def test_default_panel_has_search_before_control_center(self):
        data = channel_from_xml(PANEL_XML)
        ids = data["/panels/panel-1/plugin-ids"]
        search = next(k.split("-")[1].split("/")[0] for k, v in data.items() if v == "luxos-search --panel")
        cc = next(k.split("-")[1].split("/")[0] for k, v in data.items() if v == "luxos-control-center --panel")
        self.assertEqual(ids.index(search) + 1, ids.index(cc))
        self.assertEqual(data["/plugins/plugin-" + search], "genmon")

    def test_new_profile_only_marks(self):
        self.write_channel(channel_from_xml(PANEL_XML))
        before = self.channel()
        self.assertEqual(self.run_search("--add-to-panel").returncode, 0)
        self.assertEqual(self.channel(), before)
        self.assertTrue(os.path.exists(os.path.join(self.cfg, "luxos", "search-icon-added")))
        self.assertFalse(any(c.startswith("xfce4-panel") for c in self.calls()))

    def test_old_profile_gets_search_once(self):
        self.write_channel(self.old_profile())
        self.assertEqual(self.run_search("--add-to-panel").returncode, 0)
        data = self.channel()
        ids = data["/panels/panel-1/plugin-ids"]
        self.assertEqual(ids[ids.index("12") - 1], "15")          # nove id = nejvyssi + 1, pred Ovladacim centrem
        self.assertEqual(data["/plugins/plugin-15"], "genmon")
        self.assertEqual(data["/plugins/plugin-15/command"], "luxos-search --panel")
        self.assertEqual(data["/plugins/plugin-15/update-period"], "86400000")
        self.assertIn("xfce4-panel -r", self.calls())
        # uzivatel lupu odebere: uz se nevrati
        data["/panels/panel-1/plugin-ids"].remove("15")
        self.write_channel(data)
        open(self.log, "w").close()
        self.run_search("--add-to-panel")
        self.assertNotIn("15", self.channel()["/panels/panel-1/plugin-ids"])
        self.assertEqual(self.calls(), [])

    def test_custom_panel_without_control_center_unchanged(self):
        data = self.old_profile()
        data["/panels/panel-1/plugin-ids"].remove("12")
        del data["/plugins/plugin-12"], data["/plugins/plugin-12/command"]
        self.write_channel(data)
        self.run_search("--add-to-panel")
        self.assertEqual(self.channel(), data)
        self.assertTrue(os.path.exists(os.path.join(self.cfg, "luxos", "search-icon-added")))

    def test_xfconf_not_running_retries_next_login(self):
        self.write_channel(self.old_profile())
        self.run_search("--add-to-panel", FAKE_XFCONF_DOWN="1")
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "luxos", "search-icon-added")))

    def test_session_calls_migration(self):
        with open(os.path.join(HERE, "..", "files", "bin", "luxos-session")) as f:
            self.assertTrue(re.search(r"luxos-search --add-to-panel", f.read()))


if __name__ == "__main__":
    unittest.main()
