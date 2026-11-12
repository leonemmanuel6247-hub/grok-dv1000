# Adaptation HP Pavilion dv1000

Cible: Debian 12 (bookworm) 32-bit, Pentium M / i686, 2 GiB RAM, ~149 GiB disque.

Le depot upstream (https://github.com/xai-org/grok-build) suppose un hote 64-bit
(x86_64 ou aarch64) avec assez de RAM pour un workspace Rust large. Ce tree est
adapte pour compiler et lier `xai-grok-pager` sur cette machine.

## Contraintes

| Ressource | Machine | Impact |
|-----------|---------|--------|
| Arch | i686 (Pentium M) | triple `i686-unknown-linux-gnu` |
| RAM | 2 GiB, pas de swap d'origine | 1 job cargo, codegen-units=1, pas de jemalloc |
| Disque | ~149 GiB | suffisant pour `target/` |
| OS | Debian 12 32-bit | gcc i386 natif, protoc linux-x86_32 |

## Changements

- `rust-toolchain.toml`: host/target `i686-unknown-linux-gnu` uniquement
- `.cargo/config.toml`: `jobs = 1`, target i686, rustflags codegen-units=1
- `Cargo.toml`: profiles `dev`/`release` a 1 CGU, debug off, LTO off
- `xai-grok-pager-bin`: jemalloc retire des features par defaut
- `bin/protoc`: asset DotSlash `linux-x86_32` (protobuf 29.3)
- bundling rg/fd: triple i686 reconnu (assets musl absents: fournir un binaire local ou installer `ripgrep`/`fd-find` via apt)
- `detect_platform()`: reconnait `i686`

## Bootstrap

```bash
./scripts/bootstrap-dv1000.sh
```

Installe gcc, libssl-dev, cmake, protoc 29.3 i386, rustup 1.94 i686,
et un swapfile de 3 GiB si la RAM est sous 3 GiB.

## Build

```bash
. "$HOME/.cargo/env"
./scripts/build-dv1000.sh check
./scripts/build-dv1000.sh release
```

Binaire: `target/i686-unknown-linux-gnu/release/xai-grok-pager`

Lier en `grok`:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$(pwd)/target/i686-unknown-linux-gnu/release/xai-grok-pager" "$HOME/.local/bin/grok"
```

Paquets runtime utiles (non bundles en 32-bit):

```bash
sudo apt-get install -y ripgrep fd-find
```

## Limites

- Compilation complete: plusieurs heures, swap utilise.
- jemalloc n'est pas le global allocator (systeme malloc).
- Auto-update official ne publie pas de binaire i686.
- Pentium M n'a pas AVX; le codegen i686 reste sur le baseline 32-bit.

## Source d'API: NemApi (local)

Ce fork ne parle plus a xAI/Grok cloud. L'inference est routee vers **NemApi**,
un proxy OpenAI-compatible local (https://github.com/teteekoue/NemApi), ecoute
par defaut sur `http://127.0.0.1:8090/v1`.

NemApi est un projet **proprietaire** (LICENSE all rights reserved): son code
n'est **pas** vendu/copie dans ce tree. Il reste un service externe que ce CLI
interroge via son endpoint OpenAI. Ce CLI est un client, pas un miroir de NemApi.

### Changements chirurgicaux

- `xai-grok-env`: endpoints compiles -> `127.0.0.1:8090` (plus de grok.com/x.ai)
- `xai-grok-config`: `xai_api_base_url` par defaut -> `http://127.0.0.1:8090/v1`
- `xai-grok-config/distribution`: capacites cloud retirees (Telemetry,
  ErrorReporting, RemoteFetch, AccountLogin, RemoteControl, Voice)
- `xai-grok-login`: `preferred_method = api_key` force; cle par defaut `nemapi`
  quand aucune `NEMAPI_API_KEY`/`XAI_API_KEY` n'est definie
- `default_models.json`: modeles NemApi (deepseek-chat, qwen-chat, claude-chat,
  gemini-chat, gpt-chat, kimi-chat, glm-chat) + aliases grok-4.x -> deepseek-chat,
  backend `chat_completions` (pas `/responses`)
- en-tete `X-NemApi-Agent: grok-build` injecte; en-tetes xAI retires
- timeouts: idle par defaut 900s (latence navigateur); retries 15 -> 3
- autoupdater: off par defaut (`GROK_ENABLE_AUTOUPDATER=1` pour l'activer)

### Config sur l'hote (jamais dans un conteneur)

```bash
./scripts/apply-nemapi-config.sh   # ecrit ~/.grok/config.toml sur la machine
```

Lance NemApi sur la machine (`python run.py` dans son repo, extension Chromium
chargee, un onglet par fournisseur connecte). Le workspace CLI reste sur l'hote
(`~/.grok`); il n'est pas monte dans un conteneur.

### Test rapide sans NemApi (mock OpenAI local)

```bash
python3 scripts/nemapi-mock.py 8090 &
curl -s http://127.0.0.1:8090/v1/models
curl -s http://127.0.0.1:8090/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"salut"}]}'
```

Le mock (`scripts/nemapi-mock.py`) est independant et sans licence: il n'est pas
derive de NemApi.
