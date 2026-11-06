"""
Sincronizacao fisica dos arquivos de mods com a pasta do jogo.

O manifesto registra, alem dos caminhos copiados, qual arquivo de qual mod venceu
cada conflito e o estado do destino logo apos a copia. Isso permite:

  - trocar o arquivo quando o mod vencedor muda, mesmo com tamanho/data iguais;
  - perceber quando o jogo (ou o usuario) alterou um arquivo implantado, como um
    .ini de configuracao, e restaurar a versao do MO2 (que sempre vence),
    guardando a versao alterada em .mo2_root_orphans/;
  - nunca tratar conteudo de modloader/ como arquivo original do jogo.
"""

from __future__ import annotations

import filecmp
import json
import logging
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("gtasa_support")

TRACKING_FILE = ".mo2_root_mod_files.json"
BACKUP_DIR = ".mo2_root_backups"
ORPHAN_DIR = ".mo2_root_orphans"
MANIFEST_VERSION = 3
_ACTIVE_STATE = 0x2
_MTIME_TOLERANCE_NS = 100_000_000
_HIDDEN_SUFFIX = ".mohidden"

_PROTECTED_ROOT_ENTRIES = {
    TRACKING_FILE.casefold(),
    (TRACKING_FILE + ".tmp").casefold(),
    BACKUP_DIR.casefold(),
    ORPHAN_DIR.casefold(),
}
_PROTECTED_EXECUTABLES = {"gta_sa.exe", "gta-sa.exe"}
# Arquivos geridos pelo proprio plugin ou pelo modloader em tempo de execucao.
_PROTECTED_PATHS = {"modloader/modloader.ini", "modloader/modloader.log"}
# Metadados do MO2 na raiz de cada mod; nunca pertencem ao jogo.
_MOD_ROOT_METADATA_FILES = {"meta.ini"}
_MOD_ROOT_METADATA_DIRS = {"fomod"}
# Nada dentro destas pastas faz parte da instalacao original do jogo.
_NON_ORIGINAL_ROOTS = {"modloader"}


@dataclass
class SyncResult:
    copied: int = 0
    removed: int = 0
    restored: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _path_key(path: Path | str) -> str:
    """Cria uma chave estavel e case-insensitive para caminhos relativos."""
    return str(path).replace("\\", "/").casefold()


def _source_id(path: Path) -> str:
    """Identifica a origem; um novo mod nunca e confundido com o anterior."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_safe_relative(path: Path) -> bool:
    """Impede que um caminho de mod escape da pasta do jogo."""
    return not path.is_absolute() and ".." not in path.parts and bool(path.parts)


def _is_protected(path: Path) -> bool:
    first_part = path.parts[0].casefold() if path.parts else ""
    return (
        first_part in _PROTECTED_ROOT_ENTRIES
        or path.name.casefold() in _PROTECTED_EXECUTABLES
        or _path_key(path) in _PROTECTED_PATHS
    )


def _is_non_original(path: Path) -> bool:
    """Arquivos em modloader/ sempre vieram de algum mod, nunca do jogo."""
    return bool(path.parts) and path.parts[0].casefold() in _NON_ORIGINAL_ROOTS


def _make_writable(path: Path) -> None:
    """Remove o atributo somente-leitura sem alterar outras permissoes."""
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IWRITE)


def _remove_file(path: Path) -> None:
    _make_writable(path)
    path.unlink()


def _replace_file(source: Path, destination: Path) -> None:
    """Copia para um temporario e substitui o destino em uma unica operacao."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".mo2-copy-", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        shutil.copy2(source, temporary_path)
        _make_writable(destination)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            _remove_file(temporary_path)


