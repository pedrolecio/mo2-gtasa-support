import tempfile
import unittest
from pathlib import Path

import modloader_ini
from test_root_linker import FakeModList, FakeOrganizer


class ModloaderIniTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.game = self.root / "game"
        (self.game / "modloader").mkdir(parents=True)
        self.ini = self.game / "modloader" / "modloader.ini"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _make_mod(self, name: str, *folders: str) -> Path:
        mod_root = self.root / "mods" / name
        for folder in folders:
            (mod_root / "modloader" / folder).mkdir(parents=True, exist_ok=True)
            (self.game / "modloader" / folder).mkdir(parents=True, exist_ok=True)
        return mod_root

    def _priorities(self, section: str = "Profiles.Default.Priority") -> dict[str, str]:
        lines = self.ini.read_text(encoding="utf-8").splitlines()
        bounds = modloader_ini._section_bounds(lines, section)
        self.assertIsNotNone(bounds)
        result = {}
        for line in lines[bounds[0] + 1 : bounds[1]]:
            entry = modloader_ini._split_entry(line)
            if entry:
                result[entry[0]] = entry[1]
        return result

    def test_priorities_follow_mo2_and_unmanaged_folders_are_ignored(self):
        low = self._make_mod("low", "Shared", "LowOnly")
        high = self._make_mod("high", "shared")
        (self.game / "modloader" / "Leftover").mkdir()
        (self.game / "modloader" / ".data").mkdir()
        (self.game / "modloader" / ".profiles").mkdir()
        organizer = FakeOrganizer(FakeModList({"low": low, "high": high}, {"low": 0, "high": 4}))

        unmanaged = modloader_ini.write_priorities(str(self.game), organizer)

        priorities = self._priorities()
        self.assertEqual(unmanaged, ["Leftover"])
        self.assertEqual(priorities["LowOnly"], "1")
        # Mesmo nome com caixa diferente vira uma unica entrada (a maior prioridade).
        self.assertEqual([k for k in priorities if k.casefold() == "shared"], ["Shared"])
        self.assertEqual(priorities["Shared"], "5")
        self.assertEqual(priorities["Leftover"], "0")
        self.assertNotIn(".data", priorities)
        self.assertNotIn(".profiles", priorities)

    def test_unmanaged_manual_priority_is_kept_when_ignoring_is_disabled(self):
        mod = self._make_mod("mod", "Managed")
        (self.game / "modloader" / "Manual").mkdir()
        self.ini.write_text(
            "[Profiles.Default.Priority]\n; my comment\nManual = 70\nGone = 3\n",
            encoding="utf-8",
        )
        organizer = FakeOrganizer(FakeModList({"mod": mod}, {"mod": 9}))

        modloader_ini.write_priorities(str(self.game), organizer, ignore_unmanaged=False)

        content = self.ini.read_text(encoding="utf-8")
        priorities = self._priorities()
        self.assertIn("; my comment", content)
        self.assertEqual(priorities["Manual"], "70")
        self.assertEqual(priorities["Managed"], "10")
        self.assertNotIn("Gone", priorities)

    def test_selected_profile_and_other_sections_are_respected(self):
        mod = self._make_mod("mod", "Managed")
        self.ini.write_text(
            "[Folder.Config]\n"
            "Profile = Custom                 ; comment\n"
            "PriorityLimit = 100\n"
            "\n"
            "[Profiles.Default.Priority]\n"
            "Untouched = 50\n"
            "\n"
            "[Profiles.Custom.IgnoreMods]\n"
            "_ignore\n",
            encoding="utf-8",
        )
        organizer = FakeOrganizer(FakeModList({"mod": mod}, {"mod": 2}))

        modloader_ini.write_priorities(str(self.game), organizer)

        lines = self.ini.read_text(encoding="utf-8").splitlines()
        self.assertEqual(modloader_ini._get_value(lines, "Folder.Config", "Profile"), "Custom")
        self.assertEqual(modloader_ini._get_value(lines, "Folder.Config", "PriorityLimit"), "9999")
        self.assertEqual(self._priorities("Profiles.Custom.Priority"), {"Managed": "3"})
        self.assertEqual(self._priorities("Profiles.Default.Priority"), {"Untouched": "50"})
        self.assertIn("_ignore", lines)

    def test_nothing_is_written_without_modloader_content(self):
        (self.game / "modloader").rmdir()
        organizer = FakeOrganizer(FakeModList({}, {}))
        self.assertEqual(modloader_ini.write_priorities(str(self.game), organizer), [])
        self.assertFalse(self.ini.exists())

    def test_unchanged_file_is_not_rewritten(self):
        mod = self._make_mod("mod", "Managed")
        organizer = FakeOrganizer(FakeModList({"mod": mod}, {"mod": 2}))
        modloader_ini.write_priorities(str(self.game), organizer)
        first = self.ini.stat().st_mtime_ns
        modloader_ini.write_priorities(str(self.game), organizer)
        self.assertEqual(self.ini.stat().st_mtime_ns, first)


if __name__ == "__main__":
    unittest.main()
