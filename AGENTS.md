# Agent Instructions for Gemini Quota

This repository contains a CLI tool for monitoring quota usage across multiple providers (Gemini, Antigravity, Chutes.ai).

## 🛠 Build, Lint, and Test

The project uses [uv](https://github.com/astral-sh/uv) for dependency management and packaging.

### Commands
- **Install Dependencies:** `uv sync`
- **Run CLI:** `uv run gemini-quota`
- **Testing:** `uv run pytest`

### Project Structure
- `src/gemini_quota/`:
    - `cli.py`: CLI entry point using `click`. Handles the main loop and interactive login flow.
    - `quota_client.py`: The **Orchestrator**. It instantiates the correct provider and delegates fetching/filtering/sorting.
    - `auth.py`: Manages account storage and credential loading. Delegates login to providers.
    - `providers/`:
        - `base.py`: Abstract base class `BaseProvider` defining the interface for all providers.
        - `google.py`: Handles Google OAuth, project discovery, and Gemini/Antigravity quotas.
        - `chutes.py`: Handles Chutes.ai API key validation, balance, and daily usage quotas.
    - `display.py`: Pure rendering logic. Agnostic of provider details; uses data provided by the `QuotaClient`.

## 🛠 Business Logic Details

### Provider Pattern
Each provider is responsible for its own:
- **Auth:** Interactive login and token refresh.
- **Data:** API calls to its specific endpoints.
- **Display Metadata:** Defining its primary color, source priority, and sorting/filtering rules.

### Authentication Flow
- `AuthManager.login(provider_type, **kwargs)` is the entry point.
- It uses `QuotaClient` to get the appropriate provider instance and calls its `login()` method.
- **Google:** Uses `InstalledAppFlow` and performs complex project discovery via `loadCodeAssist`, `getManagedProject`, and Cloud Resource Manager.
- **Chutes:** Validates the API key via `GET /users/me`.

### Quota Fetching
- `QuotaClient.fetch_quotas()` triggers the provider's fetching logic.
- **Google:** Fetches CLI and Antigravity quotas in parallel.
- **Chutes:** Fetches balance and primary quota usage summaries.

## 🤖 Agent Rules
- **Modular Extensibility:** When adding a new provider, create a new class in `providers/` and register it in `quota_client.py`.
- **Provider Isolation:** Do not add provider-specific strings or logic to `display.py` or `cli.py`. Use the `BaseProvider` interface.
- **Path Construction:** Always use absolute paths for file operations.
- **Security:** Never log or commit OAuth secrets or API keys.