def _move_file(source: Path, destination: Path) -> None:
    """Move substituindo um destino existente."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _remove_file(destination)
    _make_writable(source)
    shutil.move(os.fspath(source), os.fspath(destination))


def _cleanup_empty_dirs(base_path: Path, rel_paths: list[str]) -> None:
    """Tenta remover diretorios vazios resultantes da exclusao de arquivos."""
    dirs_to_check: set[Path] = set()
    for rel_str in rel_paths:
        relative = Path(rel_str)
        if not _is_safe_relative(relative):
            continue
        current = (base_path / relative).parent
        while current != base_path and base_path in current.parents:
            dirs_to_check.add(current)
            current = current.parent

    for directory in sorted(dirs_to_check, key=lambda item: len(item.parts), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def _load_manifest(
    tracking_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Le o formato atual e migra os formatos antigos. Retorna (arquivos, pastas)."""
    if not tracking_path.exists():
        return {}, {}

    try:
        with tracking_path.open("r", encoding="utf-8") as stream:
            raw_manifest = json.load(stream)
    except (OSError, json.JSONDecodeError, TypeError, UnicodeDecodeError) as error:
        log.warning(f"[GTASA Linker] Invalid manifest at {tracking_path}: {error}")
        return {}, {}

    if isinstance(raw_manifest, list):
        files = {}
        for raw_path in raw_manifest:
            if isinstance(raw_path, str) and _is_safe_relative(Path(raw_path)):
                files[_path_key(raw_path)] = {"path": raw_path, "source": None}
        return files, {}

    if not isinstance(raw_manifest, dict) or not isinstance(raw_manifest.get("files"), dict):
        log.warning("[GTASA Linker] Unknown manifest format; it will be rebuilt.")
        return {}, {}

    def _entries(raw: Any) -> dict[str, dict[str, Any]]:
        result = {}
        if not isinstance(raw, dict):
            return result
        for raw_key, raw_entry in raw.items():
            if not isinstance(raw_entry, dict):
                continue
            raw_path = raw_entry.get("path", raw_key)
            if isinstance(raw_path, str) and _is_safe_relative(Path(raw_path)):
                result[_path_key(raw_path)] = raw_entry
        return result

    return _entries(raw_manifest["files"]), _entries(raw_manifest.get("dirs"))


