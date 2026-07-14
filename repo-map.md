# Repo Map
Purpose: CLI for monitoring quota usage, reset times, and credits across multiple API providers.
Stack: Python 3.11+ (Click/Rich/requests) and a self-contained Rust rewrite (Clap/Reqwest/Rusqlite).

## Layout
- `src/limitwatch/` — CLI, auth/config/storage, quota orchestration, rendering, exports, history, and completions.
- `src/limitwatch/providers/` — shared provider interface and isolated Google, GitHub Copilot, Chutes, OpenAI, and OpenRouter integrations.
- `tests/` — pytest unit tests mirroring application modules/providers.
- `.github/workflows/` — Python CI and release automation.
- `limitwatch-rs/` — Rust crate; implementation in `src/`, compatibility/integration tests in `tests/`, and Rust-specific usage/limits in `README.md`.

## Entry points
- `src/limitwatch/cli.py` — `limitwatch` console command (`cli_entry_point`).
- `src/limitwatch/quota_client.py` — provider registry and quota-fetch orchestration.
- `src/limitwatch/providers/base.py` — provider contract and shared quota model.
- `limitwatch-rs/src/main.rs` / `cli.rs` — Rust binary entry point and command surface.
- `limitwatch-rs/src/quota_client.rs` / `providers/` — Rust registry for GitHub Copilot, OpenAI, and OpenRouter; Chutes is removed and Google records are preserved but ignored.
- `limitwatch-rs/src/{auth,config,storage,history,export}.rs` — shared JSON/SQLite compatibility and exports.

## Commands
- Install: `uv sync`
- Run: `uv run limitwatch`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Rust checks: `cd limitwatch-rs && cargo fmt --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-targets --all-features`
- Rust run: `cd limitwatch-rs && cargo run -- --help`

## Conventions & gotchas
- Provider-specific auth, API, filtering, sorting, and display metadata stay in provider modules, not CLI/display.
- Accounts/config are persisted at `~/.config/limitwatch/accounts.json`; never expose stored credentials.
- Python packaging uses a `src/` layout and a VCS-derived version.
- Rust and Python default to `~/.config/limitwatch/{accounts.json,config.json,history.db}`; back up shared data and never expose credentials.
- Rust live-auth limitations, supported providers, and external `gh`/OAuth prerequisites are documented in `limitwatch-rs/README.md`.
- Sanitized offline parity expectations live in `limitwatch-rs/tests/fixtures/parity/`.
