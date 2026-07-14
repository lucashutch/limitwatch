# Task Implementation Plan
Objective: Bring Rust warm-run performance below the observed 2.03s toward/parity with installed Python’s 1.43s, while making Myriota render Python-equivalent credits, percentage, and reset countdown from the internal Copilot snapshot.

Planning Notes: Scope is strictly `limitwatch-rs/**`. Preserve account/provider concurrency. Use the supplied live measurements as the baseline, then compare repeated warm runs rather than one-off startup/network noise; instrumentation must never emit credentials, headers, query values, bodies, or identifying URL segments.

## Affected Files
- `limitwatch-rs/src/cli.rs`
- `limitwatch-rs/src/quota_client.rs`
- `limitwatch-rs/src/providers/github_copilot.rs`
- `limitwatch-rs/src/display.rs`
- `limitwatch-rs/tests/provider_contracts.rs`
- `limitwatch-rs/tests/cli_integration.rs`
- `limitwatch-rs/tests/github_verbose.rs`
- `limitwatch-rs/tests/fixtures/github_copilot/myriota_internal_user.json`
- `limitwatch-rs/scripts/benchmark-warm.sh`

## Phases
### Phase 1: Shared transport and safe timing evidence (standalone)
- Files: `limitwatch-rs/src/cli.rs`, `limitwatch-rs/src/quota_client.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/github_verbose.rs`
- [ ] Replace per-request `reqwest::blocking::Client::new()` in `Http::execute` with one reusable, thread-safe client configured to retain connection pooling across concurrent account/provider work.
- [ ] Keep existing concurrent fetch topology intact and add opt-in elapsed timings around provider fetches and sanitized requests so pooling, endpoint count, and critical-path changes can be measured without exposing secrets or changing normal output.
- [ ] Add deterministic tests using local/fake transport evidence for client reuse/concurrent behavior and timing redaction, including disabled-by-default output.
- Testing: `cd limitwatch-rs && cargo test --test cli_integration && cargo test --test github_verbose`

### Phase 2: Internal-first Myriota correctness and request elimination (depends: Phase 1)
- Files: `limitwatch-rs/src/providers/github_copilot.rs`, `limitwatch-rs/src/display.rs`, `limitwatch-rs/tests/provider_contracts.rs`, `limitwatch-rs/tests/cli_integration.rs`, `limitwatch-rs/tests/fixtures/github_copilot/myriota_internal_user.json`
- [ ] Align internal snapshot selection and quota mapping with Python’s live contract: represent 231.3 used credits, derive the 0.9% used value from the matching entitlement, and carry the exact reset timestamp needed for countdown rendering rather than the current 1.0%-only result.
- [ ] Render credit-bearing internal quotas as Python-equivalent `231.3 cr (0.9%) (19d...)`, while retaining generic rendering for other providers and making countdown tests deterministic around a fixed clock/reset fixture.
- [ ] Short-circuit organization billing/seat calls after a valid matching internal snapshot succeeds; retain billing fallback for absent, malformed, or unmatched snapshots and retain concurrent account/provider fetching.
- [ ] Extend fixture-driven contracts to assert exact model fields, request counts/order, no billing calls on internal success, fallback calls on failure, and exact Myriota text output.
- Testing: `cd limitwatch-rs && cargo test --test provider_contracts github_internal_user && cargo test --test cli_integration myriota`

### Phase 3: Reproducible warm benchmark and release gates (depends: Phase 2)
- Files: `limitwatch-rs/scripts/benchmark-warm.sh`
- [ ] Add a credential-free deterministic benchmark mode (local fixture/mock endpoint or ignored harness) for transport/request-path regressions plus a clearly opt-in live script that builds release Rust, warms both binaries, runs repeated samples against installed Python, and reports median/spread and command metadata without credentials or quota payloads.
- [ ] Document/enforce the measured comparison procedure using 2.03s Rust and 1.43s Python as pre-change evidence, and record post-change warm results before accepting the optimization rather than claiming improvement from architecture alone.
- [ ] Run formatting, lint, full tests, the offline benchmark, and—only in an authorized local environment—the repeated live Rust-versus-installed-Python benchmark.
- Testing: `cd limitwatch-rs && cargo fmt --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-targets --all-features && ./scripts/benchmark-warm.sh --offline`

## Status
- Phase 1: complete; pooled transport tests and quality gates pass
- Phase 2: complete; exact Myriota output and request short-circuit tests pass
- Phase 3: complete; full gates pass, live median Rust 506ms vs Python 1379ms (5 samples)
- Prior Phase 1: done — Python-exact billing request sequence and focused quality gates passed.
- Prior Phase 2: done — Billing 404 fallback regressions and full gates passed.
- Prior internal-path phase: done — Internal Myriota fixture and focused tests passed.
- Prior tracing phase: done — Safe tracing and all 40 tests passed.
