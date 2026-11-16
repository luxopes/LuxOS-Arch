#!/usr/bin/env python3
"""Uvitaci okno (luxos-welcome) s nahradnim yad: tlacitko Aktualizovat otevre Aktualizace softwaru
(ne Terminal se sudo lux update - audit 1.0.2), mezi textem a tlacitky je mezera.
    python3 packages/luxos-desktop/tests/test_luxos_welcome.py"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WELCOME = os.path.join(HERE, "..", "files", "bin", "luxos-welcome")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")


class Welcome(unittest.TestCase):
    def run_welcome(self, codes):
        t = tempfile.mkdtemp()
        b = os.path.join(t, "bin")
        os.makedirs(b)
        log = os.path.join(t, "log")

        def tool(name, body):
            with open(os.path.join(b, name), "w") as f:
                f.write("#!/bin/bash\n" + body + "\n")
            os.chmod(os.path.join(b, name), 0o755)
        # yad: argumenty do souboru, navratove kody postupne ze seznamu
        tool("yad", f'printf "%s\\n" "$@" >"{t}/yad-args"; n=$(cat "{t}/n" 2>/dev/null || echo 0); '
                    f'echo $((n + 1)) >"{t}/n"; codes=({" ".join(map(str, codes))}); exit ${{codes[n]:-0}}')
        for name in ("luxos-update", "luxos-terminal", "luxos-store", "luxos-tour"):
            tool(name, f'echo "{name} $*" >>"{log}"')
        tool("luxos-appearance", 'echo light')
        tool("setsid", '[[ $1 == -f ]] && shift; "$@"')
        env = {"PATH": b + ":/usr/bin", "HOME": t, "XDG_CONFIG_HOME": os.path.join(t, "cfg"),
               "LANG": "en_US.UTF-8", "LUXOS_I18N_DIR": I18N}
        src = open(WELCOME).read().replace(". /usr/lib/luxos/i18n.sh", f". {I18N}/i18n.sh")
        subprocess.run(["bash", "-c", src], env=env, timeout=30, check=True)
        calls = open(log).read() if os.path.exists(log) else ""
        return calls, open(os.path.join(t, "yad-args")).read()

    def test_update_opens_software_update(self):
        calls, _args = self.run_welcome([13, 0])
        self.assertIn("luxos-update", calls)
        self.assertNotIn("luxos-terminal", calls)

    def test_space_between_text_and_buttons(self):
        _calls, args = self.run_welcome([0])
        # text konci prazdnym radkem (yad jinak lepi tlacitka hned pod posledni radek)
        self.assertIn("from Terminal\n\n--button=", args)


if __name__ == "__main__":
    unittest.main()
