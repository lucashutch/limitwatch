# LimitWatch

A Python CLI tool to monitor quota usage, reset times, and credits across **Google (Gemini CLI + Antigravity)**, **GitHub Copilot**, **Chutes.ai**, **OpenAI Codex**, and **OpenRouter** accounts.

## Features

- **🔌 Multi-provider support**: View quotas/credits from Google, GitHub Copilot, Chutes.ai, OpenAI Codex, and OpenRouter in one run.
- **🔐 Unified interactive login**: Use `limitwatch --login` to select a provider and authenticate with the provider-specific flow.
- **👥 Multi-account monitoring**: Track multiple accounts per provider and render them together.
- **🏷️ Account aliases**: Assign friendly names with `--alias` and target accounts by alias.
- **🗂️ Account groups**: Assign accounts to groups with `--group` and filter output by group.
- **🎯 Flexible filtering**: Filter by account, provider, group, and model text; optionally show all model variants.
- **📊 Rich quota display**: Progress bars, used/total context, remaining percentage, and reset countdowns.
- **🧠 Smart model selection**: Prioritizes primary premium models by default while preserving useful fallbacks.
- **🧾 Multiple output modes**: Standard view, compact view (`--compact`), and script-friendly JSON (`--json`).
- **🧱 Modular provider architecture**: Providers are isolated and extensible through the shared base interface.

## Supported Providers & Authentication

| Provider | What is monitored | Authentication method |
| --- | --- | --- |
| **Google** | Gemini CLI + Antigravity quotas | OAuth device/browser flow via Google account login |
| **GitHub Copilot** | Personal and optional org Copilot usage | GitHub token (auto-discovered from `gh auth token` when available, or entered manually) |
| **Chutes.ai** | Balance and quota usage | API key |
| **OpenAI Codex** | Codex plan usage windows (e.g., primary/secondary periods) | Existing local OpenAI/Codex tokens if found, otherwise OpenAI device-code login |
| **OpenRouter** | Remaining credits / key usage | API key (management or regular key) |

## Installation

This project is managed with [uv](https://github.com/astral-sh/uv).

### Global Installation (Recommended)
Install the tool globally to run it from anywhere:
```bash
uv tool install .
```

### Local Development
1. Clone the repository.
2. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

```bash
# Initial setup: login to your account(s)
limitwatch --login

# View your quotas
limitwatch
```

### Example Output

```text
Quota Status

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 Google: dev-home (u***@example.com)
Gemini Flash (CLI)     ████████████████████████████████████▍               76.4% (11h 12m)
Gemini Pro (CLI)       ██████████████████████████▉                         58.1% (2h 49m)
Gemini Flash (AG)      ████████████████████████████████████████▏           84.7% (3d 7h)
Claude (AG)            ████████████████████████                            52.0% (1d 5h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 GitHub Copilot: work-gh
Myriota                ██████████████████▎                                  31.2% used
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 Chutes: c***-primary
Balance: $18.40        ██████████████████████████████████████████████████ 100.0%
Quota (267/300)        ███████████████████████████████████████████▍        89.0% (7h 42m)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 OpenAI Codex: l***@example.com
Primary (7d)           ████▊                                                8.0% used (5d 18h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 OpenRouter: key-prod
Credits: $6.73 remaining █████████████████████                              67.3%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Configuration

The tool stores configuration and account data in:
`~/.config/limitwatch/accounts.json`

## Development

### Running Tests
The project uses `pytest` for unit testing. Coverage reporting is enabled by default.
```bash
uv run pytest
```

### Linting & Formatting
```bash
ruff check .
ruff format .
```

## License

[MIT](LICENSE)
