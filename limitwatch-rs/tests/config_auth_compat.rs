use limitwatch::{auth::AuthManager, config::Config, model::Account};
use serde_json::{json, Value};
use std::{collections::BTreeMap, fs};

#[test]
fn fixtures_round_trip_preserve_unknown_fields() {
    let dir = tempfile::tempdir().unwrap();
    fs::copy(
        "tests/fixtures/accounts.json",
        dir.path().join("accounts.json"),
    )
    .unwrap();
    fs::copy("tests/fixtures/config.json", dir.path().join("config.json")).unwrap();
    let auth = AuthManager::new(dir.path().join("accounts.json"));
    assert_eq!(auth.accounts.len(), 2);
    assert_eq!(auth.active_index, 1);
    assert_eq!(auth.supported_accounts().count(), 1);
    auth.save_accounts().unwrap();
    let value: Value =
        serde_json::from_slice(&fs::read(dir.path().join("accounts.json")).unwrap()).unwrap();
    assert_eq!(value["futureRoot"], true);
    assert_eq!(value["accounts"][0]["futureField"], json!({"x":1}));
    let config = Config::new(Some(dir.path().to_path_buf()));
    assert_eq!(config.cache_ttl(), 120);
    assert!(!config.history_enabled());
    config.save().unwrap();
    let value: Value =
        serde_json::from_slice(&fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    assert_eq!(value["futureOption"], json!([1, 2]));
}

#[test]
fn missing_and_malformed_files_use_defaults() {
    let dir = tempfile::tempdir().unwrap();
    let config = Config::new(Some(dir.path().to_path_buf()));
    assert_eq!(config.cache_ttl(), 60);
    fs::write(dir.path().join("accounts.json"), "nope").unwrap();
    assert!(AuthManager::new(dir.path().join("accounts.json"))
        .accounts
        .is_empty());
}

fn account(provider: &str, email: &str) -> Account {
    Account {
        provider_type: provider.into(),
        email: email.into(),
        ..Default::default()
    }
}

#[test]
fn login_updates_logout_and_metadata_are_compatible() {
    let dir = tempfile::tempdir().unwrap();
    let mut auth = AuthManager::new(dir.path().join("accounts.json"));
    let mut first = account("openai", "a@example.com");
    first.extra.insert("old".into(), json!(1));
    auth.login(first).unwrap();
    let mut update = account("openai", "a@example.com");
    update.refresh_token = Some("token".into());
    auth.login(update).unwrap();
    assert_eq!(auth.accounts.len(), 1);
    assert_eq!(auth.accounts[0].extra["old"], 1);
    let mut metadata = BTreeMap::new();
    metadata.insert("alias".into(), Some("mine".into()));
    metadata.insert("group".into(), Some("work".into()));
    auth.update_account_metadata("a@example.com", &metadata)
        .unwrap();
    assert!(auth.logout("mine").unwrap());
    assert!(auth.accounts.is_empty());
}

#[test]
fn ignored_records_survive_and_cannot_instantiate_or_be_managed() {
    let dir = tempfile::tempdir().unwrap();
    fs::copy(
        "tests/fixtures/accounts.json",
        dir.path().join("accounts.json"),
    )
    .unwrap();
    let mut auth = AuthManager::new(dir.path().join("accounts.json"));
    assert!(!auth.logout("main").unwrap());
    assert!(limitwatch::quota_client::QuotaClient::new(auth.accounts[0].clone()).is_err());
    auth.save_accounts().unwrap();
    let value: Value = serde_json::from_slice(&fs::read(auth.auth_path).unwrap()).unwrap();
    assert_eq!(value["accounts"][0]["futureField"], json!({"x": 1}));
    assert_eq!(value["accounts"][0]["refreshToken"], "secret");
}

#[test]
fn ambiguous_alias_is_not_modified_and_active_index_tracks_removal() {
    let dir = tempfile::tempdir().unwrap();
    let mut auth = AuthManager::new(dir.path().join("accounts.json"));
    for email in ["one@example.com", "two@example.com"] {
        let mut a = account("openai", email);
        a.alias = Some("shared".into());
        auth.login(a).unwrap();
    }
    assert_eq!(auth.active_index, 1);
    assert!(!auth.logout("shared").unwrap());
    assert!(auth.logout("one@example.com").unwrap());
    assert_eq!(auth.active_index, 0);
}

#[test]
fn github_identity_allows_distinct_accounts() {
    let dir = tempfile::tempdir().unwrap();
    let mut auth = AuthManager::new(dir.path().join("accounts.json"));
    for name in ["one", "two"] {
        let mut a = account("github_copilot", name);
        a.extra.insert("github_account".into(), json!(name));
        auth.login(a).unwrap();
    }
    assert_eq!(auth.accounts.len(), 2);
}

#[test]
fn parity_fixture_documents_google_omission() {
    let f: Value = serde_json::from_str(include_str!("fixtures/parity/reference.json")).unwrap();
    assert_eq!(f["ignoredProviders"], json!(["google"]));
    assert!(!f["supportedProviders"]
        .as_array()
        .unwrap()
        .contains(&json!("google")));
}
