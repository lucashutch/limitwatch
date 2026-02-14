# Gemini Quota Checker

A powerful Python CLI tool to monitor your **Gemini CLI** and **Antigravity** quota usage and reset times across multiple Google accounts.

## Features

- **🚀 Integrated Login**: Authenticate directly within the tool using `gemini-quota --login`. No more manual config file hacking.
- **👥 Multi-Account Support**: Manage and monitor multiple accounts simultaneously.
- **🔍 Source Separation**: Clearly distinguishes between Gemini CLI (Cyan) and Antigravity (Magenta) quotas.
- **📦 Quota Grouping**: Consolidates related models into families (Gemini 3 Pro, Claude, etc.) for a cleaner view.
- **🕒 Human-Readable Reset Times**: Automatically calculates and shows time remaining until your quota resets (e.g., `3d 12h`).
- **📊 Visual Progress Bars**: Dynamic horizontal bars colored by availability (Green > 50%, Yellow 20-50%, Red < 20%).
- **🧠 Smart Filtering**: 
  - Shows primary premium models (Gemini 3, Claude) by default.
  - Automatically shows legacy models (2.5, 1.5) if they are the only ones available for a source.
  - Always hides verbose/experimental models (like Gemini 2.0 Flash) behind the `--show-all` flag.
- **📄 JSON Output**: Integration-ready JSON output for use in scripts or dashboards.
- **⚡ Parallel Fetching**: Fast, concurrent API requests across all accounts.

## Installation

This project is managed with [uv](https://github.com/astral-sh/uv).

### Global Installation (Recommended)
Install the tool globally to run it from anywhere:
```bash
uv tool install .
```

After installation, you can use the `gemini-quota` command directly.

### Local Development
1. Clone the repository.
2. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

```bash
# Initial setup: login to your Google account(s)
gemini-quota --login

# View your quotas
gemini-quota
```

### Example Output

```text
Gemini CLI Quota Status

📧 Account: user@example.com
Gemini 3 Flash (CLI)  ████████████████████████                60.0% (14h 22m)
Gemini 3 Pro (CLI)    ████████████                            30.0% (4h 15m)
Gemini 3 Flash (AG)   ████████████████████████████████        80.0% (5d 12h)
Gemini 3 Pro (AG)     ████████████████████                    50.0% (2d 03h)
Claude (AG)           ████████████████                        40.0% (2d 19h 57m)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Options

For a full list of available flags and descriptions, run:
```bash
gemini-quota --help
```

## Configuration

The tool stores its configuration and encrypted refresh tokens in:
`~/.config/gemini-quota/accounts.json`

## Development

### Running Tests
The project uses `pytest` for unit testing.
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
