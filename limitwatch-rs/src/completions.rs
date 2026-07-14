use crate::{auth::AuthManager, config::Config};
use clap::Command;
use clap_complete::{
    generate,
    shells::{Bash, Fish, Zsh},
};
use std::collections::BTreeSet;
pub fn generate_script(shell: &str, mut cmd: Command) -> anyhow::Result<()> {
    match shell {
        "bash" => generate(Bash, &mut cmd, "limitwatch", &mut std::io::stdout()),
        "zsh" => generate(Zsh, &mut cmd, "limitwatch", &mut std::io::stdout()),
        "fish" => generate(Fish, &mut cmd, "limitwatch", &mut std::io::stdout()),
        _ => anyhow::bail!("unsupported shell: {shell}"),
    }
    Ok(())
}
pub fn candidates(kind: &str, prefix: &str) -> Vec<String> {
    let auth = AuthManager::new(Config::new(None).auth_path());
    let mut out = BTreeSet::new();
    match kind {
        "account" => {
            for (_, a) in auth.supported_accounts() {
                out.insert(a.email.clone());
                if let Some(x) = &a.alias {
                    out.insert(x.clone());
                }
            }
        }
        "group" => {
            for (_, a) in auth.supported_accounts() {
                if let Some(x) = &a.group {
                    out.insert(x.clone());
                }
            }
        }
        "provider" => {
            for x in ["chutes", "github_copilot", "openai", "openrouter"] {
                out.insert(x.into());
            }
        }
        "quota" => {
            for (_, a) in auth.supported_accounts() {
                if let Some(q) = a.extra.get("cachedQuotas").and_then(|x| x.as_array()) {
                    for q in q {
                        for k in ["name", "display_name"] {
                            if let Some(x) = q.get(k).and_then(|x| x.as_str()) {
                                out.insert(x.into());
                            }
                        }
                    }
                }
            }
        }
        "format" => {
            for x in ["csv", "markdown"] {
                out.insert(x.into());
            }
        }
        "view" => {
            for x in ["heatmap", "chart", "calendar", "bars", "stats"] {
                out.insert(x.into());
            }
        }
        _ => {}
    }
    out.into_iter().filter(|x| x.starts_with(prefix)).collect()
}
