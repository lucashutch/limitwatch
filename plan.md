# Task Implementation Plan
Objective: Audit the Python CLI as the behavioral reference and bring the Rust CLI’s supported-provider behavior, JSON contracts, cache/deadline handling, terminal rendering, history/export commands, and completions as close to Python as practical, while removing Chutes from the Rust rewrite only.

Planning Notes: Five phases separate the high-risk CLI/fetch/render/provider work while keeping shared `cli.rs` changes sequential. Chutes is intentionally removed and de-registered from Rust; Python source, tests, and documentation remain untouched. The Rust README explicitly declares Google intentionally omitted; retain that as a documented, tested divergence rather than attempting the Python OAuth/project-discovery stack in this parity pass. Rich styling cannot be reproduced exactly, so use equivalent plain/ANSI output and golden contracts. Baseline audit gates currently pass: `uv run pytest` (361 tests) and Rust `cargo test --all-targets --all-features`.

## Audit Findings
- **CLI surface/help:** Rust has sparse help text, uses Clap’s `-V` rather than Python’s `-v`, and exposes Rust-only `--list-accounts`, `--select-account`, `--max-age-ms`, and `--cache-ttl`. History lacks Python’s individual `--heatmap/--chart/--calendar/--bars/--stats` flags, and history/export lack Python’s `--verbose`.
- **Auth actions/JSON:** Login defaults, provider selection, interactive logout, logout-all confirmation, metadata success/failure messages, and JSON shapes differ. Rust’s logout-all is unconditional; Python confirms interactively. Rust also needs explicit behavior when the requested/default provider is the intentionally unsupported Google provider.
- **Metadata/storage:** Rust metadata updates do not use the typed project fields, and its strict account-load validation can discard records that Python preserves. Alias ambiguity, clearing values, active-account persistence, and unknown-field round trips need contract tests.
- **Fetch/cache/deadline:** Rust timeout fallback currently retains an error even when cached quotas are available, suppresses cache use when `--refresh` is set, does not match Python’s error fallback rules, and caches all nonempty quota lists including error quotas. Timestamp parsing and timing contents also differ.
- **Filtering/JSON/rendering:** Account/provider/group/query behavior is close but error rendering, empty-query handling, quota filtering, JSON `quotas` values, timing fields, account headers, separators, compact width, usage labels/credits, reset strings, and ANSI/plain output diverge materially.
- **History/export:** Rust history views currently emit abbreviated row dumps instead of Python’s table, sparklines, heatmap, chart, calendar, bars, and stats output. Export formatting, filter metadata, timestamp/numeric formatting, and Google-record exclusion do not consistently match the documented Rust compatibility policy.
- **Completion:** Generated Clap scripts do not expose the Python-style dynamic account/group/quota candidates through the shell flow, and Rust completion lookup ignores Python’s `LIMITWATCH_CONFIG_DIR`/`XDG_CONFIG_HOME` handling. Google omission must remain explicit in provider candidates.
- **Providers:** GitHub internal snapshot parsing and billing paths/field coverage differ; OpenAI omits additional windows/credits and Python token/identity discovery details; OpenRouter’s no-limit key display differs. Provider timing/error normalization also needs parity coverage after Chutes is removed from Rust.
- **Rust Chutes removal:** The Rust provider module, registry, supported-provider checks, interactive provider choices, completion candidates, documentation, and Chutes-specific tests/fixtures still need explicit removal; Python Chutes remains unchanged.

