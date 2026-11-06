import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import root_linker


class FakeMod:
    def __init__(self, path: Path):
        self._path = path

    def absolutePath(self) -> str:
        return str(self._path)


class FakeModList:
    def __init__(self, mods: dict[str, Path], priorities: dict[str, int]):
        self._mods = {name: FakeMod(path) for name, path in mods.items()}
        self._priorities = priorities
        self.active = set(mods)

    def allModsByProfilePriority(self) -> list[str]:
        # Deliberadamente invertido: o linker deve consultar priority().
        return list(reversed(self._mods))

    def priority(self, name: str) -> int:
        return self._priorities[name]

    def state(self, name: str) -> int:
        return 0x2 if name in self.active else 0

    def getMod(self, name: str):
        return self._mods.get(name)


class FakeOrganizer:
    def __init__(self, mod_list: FakeModList):
        self._mod_list = mod_list

    def modList(self) -> FakeModList:
        return self._mod_list


class RootLinkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.game = self.root / "game"
        self.game.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _make_mod(self, name: str, relative: str, content: bytes) -> Path:
        mod_root = self.root / name
        target = mod_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return mod_root

    def test_new_higher_priority_mod_replaces_same_metadata_file(self):
        relative = "models/player.img"
        low = self._make_mod("low", relative, b"LOW!")
        high = self._make_mod("high", relative, b"HIGH")
        common_time = 1_700_000_000_000_000_000
        os.utime(low / relative, ns=(common_time, common_time))
        os.utime(high / relative, ns=(common_time, common_time))

        mod_list = FakeModList({"low": low, "high": high}, {"low": 1, "high": 10})
        mod_list.active = {"low"}
        organizer = FakeOrganizer(mod_list)
        root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual((self.game / relative).read_bytes(), b"LOW!")

        # Mesmo tamanho e mtime: a implementacao antiga deixava LOW! no destino.
        mod_list.active.add("high")
        root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual((self.game / relative).read_bytes(), b"HIGH")

        manifest = json.loads((self.game / root_linker.TRACKING_FILE).read_text())
        self.assertEqual(manifest["files"][relative]["source_mod"], "high")

    def test_existing_read_only_game_file_is_backed_up_and_restored(self):
        relative = "data/gta.dat"
        original = self.game / relative
        original.parent.mkdir(parents=True)
        original.write_bytes(b"VANILLA")
        original.chmod(stat.S_IREAD)

        mod_root = self._make_mod("replacement", relative, b"MODDED!")
        mod_list = FakeModList({"replacement": mod_root}, {"replacement": 1})
        organizer = FakeOrganizer(mod_list)

        root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(original.read_bytes(), b"MODDED!")
        self.assertEqual(
            (self.game / root_linker.BACKUP_DIR / relative).read_bytes(), b"VANILLA"
        )

        mod_list.active.clear()
        root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(original.read_bytes(), b"VANILLA")

    def test_legacy_tracking_is_migrated_and_forces_a_refresh(self):
        relative = "cleo/script.cs"
        mod_root = self._make_mod("script", relative, b"NEW")
        destination = self.game / relative
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"OLD")
        source_stat = (mod_root / relative).stat()
        os.utime(destination, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        (self.game / root_linker.TRACKING_FILE).write_text(
            json.dumps([relative]), encoding="utf-8"
        )

        organizer = FakeOrganizer(FakeModList({"script": mod_root}, {"script": 1}))
        root_linker.sync_mods(organizer, str(self.game))

        self.assertEqual(destination.read_bytes(), b"NEW")
        manifest = json.loads((self.game / root_linker.TRACKING_FILE).read_text())
        self.assertEqual(manifest["version"], root_linker.MANIFEST_VERSION)
        self.assertEqual(manifest["files"][relative]["source_mod"], "script")

    def test_clear_mods_restores_original_and_removes_tracking(self):
        relative = "audio/config.ini"
        original = self.game / relative
        original.parent.mkdir(parents=True)
        original.write_text("original", encoding="utf-8")
        mod_root = self._make_mod("audio", relative, b"modified")
        organizer = FakeOrganizer(FakeModList({"audio": mod_root}, {"audio": 1}))

        root_linker.sync_mods(organizer, str(self.game))
        root_linker.clear_mods(str(self.game))

        self.assertEqual(original.read_text(encoding="utf-8"), "original")
        self.assertFalse((self.game / root_linker.TRACKING_FILE).exists())

    def test_untracked_modloader_file_is_orphaned_and_never_restored(self):
        relative = "modloader/Weapons/ak47.txd"
        stale = self.game / relative
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"OLD BUILD")

        mod_root = self._make_mod("weapons", relative, b"NEW BUILD")
        mod_list = FakeModList({"weapons": mod_root}, {"weapons": 1})
        organizer = FakeOrganizer(mod_list)

        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(stale.read_bytes(), b"NEW BUILD")
        self.assertEqual(result.orphaned, [str(Path(relative))])
        self.assertFalse((self.game / root_linker.BACKUP_DIR / relative).exists())
        self.assertEqual(
            (self.game / root_linker.ORPHAN_DIR / relative).read_bytes(), b"OLD BUILD"
        )

        # Desativar o mod remove o arquivo; a versao antiga nao volta.
        mod_list.active.clear()
        root_linker.sync_mods(organizer, str(self.game))
        self.assertFalse(stale.exists())

    def test_identical_untracked_modloader_file_is_adopted_without_orphan(self):
        relative = "modloader/Weapons/ak47.txd"
        stale = self.game / relative
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"SAME")
        mod_root = self._make_mod("weapons", relative, b"SAME")
        organizer = FakeOrganizer(FakeModList({"weapons": mod_root}, {"weapons": 1}))

        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(result.orphaned, [])
        self.assertFalse((self.game / root_linker.ORPHAN_DIR).exists())

    def test_legacy_modloader_backups_are_moved_to_orphans(self):
        relative = "modloader/Weapons/ak47.txd"
        backup = self.game / root_linker.BACKUP_DIR / relative
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"OLD BUILD")
        vanilla_backup = self.game / root_linker.BACKUP_DIR / "data/gta.dat"
        vanilla_backup.parent.mkdir(parents=True)
        vanilla_backup.write_bytes(b"VANILLA")

        organizer = FakeOrganizer(FakeModList({}, {}))
        root_linker.sync_mods(organizer, str(self.game))

        self.assertFalse(backup.exists())
        self.assertFalse((self.game / root_linker.BACKUP_DIR / "modloader").exists())
        self.assertTrue(vanilla_backup.exists())
        self.assertEqual(
            (self.game / root_linker.ORPHAN_DIR / relative).read_bytes(), b"OLD BUILD"
        )

    def test_file_modified_by_game_is_restored_from_mo2_and_kept_in_orphans(self):
        relative = "modloader/Weapons/Tec9/tec9.weaponinfo"
        mod_root = self._make_mod("weapons", relative, b"id=32\n")
        organizer = FakeOrganizer(FakeModList({"weapons": mod_root}, {"weapons": 1}))
        destination = self.game / relative

        root_linker.sync_mods(organizer, str(self.game))
        # Um editor in-game regrava o arquivo implantado.
        destination.write_bytes(b"id=32\nhandik.version=4\n")
        os.utime(destination, ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))

        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(destination.read_bytes(), b"id=32\n")
        self.assertEqual(result.restored, [str(Path(relative))])
        self.assertEqual(
            (self.game / root_linker.ORPHAN_DIR / relative).read_bytes(),
            b"id=32\nhandik.version=4\n",
        )

        # Sem novas alteracoes nada e copiado de novo.
        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual((result.copied, result.restored), (0, []))

    def test_edit_in_mo2_wins_even_if_game_changed_the_copy(self):
        relative = "config.ini"
        mod_root = self._make_mod("cfg", relative, b"default")
        organizer = FakeOrganizer(FakeModList({"cfg": mod_root}, {"cfg": 1}))
        destination = self.game / relative

        root_linker.sync_mods(organizer, str(self.game))
        destination.write_bytes(b"changed by game")
        (mod_root / relative).write_bytes(b"edited in MO2")

        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(destination.read_bytes(), b"edited in MO2")
        self.assertEqual(result.restored, [relative])

    def test_unchanged_game_copy_is_not_saved_to_orphans(self):
        relative = "config.ini"
        mod_root = self._make_mod("cfg", relative, b"default")
        organizer = FakeOrganizer(FakeModList({"cfg": mod_root}, {"cfg": 1}))

        root_linker.sync_mods(organizer, str(self.game))
        (mod_root / relative).write_bytes(b"new version")
        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual((self.game / relative).read_bytes(), b"new version")
        self.assertEqual(result.restored, [])
        self.assertFalse((self.game / root_linker.ORPHAN_DIR).exists())

    def test_version_2_manifest_restores_modified_destination(self):
        relative = "config.ini"
        mod_root = self._make_mod("cfg", relative, b"default")
        source_stat = (mod_root / relative).stat()
        destination = self.game / relative
        destination.write_bytes(b"changed by game")
        manifest = {
            "version": 2,
            "files": {
                relative: {
                    "path": relative,
                    "source": root_linker._source_id(mod_root / relative),
                    "source_mod": "cfg",
                    "size": source_stat.st_size,
                    "mtime_ns": source_stat.st_mtime_ns,
                }
            },
        }
        (self.game / root_linker.TRACKING_FILE).write_text(json.dumps(manifest))
        organizer = FakeOrganizer(FakeModList({"cfg": mod_root}, {"cfg": 1}))

        root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(destination.read_bytes(), b"default")
        self.assertEqual(
            (self.game / root_linker.ORPHAN_DIR / relative).read_bytes(), b"changed by game"
        )
        saved = json.loads((self.game / root_linker.TRACKING_FILE).read_text())
        self.assertEqual(saved["version"], root_linker.MANIFEST_VERSION)
        self.assertIn("dest_size", saved["files"][relative])

    def test_copy_kept_by_version_2_1_0_is_restored(self):
        # 2.1.0 recorded the game-modified file as the expected destination.
        relative = "modloader/Weapons/tec9.weaponinfo"
        mod_root = self._make_mod("weapons", relative, b"id=32\n")
        source_stat = (mod_root / relative).stat()
        destination = self.game / relative
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"id=32\nhandik.version=4\n")
        destination_stat = destination.stat()
        manifest = {
            "version": 3,
            "files": {
                relative.casefold(): {
                    "path": relative,
                    "source": root_linker._source_id(mod_root / relative),
                    "source_mod": "weapons",
                    "size": source_stat.st_size,
                    "mtime_ns": source_stat.st_mtime_ns,
                    "dest_size": destination_stat.st_size,
                    "dest_mtime_ns": destination_stat.st_mtime_ns,
                }
            },
            "dirs": {},
        }
        (self.game / root_linker.TRACKING_FILE).write_text(json.dumps(manifest))
        organizer = FakeOrganizer(FakeModList({"weapons": mod_root}, {"weapons": 1}))

        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertEqual(destination.read_bytes(), b"id=32\n")
        self.assertEqual(result.restored, [str(Path(relative))])

    def test_mo2_metadata_hidden_and_protected_files_are_skipped(self):
        mod_root = self._make_mod("mod", "meta.ini", b"[General]")
        self._make_mod("mod", "fomod/ModuleConfig.xml", b"<config/>")
        self._make_mod("mod", "cleo/old.cs.mohidden", b"hidden")
        self._make_mod("mod", "modloader/modloader.ini", b"[Folder.Config]")
        self._make_mod("mod", "modloader/Mod/meta.ini", b"kept: not at mod root")
        organizer = FakeOrganizer(FakeModList({"mod": mod_root}, {"mod": 1}))

        root_linker.sync_mods(organizer, str(self.game))

        self.assertFalse((self.game / "meta.ini").exists())
        self.assertFalse((self.game / "fomod").exists())
        self.assertFalse((self.game / "cleo/old.cs.mohidden").exists())
        self.assertFalse((self.game / "modloader/modloader.ini").exists())
        self.assertTrue((self.game / "modloader/Mod/meta.ini").exists())

    def test_empty_directories_are_deployed_and_removed(self):
        mod_root = self._make_mod("cleo", "cleo/script.cs", b"script")
        (mod_root / "cleo/cleo_saves").mkdir()
        mod_list = FakeModList({"cleo": mod_root}, {"cleo": 1})
        organizer = FakeOrganizer(mod_list)

        root_linker.sync_mods(organizer, str(self.game))
        self.assertTrue((self.game / "cleo/cleo_saves").is_dir())

        mod_list.active.clear()
        root_linker.sync_mods(organizer, str(self.game))
        self.assertFalse((self.game / "cleo").exists())

    def test_files_of_unreadable_mod_are_kept(self):
        relative = "plugin.asi"
        mod_root = self._make_mod("plugin", relative, b"asi")
        mod_list = FakeModList({"plugin": mod_root}, {"plugin": 1})
        organizer = FakeOrganizer(mod_list)
        root_linker.sync_mods(organizer, str(self.game))

        # A pasta do mod some temporariamente (ex.: sendo reinstalada).
        mod_root.rename(self.root / "plugin-moved")
        result = root_linker.sync_mods(organizer, str(self.game))
        self.assertTrue((self.game / relative).exists())
        self.assertTrue(result.errors)
        manifest = json.loads((self.game / root_linker.TRACKING_FILE).read_text())
        self.assertIn(relative, manifest["files"])


if __name__ == "__main__":
    unittest.main()
