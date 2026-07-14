# LimitWatch (Rust)

This directory is a self-contained Rust reimplementation of the Python
LimitWatch CLI. It monitors GitHub Copilot, OpenAI Codex, and OpenRouter.
Chutes is intentionally omitted from the Rust implementation. Google records
are preserved for compatibility but Google is intentionally unsupported here.

## Build and install

Rust 1.85 or newer is recommended (the code uses edition 2021). From this
directory:

```sh
cargo build --release
cargo run -- --help
cargo install --path .
```

The installed executable is `limitwatch`. Network access is required to fetch
provider data; SQLite is bundled, so no system SQLite installation is needed.

## Usage and options

`limitwatch` and `limitwatch show` display current quotas. The root command
accepts the same show options:

```text
-a, --account <ID>       Repeatable email or alias filter
    --alias <ALIAS>      Set/clear metadata for one selected account
-g, --group <GROUP>      Group filter, or metadata update with --account
-p, --provider <TYPE>    Repeatable provider filter
-q, --query <TEXT>       Repeatable quota text filter
-r, --refresh            Request refresh behavior
-s, --show-all           Include normally hidden quotas
-c, --compact            Compact output
-j, --json               Machine-readable output
-l, --login              Add/update an account
    --project-id <ID>    Set project metadata with --account
    --logout             Remove the selected account
    --logout-all         Remove all accounts
    --no-record          Do not write this fetch to history
    --verbose            Enable verbose mode
    --timings            Include timings in JSON
    --max-age-ms <MS>    Overall fetch deadline (Rust extension, default 4000)
    --cache-ttl <SEC>    Override cached-quota lifetime (Rust extension)
    --select-account <ID>  Make one supported account active (Rust extension)
    -v, --version          Report the Rust CLI version
```

Metadata values `none` or an empty value clear the field. Explicit account
selection takes precedence over group filtering.

Other commands:

* `history [--preset 24h|7d|30d|90d] [--since TIME] [--until TIME]
  [-a ACCOUNT] [-p PROVIDER] [-q QUOTA] [--table] [--summary]
  [--heatmap|--chart|--calendar|--bars|--stats]`
* `export [--format csv|markdown] [-o PATH]` with the same time/account/provider/
  quota filters. The default range is 7 days; output goes to stdout unless a
  path is supplied.
* `completion bash|zsh|fish` prints a completion script.
* `--version` and `--help` report build/version and command help.

Examples:

```sh
limitwatch --provider openrouter --compact
limitwatch --account work --json --timings
limitwatch history --preset 7d --table
limitwatch export --format markdown --output quotas.md
```

## Provider authentication

Bare `--login` prompts for a provider on a terminal and defaults to GitHub
Copilot when non-interactive. `--provider` selects explicitly. Discovery is
preferred; `LIMITWATCH_LOGIN_JSON` can supply explicit sanitized input.
`--logout` confirms the selected account interactively; JSON and piped use
returns an explicit error rather than reading confirmation input. `--logout-all` retains
its interactive confirmation unless JSON output is requested.

```sh
LIMITWATCH_LOGIN_JSON='{"apiKey":"..."}' limitwatch --login --provider openrouter
```

* **GitHub Copilot** (`github_copilot`): optional `githubToken`; if omitted,
  the authenticated `gh auth token` is used. The `gh` CLI must then be installed
  and logged in.
* **OpenAI Codex** (`openai`): `accessToken`, with optional `email`, validated
  against ChatGPT usage.
* **OpenRouter** (`openrouter`): `apiKey`, with optional account `name`.

The Rust CLI rejects `google` and `chutes` provider requests. Existing Google
records remain in `accounts.json` but are ignored by Rust selection, fetching,
history filters, and completions.

## Shared data and compatibility

Both implementations default to `~/.config/limitwatch/` and share:

* `accounts.json` (credentials, aliases, groups, projects, and cache),
* `config.json` (`cacheTtl`, `historyDbPath`, `enableHistory`, theme/threshold),
* `history.db` and its `quota_snapshots` rows.

Unknown JSON fields are retained on normal Rust round trips. Writes use a
temporary file and atomic replacement. A custom history path may begin with
`~/`. Back up shared files before switching versions during evaluation.

Existing Google records are preserved on normal saves but ignored by Rust
selection, fetching, history filters, and completions. `--refresh` requests
provider/token refresh work where supported, while a fresh quota cache remains
available as a timeout fallback; `--verbose` diagnostics are
credential-redacted. JSON/redirected output is ANSI-free and color honors
`NO_COLOR`.

## Security

Account storage contains bearer/refresh tokens and API keys in plaintext with
the permissions inherited from the local configuration directory. Do not
commit, print, or send these files. Prefer a private user configuration
directory, restrict its permissions, and redact diagnostics. JSON quota output
does not intentionally include credentials, but may contain provider messages.

## Completions

Generate and source/install a script using the conventions of your shell:

```sh
limitwatch completion bash > ~/.local/share/bash-completion/completions/limitwatch
limitwatch completion zsh > ~/.zfunc/_limitwatch
limitwatch completion fish > ~/.config/fish/completions/limitwatch.fish
```

Internal dynamic candidates cover accounts/aliases, groups, providers, cached
quota names, export formats, and history views.

## Development and testing

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo run -- --help >/dev/null
cargo run -- completion bash >/dev/null
cargo run -- completion zsh >/dev/null
cargo run -- completion fish >/dev/null
```

Integration tests cover config/account interchange, provider parsing and
contracts, history/export behavior, and CLI behavior.

Sanitized Python-reference expectations are checked into
`tests/fixtures/parity/`. They use mocked responses, no credentials or live
APIs. Update them only after comparing equivalent Python inputs and reviewing
the sanitized diff; preserve explicit divergences such as Google omission.

## Known compatibility limits

The Python implementation remains the behavioral reference. Google OAuth and
project discovery remain intentionally outside this Rust rewrite. OpenAI
supports local credential files, device authorization, bounded token polling,
and refresh-on-401; GitHub login depends on an available `gh` executable when
no token is supplied. Provider APIs, OAuth policies, network access, and
external CLI versions can therefore affect live parity. Rendering is plain text
rather than Rich terminal styling. Validate on representative copies of real
data before relying on cross-version write compatibility.
