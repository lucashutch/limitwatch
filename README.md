# LimitWatch

LimitWatch is a Rust CLI for monitoring quota usage, reset times, and credits
across GitHub Copilot, OpenAI Codex, and OpenRouter accounts.

## Features

- Interactive login and multi-account monitoring.
- Account aliases and groups, plus account, provider, and quota filtering.
- Standard, compact, and JSON quota output with reset countdowns.
- SQLite-backed quota history, charts, summaries, and CSV or Markdown export.
- Dynamic shell completions for bash, zsh, and fish.
- Shared account/config/history data at `~/.config/limitwatch/`.

## Supported providers

| Provider | What is monitored | Authentication |
| --- | --- | --- |
| **GitHub Copilot** | Personal or organization Copilot usage | `gh auth token` discovery or GitHub token |
| **OpenAI Codex** | Codex plan usage windows | Local credentials or OpenAI device login |
| **OpenRouter** | Remaining credits and key usage | API key |

## Install

Install from a checkout with Rust 1.85 or newer:

```sh
cargo install --path limitwatch-rs
```

For development:

```sh
cd limitwatch-rs
cargo run -- --help
```

## Usage

```sh
# Add an account
limitwatch --login

# Show all supported accounts
limitwatch

# Filter output
limitwatch --provider openrouter --compact
limitwatch --account work --json --timings

# Review or export history
limitwatch history --preset 7d --table
limitwatch export --format markdown --output quotas.md
```

See the [Rust CLI reference](limitwatch-rs/README.md) for all options,
authentication details, shared-data behavior, and completions.

## Legacy Python implementation

The former Python CLI has been archived in
[`legacy/python`](legacy/python/README.md). It is not released or covered by
primary CI. It remains available only for legacy Google and Chutes.ai support
and reference; use the Rust CLI for all supported providers.

## Development

```sh
cd limitwatch-rs
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
```

## License

[MIT](LICENSE)