def _save_manifest(
    tracking_path: Path,
    tracked_files: dict[str, dict[str, Any]],
    tracked_dirs: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Grava o manifesto atomicamente para nao deixa-lo truncado apos um crash."""
    payload = {
        "version": MANIFEST_VERSION,
        "files": dict(sorted(tracked_files.items())),
        "dirs": dict(sorted((tracked_dirs or {}).items())),
    }
    tracking_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = tracking_path.with_name(tracking_path.name + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        _make_writable(tracking_path)
        os.replace(temporary_path, tracking_path)
    finally:
        if temporary_path.exists():
            _remove_file(temporary_path)


def _stat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _same_stat(size_a: Any, mtime_a: Any, size_b: Any, mtime_b: Any) -> bool:
    if not isinstance(mtime_a, int) or not isinstance(mtime_b, int):
        return False
    return size_a == size_b and abs(mtime_a - mtime_b) <= _MTIME_TOLERANCE_NS


def _ordered_mod_names(mod_list: Any) -> list[str]:
    """Ordena explicitamente da menor para a maior prioridade do MO2."""
    names = list(mod_list.allModsByProfilePriority())
    try:
        return sorted(names, key=mod_list.priority)
    except Exception:
        log.warning(
            "[GTASA Linker] Could not read mod priorities; using the order from MO2."
        )
        return names


def _scan_mod(mod_root: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """
    Lista (origem, relativo) dos arquivos de um mod e as pastas vazias dele.
    Ignora metadados do MO2 e arquivos ocultos (.mohidden). Erros de leitura
    sao propagados para que o mod inteiro seja tratado como "nao lido".
    """
    files: list[tuple[Path, Path]] = []
    empty_dirs: list[Path] = []

    def _raise(error: OSError) -> None:
        raise error

    for current, dir_names, file_names in os.walk(mod_root, onerror=_raise):
        current_path = Path(current)
        relative_dir = current_path.relative_to(mod_root)
        at_root = not relative_dir.parts

        if not at_root and not dir_names and not file_names:
            empty_dirs.append(relative_dir)

        dir_names[:] = [
            name
            for name in dir_names
            if not name.casefold().endswith(_HIDDEN_SUFFIX)
            and not (at_root and name.casefold() in _MOD_ROOT_METADATA_DIRS)
        ]

        for name in file_names:
            folded = name.casefold()
            if folded.endswith(_HIDDEN_SUFFIX):
                continue
            if at_root and folded in _MOD_ROOT_METADATA_FILES:
                continue
            files.append((current_path / name, relative_dir / name))

    return files, empty_dirs


def _collect_target_state(
    mod_list: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str], list[str]]:
    """
    Coleta o arquivo vencedor para cada destino, respeitando a prioridade.
    Retorna (arquivos, pastas vazias, mods que nao puderam ser lidos, erros).
    """
    target_files: dict[str, dict[str, Any]] = {}
    target_dirs: dict[str, dict[str, Any]] = {}
    failed_mods: set[str] = set()
    errors: list[str] = []

    for mod_name in _ordered_mod_names(mod_list):
        if not bool(mod_list.state(mod_name) & _ACTIVE_STATE):
            continue

        mod_ptr = mod_list.getMod(mod_name)
        if not mod_ptr:
            continue

        mod_root = Path(mod_ptr.absolutePath())
        if not mod_root.is_dir():
            message = f"Mod directory not found for '{mod_name}': {mod_root}"
            log.warning(f"[GTASA Linker] {message}")
            failed_mods.add(str(mod_name))
            errors.append(message)
            continue

        try:
            files, empty_dirs = _scan_mod(mod_root)
        except OSError as error:
            # Sem conseguir ler o mod, nao sabemos o que ele fornece; os arquivos
            # dele que ja estao implantados sao mantidos como estao.
            message = f"Could not read mod '{mod_name}': {error}"
            log.error(f"[GTASA Linker] {message}")
            failed_mods.add(str(mod_name))
            errors.append(message)
            continue

        for source, relative in files:
            if not _is_safe_relative(relative) or _is_protected(relative):
                continue
            # Como os mods estao em ordem crescente, o ultimo tem maior prioridade.
            target_files[_path_key(relative)] = {
                "source_path": source,
                "source": _source_id(source),
                "source_mod": str(mod_name),
                "path": str(relative),
            }

        for relative in empty_dirs:
            if _is_safe_relative(relative) and not _is_protected(relative):
                target_dirs[_path_key(relative)] = {
                    "path": str(relative),
                    "source_mod": str(mod_name),
                }

    return target_files, target_dirs, failed_mods, errors


def _restore_backup(backup: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _remove_file(destination)
    shutil.move(os.fspath(backup), os.fspath(destination))


def _migrate_non_original_backups(backup_path: Path, orphan_path: Path) -> int:
    """
    Versoes anteriores faziam backup de arquivos em modloader/ como se fossem
    originais e os "restauravam" ao desativar o mod, trazendo de volta versoes
    antigas. Esses backups sao movidos para a pasta de orfaos, que nunca e
    restaurada automaticamente.
    """
    if not backup_path.is_dir():
        return 0

    moved: list[str] = []
    for child in backup_path.iterdir():
        if not child.is_dir() or child.name.casefold() not in _NON_ORIGINAL_ROOTS:
            continue
        for current, _, file_names in os.walk(child):
            for name in file_names:
                source = Path(current) / name
                relative = source.relative_to(backup_path)
                try:
                    _move_file(source, orphan_path / relative)
                    moved.append(str(relative))
                except OSError as error:
                    log.error(
                        f"[GTASA Linker] Failed to move stale backup {relative}: {error}"
                    )
    _cleanup_empty_dirs(backup_path, moved)

    if moved:
        log.warning(
            f"[GTASA Linker] Moved {len(moved)} non-original backups from "
            f"{BACKUP_DIR}/modloader to {ORPHAN_DIR}/ (they will not be restored)."
        )
    return len(moved)


def _take_over_untracked(
    source: Path,
    destination: Path,
    relative: Path,
    backup_path: Path,
    orphan_path: Path,
    result: SyncResult,
) -> None:
    """
    Trata um arquivo ja existente no destino que o manifesto nao conhece.
    Fora de modloader/ ele pode ser original do jogo: guarda um backup que sera
    restaurado quando nenhum mod fornecer mais o caminho. Dentro de modloader/
    ele e sobra de alguma instalacao manual: vai para a pasta de orfaos (a nao
    ser que seja identico ao novo arquivo) e nunca e restaurado.
    """
    if _is_non_original(relative):
        try:
            identical = filecmp.cmp(destination, source, shallow=False)
        except OSError:
            identical = False
        if not identical:
            _move_file(destination, orphan_path / relative)
            result.orphaned.append(str(relative))
        return

    backup = backup_path / relative
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup)


def _keep_game_copy(
    source: Path,
    destination: Path,
    relative: Path,
    orphan_path: Path,
    result: SyncResult,
) -> None:
    """
    O jogo ou o usuario alterou um arquivo implantado (ex.: um .ini regravado
    por um mod ou um .weaponinfo salvo por um editor in-game). A versao do MO2
    vai substitui-lo; a versao alterada e guardada na pasta de orfaos.
    """
    try:
        identical = filecmp.cmp(destination, source, shallow=False)
    except OSError:
        identical = False
    if identical:
        return
    saved = orphan_path / relative
    saved.parent.mkdir(parents=True, exist_ok=True)
    if saved.exists():
        _remove_file(saved)
    shutil.copy2(destination, saved)
    result.restored.append(str(relative))


def _summary(paths: list[str], limit: int = 10) -> str:
    text = ", ".join(paths[:limit])
    return text + (" ..." if len(paths) > limit else "")


def sync_mods(organizer: Any, game_dir: str) -> SyncResult:
    """Sincroniza os mods ativos com a pasta do jogo."""
    game_path = Path(game_dir)
    tracking_path = game_path / TRACKING_FILE
    backup_path = game_path / BACKUP_DIR
    orphan_path = game_path / ORPHAN_DIR
    result = SyncResult()

    _migrate_non_original_backups(backup_path, orphan_path)

    previous_files, previous_dirs = _load_manifest(tracking_path)
    target_files, target_dirs, failed_mods, scan_errors = _collect_target_state(
        organizer.modList()
    )
    result.errors.extend(scan_errors)
    next_files: dict[str, dict[str, Any]] = {}
    next_dirs: dict[str, dict[str, Any]] = {}
    removed_paths: list[str] = []

    # Remove arquivos que deixaram de ser fornecidos por qualquer mod e restaura
    # o original. Em caso de erro, mantem a entrada para tentar novamente.
    for key, previous in previous_files.items():
        if key in target_files:
            continue

        relative = Path(str(previous.get("path", key)))
        if not _is_safe_relative(relative) or _is_protected(relative):
            continue

        if previous.get("source_mod") in failed_mods:
            next_files[key] = previous
            continue

        destination = game_path / relative
        backup = backup_path / relative
        try:
            if destination.is_file():
                _remove_file(destination)
                result.removed += 1
            if backup.is_file() and not _is_non_original(relative):
                _restore_backup(backup, destination)
            removed_paths.append(str(relative))
        except OSError as error:
            message = f"Failed to remove or restore {relative}: {error}"
            log.error(f"[GTASA Linker] {message}")
            result.errors.append(message)
            next_files[key] = previous

    # Pastas vazias que nenhum mod fornece mais.
    for key, previous in previous_dirs.items():
        if key in target_dirs:
            continue
        relative = Path(str(previous.get("path", key)))
        if not _is_safe_relative(relative) or _is_protected(relative):
            continue
        if previous.get("source_mod") in failed_mods:
            next_dirs[key] = previous
            continue
        try:
            (game_path / relative).rmdir()
        except OSError:
            # Nao existe ou nao esta vazia (o jogo gravou algo): deixa de rastrear.
            pass
        removed_paths.append(str(relative / "_"))

    _cleanup_empty_dirs(game_path, removed_paths)

    for key, target in target_files.items():
        source = target["source_path"]
        relative = Path(target["path"])
        destination = game_path / relative
        previous = previous_files.get(key)

        try:
            source_stat = source.stat()
            destination_stat = _stat_or_none(destination)
            source_unchanged = (
                previous is not None
                and previous.get("source") == target["source"]
                and previous.get("size") == source_stat.st_size
                and previous.get("mtime_ns") == source_stat.st_mtime_ns
            )

            # Uma copia intacta tem o mesmo tamanho e data da origem que foi
            # implantada (copy2 preserva a data). Compara com essa origem, e nao
            # com dest_size/dest_mtime_ns: a versao 2.1.0 gravava ali o estado de
            # arquivos alterados pelo jogo, que assim pareciam intactos.
            deployed_as_recorded = False
            if previous is not None and destination_stat is not None:
                deployed_as_recorded = _same_stat(
                    destination_stat.st_size,
                    destination_stat.st_mtime_ns,
                    previous.get("size"),
                    previous.get("mtime_ns"),
                )

            # O MO2 e sempre a fonte da verdade: copia quando a origem mudou ou
            # quando o jogo/usuario alterou a copia implantada.
            if not (source_unchanged and deployed_as_recorded):
                if destination_stat is not None:
                    if previous is None:
                        _take_over_untracked(
                            source, destination, relative, backup_path, orphan_path, result
                        )
                    elif not deployed_as_recorded:
                        _keep_game_copy(source, destination, relative, orphan_path, result)
                _replace_file(source, destination)
                result.copied += 1
                destination_stat = destination.stat()

            next_files[key] = {
                "path": str(relative),
                "source": target["source"],
                "source_mod": target["source_mod"],
                "size": source_stat.st_size,
                "mtime_ns": source_stat.st_mtime_ns,
                "dest_size": destination_stat.st_size,
                "dest_mtime_ns": destination_stat.st_mtime_ns,
            }
        except OSError as error:
            message = (
                f"Failed to copy {relative} from mod '{target['source_mod']}': {error}"
            )
            log.error(f"[GTASA Linker] {message}")
            result.errors.append(message)
            if previous is not None:
                next_files[key] = previous

    for key, target in target_dirs.items():
        try:
            (game_path / target["path"]).mkdir(parents=True, exist_ok=True)
            next_dirs[key] = target
        except OSError as error:
            message = f"Failed to create directory {target['path']}: {error}"
            log.error(f"[GTASA Linker] {message}")
            result.errors.append(message)

    try:
        _save_manifest(tracking_path, next_files, next_dirs)
    except OSError as error:
        message = f"Failed to save manifest: {error}"
        log.error(f"[GTASA Linker] {message}")
        result.errors.append(message)

    if result.restored:
        log.warning(
            f"[GTASA Linker] Restored {len(result.restored)} file(s) changed in the game "
            f"folder from MO2; the changed copies were saved in {ORPHAN_DIR}/: "
            f"{_summary(result.restored)}"
        )
    if result.orphaned:
        log.warning(
            f"[GTASA Linker] Moved {len(result.orphaned)} untracked file(s) from "
            f"modloader/ to {ORPHAN_DIR}/: {_summary(result.orphaned)}"
        )
    if result.copied or result.removed:
        log.info(
            f"[GTASA Linker] Sync complete: {result.copied} copied, "
            f"{result.removed} removed."
        )
    return result


def clear_mods(game_dir: str) -> None:
    """Remove os arquivos copiados e restaura os originais preservados."""
    game_path = Path(game_dir)
    tracking_path = game_path / TRACKING_FILE
    backup_path = game_path / BACKUP_DIR

    if not tracking_path.exists():
        return

    tracked_files, tracked_dirs = _load_manifest(tracking_path)
    failed_files: dict[str, dict[str, Any]] = {}
    removed_paths: list[str] = []
    removed_count = 0

    for key, tracked in tracked_files.items():
        relative = Path(str(tracked.get("path", key)))
        if not _is_safe_relative(relative) or _is_protected(relative):
            continue

        destination = game_path / relative
        backup = backup_path / relative
        try:
            if destination.is_file():
                _remove_file(destination)
                removed_count += 1
            if backup.is_file() and not _is_non_original(relative):
                _restore_backup(backup, destination)
            removed_paths.append(str(relative))
        except OSError as error:
            log.error(f"[GTASA Linker] Failed to clean or restore {relative}: {error}")
            failed_files[key] = tracked

    for key, tracked in tracked_dirs.items():
        relative = Path(str(tracked.get("path", key)))
        if _is_safe_relative(relative) and not _is_protected(relative):
            try:
                (game_path / relative).rmdir()
            except OSError:
                pass
            removed_paths.append(str(relative / "_"))

    _cleanup_empty_dirs(game_path, removed_paths)

    try:
        if failed_files:
            _save_manifest(tracking_path, failed_files)
        else:
            _remove_file(tracking_path)
    except OSError as error:
        log.error(f"[GTASA Linker] Failed to update manifest after cleanup: {error}")

    log.info(f"[GTASA Linker] Cleanup complete: {removed_count} files removed.")
