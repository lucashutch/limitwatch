# Agent Instructions for Gemini Quota

This repository contains a CLI tool for monitoring Gemini CLI and Antigravity quota usage.

## 🛠 Build, Lint, and Test

The project uses [uv](https://github.com/astral-sh/uv) for dependency management and packaging.

### Commands
- **Install Dependencies:** `uv sync`
- **Run CLI:** `uv run gemini-quota`
- **Linting:** Use `ruff check .` (if installed) or adhere to the existing style.
- **Formatting:** Use `ruff format .` or `black .`.
- **Testing:** Unit tests are located in the `tests/` directory.
    - Run all tests: `uv run pytest`
    - Run a single test file: `uv run pytest tests/test_file.py`
    - Run a specific test: `uv run pytest tests/test_file.py::test_function_name`

### Project Structure
- `src/`: Core source code.
    - `cli.py`: Main entry point and CLI command definitions using `click`.
    - `auth.py`: OAuth2 flow and account management logic.
    - `config.py`: Configuration and file path management.
    - `display.py`: Logic for rendering rich output and progress bars.
    - `quota_client.py`: API clients for fetching quotas.

## 📦 Dependencies and Environment

The project relies on several key Google libraries and the `rich` library for CLI rendering.

- **Click:** Used for defining CLI commands and options.
- **Rich:** Used for console output, including colored text, progress bars, and status indicators.
- **Google Auth & OAuthlib:** Handles the OAuth2 flow and credential management.
- **Requests:** Used for direct API calls to Google's internal quota endpoints.

### Environment Setup
- Python 3.11 or higher is required.
- The tool stores configuration and account data in `~/.config/gemini-quota/`.
- `accounts.json` contains refresh tokens and project associations.

## 🛠 Business Logic Details

### Authentication Flow
- The `AuthManager` handles loading, saving, and refreshing credentials.
- `login()` uses `InstalledAppFlow` to perform a local server OAuth flow.
- It attempts to automatically discover the Google Cloud Project ID (`projectId`) via internal endpoints or Cloud Resource Manager.

### Quota Fetching
- `QuotaClient` performs parallel requests to fetch both Gemini CLI and Antigravity quotas.
- CLI quotas use `cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`.
- Antigravity quotas use `cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels`.
- Smart filtering in `DisplayManager` hides verbose models (like Gemini 2.0/2.5) by default unless primary models are missing or `--show-all` is used.

## 🤖 Agent Rules
- **No Proactive Docs:** Do not create `.md` files unless specifically requested.
- **Path Construction:** Always use absolute paths for file operations.
- **Verify Changes:** Run the CLI or scripts to verify your changes whenever possible.
- **Security:** Never log or commit OAuth secrets or refresh tokens. The hardcoded Client IDs are public knowledge for these specific Google services.
