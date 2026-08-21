# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

[2.0.3]: https://github.com/pedrolecio/mo2-gtasa-support/compare/1.1...v2.0.3
