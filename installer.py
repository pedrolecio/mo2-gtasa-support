"""
installer.py
------------
IPluginInstallerSimple para GTA San Andreas.

Detecta automaticamente o tipo de mod e organiza os arquivos durante a instalação:

  0. Uma única pasta "embrulhando" o conteúdo (ex.: "MeuMod v1/...") é aberta
  1. Mods com pasta "cleo/", "modloader/", ... existente → mantém a estrutura
  2. Mods CLEO (.cs, .csa, .csi, .fxt) na raíz → subpasta "cleo/"
  3. Mods com arquivos de raíz (.asi, .dll, .img, .dat ...) → instalados na raíz
  4. Mods com pastas de assets (models/, audio/, etc.) ou modelos soltos
     (.dff, .txd, .col, .ifp, .ide, .ipl) → embrulhados em "modloader/<nome>/"
  5. Qualquer outra coisa → instalador manual do MO2
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

import mobase
from PyQt6.QtWidgets import QWidget

log = logging.getLogger("gtasa_support")

# Extensões reconhecidas como scripts CLEO
CLEO_EXTENSIONS = {".cs", ".csa", ".csi", ".fxt"}

# Extensões tipicamente instaladas na raíz do jogo
ROOT_EXTENSIONS = {".asi", ".dll", ".exe", ".img", ".dat", ".cat"}

# Subpastas que indicam um mod de Modloader (assets do jogo)
MODLOADER_FOLDERS = {
    "models", "audio", "anim", "data", "txd", "vehicles",
    "weapons", "maps", "tex", "effects",
}

# Pastas de raíz que indicam uma instalação mista já estruturada
KNOWN_ROOT_FOLDERS = {"cleo", "modloader", "scripts", "moonloader"}

# Arquivos soltos que o Modloader carrega diretamente de modloader/<mod>/
MODLOADER_FILE_EXTENSIONS = {".dff", ".txd", ".col", ".ifp", ".ide", ".ipl"}

# Arquivos que costumam acompanhar uma pasta "embrulho" sem fazer parte do mod
DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".url", ".htm", ".html", ".nfo", ".png", ".jpg", ".jpeg",
}

_INVALID_NAME_CHARS = set('<>:"/\\|?*')


def _safe_folder_name(name: str) -> str:
    """Remove caracteres inválidos em nomes de pasta do Windows."""
    cleaned = "".join("_" if ch in _INVALID_NAME_CHARS or ord(ch) < 32 else ch for ch in name)
    cleaned = cleaned.strip().rstrip(". ")
    return cleaned or "Mod"


def _unwrap_single_folder(tree: mobase.IFileTree) -> bool:
    """
    Se o arquivo contém apenas uma pasta (mais, no máximo, documentação) e essa
    pasta não é uma estrutura reconhecida, move o conteúdo dela para a raíz.
    """
    dirs = [e for e in tree if e.isDir()]
    files = [e for e in tree if e.isFile()]
    if len(dirs) != 1:
        return False
    if any(Path(f.name()).suffix.lower() not in DOCUMENT_EXTENSIONS for f in files):
        return False

    wrapper = dirs[0]
    name = wrapper.name().lower()
    if name in KNOWN_ROOT_FOLDERS or name in MODLOADER_FOLDERS:
        return False
    child_names = {child.name().lower() for child in wrapper}
    if not child_names or name in child_names:
        return False
    # Não sobrescreve a documentação da raíz com a da pasta.
    if child_names & {f.name().lower() for f in files}:
        return False

    tree.merge(wrapper)
    wrapper.detach()
    return True


def _collect_entries(tree: mobase.IFileTree) -> list[mobase.FileTreeEntry]:
    """Retorna todos os FileTreeEntry (arquivos e pastas) no nível raíz da árvore."""
    return [tree[i] for i in range(len(tree))]


def _has_extension(tree: mobase.IFileTree, extensions: set[str]) -> bool:
    """Verifica se há algum arquivo com as extensões dadas em qualquer nível da árvore."""
    for entry in tree:
        if entry.isFile():
            if Path(entry.name()).suffix.lower() in extensions:
                return True
        elif entry.isDir():
            # Em python, entradas de diretório muitas vezes já são o próprio IFileTree
            if _has_extension(entry, extensions):
                return True
    return False


def _root_names_lower(tree: mobase.IFileTree) -> set[str]:
    """Retorna os nomes (em minúsculas) de todas as entradas no nível raíz."""
    return {entry.name().lower() for entry in tree}


class GTASAInstaller(mobase.IPluginInstallerSimple):
    """
    Instalador inteligente para mods do GTA San Andreas.
    """

    _organizer: mobase.IOrganizer

    def __init__(self):
        super().__init__()

    # ── IPlugin ────────────────────────────────────────────────────────────────

    def init(self, organizer: mobase.IOrganizer) -> bool:
        self._organizer = organizer
        return True

    def name(self) -> str:
        return "GTA SA Mod Installer"

    def author(self) -> str:
        return "GTA SA Support Plugin"

    def description(self) -> str:
        return (
            "Instala mods para GTA San Andreas, organizando automaticamente "
            "scripts CLEO, mods Modloader e arquivos de raíz."
        )

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(1, 1, 0, mobase.ReleaseType.final)

    def isActive(self) -> bool:
        return self._organizer.managedGame().gameShortName() == "GTASA"

    def settings(self) -> list[mobase.PluginSetting]:
        return []

    # ── IPluginInstallerSimple ─────────────────────────────────────────────────

    def priority(self) -> int:
        # Prioridade alta para sobrescrever o instalador genérico do MO2
        return 80

    def isManualInstaller(self) -> bool:
        return False

    def onInstallationStart(
        self,
        archive: str,
        reinstallation: bool,
        current_mod: mobase.IModInterface | None,
    ) -> None:
        pass

    def onInstallationEnd(
        self,
        result: mobase.InstallResult,
        new_mod: mobase.IModInterface | None,
    ) -> None:
        pass

    def isArchiveSupported(self, tree: mobase.IFileTree) -> bool:
        """Aceita qualquer arquivo se o jogo gerenciado for GTA SA."""
        return self.isActive()

    def install(
        self,
        name: mobase.GuessedString,
        tree: mobase.IFileTree,
        version: str,
        nexus_id: int,
    ) -> mobase.InstallResult:
        """
        Ponto de entrada principal. Reorganiza o FileTree conforme o tipo de mod
        detectado, depois delega ao manager interno do MO2 para concluir a instalação.
        """
        try:
            name_str = str(name)
            new_tree = self._reorganize(name_str, tree)
            if new_tree is None:
                # O fallback indicou que não sabe como instalar ou que a instalação
                # requer intervenção manual (arquivos dff/txd soltos etc).
                return getattr(mobase.InstallResult, "MANUAL_REQUESTED", mobase.InstallResult.NOT_ATTEMPTED)
            # A árvore já foi modificada in-place ou substitída por _reorganize (o MO2 processa as mudanças em `tree`)
        except Exception as e:
            log.error(f"[GTASA Installer] Failed to reorganize archive: {e}")
            # Mesmo em caso de erro, cai para instalador manual/padrão
            return getattr(mobase.InstallResult, "MANUAL_REQUESTED", mobase.InstallResult.NOT_ATTEMPTED)

        return mobase.InstallResult.SUCCESS

    # ── Lógica de detecção e reorganização ────────────────────────────────────

    def _reorganize(self, mod_name: str, tree: mobase.IFileTree) -> mobase.IFileTree | None:
        """
        Aplica a reorganização correta dependendo do tipo de mod detectado.
        Retorna a árvore (possivelmente modificada).
        """
        # ── Caso 0: abre pastas que só embrulham o conteúdo (pode haver várias)
        for _ in range(4):
            if not _unwrap_single_folder(tree):
                break
            log.info(f"[GTASA Installer] '{mod_name}': unwrapped a top-level folder.")

        root_names = _root_names_lower(tree)

        # ── Caso 1: Já tem estrutura conhecida (cleo/, modloader/, scripts/, …)
        if root_names & KNOWN_ROOT_FOLDERS:
            log.info(
                f"[GTASA Installer] '{mod_name}': keeping the existing directory layout."
            )
            return tree

        # Coleta arquivos na raíz
        root_files = [e for e in tree if e.isFile()]
        root_file_exts = {Path(e.name()).suffix.lower() for e in root_files}

        # ── Caso 2: Contém scripts CLEO na raíz
        if root_file_exts & CLEO_EXTENSIONS:
            log.info(
                f"[GTASA Installer] '{mod_name}': moving root CLEO scripts to cleo/."
            )
            return self._wrap_cleo_files(tree)

        # ── Caso 3: Contém arquivos típicos de raíz (.asi, .dll, etc.) na raíz
        if root_file_exts & ROOT_EXTENSIONS:
            log.info(
                f"[GTASA Installer] '{mod_name}': using the game-root layout."
            )
            return tree

        # ── Caso 4: Contém pastas de assets do Modloader
        root_folders_lower = {e.name().lower() for e in tree if e.isDir()}
        if root_folders_lower & MODLOADER_FOLDERS or root_file_exts & MODLOADER_FILE_EXTENSIONS:
            log.info(
                f"[GTASA Installer] '{mod_name}': wrapping assets in "
                f"modloader/{mod_name}/."
            )
            return self._wrap_in_modloader(mod_name, tree)

        # ── Caso 5: Busca CLEO em subpastas
        if _has_extension(tree, CLEO_EXTENSIONS):
            log.info(
                f"[GTASA Installer] '{mod_name}': nested CLEO layout requires "
                "manual installation."
            )
            return None

        # ── Fallback: requer instalação manual
        log.info(
            f"[GTASA Installer] '{mod_name}': unrecognized layout requires "
            "manual installation."
        )
        return None

    def _wrap_cleo_files(self, tree: mobase.IFileTree) -> mobase.IFileTree:
        """
        Move todos os arquivos CLEO da raíz para uma subpasta 'cleo/'.
        Arquivos não-CLEO permanecem na raíz.
        """
        # Obtém ou cria o diretório cleo/
        cleo_dir = tree.addDirectory("cleo")

        # Move arquivos CLEO da raíz para cleo/
        to_move = [
            e for e in list(tree)
            if e.isFile() and Path(e.name()).suffix.lower() in CLEO_EXTENSIONS
        ]
        for entry in to_move:
            # remove da raíz e adiciona em cleo/
            tree.move(entry, "cleo/")

        return tree

    def _wrap_in_modloader(self, mod_name: str, tree: mobase.IFileTree) -> mobase.IFileTree:
        """
        Embrulha todo o conteúdo da árvore dentro de 'modloader/<mod_name>/'.
        """
        # Cria "modloader/mod_name/" e move tudo para lá
        destination = f"modloader/{_safe_folder_name(mod_name)}/"
        for entry in list(tree):
            tree.move(entry, destination)
        return tree
