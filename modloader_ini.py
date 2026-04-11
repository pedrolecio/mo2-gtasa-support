"""
modloader_ini.py
----------------
Sincroniza as prioridades do Modloader com a ordem de carga do MO2.

Como funciona:
  - O MO2 ordena os mods de prioridade 0 (menor) a N (maior).
  - O Modloader usa Priority = X onde X maior significa "carregado depois" (sobrescreve).
  - A lógica atribui a prioridade de cada mod no Modloader para ser exatamente a sua prioridade do MO2 + 1 (já que a contagem do MO2 começa em 0).
"""

import os
import re
import logging
import traceback
from pathlib import Path

log = logging.getLogger("gtasa_support")


def write_priorities(game_dir: str, organizer) -> None:
    """Ponto de entrada principal. Captura qualquer exceção para não travar o MO2."""
    try:
        _write_priorities_impl(game_dir, organizer)
    except Exception:
        log.error(f"[GTASA] Erro ao sincronizar prioridades:\n{traceback.format_exc()}")


def _write_priorities_impl(game_dir: str, organizer) -> None:
    mod_list = organizer.modList()
    all_mods = mod_list.allModsByProfilePriority()

    # Coleta os mods ativos com suas pastas no modloader
    entries_dict: dict[str, int] = {}

    for name in all_mods:
        # IModList.state() flag 0x2 = Active
        if bool(mod_list.state(name) & 0x2):
            mod_ptr = mod_list.getMod(name)
            if mod_ptr:
                mod_path = Path(mod_ptr.absolutePath())
                priority = mod_list.priority(name) + 1
                
                # Procura por subpastas dentro de 'modloader/' deste mod
                ml_path = mod_path / "modloader"
                if ml_path.is_dir():
                    for item in ml_path.iterdir():
                        if item.is_dir():
                            # Se múltiplos mods injetam arquivos na mesma pasta, usamos a maior prioridade
                            current_prio = entries_dict.get(item.name, 0)
                            entries_dict[item.name] = max(current_prio, priority)

    if not entries_dict:
        log.info("[GTASA] Nenhum mod ativo com pastas de modloader encontrado; modloader.ini não modificado.")
        return

    # Monta as linhas de prioridade
    priority_lines = [f"{folder} = {prio}" for folder, prio in entries_dict.items()]

    # Destinos onde o modloader.ini será escrito:
    #   1. Pasta do perfil MO2 (sobrescreve a pasta real via VFS)
    #   2. Pasta real do jogo/modloader (fallback caso a VFS não esteja ativa)
    targets: list[Path] = []
    try:
        profile_path = Path(organizer.profilePath())
        targets.append(profile_path / "modloader.ini")
    except Exception:
        pass
    targets.append(Path(game_dir) / "modloader" / "modloader.ini")

    section = "[Profiles.Default.Priority]"
    # Regex que captura a seção e seu conteúdo até a próxima seção ou fim do arquivo
    pattern = re.compile(
        r"(\[Profiles\.Default\.Priority\])(.*?)(\n\[|\Z)", re.DOTALL
    )

    for ini_path in targets:
        ini_path.parent.mkdir(parents=True, exist_ok=True)

        # Lê o conteúdo existente
        content = ""
        if ini_path.exists():
            for enc in ("utf-8", "cp1252"):
                try:
                    content = ini_path.read_text(encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue

        # Garante que a seção existe
        if section not in content:
            content = content.rstrip() + f"\n\n{section}\n"

        def _replace(m: re.Match) -> str:
            header = m.group(1)
            body   = m.group(2)
            tail   = m.group(3)
            # Mantém linhas de comentário existentes
            comments = [l for l in body.splitlines() if l.strip().startswith(";")]
            return header + "\n" + "\n".join(comments + priority_lines) + "\n" + tail

        new_content = pattern.sub(_replace, content)

        # Escrita atômica via arquivo temporário
        tmp_path = ini_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(new_content)
            if ini_path.exists():
                os.remove(ini_path)
            os.rename(tmp_path, ini_path)
            log.info(f"[GTASA] Prioridades escritas em: {ini_path}")
        except Exception:
            log.error(f"[GTASA] Falha ao escrever {ini_path}:\n{traceback.format_exc()}")
            if tmp_path.exists():
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
