# Repo Map

Purpose: Rust CLI for monitoring quota usage, reset times, and credits across
GitHub Copilot, OpenAI Codex, and OpenRouter.

## Layout

- `Cargo.toml` / `Cargo.lock` — crate manifest and locked dependencies.
- `src/` — CLI, auth/config/storage, quota orchestration,
  rendering, history, exports, and completions.
- `src/providers/` — provider contract and GitHub Copilot,
  OpenAI, and OpenRouter integrations.
- `tests/` — integration and contract tests plus sanitized
  fixtures.
- `.github/workflows/` — Rust CI and release automation.

## Entry points

- `src/main.rs` / `src/cli.rs` — binary entry point and command
  surface.
- `src/quota_client.rs` / `src/providers/` — provider registry and
  quota-fetch orchestration.
- `src/{auth,config,storage,history,export}.rs` — account/config JSON, SQLite
  history, and export behavior.

## Commands

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo run -- --help
```

## Conventions and gotchas

- Provider-specific behavior stays in provider modules.
- Account/config data is persisted at `~/.config/limitwatch/`; never expose
  credentials.
- Google and Chutes records are retained in storage when possible but
  are unsupported by the Rust CLI.
