# LimitWatch

A powerful Python CLI tool to monitor your **Gemini CLI**, **Antigravity**, **Chutes.ai**, **GitHub Copilot**, and **OpenAI** quota usage and reset times across multiple accounts.

## Features

- **🚀 Modular Provider Architecture**: Easily extensible system supporting Google (Gemini/Antigravity) and Chutes.ai.
- **🔐 Unified Login**: Interactive login flow (`limitwatch --login`) that lets you select your provider and handles authentication (OAuth for Google, API keys for Chutes).
- **👥 Multi-Account Support**: Manage and monitor multiple accounts from different providers simultaneously.
- **🔍 Source Separation**: Distinct color coding for each source:
  - **Gemini CLI**: Cyan
  - **Antigravity**: Magenta
  - **Chutes.ai**: Yellow
- **🕒 Real-time Reset Countdown**: Automatically calculates and shows time remaining until your quota resets (e.g., `2h 15m`).
- **📊 Detailed Usage Stats**: Shows used/total units (e.g., `285/300`) and visual progress bars colored by availability.
- **🧠 Smart Filtering**:
  - Shows primary premium models by default.
  - Automatically shows legacy models if they are the only ones available.
  - Hides verbose/experimental models behind the `--show-all` flag.
- **📄 JSON Output**: Integration-ready JSON output for use in scripts or dashboards.

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

📧 Account: user@example.com (google)
Gemini 3 Flash (CLI)  ████████████████████████                60.0% (14h 22m)
Gemini 3 Pro (CLI)    ████████████                            30.0% (4h 15m)
Gemini 3 Flash (AG)   ████████████████████████████████        80.0% (5d 12h)
Claude (AG)           ████████████████                        40.0% (2d 19m)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📧 Account: developer (chutes)
Balance: $10.50       ██████████████████████████████████████  100.0%
Quota (285/300)       ██████████████████████████████████      95.0% (2h 15m)
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
