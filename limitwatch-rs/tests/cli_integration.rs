use std::{
    fs,
    path::Path,
    process::{Command, Output, Stdio},
};
use tempfile::TempDir;

#[test]
fn myriota_internal_credits_render_exact_python_text_at_fixed_clock() {
    use chrono::{TimeZone, Utc};
    use limitwatch::{
        display,
        model::{Account, Quota},
        providers,
    };

    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "fixtures/github_copilot/myriota_internal_user.json"
    ))
    .unwrap();
    let snapshot = &fixture["quota_snapshots"]["premium_interactions"];
    let mut quota = Quota {
        name: "GitHub Copilot Org (Myriota)".into(),
        display_name: "Myriota".into(),
        source_type: Some("GitHub Copilot".into()),
        limit: snapshot["entitlement"].as_f64(),
        used: snapshot["used"].as_f64(),
        remaining: snapshot["remaining"].as_f64(),
        used_pct: Some(
            snapshot["used"].as_f64().unwrap() / snapshot["entitlement"].as_f64().unwrap() * 100.0,
        ),
        remaining_pct: Some(snapshot["percent_remaining"].as_f64().unwrap()),
        reset_time: fixture["quota_reset_date"].as_str().map(str::to_owned),
        ..Default::default()
    };
    quota
        .extra
        .insert("billing_model".into(), serde_json::json!("ai_credits"));
    let provider = providers::create(Account {
        provider_type: "github_copilot".into(),
        email: "octo".into(),
        ..Default::default()
    })
    .unwrap();
    let text = display::render_quotas_at(
        "octo",
        None,
        None,
        &*provider,
        vec![quota],
        false,
        false,
        Utc.with_ymd_and_hms(2026, 7, 12, 4, 17, 0).unwrap(),
    );

    assert!(text.contains("231.3 cr (0.9%) (19d 19h 43m)"), "{text}");
}

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_limitwatch"))
}

fn accounts(home: &Path, body: &str) {
    let dir = home.join(".config/limitwatch");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("accounts.json"), body).unwrap();
}

fn terminal_logout(home: &Path, input: &str) -> Output {
    let command = format!("{} --logout", env!("CARGO_BIN_EXE_limitwatch"));
    let mut child = Command::new("script")
        .args(["-qfec", &command, "/dev/null"])
        .env("HOME", home)
        .env("NO_COLOR", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    use std::io::Write;
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    child.wait_with_output().unwrap()
}

fn text(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).replace('\r', "")
}

#[test]
fn color_requires_terminal_and_honors_no_color() {
    assert!(limitwatch::display::color_enabled(true, false));
    assert!(!limitwatch::display::color_enabled(true, true));
    assert!(!limitwatch::display::color_enabled(false, false));
}

#[test]
fn concurrent_http_handles_share_one_connection_pool_and_independent_evidence() {
    let http = limitwatch::quota_client::SharedHttp::new().unwrap();
    let clones: Vec<_> = (0..8).map(|_| http.clone()).collect();
    let ids: Vec<_> = clones
        .into_iter()
        .map(|client| std::thread::spawn(move || client.pool_id()))
        .map(|thread| thread.join().unwrap())
        .collect();
    assert!(ids.iter().all(|id| *id == http.pool_id()));
    assert!(http.timings().is_empty());
}

#[test]
fn github_validated_identity_metadata_survives_account_storage_reload() {
    use limitwatch::{auth::AuthManager, model::Account};
    let home = TempDir::new().unwrap();
    let path = home.path().join("accounts.json");
    let mut auth = AuthManager::new(&path);
    let mut account = Account {
        provider_type: "github_copilot".into(),
        email: "Lucashutch".into(),
        ..Default::default()
    };
    account
        .extra
        .insert("github_account".into(), serde_json::json!("Lucashutch"));
    account.extra.insert(
        "github_selected_account".into(),
        serde_json::json!("lucashutch"),
    );
    account
        .extra
        .insert("githubAuthSource".into(), serde_json::json!("gh_cli"));
    account
        .extra
        .insert("githubToken".into(), serde_json::json!("validated-token"));
    account
        .extra
        .insert("organization".into(), serde_json::json!("Myriota"));
    auth.login(account).unwrap();
    auth.save_accounts().unwrap();

    let reloaded = AuthManager::new(path);
    let saved = &reloaded.accounts[0];
    assert_eq!(saved.email, "Lucashutch");
    assert_eq!(saved.extra["github_account"], "Lucashutch");
    assert_eq!(saved.extra["github_selected_account"], "lucashutch");
    assert_eq!(saved.extra["organization"], "Myriota");
    assert_eq!(saved.extra["githubToken"], "validated-token");
}

