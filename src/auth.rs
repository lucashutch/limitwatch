use crate::{config::atomic_json, model::Account};
use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AccountsFile {
    #[serde(default)]
    pub accounts: Vec<Account>,
    #[serde(rename = "activeIndex", default)]
    pub active_index: usize,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

pub struct AuthManager {
    pub auth_path: PathBuf,
    pub accounts: Vec<Account>,
    pub active_index: usize,
    extra: BTreeMap<String, Value>,
}
impl AuthManager {
    pub fn new(auth_path: impl Into<PathBuf>) -> Self {
        let auth_path = auth_path.into();
        let loaded = load(&auth_path).unwrap_or_default();
        Self {
            auth_path,
            accounts: loaded.accounts,
            active_index: loaded.active_index,
            extra: loaded.extra,
        }
    }
    pub fn save_accounts(&self) -> Result<()> {
        atomic_json(
            &self.auth_path,
            &AccountsFile {
                accounts: self.accounts.clone(),
                active_index: self.active_index,
                extra: self.extra.clone(),
            },
        )
    }
    pub fn supported_accounts(&self) -> impl Iterator<Item = (usize, &Account)> {
        self.accounts
            .iter()
            .enumerate()
            .filter(|(_, account)| account.is_supported())
    }

    pub fn login(&mut self, account: Account) -> Result<String> {
        if !account.validate() || !account.is_supported() {
            bail!("Account data missing email or has unsupported type");
        }
        let email = account.email.clone();
        if let Some((index, existing)) = self.accounts.iter_mut().enumerate().find(|(_, a)| {
            a.provider_type == account.provider_type && a.identity() == account.identity()
        }) {
            let mut old = serde_json::to_value(&*existing)?
                .as_object()
                .cloned()
                .unwrap_or_default();
            old.extend(
                serde_json::to_value(&account)?
                    .as_object()
                    .cloned()
                    .unwrap_or_default(),
            );
            *existing = serde_json::from_value(Value::Object(old))?;
            self.active_index = index;
        } else {
            self.accounts.push(account);
            self.active_index = self.accounts.len() - 1;
        }
        self.save_accounts()?;
        Ok(email)
    }
    pub fn logout(&mut self, identifier: &str) -> Result<bool> {
        let matches: Vec<_> = self
            .supported_accounts()
            .filter(|(_, a)| {
                a.email == identifier
                    || a.identity() == identifier
                    || a.alias.as_deref() == Some(identifier)
            })
            .map(|(index, _)| index)
            .collect();
        if matches.len() != 1 {
            return Ok(false);
        }
        let removed = matches[0];
        self.accounts.remove(removed);
        self.active_index = if self.accounts.is_empty() {
            0
        } else if self.active_index > removed {
            self.active_index - 1
        } else {
            self.active_index.min(self.accounts.len() - 1)
        };
        self.save_accounts()?;
        Ok(true)
    }
    pub fn logout_all(&mut self) -> Result<()> {
        self.accounts.retain(|account| !account.is_supported());
        self.active_index = 0;
        self.save_accounts()
    }
    pub fn update_account_metadata(
        &mut self,
        email: &str,
        metadata: &BTreeMap<String, Option<String>>,
    ) -> Result<bool> {
        let matches: Vec<_> = self
            .supported_accounts()
            .filter(|(_, a)| {
                a.email == email || a.identity() == email || a.alias.as_deref() == Some(email)
            })
            .map(|(index, _)| index)
            .collect();
        if matches.len() != 1 {
            return Ok(false);
        };
        let a = &mut self.accounts[matches[0]];
        for (key, value) in metadata {
            let clear = value
                .as_deref()
                .is_none_or(|v| v.is_empty() || v.eq_ignore_ascii_case("none"));
            match (key.as_str(), clear) {
                ("alias", true) => a.alias = None,
                ("alias", false) => a.alias = value.clone(),
                ("group", true) => a.group = None,
                ("group", false) => a.group = value.clone(),
                ("projectId", true) => a.project_id = None,
                ("projectId", false) => a.project_id = value.clone(),
                ("managedProjectId", true) => a.managed_project_id = None,
                ("managedProjectId", false) => a.managed_project_id = value.clone(),
                (_, true) => {
                    a.extra.remove(key);
                }
                (_, false) => {
                    a.extra.insert(
                        key.clone(),
                        Value::String(value.clone().unwrap_or_default()),
                    );
                }
            }
        }
        self.save_accounts()?;
        Ok(true)
    }
}
fn load(path: &Path) -> Option<AccountsFile> {
    let mut root = serde_json::from_slice::<Value>(&fs::read(path).ok()?).ok()?;
    let object = root.as_object_mut()?;
    let accounts = object
        .remove("accounts")
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|value| serde_json::from_value::<Account>(value).ok())
        .collect();
    let active_index = object
        .remove("activeIndex")
        .and_then(|value| value.as_u64())
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_default();
    let extra = object
        .iter()
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    Some(AccountsFile {
        accounts,
        active_index,
        extra,
    })
}
