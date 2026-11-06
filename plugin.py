"""
plugin.py
---------
GTASAGame: implementa IPluginGame para o GTA San Andreas clássico.

Estratégia de sincronização física:
  - dataDirectory() retorna uma pasta vazia para evitar o VFS incompatível com
    algumas versões 1.0/Hoodlum.
  - Antes da execução, root_linker copia os arquivos vencedores de cada conflito
    para a raiz do jogo e preserva os arquivos originais em backup.
  - O jogo (e o SA-MP) é iniciado diretamente, sem injeção do USVFS.
"""

from __future__ import annotations

import ctypes
import logging
import os
import traceback
import winreg
from ctypes import wintypes
from pathlib import Path

import mobase
from PyQt6.QtCore import QDir, QFileInfo, QProcess
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import modloader_ini
from . import root_linker

log = logging.getLogger("gtasa_support")

GAME_NAME       = "GTA: San Andreas"
MAIN_EXE        = "gta_sa.exe"   # Steam / versão original
ALT_EXE         = "gta-sa.exe"   # Hoodlum e algumas versões crackeadas
SAMP_EXE        = "samp.exe"
STEAM_APPID     = "12120"

# Executáveis iniciados diretamente, sem USVFS, após a sincronização física.
_DIRECT_LAUNCH  = {MAIN_EXE, ALT_EXE, SAMP_EXE}
# Processos que mantêm arquivos do jogo abertos durante a execução.
_GAME_PROCESSES = {MAIN_EXE, ALT_EXE}

SETTING_IGNORE_UNMANAGED  = "ignore_unmanaged_modloader_folders"

# ── Detecção do jogo ────────────────────────────────────────────────────────


def _detect_exe(game_dir: str) -> str:
    """
    Retorna o nome do executável principal encontrado na pasta do jogo.
    Usa gta_sa.exe quando existe; gta-sa.exe (Hoodlum renomeado) como alternativa.
    """
    for exe in (MAIN_EXE, ALT_EXE):
        if os.path.isfile(os.path.join(game_dir, exe)):
            return exe
    return MAIN_EXE


def _has_game_exe(directory: str) -> bool:
    return (
        os.path.isfile(os.path.join(directory, MAIN_EXE))
        or os.path.isfile(os.path.join(directory, ALT_EXE))
    )


def _find_game() -> str:
    """
    Tenta localizar a instalação do GTA SA no registro do Steam ou em caminhos comuns.
    Retorna a string do caminho se encontrado, ou "" caso contrário.
    """
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 12120",
            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 12120",
        ):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallLocation")
                    if path and _has_game_exe(path):
                        return path
            except (FileNotFoundError, OSError):
                pass

    common_dirs = [
        r"C:\Program Files (x86)\Steam\steamapps\common\Grand Theft Auto San Andreas",
        r"C:\Program Files\Steam\steamapps\common\Grand Theft Auto San Andreas",
        r"C:\Program Files (x86)\Rockstar Games\GTA San Andreas",
        r"C:\Program Files\Rockstar Games\GTA San Andreas",
        r"D:\SteamLibrary\steamapps\common\Grand Theft Auto San Andreas",
        r"E:\SteamLibrary\steamapps\common\Grand Theft Auto San Andreas",
    ]
    for d in common_dirs:
        if _has_game_exe(d):
            return d

    return ""


