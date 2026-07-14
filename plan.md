# Task Implementation Plan
Objective: Polish the Rust CLI’s remaining login feedback, plain-text history/quota presentation, diagnostics, documentation, and CI without reopening completed provider-parity work.

Planning Notes: Python remains the UX reference for GitHub Copilot, OpenAI, and OpenRouter only. Google and Chutes remain rejected by Rust; Google records continue to be preserved but ignored. `repo-map.md` accurately describes this arrangement and requires no change. The root README continues to describe the Python CLI; add a scoped Rust-reference link rather than incorrectly removing Python-supported providers.

## Affected Files
- `limitwatch-rs/src/cli.rs`
- `limitwatch-rs/src/providers/openai.rs`
- `limitwatch-rs/src/providers/openrouter.rs`
- `limitwatch-rs/src/display.rs`
- `limitwatch-rs/src/history.rs`
- `limitwatch-rs/src/export.rs`
- `limitwatch-rs/README.md`
- `limitwatch-rs/tests/cli_integration.rs`
- `limitwatch-rs/tests/provider_contracts.rs`
- `limitwatch-rs/tests/history_export.rs`
- `limitwatch-rs/tests/fixtures/golden/normal_quota_plain.txt`
- `limitwatch-rs/tests/fixtures/golden/normal_quota_ansi.txt`
- `README.md`
- `.github/workflows/test-and-lint.yml`

## Phases
### Phase 1: Interactive provider login polish (standalone)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/providers/openai.rs`, `limitwatch-rs/src/providers/openrouter.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/provider_contracts.rs`
- [ ] Add the TTY-only OpenRouter API-key prompt when neither `--json` nor `LIMITWATCH_LOGIN_JSON` supplies input; validate through the existing provider login, then offer a friendly account name when the returned label is redacted/key-like before persisting it.
- [ ] Preserve explicit JSON/environment and non-interactive login behavior, and keep credential values out of prompts, status output, and failures.
- [ ] Make OpenAI login emit Python-equivalent stderr progress for discovery, valid/invalid OpenCode and Codex CLI credentials, and the transition into device authorization, without changing its refresh, polling, or token persistence contracts.
- [ ] Add focused mocked-provider and scripted-input coverage for OpenRouter input/redacted-label handling and OpenAI discovery/device status selection; use extracted input/status helpers if a full TTY HTTP integration harness is impractical.
- Testing: `cd limitwatch-rs && cargo test --lib cli:: && cargo test --test cli_integration --test provider_contracts`

### Phase 2: Plain-text history and quota-view density (depends: Phase 1)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/display.rs`, `limitwatch-rs/src/history.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/history_export.rs`, `limitwatch-rs/tests/fixtures/golden/normal_quota_plain.txt`, `limitwatch-rs/tests/fixtures/golden/normal_quota_ansi.txt`
- [ ] Route history commands through the maintained plain-text renderers and consolidate duplicate/abbreviated history rendering paths so sparklines, tables, heatmaps, charts, calendars, bars, and stats consistently use the existing aggregate data.
- [ ] Replace raw heatmap count cells with relative intensity glyphs plus a concise legend (retaining totals), and tighten fixed-width sparkline/table, bar/chart, and stats layouts while retaining trend, health, and per-quota information.
- [ ] Correct only confirmed kept-provider main-view regressions: account separators/spacing, text-only `show_progress: false` credit rows, and AI-credit labels in normal and compact output; retain ANSI/`NO_COLOR` behavior and the intentional non-Rich limitation.
- [ ] Add deterministic small rendering snapshots/assertions for intensity scaling, alignment, and main quota text/ANSI output rather than broadening provider behavior tests.
- Testing: `cd limitwatch-rs && cargo test --lib display:: && cargo test --lib history:: && cargo test --test cli_integration --test history_export`

### Phase 3: Diagnostics, docs, and Rust CI gate (depends: Phase 2)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/export.rs`, `limitwatch-rs/README.md`, `limitwatch-rs/tests/cli_integration.rs`, `README.md`, `.github/workflows/test-and-lint.yml`
- [ ] Make `history --verbose` and `export --verbose` print credential-redacted stderr diagnostics for the resolved database path, effective filters, and record/result counts while keeping normal stdout/export content unchanged.
- [ ] Document OpenRouter’s TTY login flow, OpenAI discovery/device feedback, `--refresh` semantics (network fetch for GitHub/OpenRouter and OpenAI token refresh where available, with deadline cache fallback retained), verbose diagnostics, and the supported-provider/Google-record policy in the Rust README.
- [ ] Add a concise root-README pointer to the Rust implementation and its narrower supported-provider set without changing the Python CLI’s provider claims; leave the accurate `repo-map.md` untouched.
- [ ] Add an independent Rust CI job that runs format, Clippy with warnings denied, and all-target/full-feature tests alongside the existing Python jobs; test verbose output and generated docs commands locally.
- Testing: `cd limitwatch-rs && cargo fmt --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-targets --all-features && cargo run -- --help >/dev/null && cargo run -- completion bash >/dev/null && cargo run -- completion zsh >/dev/null && cargo run -- completion fish >/dev/null`

## Status
- Phase 1: complete — TTY-only OpenRouter API-key/name prompts, redacted-label handling, and credential-safe OpenAI discovery/device progress were added with focused coverage.
- Phase 2: complete — history now uses maintained aligned renderers with intensity heatmaps/legend and focused renderer assertions; kept-provider main-view behavior remains compatible.
- Phase 3: complete — verbose history/export diagnostics, Rust-focused documentation, and an independent Rust CI job were added; a follow-up Clippy-only correction in history rendering also passes.
