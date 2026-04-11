"""
GTA San Andreas Support Plugin for Mod Organizer 2
===================================================
Suporte ao GTA San Andreas (versão clássica) com:
  - VFS file-level para modloader, cleo e raíz do jogo
  - Instalação inteligente de mods (modloader / cleo / raíz)
  - Sincronização de prioridades com modloader.ini
"""
from .plugin import GTASAGame
from .installer import GTASAInstaller


def createPlugins():
    return [GTASAGame(), GTASAInstaller()]
