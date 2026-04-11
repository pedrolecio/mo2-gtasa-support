"""
plugin.py
---------
GTASAGame: implementa IPluginGame + IPluginFileMapper para o GTA San Andreas clássico.

Estratégia de VFS (Virtual File System):
  - dataDirectory() retorna a raíz do JOGO, não a pasta modloader.
    Isso diz ao MO2 que o "data root" de todos os mods é a raíz do jogo.
  - mappings() percorre todos os mods ativos (ordem de prioridade) e cria
    mapeamentos INDIVIDUAIS de arquivo (não de pasta) para a raíz do jogo.
    Isso garante que o MO2 crie uma lista unificada de arquivos para cada
    subpasta (como cleo/), permitindo que CLEO, Modloader e quaisquer outras
    ferramentas vejam todos os arquivos de todos os mods simultaneamente.
  - Mapeamentos da pasta Overwrite → raíz do jogo são adicionados com
    create_target=True, permitindo que mods e ferramentas criem arquivos novos
    (ex: modloader.log, saves) que serão redirecionados ao Overwrite do MO2.
"""

from __future__ import annotations

import logging
import os
import traceback
import winreg
from pathlib import Path

import mobase
from PyQt6.QtCore import QDir, QFileInfo, QStandardPaths
from PyQt6.QtGui import QIcon

from . import modloader_ini
from . import root_linker

log = logging.getLogger("gtasa_support")

GAME_NAME       = "GTA: San Andreas"
MAIN_EXE        = "gta_sa.exe"   # Steam / versão original
ALT_EXE         = "gta-sa.exe"   # Hoodlum e algumas versões crackeadas
STEAM_APPID     = "12120"

# Tamanhos de arquivo do gta_sa.exe conhecidos da versão Hoodlum (bytes)
# v1.0 US Hoodlum = 14.383.616  |  v1.0 EU Hoodlum = 14.246.912
_HOODLUM_SIZES: set[int] = {14_383_616, 14_246_912}

# Extensões CLEO que precisam de mapeamento especial (raíz → cleo/)
_CLEO_EXTS = {".cs", ".csa", ".csi", ".fxt"}

# ── Detecção do jogo ────────────────────────────────────────────────────────


def _detect_exe(game_dir: str) -> str:
    """
    Retorna o nome do executável principal encontrado na pasta do jogo.
    Prioriza gta-sa.exe (Hoodlum/Downgraded) pois é o padrão para mods;
    usa gta_sa.exe como fallback (Steam/Original).
    """
    for exe in (ALT_EXE, MAIN_EXE): # Prioridade Hoodlum
        if os.path.isfile(os.path.join(game_dir, exe)):
            return exe
    return MAIN_EXE  # default


def _detect_hoodlum(game_dir: str) -> bool:
    """
    Verifica se a instalação usa o crack Hoodlum.
    Indicadores checados (em ordem):
      1. hoodlum.nfo presente na pasta do jogo
      2. gta-sa.exe presente (exe renomeado pelo Hoodlum)
      3. Tamanho do gta_sa.exe bate com tamanhos conhecidos do Hoodlum
    """
    # Indicador 1: arquivo .nfo do grupo
    if os.path.isfile(os.path.join(game_dir, "hoodlum.nfo")):
        return True
    # Indicador 2: executável renomeado
    if os.path.isfile(os.path.join(game_dir, ALT_EXE)):
        return True
    # Indicador 3: tamanho do exe bate
    main_path = os.path.join(game_dir, MAIN_EXE)
    if os.path.isfile(main_path):
        size = os.path.getsize(main_path)
        if size in _HOODLUM_SIZES:
            return True
    return False


def _find_game() -> str:
    """
    Tenta localizar a instalação do GTA SA no registro do Steam ou em caminhos comuns.
    Aceita tanto gta_sa.exe quanto gta-sa.exe (Hoodlum).
    Retorna a string do caminho se encontrado, ou "" caso contrário.
    """
    def _valid(path: str) -> bool:
        return (
            os.path.isfile(os.path.join(path, MAIN_EXE))
            or os.path.isfile(os.path.join(path, ALT_EXE))
        )

    # 1. Registro Steam
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 12120",
            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 12120",
        ):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallLocation")
                    if path and _valid(path):
                        return path
            except (FileNotFoundError, OSError):
                pass

    # 2. Caminhos comuns de instalação
    common_dirs = [
        r"C:\Program Files (x86)\Steam\steamapps\common\Grand Theft Auto San Andreas",
        r"C:\Program Files\Steam\steamapps\common\Grand Theft Auto San Andreas",
        r"C:\Program Files (x86)\Rockstar Games\GTA San Andreas",
        r"C:\Program Files\Rockstar Games\GTA San Andreas",
        r"D:\SteamLibrary\steamapps\common\Grand Theft Auto San Andreas",
        r"E:\SteamLibrary\steamapps\common\Grand Theft Auto San Andreas",
    ]
    for d in common_dirs:
        if _valid(d):
            return d

    return ""


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


