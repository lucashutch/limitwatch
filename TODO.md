# LimitWatch Roadmap

### New Providers
- Anthropic (Rate limits and usage)
- Mistral AI
- Minimax Subscription
- Kimi (Moonshot.ai subscription)
- Z.AI
- Together AI / Fireworks
- Opencode Zen (credits billing + active Go/Black subscription, waiting for API access)

### New Features
1. **Historical Quota Tracking** - Improve formatting data visualization and analysis for historical quota usage trends.

### Improvements
- Add configuration schema validation for accounts.json and config.json with migration support for breaking changes
- Add quota data caching layer to avoid redundant API calls and support offline viewing of stale data

### Unit Testing & Quality
- Improve error handling for network timeouts.
- Add documentation for manual project ID configuration.
