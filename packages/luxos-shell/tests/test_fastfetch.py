"""Default fastfetch uses the terminal's image and current LuxOS configuration.

The real fastfetch is replaced by a recorder; no terminal/real profile is touched.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "files/fastfetch/fastfetch"


class Fastfetch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="luxos-fetch-")
        root = Path(self.temp.name)
        self.logo = root / "logo with spaces.six"
        self.logo.write_bytes(b"image")
        self.conf = root / "config.jsonc"
        self.conf.write_text('{"logo":{"type":"none"}}')
        binary = root / "recorder"
        binary.write_text("#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        binary.chmod(0o755)
        self.wrapper = root / "fastfetch"
        self.wrapper.write_text(SOURCE.read_text().replace("/usr/bin/fastfetch", str(binary)).replace(
            "/etc/xdg/luxos/fastfetch/config.jsonc", str(self.conf)))
        self.env = dict(os.environ, TERM_PROGRAM="LuxOS-Terminal", TERM="xterm-256color",
                        LUXOS_TERMINAL_LOGO=str(self.logo))

    def tearDown(self):
        self.temp.cleanup()

    def run_fetch(self, *args):
        result = subprocess.run(["/bin/sh", str(self.wrapper), *args], env=self.env,
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_plain_command_uses_current_config_and_image(self):
        self.assertEqual(self.run_fetch(), ["--config", str(self.conf), "--logo-type", "raw",
                                           "--logo", str(self.logo)])

    def test_explicit_options_are_preserved(self):
        for args in (("--help",), ("--format", "json"), ("-c", "my config.jsonc"),
                     ("--logo-type", "none"), ("--structure", "OS")):
            with self.subTest(args=args):
                self.assertEqual(self.run_fetch(*args), list(args))

    def test_other_terminal_or_missing_image_has_unicode_fallback(self):
        for key, value in (("TERM_PROGRAM", "tmux"), ("TERM", "screen-256color"),
                           ("LUXOS_TERMINAL_LOGO", "/missing/image")):
            original = self.env[key]
            self.env[key] = value
            self.assertEqual(self.run_fetch(), ["--config", str(self.conf)])
            self.env[key] = original

    def test_missing_config_still_passes_image(self):
        self.conf.unlink()
        self.assertEqual(self.run_fetch(), ["--logo-type", "raw", "--logo", str(self.logo)])
