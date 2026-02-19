# Gemini Quota Roadmap

## 🚀 Upcoming Features

### 1. Shell Prompt Integration
- [x] Add `--query <model_name>` flag to output usage values.
- [x] Implement a `--raw` flag (Cancelled: Use `--json` instead for context).
- [x] Support filtering by provider/account in query mode.

### 2. Account Aliasing/Grouping
- [x] Update `AuthManager` to store an optional `alias` or `group` for each account.
- [x] Add CLI command/option to set or update aliases (e.g., `gemini-quota --account <email> --alias work`).
- [x] Add CLI command/option to set or update groups (e.g., `gemini-quota --account <email> --group home`).
- [x] Add CLI command/option to filter output based on alias or groups (e.g., `gemini-quota -g home`). will only show quotas in the home group.
- [x] Update `DisplayManager` to show aliases/groups in headers instead of emails when available.

### 3. Compact View
- [ ] Add `--compact` / `-c` flag for a dense, one-line-per-quota summary.
- [ ] Optimize layout for small terminal windows.
- [ ] Include minimal provider indicators (e.g., `[G]` for Google, `[C]` for Chutes).

### 4. Watch / Interval Mode
- [ ] Add `--watch` flag to auto-refresh the display.
- [ ] Add `--interval <seconds>` to control refresh rate (default 60s).
- [ ] Use `rich` console clearing for a flicker-free experience.

### 5. New Providers
- [ ] OpenAI (Usage and credits)
- [ ] Anthropic (Rate limits and usage)
- [ ] Mistral AI
- [ ] Z.AI
- [ ] Together AI / Fireworks
- [ ] Opencode Zen (black subscription or credits)

### 1. Unit Testing & Quality
- [x] Add more unit tests for provider-specific logic (Coverage increased to 85%).
- [ ] Improve error handling for network timeouts.
- [ ] Add documentation for manual project ID configuration.
