# miura

TUI de chat persistente sobre el proxy [Atomic AI](../../services/atomic-ai): sesiones en SQLite con índice FTS5, memoria entre sesiones y streaming — **sin dependencias nativas ni servicios de persistencia externos** (`node:sqlite` + Ink).

## Requisitos

- Node **>= 23.4.0** (por `node:sqlite` estable sin flag; verificado en 24.19.0)
- El proxy Atomic AI corriendo en `127.0.0.1:8120` (o la URL que pongas en `MIURA_PROXY_URL`)

## Uso

```bash
pnpm --filter @miuracode/cli dev        # directo con tsx
pnpm --filter @miuracode/cli build      # binario dist/index.js (bin: miura)
```

```bash
miura                        # nueva sesión (modelo por defecto: miura-fast)
miura -c                     # continúa la sesión más reciente
miura -r <uuid|prefijo>      # reanuda una sesión concreta
miura -m miura-reasoner      # arranca con otro carril/modelo
miura sessions               # lista sesiones (CLI, sin TUI)
miura search <texto>         # búsqueda FTS5 en todo el historial
miura models                 # carriles que expone el proxy
miura config                 # configuración efectiva
```

### Dentro del TUI (`/help`)

| Comando                 | Acción                                                      |
| ----------------------- | ----------------------------------------------------------- |
| `/new`                  | abandona la sesión actual y crea otra                       |
| `/model <nombre>`       | cambia el modelo/carril del turno                           |
| `/title <texto>`        | renombra la sesión                                          |
| `/search <texto>`       | busca en el historial de todas las sesiones (FTS5, snippet) |
| `/sessions`             | lista sesiones recientes                                    |
| `/remember clave=valor` | guarda un hecho en la **memoria persistente**               |
| `/forget clave`         | lo borra                                                    |
| `/exit`                 | sale (también Ctrl+C con el input vacío)                    |

Flechas ↑/↓ recorren el historial de input; Ctrl+C con texto pendiente solo limpia la línea.

## Persistencia propia (sin Chroma, sin Postgres)

- `~/.miuracode/miura.db` — SQLite (WAL) con tablas `sessions`, `messages` (+ `reasoning`), `memory` e índices **FTS5** external-content con triggers de sincronización.
- `~/.miuracode/settings.json` — `proxyUrl`, `model`, `systemPrompt`; overrides por entorno: `MIURA_PROXY_URL`, `MIURA_MODEL`, `MIURA_CONFIG_DIR`.
- La **memoria** (hechos `clave=valor`) viaja como bloque `system` en cada turno, encima de la historia (últimos 40 mensajes).

## Notas sobre modelos

El carril `miura-fast` del proxy mapea a NVIDIA NIM (free tier); `miura-reasoner` al razonador. Si un modelo "responde" con razonamiento pero sin contenido, el TUI lo avisa en pantalla — ver [docs/LOCAL_LLAMACPP_FINDINGS.md](../../services/atomic-ai/docs/LOCAL_LLAMACPP_FINDINGS.md) en el proxy para el detalle de por qué el lane local llama.cpp quedó descartado para generación.
