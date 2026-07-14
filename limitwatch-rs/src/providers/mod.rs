pub mod base;
pub mod chutes;
pub mod github_copilot;
pub mod openai;
pub mod openrouter;
use crate::model::Account;
use anyhow::{bail, Result};
use base::Provider;
pub fn create(account: Account) -> Result<Box<dyn Provider>> {
    Ok(match account.provider_type.as_str() {
        "chutes" => Box::new(chutes::ChutesProvider::new(account)),
        "github_copilot" => Box::new(github_copilot::GitHubCopilotProvider::new(account)),
        "openai" => Box::new(openai::OpenAiProvider::new(account)),
        "openrouter" => Box::new(openrouter::OpenRouterProvider::new(account)),
        other => bail!("unsupported provider: {other}"),
    })
}
pub fn available() -> [(&'static str, &'static str); 4] {
    [
        ("chutes", "Chutes"),
        ("github_copilot", "GitHub Copilot"),
        ("openai", "OpenAI Codex"),
        ("openrouter", "OpenRouter"),
    ]
}
