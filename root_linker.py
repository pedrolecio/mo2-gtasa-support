"""
root_linker.py
--------------
Lógica para sincronização física de arquivos (estilo RootBuilder).
Copia arquivos dos mods para a pasta do jogo antes do lançamento e permite limpeza posterior.
"""

import os
import shutil
import logging
import json
from pathlib import Path

log = logging.getLogger("gtasa_support")

TRACKING_FILE = ".mo2_root_mod_files.json"
BACKUP_DIR = ".mo2_root_backups"

def _cleanup_empty_dirs(game_path: Path, rel_paths: list[str]) -> None:
    """Tenta remover diretórios vazios resultantes da exclusão de arquivos."""
    dirs_to_check = set()
    for rel_str in rel_paths:
        p = (game_path / rel_str).parent
        while p != game_path and game_path in p.parents:
            dirs_to_check.add(p)
            p = p.parent
            
    for p in sorted(dirs_to_check, key=lambda x: len(x.parts), reverse=True):
        if p.exists() and p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass

def sync_mods(organizer, game_dir):
    """
    Sincroniza fisicamente os mods com a pasta do jogo.
    Remove arquivos de mods desativados e copia os novos.
    """
    game_path = Path(game_dir)
    mod_list = organizer.modList()
    all_mods = mod_list.allModsByProfilePriority()
    
    tracking_path = game_path / TRACKING_FILE
    tracked_files = []
    if tracking_path.exists():
        try:
            with open(tracking_path, "r") as f:
                tracked_files = json.load(f)
        except:
            pass

    # ── 1. Coleta o "Estado Desejado" (arquivos de mods ativos) ────────────
    target_state: dict[str, tuple[Path, Path]] = {} # rel_str -> (src_full, rel_path_obj)
    
    for name in all_mods:
        if not bool(mod_list.state(name) & 0x2):
            continue
        
        mod_ptr = mod_list.getMod(name)
        if not mod_ptr:
            continue
            
        mod_root = Path(mod_ptr.absolutePath())
        for src_file in mod_root.rglob("*"):
            if not src_file.is_file():
                continue
                
            rel = src_file.relative_to(mod_root)
            rel_str = str(rel).lower()

            # Proteção: não sobrescreve o exe principal
            if rel.name.lower() in ["gta_sa.exe", "gta-sa.exe"]:
                continue
                
            # Ordem de prioridade (mods de maior prioridade sobrescrevem no dict)
            target_state[rel_str] = (src_file, rel)

    # ── 2. Limpeza: remove arquivos rastreados que não estão mais ativos ───
    removed_count = 0
    removed_paths = []
    current_tracked = set(tracked_files)
    to_keep_tracked = set()
    backup_path = game_path / BACKUP_DIR

    for rel_str in current_tracked:
        if rel_str not in target_state:
            dst_file = game_path / rel_str
            if dst_file.exists():
                try:
                    os.remove(dst_file)
                    removed_count += 1
                    removed_paths.append(rel_str)
                except Exception as e:
                    log.error(f"[GTASA Linker] Erro ao remover {rel_str}: {e}")
            
            # Restaura backup se existir
            b_file = backup_path / rel_str
            if b_file.exists():
                try:
                    os.makedirs(dst_file.parent, exist_ok=True)
                    shutil.move(str(b_file), str(dst_file))
                except Exception as e:
                    log.error(f"[GTASA Linker] Erro ao restaurar backup de {rel_str}: {e}")
        else:
            to_keep_tracked.add(rel_str)

    if removed_paths:
        _cleanup_empty_dirs(game_path, removed_paths)

    if removed_count > 0:
        log.info(f"[GTASA Linker] Removidos {removed_count} arquivos de mods desativados.")

    # ── 3. Cópia: atualiza/adiciona arquivos dos mods ativos ───────────────
    added_count = 0
    for rel_str, (src_file, rel) in target_state.items():
        dst_file = game_path / rel
        
        should_copy = False
        if rel_str not in to_keep_tracked or not dst_file.exists():
            should_copy = True
        else:
            # Mesmo já rastreado, o mod de maior prioridade pode ter assumido a liderança.
            try:
                s_stat = src_file.stat()
                d_stat = dst_file.stat()
                # Se tamanho ou mtime forem diferentes, o arquivo mudou ou veio de outro mod
                if s_stat.st_size != d_stat.st_size or abs(s_stat.st_mtime - d_stat.st_mtime) > 0.1:
                    should_copy = True
            except Exception:
                should_copy = True
                
        if should_copy:
            try:
                # Backup de arquivo original se necessário (só faz a primeira vez que toca)
                if dst_file.exists() and rel_str not in current_tracked:
                    b_file = backup_path / rel
                    os.makedirs(b_file.parent, exist_ok=True)
                    if not b_file.exists():
                        shutil.copy2(dst_file, b_file)

                os.makedirs(dst_file.parent, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                to_keep_tracked.add(rel_str)
                added_count += 1
            except Exception as e:
                log.error(f"[GTASA Linker] Erro ao copiar {rel_str}: {e}")

    # ── 4. Salva novo estado de rastreamento ──────────────────────────────
    try:
        with open(tracking_path, "w") as f:
            json.dump(list(to_keep_tracked), f)
    except Exception as e:
        log.error(f"[GTASA Linker] Erro ao salvar tracking: {e}")
        
    log.info(f"[GTASA Linker] Sincronização concluída. Ativos: {len(target_state)}, Adicionados: {added_count}.")

def clear_mods(game_dir):
    """
    Remove todos os arquivos que foram copiados pelo linker.
    """
    game_path = Path(game_dir)
    tracking_path = game_path / TRACKING_FILE
    backup_path = game_path / BACKUP_DIR
    
    if not tracking_path.exists():
        log.info("[GTASA Linker] Nenhum arquivo para limpar.")
        return

    try:
        with open(tracking_path, "r") as f:
            files_to_remove = json.load(f)
            
        count = 0
        for rel_path in files_to_remove:
            path = game_path / rel_path
            if path.exists() and path.is_file():
                try:
                    os.remove(path)
                    count += 1
                except:
                    pass
            
            # Restaura backup se existir
            b_file = backup_path / rel_path
            if b_file.exists():
                try:
                    os.makedirs(path.parent, exist_ok=True)
                    shutil.move(str(b_file), str(path))
                except:
                    pass
        
        # Tenta remover pastas vazias remanescentes (de baixo para cima)
        _cleanup_empty_dirs(game_path, files_to_remove)
        
        os.remove(tracking_path)
        log.info(f"[GTASA Linker] Limpeza concluída. {count} arquivos removidos.")
    except Exception as e:
        log.error(f"[GTASA Linker] Erro na limpeza: {e}")
