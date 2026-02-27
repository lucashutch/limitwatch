# LimitWatch Roadmap

### New Providers
- Anthropic (Rate limits and usage)
- Mistral AI
- Minimax Subscription
- Kimi (Moonshot.ai subscription)
- Z.AI
- Together AI / Fireworks
- Opencode Zen (credits billing + active Go/Black subscription, waiting for API access)
- Chutes: expand to support credits balance as well as subscription usage

### New Features
1. **Historical Quota Tracking** - Store quota usage over time in a local SQLite database with trend visualization and usage patterns
3. **Export Functionality** - Export historical quota data to CSV, Excel, or Markdown formats with customizable date ranges and filters
4. **Shell Autocompletions** - Generate shell completion scripts for bash/zsh/fish with account names, providers, and aliases

### Improvements
- Add configuration schema validation for accounts.json and config.json with migration support for breaking changes
- Add quota data caching layer to avoid redundant API calls and support offline viewing of stale data

### Unit Testing & Quality
- Improve error handling for network timeouts.
- Add documentation for manual project ID configuration.
