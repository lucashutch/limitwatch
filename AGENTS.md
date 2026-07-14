# Agent Instructions for LimitWatch

This repository's primary implementation is a Rust CLI for monitoring GitHub
Copilot, OpenAI Codex, and OpenRouter quota usage.

## Build, lint, and test

Run Rust commands from the repository root:

- Format: `cargo fmt`
- Format check: `cargo fmt --check`
- Lint: `cargo clippy --all-targets --all-features -- -D warnings`
- Test: `cargo test --all-targets --all-features`
- Run: `cargo run -- --help`

Format, lint, and test relevant changes before committing. Use Cargo for Rust
dependency management; do not manually edit `Cargo.lock`.

## Project structure

- `src/` — CLI, configuration, storage, history, export,
  display, auth, and quota orchestration.
- `src/providers/` — provider interface and GitHub Copilot,
  OpenAI, and OpenRouter integrations.
- `tests/` — integration, contract, compatibility, and rendering
  tests with sanitized fixtures.

## Conventions

- Keep provider-specific auth, API, filtering, sorting, and display metadata in
  provider modules, not generic CLI or display code.
- Preserve unknown fields when reading and writing shared account/config JSON.
- LimitWatch stores data in `~/.config/limitwatch/`. Never log or commit OAuth
  secrets, API keys, or account files.
- Google and Chutes records may be preserved in shared storage but are not
  supported by the Rust CLI.
