use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Account {
    #[serde(rename = "type")]
    pub provider_type: String,
    pub email: String,
    #[serde(rename = "refreshToken", skip_serializing_if = "Option::is_none")]
    pub refresh_token: Option<String>,
    #[serde(rename = "apiKey", skip_serializing_if = "Option::is_none")]
    pub api_key: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub services: Vec<String>,
    #[serde(rename = "projectId", skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
    #[serde(rename = "managedProjectId", skip_serializing_if = "Option::is_none")]
    pub managed_project_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub alias: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group: Option<String>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

impl Account {
    pub fn is_supported(&self) -> bool {
        matches!(
            self.provider_type.as_str(),
            "chutes" | "github_copilot" | "openai" | "openrouter"
        )
    }

    pub fn validate(&self) -> bool {
        !self.email.is_empty() && !self.provider_type.is_empty()
    }

    pub fn identity(&self) -> &str {
        if self.provider_type == "github_copilot" {
            self.extra
                .get("github_account")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .unwrap_or(&self.email)
        } else {
            &self.email
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Quota {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub display_name: String,
    pub remaining_pct: Option<f64>,
    pub used_pct: Option<f64>,
    pub remaining: Option<f64>,
    pub used: Option<f64>,
    pub limit: Option<f64>,
    pub reset_time: Option<String>,
    pub source_type: Option<String>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Timing {
    pub name: String,
    pub elapsed_ms: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}
