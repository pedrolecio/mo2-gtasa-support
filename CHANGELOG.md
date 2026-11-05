# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.1.0] - 2026-11-05

### Added

- Plugin settings `ignore_unmanaged_modloader_folders` and `preserve_modified_files`.
- `.mo2_root_orphans/` for untracked files found inside `modloader/`.
- Deployment of empty directories shipped by mods.
- Launch is cancelled while `gta_sa.exe`/`gta-sa.exe` is still running.
- Sync errors are shown before launching, with the option to cancel.
- Installer: unwraps a single top-level folder and installs loose `.dff`, `.txd`,
  `.col`, `.ifp`, `.ide` and `.ipl` files under `modloader/<Mod Name>/`.

### Changed

- Files inside `modloader/` are never backed up as original game files; backups of
  them made by older versions are moved to `.mo2_root_orphans/`.
- Files changed by the game or the user after deployment are kept until the mod's
  own file changes, instead of being overwritten on every launch.
- `modloader/` folders that no active mod provides get priority 0 instead of
  Modloader's default priority 50.
- Modloader priorities are written after file synchronization, to the profile
  selected in `[Folder.Config]`, matching folder names case-insensitively and
  skipping `.data`/`.profiles`. The unused copy in the MO2 profile is no longer
  written, and the file is only rewritten when it changes.
- The game and SA-MP start with the arguments and working directory configured in
  MO2; SA-MP is also started without USVFS.
- `gta-sa.exe` is listed as an executable when present.
- Manifest version 3 also records the deployed file state and empty directories.
- Plugin version updated to `2.1.0`; installer version updated to `1.1.0`.

### Fixed

- Disabling or updating a mod could "restore" old versions of its own files from
  backup, leaving parts of disabled or outdated mods in `modloader/`.
- MO2 `meta.ini` files were copied into the game directory; `fomod/` and hidden
  `*.mohidden` files are skipped as well.
- A mod could overwrite `modloader/modloader.ini` after priorities were written.
- A failed synchronization started the game through USVFS.
- A mod directory that could not be read caused its deployed files to be removed.
- `listSaves()` raised `TypeError` because it did not accept the folder argument.

## [2.0.3] - 2026-08-21

### Added

- Versioned root-linker manifest that records the winning source mod for every file.
- Automatic migration from the legacy list-based tracking format.
- Atomic file replacement and support for read-only destination files.
- Automated tests for conflict replacement, backups, legacy migration, and cleanup.
- Direct GTA San Andreas launch without USVFS injection after physical synchronization.

### Changed

- Conflict resolution now explicitly follows MO2 priority, with higher-priority mods
  winning regardless of iteration order.
- Logging is now concise and consistently written in English.
- Routine Modloader writes, no-op synchronizations, and intentionally skipped protected
  executables no longer produce noisy log entries.
- Plugin version updated to `2.0.3`; installer version updated to `1.0.1`.

### Fixed

- Newly enabled or reprioritized mods can now replace files already present in the game
  directory, even when the competing files have identical size and timestamps.
- Original game files are safely backed up before replacement and restored when the last
  providing mod is disabled or the linker is cleared.
- GTA San Andreas no longer fails to start because the supposedly physical launch path
  still attempted to inject the USVFS proxy.
- Tracking writes no longer risk leaving a partially written manifest after interruption.

### Security

- The game executables and linker state files are protected from accidental replacement
  by mod contents.
- Relative paths are validated before files are copied, removed, or restored.

[2.1.0]: https://github.com/pedrolecio/mo2-gtasa-support/compare/v2.0.3...v2.1.0
[2.0.3]: https://github.com/pedrolecio/mo2-gtasa-support/compare/1.1...v2.0.3