#[test]
fn help_exposes_python_compatible_commands() {
    let output = bin().arg("--help").output().unwrap();
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(output.status.success());
    for command in ["show", "history", "export", "completion"] {
        assert!(text.contains(command));
    }
}

#[test]
fn version_and_completion_are_machine_readable() {
    assert!(bin().arg("--version").status().unwrap().success());
    for shell in ["bash", "zsh", "fish"] {
        let output = bin().args(["completion", shell]).output().unwrap();
        assert!(output.status.success());
        assert!(String::from_utf8(output.stdout)
            .unwrap()
            .contains("limitwatch"));
    }
}

#[test]
fn invalid_completion_shell_fails() {
    assert!(!bin()
        .args(["completion", "powershell"])
        .status()
        .unwrap()
        .success());
}

#[test]
fn fixture_completion_provider_candidates_match() {
    let f: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/parity/reference.json")).unwrap();
    let expected: Vec<String> = serde_json::from_value(f["completionProviders"].clone()).unwrap();
    assert_eq!(
        limitwatch::completions::candidates("provider", ""),
        expected
    );
}

#[test]
fn bare_logout_selects_provider_and_account_on_a_terminal_with_captured_stdout() {
    let home = TempDir::new().unwrap();
    accounts(
        home.path(),
        r#"{"accounts":[
      {"type":"github_copilot","email":"octo"},
      {"type":"openai","email":"first@example.com"},
      {"type":"openai","email":"second@example.com","alias":"Myriota"}
    ],"activeIndex":0}"#,
    );
    let output = terminal_logout(home.path(), "2\n2\ny\n");
    let transcript = text(&output);
    assert!(output.status.success(), "{transcript}");
    for expected in [
        "Select Provider",
        "OpenAI (2 accounts)",
        "Select Account",
        "Myriota",
        "Log out Myriota?",
        "Successfully logged out Myriota",
    ] {
        assert!(
            transcript.contains(expected),
            "missing {expected:?}: {transcript}"
        );
    }
    let saved = fs::read_to_string(home.path().join(".config/limitwatch/accounts.json")).unwrap();
    assert!(!saved.contains("Myriota"));
    assert!(saved.contains("octo"));
}

#[test]
fn bare_logout_can_be_cancelled_without_mutating_accounts() {
    let home = TempDir::new().unwrap();
    let original = r#"{"accounts":[{"type":"github_copilot","email":"octo"}],"activeIndex":0}"#;
    accounts(home.path(), original);
    let output = terminal_logout(home.path(), "\nn\n");
    assert!(text(&output).contains("Logout cancelled."));
    assert_eq!(
        fs::read_to_string(home.path().join(".config/limitwatch/accounts.json")).unwrap(),
        original
    );
}

#[test]
fn bare_logout_reports_no_accounts_on_a_terminal() {
    let home = TempDir::new().unwrap();
    accounts(home.path(), r#"{"accounts":[],"activeIndex":0}"#);
    let output = terminal_logout(home.path(), "");
    assert!(output.status.success());
    assert!(text(&output).contains("No accounts found to log out from."));
}

#[test]
fn bare_logout_is_explicitly_noninteractive_for_json_and_piped_input() {
    let home = TempDir::new().unwrap();
    accounts(
        home.path(),
        r#"{"accounts":[{"type":"github_copilot","email":"octo"}],"activeIndex":0}"#,
    );
    let json = bin()
        .args(["--logout", "--json"])
        .env("HOME", home.path())
        .output()
        .unwrap();
    let value: serde_json::Value = serde_json::from_slice(&json.stdout).unwrap();
    assert_eq!(value["status"], "error");
    assert!(value["message"]
        .as_str()
        .unwrap()
        .contains("requires --account"));
    let piped = bin()
        .arg("--logout")
        .env("HOME", home.path())
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert_eq!(
        text(&piped).trim(),
        "--logout requires --account in non-interactive mode"
    );
}
