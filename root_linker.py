"""
Sincronizacao fisica dos arquivos de mods com a pasta do jogo.

O manifesto registra, alem dos caminhos copiados, qual arquivo de qual mod venceu
cada conflito. Isso e importante porque dois mods podem fornecer arquivos com o
mesmo tamanho e data de modificacao, mas com conteudos diferentes.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("gtasa_support")

TRACKING_FILE = ".mo2_root_mod_files.json"
BACKUP_DIR = ".mo2_root_backups"
MANIFEST_VERSION = 2
_ACTIVE_STATE = 0x2
_PROTECTED_ROOT_ENTRIES = {TRACKING_FILE.casefold(), BACKUP_DIR.casefold()}
_PROTECTED_EXECUTABLES = {"gta_sa.exe", "gta-sa.exe"}


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
    )


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


def _cleanup_empty_dirs(game_path: Path, rel_paths: list[str]) -> None:
    """Tenta remover diretorios vazios resultantes da exclusao de arquivos."""
    dirs_to_check: set[Path] = set()
    for rel_str in rel_paths:
        relative = Path(rel_str)
        if not _is_safe_relative(relative):
            continue
        current = (game_path / relative).parent
        while current != game_path and game_path in current.parents:
            dirs_to_check.add(current)
            current = current.parent

    for directory in sorted(dirs_to_check, key=lambda item: len(item.parts), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def _load_manifest(tracking_path: Path) -> dict[str, dict[str, Any]]:
    """Le o formato atual e migra o formato antigo (uma lista de caminhos)."""
    if not tracking_path.exists():
        return {}

    try:
        with tracking_path.open("r", encoding="utf-8") as stream:
            raw_manifest = json.load(stream)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        log.warning(f"[GTASA Linker] Invalid manifest at {tracking_path}: {error}")
        return {}

    if isinstance(raw_manifest, list):
        result = {}
        for raw_path in raw_manifest:
            if isinstance(raw_path, str) and _is_safe_relative(Path(raw_path)):
                result[_path_key(raw_path)] = {"path": raw_path, "source": None}
        return result

    if not isinstance(raw_manifest, dict) or not isinstance(raw_manifest.get("files"), dict):
        log.warning("[GTASA Linker] Unknown manifest format; it will be rebuilt.")
        return {}

    result = {}
    for raw_key, raw_entry in raw_manifest["files"].items():
        if not isinstance(raw_entry, dict):
            continue
        raw_path = raw_entry.get("path", raw_key)
        if isinstance(raw_path, str) and _is_safe_relative(Path(raw_path)):
            result[_path_key(raw_path)] = raw_entry
    return result


def _save_manifest(
    tracking_path: Path, tracked_files: dict[str, dict[str, Any]]
) -> None:
    """Grava o manifesto atomicamente para nao deixa-lo truncado apos um crash."""
    payload = {
        "version": MANIFEST_VERSION,
        "files": dict(sorted(tracked_files.items())),
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


def _source_metadata(source: Path) -> dict[str, int]:
    source_stat = source.stat()
    return {"size": source_stat.st_size, "mtime_ns": source_stat.st_mtime_ns}


def _destination_matches_source(source: Path, destination: Path) -> bool:
    """Evita recopias, mas detecta arquivos alterados pelo jogo ou pelo usuario."""
    try:
        source_stat = source.stat()
        destination_stat = destination.stat()
        return (
            source_stat.st_size == destination_stat.st_size
            and abs(source_stat.st_mtime_ns - destination_stat.st_mtime_ns)
            <= 100_000_000
        )
    except OSError:
        return False


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


def _collect_target_state(mod_list: Any) -> dict[str, dict[str, Any]]:
    """Coleta o arquivo vencedor para cada destino, respeitando a prioridade."""
    target_state: dict[str, dict[str, Any]] = {}

    for mod_name in _ordered_mod_names(mod_list):
        if not bool(mod_list.state(mod_name) & _ACTIVE_STATE):
            continue

        mod_ptr = mod_list.getMod(mod_name)
        if not mod_ptr:
            continue

        mod_root = Path(mod_ptr.absolutePath())
        if not mod_root.is_dir():
            log.warning(f"[GTASA Linker] Mod directory not found for '{mod_name}': {mod_root}")
            continue

        for source in mod_root.rglob("*"):
            if not source.is_file():
                continue

            relative = source.relative_to(mod_root)
            if not _is_safe_relative(relative) or _is_protected(relative):
                continue

            # Como os mods estao em ordem crescente, o ultimo tem maior prioridade.
            target_state[_path_key(relative)] = {
                "source_path": source,
                "source": _source_id(source),
                "source_mod": str(mod_name),
                "path": str(relative),
            }

    return target_state


def _restore_backup(backup: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _remove_file(destination)
    shutil.move(os.fspath(backup), os.fspath(destination))


def sync_mods(organizer: Any, game_dir: str) -> None:
    """Sincroniza os mods ativos com a pasta do jogo."""
    game_path = Path(game_dir)
    tracking_path = game_path / TRACKING_FILE
    backup_path = game_path / BACKUP_DIR
    previous_files = _load_manifest(tracking_path)
    target_state = _collect_target_state(organizer.modList())
    next_files: dict[str, dict[str, Any]] = {}

    removed_count = 0
    removed_paths: list[str] = []

    # Remove arquivos que deixaram de ser fornecidos por qualquer mod e restaura
    # o original. Em caso de erro, mantem a entrada para tentar novamente.
    for key, previous in previous_files.items():
        if key in target_state:
            continue

        relative = Path(str(previous.get("path", key)))
        if not _is_safe_relative(relative) or _is_protected(relative):
            continue

        destination = game_path / relative
        backup = backup_path / relative
        try:
            if destination.is_file():
                _remove_file(destination)
                removed_count += 1
            if backup.is_file():
                _restore_backup(backup, destination)
            removed_paths.append(str(relative))
        except OSError as error:
            log.error(f"[GTASA Linker] Failed to remove or restore {relative}: {error}")
            next_files[key] = previous

    _cleanup_empty_dirs(game_path, removed_paths)

    copied_count = 0
    for key, target in target_state.items():
        source = target["source_path"]
        relative = Path(target["path"])
        destination = game_path / relative
        backup = backup_path / relative
        previous = previous_files.get(key)

        try:
            metadata = _source_metadata(source)
            source_changed = (
                previous is None
                or previous.get("source") != target["source"]
                or previous.get("size") != metadata["size"]
                or previous.get("mtime_ns") != metadata["mtime_ns"]
            )
            should_copy = source_changed or not _destination_matches_source(source, destination)

            if should_copy:
                # So o primeiro mod que toca em um arquivo real cria o backup.
                if previous is None and destination.is_file() and not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)

                _replace_file(source, destination)
                copied_count += 1

            next_files[key] = {
                "path": str(relative),
                "source": target["source"],
                "source_mod": target["source_mod"],
                **metadata,
            }
        except OSError as error:
            log.error(
                f"[GTASA Linker] Failed to copy {relative} from mod "
                f"'{target['source_mod']}': {error}"
            )
            if previous is not None:
                next_files[key] = previous

    try:
        _save_manifest(tracking_path, next_files)
    except OSError as error:
        log.error(f"[GTASA Linker] Failed to save manifest: {error}")

    if copied_count or removed_count:
        log.info(
            f"[GTASA Linker] Sync complete: {copied_count} copied, "
            f"{removed_count} removed."
        )


def clear_mods(game_dir: str) -> None:
    """Remove os arquivos copiados e restaura os originais preservados."""
    game_path = Path(game_dir)
    tracking_path = game_path / TRACKING_FILE
    backup_path = game_path / BACKUP_DIR

    if not tracking_path.exists():
        return

    tracked_files = _load_manifest(tracking_path)
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
            if backup.is_file():
                _restore_backup(backup, destination)
            removed_paths.append(str(relative))
        except OSError as error:
            log.error(f"[GTASA Linker] Failed to clean or restore {relative}: {error}")
            failed_files[key] = tracked

    _cleanup_empty_dirs(game_path, removed_paths)

    try:
        if failed_files:
            _save_manifest(tracking_path, failed_files)
        else:
            _remove_file(tracking_path)
    except OSError as error:
        log.error(f"[GTASA Linker] Failed to update manifest after cleanup: {error}")

    log.info(f"[GTASA Linker] Cleanup complete: {removed_count} files removed.")