## Affected Files
- `limitwatch-rs/src/cli.rs`
- `limitwatch-rs/src/auth.rs`
- `limitwatch-rs/src/model.rs`
- `limitwatch-rs/src/quota_client.rs`
- `limitwatch-rs/src/config.rs`
- `limitwatch-rs/src/providers/base.rs`
- `limitwatch-rs/src/providers/mod.rs`
- `limitwatch-rs/src/providers/chutes.rs`
- `limitwatch-rs/src/providers/github_copilot.rs`
- `limitwatch-rs/src/providers/openai.rs`
- `limitwatch-rs/src/providers/openrouter.rs`
- `limitwatch-rs/src/display.rs`
- `limitwatch-rs/src/history.rs`
- `limitwatch-rs/src/storage.rs`
- `limitwatch-rs/src/export.rs`
- `limitwatch-rs/src/completions.rs`
- `limitwatch-rs/README.md`
- `limitwatch-rs/tests/cli_integration.rs`
- `limitwatch-rs/tests/config_auth_compat.rs`
- `limitwatch-rs/tests/history_export.rs`
- `limitwatch-rs/tests/provider_contracts.rs`
- `limitwatch-rs/tests/github_verbose.rs`
- `limitwatch-rs/tests/fixtures/parity/reference.json`
- `limitwatch-rs/tests/fixtures/golden/normal_quota_plain.txt`
- `limitwatch-rs/tests/fixtures/golden/normal_quota_ansi.txt`

## Phases
### Phase 1: CLI contract and account actions (standalone)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/auth.rs`, `limitwatch-rs/src/model.rs`, `limitwatch-rs/src/providers/mod.rs`, `limitwatch-rs/src/providers/chutes.rs`, `limitwatch-rs/src/completions.rs`, `limitwatch-rs/README.md`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/config_auth_compat.rs`, `limitwatch-rs/tests/provider_contracts.rs`, `limitwatch-rs/tests/fixtures/parity/reference.json`
- [ ] Remove `src/providers/chutes.rs` and de-register Chutes from the Rust provider module list, factory, supported-account checks, interactive login/logout choices, and completion candidates; do not modify Python.
- [ ] Update the Rust README and parity fixture to remove Chutes authentication, supported-provider, and completion claims while documenting the remaining Rust provider set and the intentional Google divergence.
- [ ] Reconcile root/default-show and explicit-show options, short aliases, version/help text, action precedence, login/logout behavior, remaining-provider selection, confirmations, unsupported-provider errors, exit codes, and JSON status fields with Python; retain Rust-only selection/deadline flags only as explicitly documented extensions.
- [ ] Make metadata updates resolve email/alias consistently, update/clear typed project, alias, and group fields, reject ambiguous targets like Python’s supported behavior, and preserve unknown account fields.
- [ ] Add/update tests for Chutes absence and unsupported-provider rejection, provider/completion lists, help/options, JSON action output, confirmations/cancellation, aliases, project metadata, malformed-but-preservable records, and active-index/account persistence.
- Testing: `cd limitwatch-rs && cargo test --test cli_integration --test config_auth_compat --test provider_contracts && cargo run -- --help >/dev/null && cargo run -- show --help >/dev/null`

### Phase 2: Fetch, cache, deadline, and JSON semantics (depends: Phase 1)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/quota_client.rs`, `limitwatch-rs/src/providers/base.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/provider_contracts.rs`
- [ ] Match Python’s bounded concurrent fetches, shared absolute deadline, per-request remaining timeout, and deterministic timeout/error behavior without leaking worker failures or changing normal output.
- [ ] Implement fresh-cache fallback for timeout and eligible fetch errors, clear the timeout error when cache is used, parse numeric/string cache timestamps, honor configured/CLI TTLs, and cache only quota sets containing a non-error item.
- [ ] Ensure `--refresh` affects token refresh/provider work rather than incorrectly disabling valid quota-cache fallback, and persist provider-mutated credentials/cache fields with Python-compatible timing scope.
- [ ] Normalize account/provider/group/query filtering and JSON results so empty/error quotas, query exit status, `--timings`, and `None`/empty quota collections match the Python shape.
- Testing: `cd limitwatch-rs && cargo test --test cli_integration --test provider_contracts --test github_verbose`

### Phase 3: Terminal and ANSI output parity (depends: Phase 2)
- Files: `limitwatch-rs/src/display.rs`, `limitwatch-rs/src/cli.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/fixtures/golden/normal_quota_plain.txt`, `limitwatch-rs/tests/fixtures/golden/normal_quota_ansi.txt`
- [ ] Match Python account headers, provider labels, separators, empty/error messages, sorting, normal bar widths/fractional blocks, compact account fields, and reset countdown formatting.
- [ ] Render provider metadata such as `usage_label`, used-vs-remaining percentages, AI credits, text-only quotas, validation URLs/messages, and `show_progress` consistently across normal and compact modes.
- [ ] Make filtering happen once before rendering, suppress query-excluded errors as Python does, and keep JSON/redirected output ANSI-free while honoring terminal detection and `NO_COLOR`.
- [ ] Extend fixed-clock and golden tests for normal, compact, error, alias/group, credits, reset, plain, ANSI, and no-color output; document the deliberate Rich-to-plain rendering limitation.
- Testing: `cd limitwatch-rs && cargo test --lib display --test cli_integration`

