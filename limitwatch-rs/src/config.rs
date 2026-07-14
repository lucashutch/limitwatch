use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfigData {
    pub alert_threshold: Option<f64>,
    pub cache_ttl: Option<i64>,
    pub theme: Option<String>,
    pub history_db_path: Option<String>,
    pub enable_history: Option<bool>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

impl ConfigData {
    fn valid(&self) -> bool {
        self.alert_threshold
            .is_none_or(|v| (0.0..=100.0).contains(&v))
            && self.cache_ttl.is_none_or(|v| v >= 0)
            && self
                .theme
                .as_ref()
                .is_none_or(|v| matches!(v.as_str(), "default" | "dark" | "light"))
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub config_dir: PathBuf,
    pub data: ConfigData,
}

impl Config {
    pub fn new(config_dir: Option<PathBuf>) -> Self {
        let dir = config_dir.unwrap_or_else(default_config_dir);
        let data = fs::read(dir.join("config.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<ConfigData>(&b).ok())
            .filter(ConfigData::valid)
            .unwrap_or_default();
        Self {
            config_dir: dir,
            data,
        }
    }
    pub fn save(&self) -> Result<()> {
        atomic_json(&self.config_dir.join("config.json"), &self.data)
    }
    pub fn auth_path(&self) -> PathBuf {
        self.config_dir.join("accounts.json")
    }
    pub fn history_db_path(&self) -> PathBuf {
        self.data
            .history_db_path
            .as_deref()
            .map(expand_home)
            .unwrap_or_else(|| self.config_dir.join("history.db"))
    }
    pub fn history_enabled(&self) -> bool {
        self.data.enable_history.unwrap_or(true)
    }
    pub fn cache_ttl(&self) -> u64 {
        self.data.cache_ttl.unwrap_or(60).max(0) as u64
    }
}

pub fn default_config_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_default()
        .join(".config/limitwatch")
}
fn expand_home(value: &str) -> PathBuf {
    if value == "~" {
        return dirs::home_dir().unwrap_or_else(|| PathBuf::from(value));
    }
    value
        .strip_prefix("~/")
        .and_then(|p| dirs::home_dir().map(|h| h.join(p)))
        .unwrap_or_else(|| PathBuf::from(value))
}
pub(crate) fn atomic_json<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let parent = path.parent().context("path has no parent")?;
    fs::create_dir_all(parent)?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    serde_json::to_writer_pretty(&mut temp, value)?;
    temp.write_all(b"\n")?;
    temp.as_file().sync_all()?;
    temp.persist(path).map_err(|e| e.error)?;
    Ok(())
}