class GTASAGame(mobase.IPluginGame): # Removido IPluginFileMapper (usando modo físico)
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
        """Retorna as funcionalidades customizadas do plugin."""
        if feature_type == mobase.ModDataChecker:
            return GTASAModDataChecker()
        return None

    def name(self) -> str:
        return "GTA San Andreas Support Plugin"

    def author(self) -> str:
        return "GTA SA Support Plugin"

    def description(self) -> str:
        return (
            "Suporte ao GTA San Andreas (clássico) com VFS file-level, "
            "suporte a Modloader, CLEO e arquivos de raíz."
        )

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(2, 0, 0, mobase.ReleaseType.final)

    def settings(self) -> list[mobase.PluginSetting]:
        return []

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
        A emulação real para a raíz é feita via IPluginFileMapper.
        """
        path = os.path.join(self.gameDirectory().absolutePath(), "GTA Root Folder")
        if not os.path.exists(path):
            try: os.makedirs(path, exist_ok=True)
            except: pass
        return QDir(path)

    def documentsDirectory(self) -> QDir:
        # Desativado: Deixa o jogo usar o caminho padrão do sistema para evitar conflitos
        return QDir()

    def savesDirectory(self) -> QDir:
        return QDir()

    # ── IPluginGame: Executáveis ───────────────────────────────────────────────

    def binaryName(self) -> str:
        return MAIN_EXE

    def executables(self) -> list:
        gd = self.gameDirectory().absolutePath()
        result = []
        exe_defs = [
            (MAIN_EXE,   "GTA San Andreas"),
            ("samp.exe", "SA-MP (San Andreas Multiplayer)"),
        ]
        for exe, label in exe_defs:
            full = os.path.join(gd, exe)
            if os.path.isfile(full):
                result.append(
                    mobase.ExecutableInfo(label, QFileInfo(full))
                    .withWorkingDirectory(gd)
                    .withArgument("-nointro")
                )

        # Fallback
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
        p = Path(directory.absolutePath())
        p.mkdir(parents=True, exist_ok=True)

    def isInstalled(self) -> bool:
        gd = self.gameDirectory().absolutePath()
        return (
            os.path.isfile(os.path.join(gd, MAIN_EXE))
            or os.path.isfile(os.path.join(gd, ALT_EXE))
        )

    def looksValid(self, directory: QDir) -> bool:
        d = directory.absolutePath()
        return (
            os.path.isfile(os.path.join(d, MAIN_EXE))
            or os.path.isfile(os.path.join(d, ALT_EXE))
        )

    def detectGame(self) -> None:
        found = _find_game()
        if found:
            self._path = found

    def profileLocalSaves(self, profile: mobase.IProfile) -> bool:
        return False

    # ── IPluginGame: Stubs (não usados para jogos não-Bethesda) ───────────────

    def listSaves(self)   -> list: return []
    def iniFiles(self)    -> list: return []
    def DLCPlugins(self)  -> list: return []
    def sortMods(self)    -> bool: return False
    def featureList(self) -> dict: return {}

    # ── Hook: antes de executar o jogo ────────────────────────────────────────

    def _on_about_to_run(self, executable: str) -> bool:
        """
        Sincroniza prioridades no modloader.ini e realiza a cópia física
        dos mods (estilo RootBuilder) antes de iniciar o jogo.
        """
        try:
            gd = self.gameDirectory().absolutePath()
            
            # 1. Sincroniza prioridades do Modloader
            modloader_ini.write_priorities(gd, self._organizer)
            
            # 2. Sincroniza arquivos físicos na raíz (Modo RootBuilder)
            log.info("[GTASA] Iniciando Root Sync (Modo Físico)...")
            root_linker.sync_mods(self._organizer, gd)
            
            return True
        except Exception:
            log.error(f"[GTASA] Falha no pre-run sync:\n{traceback.format_exc()}")
            return True # Permite o lançamento mesmo com o erro

