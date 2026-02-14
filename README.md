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

1. Clone the repository.
2. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

Run the tool using `uv`:

```bash
# Login to a new account (interactive OAuth flow)
uv run gemini-quota -l

# Show primary quotas for all logged-in accounts
uv run gemini-quota

# Show all models including Gemini 2.0/2.5
uv run gemini-quota -s

# Check a specific account only
uv run gemini-quota -a user@example.com

# Manually associate/update a Google Cloud Project ID
uv run gemini-quota -a user@example.com -p YOUR_PROJECT_ID

# Output results as JSON
uv run gemini-quota -j

# Logout an account
uv run gemini-quota --logout user@example.com
```

### Command Line Options

| Flag | Long Flag | Description |
|------|-----------|-------------|
| `-l` | `--login` | Start the interactive OAuth login flow |
| `-a` | `--account` | Filter results to a specific email address |
| `-s` | `--show-all` | Show all models (including Gemini 2.0/2.5) |
| `-j` | `--json` | Output results in JSON format |
| `-p` | `--project-id` | Manually specify a Google Cloud Project ID |
| `-r` | `--refresh` | Force refresh of OAuth access tokens |
| | `--logout` | Remove a specific account |
| | `--logout-all`| Clear all authenticated accounts |
| `-h` | `--help` | Show help message and exit |

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

MIT
