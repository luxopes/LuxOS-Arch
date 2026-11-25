"""Regrese mapovani XDG slozek na home po prihlaseni do Waylandu."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "files/session/luxos-user-dirs-repair"
FOLDERS = {
    "DESKTOP": "Desktop",
    "DOWNLOAD": "Downloads",
    "TEMPLATES": "Templates",
    "PUBLICSHARE": "Public",
    "DOCUMENTS": "Documents",
    "MUSIC": "Music",
    "PICTURES": "Pictures",
    "VIDEOS": "Videos",
    "PROJECTS": "Projects",
}


class UserDirsRepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = self.home / ".config"
        self.config.mkdir()
        self.file = self.config / "user-dirs.dirs"
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.config),
                        XDG_STATE_HOME=str(self.home / ".local/state"))
        for folder in FOLDERS.values():
            (self.home / folder).mkdir()
        self.auth = self.home / ".codex/auth.json"
        self.auth.parent.mkdir()
        self.auth.write_text("saved-auth-marker")

    def write_dirs(self, paths):
        self.file.write_text("".join(f'XDG_{key}_DIR="$HOME/{value}"\n'
                                     for key, value in paths.items()))

    def run_repair(self):
        subprocess.run(["bash", str(SCRIPT)], env=self.env, check=True)

    def test_repairs_known_broken_pattern_and_keeps_custom_path_and_auth(self):
        paths = {key: "" for key in FOLDERS}
        paths["DOWNLOAD"] = "Downloads"
        self.write_dirs(paths)
        original = self.file.read_text()

        self.run_repair()

        for key, folder in FOLDERS.items():
            result = subprocess.check_output(["xdg-user-dir", key], env=self.env, text=True).strip()
            self.assertEqual(result, str(self.home / folder))
        backup = self.home / ".local/state/luxos/user-dirs.dirs.before-wayland-repair"
        self.assertEqual(backup.read_text(), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.auth.read_text(), "saved-auth-marker")
        fixed = self.file.read_text()
        self.run_repair()
        self.assertEqual(self.file.read_text(), fixed)

    def test_leaves_user_chosen_layout_untouched(self):
        paths = {key: "" for key in FOLDERS}
        paths["DOWNLOAD"] = "my-downloads"
        paths["DOCUMENTS"] = "my-docs"
        self.write_dirs(paths)
        original = self.file.read_text()

        self.run_repair()

        self.assertEqual(self.file.read_text(), original)
        self.assertFalse((self.home / ".local/state/luxos").exists())
        self.assertEqual(self.auth.read_text(), "saved-auth-marker")

    def test_leaves_eight_home_paths_with_other_custom_folder_untouched(self):
        paths = {key: "" for key in FOLDERS}
        paths["PICTURES"] = "my-pictures"
        self.write_dirs(paths)
        original = self.file.read_text()

        self.run_repair()

        self.assertEqual(self.file.read_text(), original)
        self.assertFalse((self.home / ".local/state/luxos").exists())

    def test_missing_directory_does_not_get_substituted(self):
        self.write_dirs({key: "" for key in FOLDERS})
        (self.home / "Pictures").rmdir()

        self.run_repair()

        self.assertEqual(subprocess.check_output(["xdg-user-dir", "PICTURES"],
                                              env=self.env, text=True).strip(), str(self.home) + "/")
        self.assertEqual(subprocess.check_output(["xdg-user-dir", "DOCUMENTS"],
                                              env=self.env, text=True).strip(), str(self.home / "Documents"))

    def test_missing_configuration_is_untouched(self):
        self.run_repair()
        self.assertFalse(self.file.exists())
        self.assertEqual(self.auth.read_text(), "saved-auth-marker")

    def test_first_login_generates_default_paths_without_migration(self):
        subprocess.run(["xdg-user-dirs-update"], env=self.env, check=True)
        original = self.file.read_text()

        self.run_repair()

        self.assertEqual(self.file.read_text(), original)
        self.assertEqual(subprocess.check_output(["xdg-user-dir", "DOWNLOAD"],
                                              env=self.env, text=True).strip(), str(self.home / "Downloads"))
        self.assertFalse((self.home / ".local/state/luxos").exists())


if __name__ == "__main__":
    unittest.main()
