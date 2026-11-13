"""The shipped LuxAI source archive includes the native weather integration."""
import re
from pathlib import Path
import tarfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


class WeatherPackage(unittest.TestCase):
    def test_archive_and_dependency_include_weather(self):
        pkgbuild = (PACKAGE / 'PKGBUILD').read_text()
        version = re.search(r'^pkgver=(\S+)', pkgbuild, re.M).group(1)
        with tarfile.open(PACKAGE / f'luxai-{version}.tar.gz') as archive:
            names = set(archive.getnames())
            for path in ('lsl/weather.lsl', 'lsl/weather_data.lsl', 'docs/WEATHER.md'):
                self.assertIn(f'luxai-{version}/{path}', names)
        self.assertIn('luxos-weather>=1.0.0-5', pkgbuild)
        self.assertIn('docs/WEATHER.md', pkgbuild)
