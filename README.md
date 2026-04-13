# GTA San Andreas Support Plugin for Mod Organizer 2

A comprehensive Mod Organizer 2 plugin designed for **Grand Theft Auto: San Andreas (Classic/Steam/Retail/Downgraded)**. 

Because Mod Organizer 2's native Virtual File System (VFS) has compatibility issues with the GTA:SA classic engine (specifically the common v1.0 Hoodlum executable, where VFS causes a startup crash), this plugin bypasses those limitations to provide a robust, non-destructive, and conflict-resolving modding experience.

## ✨ Core Features

* **Physical Root Linking:** Automatically safely copies mod files into your game directory before launch and cleans them up after, keeping your base game pure while avoiding engine crashes.
* **Smart Mod Installation:** Recognizes mod file types and automatically organizes them into `cleo/`, `modloader/`, or the game's root folder without manual intervention.
* **Modloader Priority Synchronization:** MO2's mod hierarchy conflict resolution rules seamlessly apply to Modloader, syncing your MO2 load order with `modloader.ini` on every launch.
* **Automatic Backups:** Real game files that happen to be overwritten by root mods are safely backed up and restored once the mod is disabled.

---

## 🚀 How It Works (Technical Overview)

This plugin handles GTA: SA modding via four primary systems:

### 1. Game Detection
The plugin detects installations of `gta_sa.exe` and `gta-sa.exe`. It identifies the Hoodlum crack via specific file sizes or `.nfo` files to ensure accurate behavior. To resolve MO2 startup crashes with the v1.0 game, it masks the game's actual data directory using a dummy path (`GTA Root Folder`) while handling files manually.

### 2. Smart Installer (`installer.py`)
Replaces MO2's default installer to automatically map out mod payloads. When you install an archive, the plugin reorganizes it based on the contents:
- **CLEO Scripts:** Any `.cs`, `.csa`, `.csi`, or `.fxt` files at the root of the archive are moved inside a `cleo/` folder.
- **Modloader Assets:** If the archive contains standard game asset folders (like `models/`, `audio/`, `data/`, `txd/`), the contents are automatically wrapped in a `modloader/<ModName>/` directory.
- **Root Plugins:** ASI plugins (`.asi`), DLLs, and INIs are recognized as root files and are kept at the root of the mod.
- **Pre-structured Mods:** If the mod already comes with `cleo/`, `modloader/`, or `moonloader/` folders, the installer respects the author's structure.
- **Fallback:** If it encounters loose ambiguous files (like a random `.dff`), it defaults to a manual installation prompt.

### 3. Modloader Priority Sync (`modloader_ini.py`)
To ensure MO2's "Load Order" is respected by the game, the plugin intercepts the launch process and dynamically edits your `modloader.ini`.
- It scans all active MO2 mods that inject into the `modloader/` folder.
- It translates their MO2 precedence (from 1 to N, where higher overwrites lower) directly into the `[Profiles.Default.Priority]` section of the `.ini`.
- This ensures that a texture mod placed lower in MO2 will override an opposing texture mod placed higher in the list, completely mirroring MO2's standard conflict rules.

### 4. Physical Root Linker (`root_linker.py`)
Since standard VFS hooking crashes the game engine, the plugin operates via a "RootBuilder" approach.
- **On Game Launch:** The plugin gathers all active mods in their designated priority order. It then physically copies these files from your MO2 `mods/` directory straight into the actual GTA San Andreas game directory.
- **Backups:** If a mod file conflicts with a vanilla game file, the vanilla file is safely moved into a `.mo2_root_backups` folder.
- **Tracking:** Every injected file is tracked in a local `.mo2_root_mod_files.json` registry.
- **On Change/Cleanup:** If you disable a mod, remove a file, or change your load order, the linker will read the tracker, delete the old mod files, clean up any left-over empty directories, and restore any original game backups automatically before launching again.

---

## 📦 File Structure

```text
gtasa_support/
  ├── __init__.py          # Plugin Entrypoint
  ├── plugin.py            # IPluginGame (Detection and execution hooks)
  ├── installer.py         # IPluginInstallerSimple (Smart Mod Archiving)
  ├── modloader_ini.py     # Mod priority synchronization logic
  ├── root_linker.py       # Pre-launch physical copy and cleanup script
  └── README.md            # Documentation
```

---

## 🛠️ Installation & Requirements

### Requirements
- **Mod Organizer 2** (v2.4 or higher, with Python support enabled)
- **GTA San Andreas** (Steam AppID 12120, Retail, or v1.0 Downgraded)
- **Modloader** installed in your game directory (Highly recommended for assets)
- **CLEO** installed in your game directory (Optional, if you plan to use CLEO scripts)

### Installation
1. Extract the `gtasa_support` folder into your Mod Organizer 2 plugins directory:
   ```
   Mod Organizer 2\plugins\gtasa_support\
   ```
2. Open Mod Organizer 2. 
3. Create a new instance and select **GTA: San Andreas**.
4. If MO2 does not auto-detect the game path, point it manually to the folder containing `gta_sa.exe` or `gta-sa.exe`.
