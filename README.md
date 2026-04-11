# GTA San Andreas Support Plugin for Mod Organizer 2

Plugin completo para o **Mod Organizer 2** que adiciona suporte ao **GTA San Andreas (versão clássica – Steam/Retail)**.

## Funcionalidades

| Feature | Descrição |
|---|---|
| **VFS File-Level** | Mapeamento de arquivos individuais (não pastas inteiras), garantindo que mods de vários autores coexistam sem conflito em subpastas como `cleo/` e `modloader/` |
| **Instalação inteligente** | Detecta automaticamente o tipo do mod durante a instalação e organiza os arquivos corretamente |
| **CLEO Support** | Scripts `.cs`, `.csa`, `.csi`, `.fxt` são roteados para `cleo/` |
| **Modloader Support** | Mods com assets (`models/`, `audio/`, etc.) são embrulhados em `modloader/<nome>/` |
| **Root Mods** | Arquivos `.asi`, `.dll`, etc. são instalados na raíz do jogo |
| **Priority Sync** | Antes de cada execução, as prioridades do `modloader.ini` são sincronizadas com a ordem de carga do MO2 |
| **Overwrite Writable** | Logs, saves e configs criados pelo jogo/mods são redirecionados para a pasta Overwrite do MO2 |

---

## Instalação

1. Copie a pasta `gtasa_support/` para a pasta `plugins/` da sua instalação do MO2:
   ```
   Mod Organizer 2\plugins\gtasa_support\
   ```

2. Inicie o MO2. O jogo **GTA: San Andreas** aparecerá na lista de jogos.

3. Aponte para o diretório onde `gta_sa.exe` está instalado se o MO2 não detectar automaticamente.

---

## Como o VFS Funciona

```
[MO2 Mods]            [VFS]               [Jogo]
Mod A/cleo/a.cs  ──►  cleo/a.cs  ──►  GTA SA/cleo/a.cs
Mod B/cleo/b.cs  ──►  cleo/b.cs  ──►  GTA SA/cleo/b.cs   } Ambos visíveis!
Mod C/models/... ──►  modloader/... ──► GTA SA/modloader/...
Overwrite/       ──►  GTA SA/     (with createTarget=True = escrita permitida)
```

O mapeamento é **file-level**: o MO2 faz merge de todos os arquivos de todos os mods em cada subpasta, em vez de sobrescrever pastas inteiras. Isso garante que o CLEO veja todos os scripts `.cs` de todos os mods simultaneamente.

---

## Tipos de Mod e Estruturas Esperadas

### Mod CLEO (scripts)
```
MeuMod/
  myscript.cs        ← detectado pelo instalador → movido para cleo/
```
Resultado no MO2:
```
MeuMod/
  cleo/
    myscript.cs
```

### Mod de Raíz (ASI plugins, etc.)
```
MeuMod/
  myplugin.asi       ← detectado → fica na raíz
```

### Mod Modloader (assets)
```
MeuMod/
  models/
    veículo.dff      ← detectado → embrulhado em modloader/MeuMod/
```
Resultado:
```
MeuMod/
  modloader/
    MeuMod/
      models/
        veículo.dff
```

### Mod já estruturado
Se já contém `cleo/`, `modloader/`, `scripts/` → mantém como está.

---

## Sincronização de Prioridades (modloader.ini)

Antes de cada execução:
- MO2 prioridade `N` → `modloader.ini` Priority `= 50 + N`
- Mods de maior prioridade no MO2 recebem números maiores → carregam por último → sobrescrevem os anteriores
- Comportamento idêntico ao sistema de conflitos do MO2

---

## Estrutura dos Arquivos

```
gtasa_support/
  __init__.py       ← Entrypoint (createPlugins)
  plugin.py         ← IPluginGame + IPluginFileMapper
  installer.py      ← IPluginInstallerSimple
  modloader_ini.py  ← Sincronização de prioridades
  README.md         ← Este arquivo
```

---

## Requisitos

- Mod Organizer 2 ≥ 2.4 (com suporte a plugins Python e PyQt6)
- GTA San Andreas (Steam AppID 12120 ou instalação manual)
- Modloader (recomendado para mods de assets)
- CLEO (opcional, para scripts `.cs`)
