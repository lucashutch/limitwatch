# Legacy Python implementation

This directory preserves the former Python implementation of LimitWatch for
reference and compatibility. The supported implementation lives in
[`../../limitwatch-rs`](../../limitwatch-rs).

The Python CLI is no longer developed, released, or exercised by the primary
CI workflows. It supports providers that are not available in the Rust CLI,
including Google and Chutes.ai; use it only when that legacy support is
required.

## Running the legacy CLI

From this directory, use [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run limitwatch --help
uv run pytest
```

Its account data is shared with the Rust CLI at `~/.config/limitwatch/`.
Back up that data before using both implementations and never commit account
files or credentials.
