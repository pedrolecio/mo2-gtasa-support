# GTA San Andreas Support for Mod Organizer 2

This plugin adds Mod Organizer 2 support for GTA San Andreas 1.0 US.

The supported setup uses the 1.0 US Hoodlum executable. Steam and other digital
store versions are not supported as installed: replace the store executable with
the Hoodlum `gta_sa.exe` before creating the MO2 instance. This executable does
not work reliably with USVFS injection, so the plugin resolves conflicts and
copies the winning mod files into the game directory before starting the game
without USVFS.

- Plugin version: **2.1.0**
- Installer version: **1.1.0**

## Features

- Supports GTA San Andreas 1.0 US with the Hoodlum `gta_sa.exe`.
- Installs common CLEO, ASI, and Modloader archive layouts.
- Copies active mod files into the game directory before launch.
- Resolves file conflicts using MO2 priority; the higher-priority mod wins.
- Updates deployed files when active sources or MO2 priorities change.
- Backs up original game files before replacing them.
- Restores original files when no active mod provides their paths anymore.
- Synchronizes MO2 priorities with the Modloader priority section.
- Never treats files inside `modloader/` as original game files, so old mod
  versions are never "restored" when a mod is disabled or updated.
- Keeps settings that the game or a mod saves into deployed files (for example
  `.ini` files) instead of overwriting them on every launch.
- Gives priority 0 (ignored) to `modloader/` folders that no active mod provides.
- Skips MO2 metadata (`meta.ini`, `fomod/`) and hidden `*.mohidden` files.
- Starts GTA San Andreas and SA-MP directly, without USVFS injection, using the
  arguments and working directory configured in MO2.
- Refuses to start while the game is still running and reports sync errors
  before launching.
- Migrates tracking data created by older versions of the plugin.

## Requirements

- Mod Organizer 2 2.4 or newer with Python plugin support.
- GTA San Andreas 1.0 US with the Hoodlum executable.

Steam and other store releases must be downgraded. The only game-side change
required by this plugin is copying the 1.0 US Hoodlum `gta_sa.exe` into the game
directory and replacing the original store executable.

CLEO and Modloader are not plugin requirements. Install them through MO2 if one
of your mods needs them; the plugin handles their root files and directory
layouts like other managed mods.

## Preparing the game

1. Install GTA San Andreas from Steam or another store.
2. Copy the 1.0 US Hoodlum `gta_sa.exe` into the game directory.
3. Replace the original executable when prompted.

No separate CLEO or Modloader installation is needed to start using the plugin.
Both can be installed later through MO2.

## Installing the plugin

