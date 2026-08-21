# GTA San Andreas Support for Mod Organizer 2

This plugin adds Mod Organizer 2 support for GTA San Andreas 1.0 US.

The supported setup uses the 1.0 US Hoodlum executable. Steam and other digital
store versions are not supported as installed: replace the store executable with
the Hoodlum `gta_sa.exe` before creating the MO2 instance. This executable does
not work reliably with USVFS injection, so the plugin resolves conflicts and
copies the winning mod files into the game directory before starting the game
without USVFS.

- Plugin version: **2.0.3**
- Installer version: **1.0.1**

## Features

- Supports GTA San Andreas 1.0 US with the Hoodlum `gta_sa.exe`.
- Installs common CLEO, ASI, and Modloader archive layouts.
- Copies active mod files into the game directory before launch.
- Resolves file conflicts using MO2 priority; the higher-priority mod wins.
- Updates deployed files when active sources or MO2 priorities change.
- Backs up original game files before replacing them.
- Restores original files when no active mod provides their paths anymore.
- Synchronizes MO2 priorities with the Modloader priority section.
- Starts GTA San Andreas directly, without USVFS injection.
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

1. Download `gtasa_support-v2.0.3.zip` from the
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

1. Modloader priorities are updated.
2. The plugin scans enabled mods in MO2 priority order.
3. Files that changed are copied into the game directory.
4. Files no longer provided by an enabled mod are removed or restored from backup.
5. GTA San Andreas is started directly without USVFS.

Other executables configured in MO2 keep the normal MO2 launch behavior.

## Archive layouts

The installer handles the following layouts automatically.

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
`data/`, `txd/`, `vehicles/`, `weapons/`, or `maps/` are installed under:

```text
modloader/<Mod Name>/
```

Unknown layouts fall back to MO2's manual installer.

## Conflict handling and backups

The linker stores its state in the game directory:

```text
.mo2_root_mod_files.json
.mo2_root_backups/
```

The JSON manifest records the winning source mod, path, size, and timestamp for
each managed file. Older list-based manifests are converted automatically.

When a mod first replaces an existing game file, the original is copied to
`.mo2_root_backups/`. The backup is kept while any active mod provides that path.
When the last provider is disabled or removed, the original is restored during
the next pre-launch synchronization.

File replacement is atomic and supports read-only destination files. A change of
winning mod always triggers replacement, even when both files have the same size
and timestamp.

Do not delete `.mo2_root_backups/` while managed files are active. Those files are
needed to restore the original installation.

## Modloader priority synchronization

For every enabled MO2 mod containing first-level directories under `modloader/`,
the plugin writes matching entries to `[Profiles.Default.Priority]` in
`modloader.ini`. Higher MO2 priority produces higher Modloader priority.

The plugin also ensures that `[Folder.Config]` contains a suitable
`PriorityLimit`. Priority files are updated in the active MO2 profile and in the
game's `modloader/` directory.

## Files created in the game directory

In addition to copied mod files, the plugin may create:

```text
GTA Root Folder/
.mo2_root_mod_files.json
.mo2_root_backups/
modloader/modloader.ini
```

`GTA Root Folder/` is an empty data directory used to keep MO2 away from the real
game root. Actual mod deployment is handled by the physical linker.

## Updating

Replace the existing `gtasa_support` plugin directory with the new release, then
restart MO2. Do not remove the tracking manifest or backup directory during an
update.

Version 2.0.3 reads and upgrades manifests written by previous versions.

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
