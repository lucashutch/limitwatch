# Repo Map

Purpose: Rust CLI for monitoring quota usage, reset times, and credits across
GitHub Copilot, OpenAI Codex, and OpenRouter.

## Layout

- `limitwatch-rs/` — primary Cargo crate.
- `limitwatch-rs/src/` — CLI, auth/config/storage, quota orchestration,
  rendering, history, exports, and completions.
- `limitwatch-rs/src/providers/` — provider contract and GitHub Copilot,
  OpenAI, and OpenRouter integrations.
- `limitwatch-rs/tests/` — integration and contract tests plus sanitized
  fixtures.
- `.github/workflows/` — Rust CI and release automation.
- `legacy/python/` — archived Python CLI, packaging metadata, and tests.

## Entry points

- `limitwatch-rs/src/main.rs` / `cli.rs` — binary entry point and command
  surface.
- `limitwatch-rs/src/quota_client.rs` / `providers/` — provider registry and
  quota-fetch orchestration.
- `limitwatch-rs/src/{auth,config,storage,history,export}.rs` — shared
  JSON/SQLite data, history, and export behavior.

## Commands

```sh
cd limitwatch-rs
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo run -- --help
```

## Conventions and gotchas

- Provider-specific behavior stays in provider modules.
- Account/config data is persisted at `~/.config/limitwatch/`; never expose
  credentials.
- Google and Chutes records are retained in shared storage when possible but
  are unsupported by the Rust CLI.
- The archived Python implementation has separate instructions in
  `legacy/python/README.md` and is not part of primary CI or releases.