# ── Processos em execução ───────────────────────────────────────────────────


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _running_process_names() -> set[str]:
    """Nomes (casefold) dos executáveis em execução; vazio se a consulta falhar."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        entry_ptr = ctypes.POINTER(_PROCESSENTRY32W)
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, entry_ptr]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, entry_ptr]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return set()
        names: set[str] = set()
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                names.add(entry.szExeFile.casefold())
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return names
    except Exception:
        log.warning(f"[GTASA] Could not list running processes:\n{traceback.format_exc()}")
        return set()


def _dialog_parent():
    return QApplication.activeWindow()


def _split_arguments(arguments: str) -> list[str]:
    """
    Divide a linha de argumentos do MO2 com as mesmas regras do Windows
    (CommandLineToArgvW). O PyQt6 não expõe QProcess.splitCommand.
    """
    if not arguments or not arguments.strip():
        return []
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shell32.CommandLineToArgvW.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)
        ]
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL

        count = ctypes.c_int(0)
        # O primeiro token segue regras de nome de programa; usamos um fictício.
        argv = shell32.CommandLineToArgvW(f"x {arguments}", ctypes.byref(count))
        if not argv:
            raise OSError(ctypes.get_last_error(), "CommandLineToArgvW failed")
        try:
            return [argv[index] for index in range(1, count.value)]
        finally:
            kernel32.LocalFree(ctypes.cast(argv, wintypes.HLOCAL))
    except Exception:
        log.warning(f"[GTASA] Could not parse arguments {arguments!r}; splitting on spaces.")
        return arguments.split()


# ── Classe principal ─────────────────────────────────────────────────────────


class GTASAModDataChecker(mobase.ModDataChecker):
    def __init__(self):
        super().__init__()

    def dataLook(self, tree: mobase.IFileTree) -> mobase.ModDataChecker.CheckResult:
        """
        Diz ao MO2 que qualquer estrutura é válida.
        Isso garante que scripts CLEO e plugins ASI na raíz sejam aceitos e exibidos.
        """
        return mobase.ModDataChecker.VALID


class GTASAGame(mobase.IPluginGame):
    """
    Plugin de suporte ao GTA San Andreas para o Mod Organizer 2.
    Modo: Physical Linker (estilo RootBuilder)
    """

    _organizer: mobase.IOrganizer
    _path: str

    def __init__(self):
        mobase.IPluginGame.__init__(self)
        self._path = ""

    # ── IPlugin ────────────────────────────────────────────────────────────────

    def init(self, organizer: mobase.IOrganizer) -> bool:
        self._organizer = organizer
        self._path = _find_game()
        organizer.onAboutToRun(self._on_about_to_run)
        return True

    def feature(self, feature_type):
        if feature_type == mobase.ModDataChecker:
            return GTASAModDataChecker()
        return None

    def name(self) -> str:
        return "GTA San Andreas Support Plugin"

    def author(self) -> str:
        return "GTA SA Support Plugin"

    def description(self) -> str:
        return (
            "Suporte ao GTA San Andreas (clássico) com sincronização física, "
            "suporte a Modloader, CLEO e arquivos de raíz."
        )

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(2, 1, 1, mobase.ReleaseType.final)

    def settings(self) -> list[mobase.PluginSetting]:
        return [
            mobase.PluginSetting(
                SETTING_IGNORE_UNMANAGED,
                "Write priority 0 (ignore) for folders in the game's modloader/ "
                "directory that no active MO2 mod provides.",
                True,
            ),
        ]

    def _setting(self, key: str, default: bool) -> bool:
        try:
            value = self._organizer.pluginSetting(self.name(), key)
        except Exception:
            return default
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().casefold() in {"true", "1", "yes"}
        return bool(value)

    def isActive(self) -> bool:
        return True

    # ── IPluginGame: Identidade ────────────────────────────────────────────────

    def gameName(self)        -> str:  return GAME_NAME
    def gameShortName(self)   -> str:  return "GTASA"
    def gameNexusName(self)   -> str:  return "gtasa"
    def nexusGameID(self)     -> int:  return 12
    def steamAPPId(self)      -> str:  return STEAM_APPID
    def validShortNames(self) -> list: return ["GTASA", "GrandTheftAutoSanAndreas"]
    def primarySources(self)  -> list: return []

    def gameIcon(self) -> QIcon:
        ico = os.path.join(os.path.dirname(__file__), "gta_sa.ico")
        return QIcon(ico) if os.path.isfile(ico) else QIcon()

    def gameVariants(self)           -> list: return []
    def setGameVariant(self, v: str) -> None: pass
    def gameVersion(self)            -> str:  return "1.0"
    def getLauncherName(self)        -> str:  return ""

    # ── IPluginGame: Caminhos ──────────────────────────────────────────────────

    def setGamePath(self, path: str) -> None:
        self._path = path

    def gameDirectory(self) -> QDir:
        if not self._path:
            self._path = _find_game()
        return QDir(self._path)

    def dataDirectory(self) -> QDir:
        """
        Retorna uma pasta fantasma vazia. Única forma de evitar o crash de
        inicialização com o crack Hoodlum/1.0 no MO2.
        A sincronização real para a raiz é feita pelo root_linker antes do jogo.
        """
        path = os.path.join(self.gameDirectory().absolutePath(), "GTA Root Folder")
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                pass
        return QDir(path)

    def documentsDirectory(self) -> QDir:
        # Desativado: deixa o jogo usar o caminho padrão do sistema.
        return QDir()

    def savesDirectory(self) -> QDir:
        return QDir()

    # ── IPluginGame: Executáveis ───────────────────────────────────────────────

    def binaryName(self) -> str:
        return _detect_exe(self.gameDirectory().absolutePath())

    def executables(self) -> list:
        gd = self.gameDirectory().absolutePath()
        result = []
        exe_defs = [
            (MAIN_EXE, "GTA San Andreas"),
            (ALT_EXE,  "GTA San Andreas (gta-sa.exe)"),
            (SAMP_EXE, "SA-MP (San Andreas Multiplayer)"),
        ]
        for exe, label in exe_defs:
            full = os.path.join(gd, exe)
            if os.path.isfile(full):
                info = mobase.ExecutableInfo(label, QFileInfo(full)).withWorkingDirectory(gd)
                if exe != SAMP_EXE:
                    info = info.withArgument("-nointro")
                result.append(info)

        if not result:
            result.append(
                mobase.ExecutableInfo(
                    "GTA San Andreas", QFileInfo(os.path.join(gd, MAIN_EXE))
                ).withWorkingDirectory(gd).withArgument("-nointro")
            )
        return result

    def executableForcedLoads(self) -> list:
        return []

    # ── IPluginGame: Perfil e Validação ───────────────────────────────────────

    def initializeProfile(self, directory: QDir, settings: mobase.ProfileSetting) -> None:
        Path(directory.absolutePath()).mkdir(parents=True, exist_ok=True)

    def isInstalled(self) -> bool:
        return _has_game_exe(self.gameDirectory().absolutePath())

    def looksValid(self, directory: QDir) -> bool:
        return _has_game_exe(directory.absolutePath())

    def detectGame(self) -> None:
        found = _find_game()
        if found:
            self._path = found

    def profileLocalSaves(self, profile: mobase.IProfile) -> bool:
        return False

    # ── IPluginGame: Stubs (não usados para jogos não-Bethesda) ───────────────

    def listSaves(self, folder: QDir) -> list: return []
    def iniFiles(self)    -> list: return []
    def DLCPlugins(self)  -> list: return []
    def sortMods(self)    -> bool: return False
    def featureList(self) -> dict: return {}

    # ── Hook: antes de executar o jogo ────────────────────────────────────────

    def _on_about_to_run(self, executable: str, working_dir: QDir, arguments: str) -> bool:
        """
        Sincroniza os arquivos físicos e as prioridades do Modloader antes de
        qualquer executável. O jogo e o SA-MP são iniciados diretamente (sem
        USVFS) com os argumentos e a pasta configurados no MO2.
        """
        executable_path = Path(executable)
        direct_launch = executable_path.name.casefold() in _DIRECT_LAUNCH
        gd = self.gameDirectory().absolutePath()

        running = _running_process_names() & _GAME_PROCESSES
        if running:
            QMessageBox.warning(
                _dialog_parent(),
                "GTA San Andreas",
                "O GTA San Andreas ainda está em execução "
                f"({', '.join(sorted(running))}).\n\n"
                "Feche o jogo (verifique o Gerenciador de Tarefas) antes de iniciar "
                "de novo; com ele aberto os arquivos dos mods ficam travados e a "
                "sincronização sai incompleta.",
            )
            log.warning(f"[GTASA] Launch cancelled: game already running ({running}).")
            return False

        try:
            sync = root_linker.sync_mods(self._organizer, gd)
            # Depois da sincronização, para enxergar o estado final de modloader/.
            modloader_ini.write_priorities(
                gd,
                self._organizer,
                ignore_unmanaged=self._setting(SETTING_IGNORE_UNMANAGED, True),
            )
        except Exception:
            details = traceback.format_exc()
            log.error(f"[GTASA] Pre-launch synchronization failed:\n{details}")
            QMessageBox.critical(
                _dialog_parent(),
                "GTA San Andreas",
                "A sincronização dos mods falhou e a execução foi cancelada.\n\n"
                f"{details.strip().splitlines()[-1]}\n\n"
                "Veja os detalhes em logs/mo_interface.log.",
            )
            # Iniciar com USVFS não serve de alternativa: o jogo não funciona com
            # a injeção e os mods não chegariam à pasta real.
            return False

        if sync.errors:
            shown = "\n".join(f"• {message}" for message in sync.errors[:8])
            more = f"\n… e mais {len(sync.errors) - 8}." if len(sync.errors) > 8 else ""
            answer = QMessageBox.question(
                _dialog_parent(),
                "GTA San Andreas",
                f"{len(sync.errors)} problema(s) durante a sincronização dos mods; "
                f"alguns arquivos podem não estar atualizados:\n\n{shown}{more}\n\n"
                "Iniciar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        if not direct_launch:
            return True

        # onAboutToRun ocorre antes da injeção do USVFS; iniciamos o executável
        # diretamente e retornamos False para cancelar o lançamento pelo MO2.
        if not executable_path.is_file():
            log.error(f"[GTASA] Executable not found: {executable_path}")
            return False

        work_dir = working_dir.absolutePath() if working_dir is not None else ""
        if not work_dir or not os.path.isdir(work_dir):
            work_dir = gd
        argument_list = _split_arguments(arguments)

        launch_result = QProcess.startDetached(
            str(executable_path), argument_list, work_dir
        )
        started = (
            bool(launch_result[0]) if isinstance(launch_result, tuple) else bool(launch_result)
        )
        if not started:
            log.error(f"[GTASA] Failed to launch without USVFS: {executable_path}")
            QMessageBox.critical(
                _dialog_parent(),
                "GTA San Andreas",
                f"Não foi possível iniciar {executable_path.name}.",
            )
        else:
            log.info(
                f"[GTASA] Game launched without USVFS: {executable_path} "
                f"{' '.join(argument_list)}".rstrip()
            )
        return False