### Phase 4: History, export, and completion parity (depends: Phase 3)
- Files: `limitwatch-rs/src/history.rs`, `limitwatch-rs/src/storage.rs`, `limitwatch-rs/src/export.rs`, `limitwatch-rs/src/completions.rs`, `limitwatch-rs/src/config.rs`, `limitwatch-rs/src/cli.rs`, `limitwatch-rs/tests/history_export.rs`, `limitwatch-rs/tests/config_auth_compat.rs`, `limitwatch-rs/tests/cli_integration.rs`
- [ ] Add Python-compatible history flags/defaults/verbose handling and implement close plain-text equivalents for sparklines, table, summary, heatmap, chart, calendar, daily bars, and stats using the existing storage metrics.
- [ ] Match Python date parsing, inclusive filters, aggregation/activity ordering, and the explicit Rust policy of preserving but ignoring Google records in Rust history views and filters.
- [ ] Align CSV/Markdown headers, escaping, number/timestamp formatting, filter sections, empty exports, output-file creation, and stdout confirmation behavior.
- [ ] Wire dynamic completion candidates for accounts, aliases, groups, providers, quotas, presets, formats, and views into generated bash/zsh/fish scripts, with the same config-directory lookup and explicit Google omission.
- [ ] Add integration tests for every history view, export filter/output mode, completion candidate class, config path environment, and generated completion script.
- Testing: `cd limitwatch-rs && cargo test --test history_export --test config_auth_compat --test cli_integration && cargo run -- completion bash >/dev/null && cargo run -- completion zsh >/dev/null && cargo run -- completion fish >/dev/null`

### Phase 5: Provider behavior and release parity gates (depends: Phase 4)
- Files: `limitwatch-rs/src/providers/base.rs`, `limitwatch-rs/src/providers/github_copilot.rs`, `limitwatch-rs/src/providers/openai.rs`, `limitwatch-rs/src/providers/openrouter.rs`, `limitwatch-rs/tests/provider_contracts.rs`, `limitwatch-rs/tests/github_verbose.rs`
- [ ] Align GitHub internal snapshot fields, organization matching, billing URL/query fallback order, allowance/percentage mapping, and sanitized verbose diagnostics while retaining the successful internal fast path.
- [ ] Add OpenAI local-token discovery/identity fallback coverage plus additional windows, credits, refresh, device-auth, and reset parsing; align OpenRouter credits/key fallback and no-limit displays.
- [ ] Expand remaining-provider fixtures/contracts for request order, failure messages, cache-safe fields, reset normalization, and credential redaction; keep Chutes absent from all Rust provider registries, docs, and tests.
- [ ] Run both implementations’ quality gates and compare sanitized CLI fixtures for equivalent inputs before marking the pass complete.
- Testing: `uv run ruff check . && uv run ruff format --check . && uv run pytest && cd limitwatch-rs && cargo fmt --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-targets --all-features`

## Status
- Phase 1: complete — Rust Chutes removed/de-registered; account actions, metadata persistence, provider validation, and focused contracts updated.
- Phase 2: complete — bounded fetches, absolute deadlines, cache/error fallback, account persistence, filtering, JSON, and timing semantics updated; full Rust tests pass.
- Phase 3: complete — terminal headers, bars, labels, errors, resets, compact mode, filtering, ANSI behavior, and golden tests updated; Rich layout remains a documented plain-text equivalent.
- Phase 4: complete — history views/flags, Google history exclusion policy, exports, and dynamic completions implemented; focused and full Rust tests pass.
- Phase 5: complete — GitHub/OpenAI/OpenRouter provider parity, reset/auth fallbacks, diagnostics redaction, provider contracts, reviewer blockers, and full quality gates pass.