1. Download `gtasa_support-v2.1.0.zip` from the
   [latest release](https://github.com/pedrolecio/mo2-gtasa-support/releases/latest).
2. Extract the `gtasa_support` directory into the MO2 plugin directory:

   ```text
   Mod Organizer 2\plugins\gtasa_support\
   ```

3. Restart MO2.
4. Create or select a GTA San Andreas instance using the prepared 1.0 US game.
5. If the game is not detected automatically, select the directory containing
   the Hoodlum `gta_sa.exe`.

The GTA San Andreas entry created by the plugin includes the `-nointro` argument.

## Using the plugin

Install and enable mods through MO2 as usual. Arrange them in the left pane to
set their priority. When two enabled mods contain the same relative path, the mod
with the higher MO2 priority is copied to the game directory.

Changes are applied when an executable is started through MO2:

1. The launch is cancelled if `gta_sa.exe` or `gta-sa.exe` is still running.
2. The plugin scans enabled mods in MO2 priority order.
3. Files that changed are copied into the game directory.
4. Files no longer provided by an enabled mod are removed or restored from backup.
5. Modloader priorities are updated from the final state of `modloader/`.
6. If any file could not be copied or removed, MO2 asks before launching.
7. GTA San Andreas (or SA-MP) is started directly without USVFS, with the
   arguments set for that executable in MO2.

If synchronization fails completely, the launch is cancelled instead of falling
back to USVFS. Other executables configured in MO2 keep the normal MO2 launch
behavior after the synchronization.

## Archive layouts

The installer handles the following layouts automatically.

### Wrapper folders

When an archive contains a single top-level folder (optionally next to readme
files) that is not a known layout, such as `MyMod v1.2/`, its contents are moved
up one level before the rules below are applied.

### Pre-structured archives

Archives that already contain one of these top-level directories keep their
existing layout:

```text
cleo/
modloader/
moonloader/
scripts/
```

### CLEO scripts

Root-level `.cs`, `.csa`, `.csi`, and `.fxt` files are moved into `cleo/`.
Nested or ambiguous CLEO layouts open the manual installer.

### Root plugins

Archives with root-level `.asi`, `.dll`, `.exe`, `.img`, `.dat`, or `.cat` files
keep their root layout. Companion files in the same archive remain alongside
them.

The main game executables (`gta_sa.exe` and `gta-sa.exe`) are never copied from a
mod.

### Modloader assets

Archives with top-level asset directories such as `models/`, `audio/`, `anim/`,
`data/`, `txd/`, `vehicles/`, `weapons/`, or `maps/`, or with loose `.dff`, `.txd`,
`.col`, `.ifp`, `.ide`, or `.ipl` files, are installed under:

```text
modloader/<Mod Name>/
```

Unknown layouts fall back to MO2's manual installer.

## Conflict handling and backups

The linker stores its state in the game directory:

```text
.mo2_root_mod_files.json
.mo2_root_backups/
.mo2_root_orphans/
```

The JSON manifest records the winning source mod, path, size, and timestamp for
each managed file. Older list-based manifests are converted automatically.

When a mod first replaces an existing game file, the original is copied to
`.mo2_root_backups/`. The backup is kept while any active mod provides that path.
When the last provider is disabled or removed, the original is restored during
the next pre-launch synchronization.

Nothing inside `modloader/` belongs to the original game, so those paths are
never backed up. An untracked file found there (for example left by a manual
installation) is moved to `.mo2_root_orphans/` before the mod's file replaces it,
unless both files are identical. Orphans are never restored automatically; you
can delete that folder once you have checked its contents. Backups of
`modloader/` files made by older versions are moved there automatically.

If the game or a mod changes a deployed file (settings saved to an `.ini`, a
`.json`, a log), the change is kept until the mod itself ships a new version of
that file. Delete the file from the game directory to get the mod's version
back on the next launch, or turn off `preserve_modified_files`.

Empty directories shipped by mods (such as `cleo/cleo_saves/`) are created and
removed together with the mod. If a mod directory cannot be read during a sync,
the files it deployed earlier are left in place.

File replacement is atomic and supports read-only destination files. A change of
winning mod always triggers replacement, even when both files have the same size
and timestamp.

Do not delete `.mo2_root_backups/` while managed files are active. Those files are
needed to restore the original installation.

## Modloader priority synchronization

For every enabled MO2 mod containing first-level directories under `modloader/`,
the plugin writes matching entries to the priority section of the Modloader
profile selected in `[Folder.Config]` (`[Profiles.Default.Priority]` by default)
in the game's `modloader/modloader.ini`. Higher MO2 priority produces higher
Modloader priority. Folder names are matched case-insensitively and Modloader's
internal folders (`.data`, `.profiles`) are skipped.

Folders in the game's `modloader/` directory that no active mod provides would
otherwise load with Modloader's default priority 50 and override lower-priority
mods. They are written with priority 0 (ignored) and listed in the log. Turn off
`ignore_unmanaged_modloader_folders` to keep their current entries instead.

The plugin also ensures that `[Folder.Config]` contains a suitable
`PriorityLimit`. The rest of `modloader.ini` and comments in the priority
section are preserved, and the file is only rewritten when something changed.
`modloader/modloader.ini` is never overwritten by a mod's copy.

## Settings

Available under *Settings > Plugins > GTA San Andreas Support Plugin*:

| Setting | Default | Effect |
| --- | --- | --- |
| `ignore_unmanaged_modloader_folders` | `true` | Priority 0 for `modloader/` folders no active mod provides. |
| `preserve_modified_files` | `true` | Keep deployed files changed by the game or user until the mod changes them. |

## Files created in the game directory

In addition to copied mod files, the plugin may create:

```text
GTA Root Folder/
.mo2_root_mod_files.json
.mo2_root_backups/
.mo2_root_orphans/
modloader/modloader.ini
```

`GTA Root Folder/` is an empty data directory used to keep MO2 away from the real
game root. Actual mod deployment is handled by the physical linker.

## Updating

Replace the existing `gtasa_support` plugin directory with the new release, then
restart MO2. Do not remove the tracking manifest or backup directory during an
update.

Version 2.1.0 reads and upgrades manifests written by previous versions.

## Troubleshooting

### The store version does not start

The original Steam and other store executables are not supported. Confirm that
the game directory contains the 1.0 US Hoodlum `gta_sa.exe` and that it replaced
the original executable before creating or running the MO2 instance.

### MO2 still shows a USVFS proxy error

Close MO2 completely and start it again so the updated Python plugin is loaded.
After a successful launch, `mo_interface.log` should contain:

```text
[GTASA] Game launched without USVFS: ...\gta_sa.exe
```

### A mod does not win a file conflict

Check that the mod is enabled and has the higher priority in MO2. Start the game
once through MO2 to run synchronization. When files are copied or removed, the
log includes a short `GTASA Linker` summary.

### An original game file was replaced

Disable every mod that provides that relative path and start the game once
through MO2. The linker restores the saved original during synchronization.

### Files cannot be copied

Check write permissions for the GTA San Andreas directory and make sure the game
or another program is not holding the destination file open. Copy errors include
the affected path and source mod in `mo_interface.log`.

## Development

The runtime plugin consists of:

```text
gtasa_support/
  __init__.py
  plugin.py
  installer.py
  modloader_ini.py
  root_linker.py
```

Run the tests from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m py_compile __init__.py installer.py modloader_ini.py plugin.py root_linker.py
```

See [CHANGELOG.md](CHANGELOG.md) for release notes.
