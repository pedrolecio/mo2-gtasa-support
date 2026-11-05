"""
modloader_ini.py
----------------
Sincroniza as prioridades do Modloader com a ordem de carga do MO2.

Como funciona:
  - O MO2 ordena os mods de prioridade 0 (menor) a N (maior).
  - No Modloader, um valor maior em [Profiles.<Perfil>.Priority] sobrescreve um
    menor; 0 faz a pasta ser ignorada.
  - Cada pasta em <mod>/modloader/ recebe a prioridade do MO2 + 1. Se varios
    mods do MO2 colocam arquivos na mesma pasta, vale a maior prioridade.
  - Pastas em <jogo>/modloader/ que nenhum mod ativo fornece (sobras de
    instalacoes manuais ou de mods desativados) recebem 0 por padrao, porque
    sem entrada o Modloader as carregaria com a prioridade padrao 50.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any

log = logging.getLogger("gtasa_support")

_ACTIVE_STATE = 0x2
_MIN_PRIORITY_LIMIT = 9999
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
_FOLDER_CONFIG = "Folder.Config"


def write_priorities(
    game_dir: str, organizer: Any, ignore_unmanaged: bool = True
) -> list[str]:
    """
    Ponto de entrada principal. Captura qualquer excecao para nao travar o MO2.
    Retorna as pastas de <jogo>/modloader/ que nenhum mod ativo fornece.
    """
    try:
        return _write_priorities_impl(game_dir, organizer, ignore_unmanaged)
    except Exception:
        log.error(
            f"[GTASA] Failed to synchronize Modloader priorities:\n"
            f"{traceback.format_exc()}"
        )
        return []


# ── Coleta ───────────────────────────────────────────────────────────────────


def _find_child_dir(parent: Path, name: str) -> Path | None:
    """Procura uma subpasta ignorando maiusculas/minusculas."""
    direct = parent / name
    if direct.is_dir():
        return direct
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() == name.casefold():
                return child
    except OSError:
        pass
    return None


def _is_mod_folder_name(name: str) -> bool:
    # .data e .profiles sao pastas internas do Modloader; .mohidden e do MO2.
    return not name.startswith(".") and not name.casefold().endswith(".mohidden")


def _collect_managed(mod_list: Any) -> dict[str, tuple[str, int]]:
    """casefold(nome da pasta) -> (nome, prioridade) para os mods ativos."""
    managed: dict[str, tuple[str, int]] = {}

    for name in mod_list.allModsByProfilePriority():
        if not bool(mod_list.state(name) & _ACTIVE_STATE):
            continue
        mod_ptr = mod_list.getMod(name)
        if not mod_ptr:
            continue

        modloader_dir = _find_child_dir(Path(mod_ptr.absolutePath()), "modloader")
        if modloader_dir is None:
            continue

        priority = mod_list.priority(name) + 1
        try:
            children = list(modloader_dir.iterdir())
        except OSError:
            continue
        for item in children:
            if not item.is_dir() or not _is_mod_folder_name(item.name):
                continue
            key = item.name.casefold()
            current = managed.get(key)
            if current is None or priority > current[1]:
                managed[key] = (item.name, priority)

    return managed


def _collect_game_folders(game_modloader: Path) -> dict[str, str]:
    """casefold(nome) -> nome das pastas existentes em <jogo>/modloader/."""
    if not game_modloader.is_dir():
        return {}
    result = {}
    for item in game_modloader.iterdir():
        if item.is_dir() and _is_mod_folder_name(item.name):
            result[item.name.casefold()] = item.name
    return result


# ── Edicao do INI (por linhas, preservando o resto do arquivo) ───────────────


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    """Indices (cabecalho, fim exclusivo) da secao, sem diferenciar maiusculas."""
    wanted = section.casefold()
    start = None
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if not match:
            continue
        if start is not None:
            return start, index
        if match.group(1).strip().casefold() == wanted:
            start = index
    if start is not None:
        return start, len(lines)
    return None


def _split_entry(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    value = value.split(";", 1)[0].strip()
    return key.strip(), value


def _get_value(lines: list[str], section: str, key: str) -> str | None:
    bounds = _section_bounds(lines, section)
    if bounds is None:
        return None
    for line in lines[bounds[0] + 1 : bounds[1]]:
        entry = _split_entry(line)
        if entry and entry[0].casefold() == key.casefold():
            return entry[1]
    return None


def _set_value(lines: list[str], section: str, key: str, value: str) -> None:
    bounds = _section_bounds(lines, section)
    new_line = f"{key} = {value}"
    if bounds is None:
        lines[0:0] = [f"[{section}]", new_line, ""]
        return
    start, end = bounds
    for index in range(start + 1, end):
        entry = _split_entry(lines[index])
        if entry and entry[0].casefold() == key.casefold():
            comment = ""
            if ";" in lines[index]:
                comment = " ;" + lines[index].split(";", 1)[1].rstrip()
            lines[index] = new_line + comment
            return
    lines.insert(start + 1, new_line)


def _replace_body(lines: list[str], section: str, body: list[str]) -> None:
    bounds = _section_bounds(lines, section)
    if bounds is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", f"[{section}]", *body])
        return
    start, end = bounds
    # Preserva linhas em branco que separam a proxima secao.
    trailing = 0
    while end - trailing - 1 > start and not lines[end - trailing - 1].strip():
        trailing += 1
    lines[start + 1 : end - trailing] = body


def _read_ini(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _write_ini(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\r\n") as stream:
            stream.write(content)
        if path.exists():
            os.chmod(path, 0o666)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


# ── Implementacao ────────────────────────────────────────────────────────────


def _write_priorities_impl(
    game_dir: str, organizer: Any, ignore_unmanaged: bool
) -> list[str]:
    mod_list = organizer.modList()
    game_modloader = Path(game_dir) / "modloader"

    managed = _collect_managed(mod_list)
    game_folders = _collect_game_folders(game_modloader)
    if not managed and not game_folders:
        return []

    unmanaged = sorted(
        (name for key, name in game_folders.items() if key not in managed),
        key=str.casefold,
    )

    ini_path = game_modloader / "modloader.ini"
    original = _read_ini(ini_path)
    lines = original.splitlines()

    profile = (_get_value(lines, _FOLDER_CONFIG, "Profile") or "Default").strip()
    priority_section = f"Profiles.{profile or 'Default'}.Priority"

    # PriorityLimit precisa cobrir a maior prioridade escrita.
    highest = max((priority for _, priority in managed.values()), default=0)
    wanted_limit = max(_MIN_PRIORITY_LIMIT, len(mod_list.allModsByProfilePriority()) + 10, highest + 10)
    try:
        current_limit = int(_get_value(lines, _FOLDER_CONFIG, "PriorityLimit") or 0)
    except ValueError:
        current_limit = 0
    if current_limit < wanted_limit:
        _set_value(lines, _FOLDER_CONFIG, "PriorityLimit", str(wanted_limit))

    # Le a secao atual para preservar comentarios e, se configurado, os valores
    # escolhidos manualmente para pastas nao gerenciadas.
    comments: list[str] = []
    existing: dict[str, str] = {}
    bounds = _section_bounds(lines, priority_section)
    if bounds is not None:
        for line in lines[bounds[0] + 1 : bounds[1]]:
            stripped = line.strip()
            if stripped.startswith(";") or stripped.startswith("#"):
                comments.append(line)
                continue
            entry = _split_entry(line)
            if entry:
                existing[entry[0].casefold()] = line.strip()

    body = list(comments)
    for key, (name, priority) in sorted(
        managed.items(), key=lambda item: (item[1][1], item[0])
    ):
        # Usa o nome como esta no disco do jogo, se existir.
        body.append(f"{game_folders.get(key, name)} = {priority}")
    for name in unmanaged:
        if ignore_unmanaged:
            body.append(f"{name} = 0")
        elif name.casefold() in existing:
            body.append(existing[name.casefold()])

    _replace_body(lines, priority_section, body)

    content = "\n".join(lines).rstrip("\n") + "\n"
    if content != original.replace("\r\n", "\n"):
        try:
            _write_ini(ini_path, content)
        except OSError:
            log.error(
                f"[GTASA] Failed to write Modloader priorities to {ini_path}:\n"
                f"{traceback.format_exc()}"
            )

    if unmanaged:
        action = "ignored (priority 0)" if ignore_unmanaged else "left unchanged"
        log.warning(
            f"[GTASA] {len(unmanaged)} folder(s) in modloader/ are not provided by "
            f"any active mod and were {action}: {', '.join(unmanaged)}"
        )
    return unmanaged
