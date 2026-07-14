use limitwatch::{cli::github_verbose, model::Timing};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn trace(name: &str, entries: &[(&str, Value)]) -> Timing {
    Timing {
        name: name.into(),
        elapsed_ms: 0.0,
        extra: entries
            .iter()
            .map(|(k, v)| ((*k).into(), v.clone()))
            .collect::<BTreeMap<_, _>>(),
    }
}

#[test]
fn request_contract_is_verbose_only_and_excludes_sensitive_fields() {
    let traces = [trace(
        "github_request",
        &[
            ("method", json!("GET")),
            (
                "path",
                json!("/organizations/<redacted>/settings/billing/usage"),
            ),
            ("status", json!(404)),
            ("token", json!("token-secret")),
            ("Authorization", json!("Bearer header-secret")),
            ("headers", json!({"X-Test":"header-value"})),
            ("query", json!("owner=account-identifier&key=query-secret")),
            ("body", json!({"secret":"response-body"})),
            ("account", json!("account-identifier")),
        ],
    )];
    assert!(github_verbose(false, &traces).is_empty());
    let output = github_verbose(true, &traces).join("\n");
    assert_eq!(
        output,
        "[GitHub] \"GET\" \"/organizations/<redacted>/settings/billing/usage\" status=404"
    );
    for secret in [
        "token-secret",
        "Authorization",
        "header-value",
        "query-secret",
        "response-body",
        "account-identifier",
    ] {
        assert!(!output.contains(secret));
    }
}

#[test]
fn selection_and_fallback_outcomes_are_verbose_only() {
    for outcome in [
        "internal snapshot selected",
        "internal unavailable; billing fallback",
    ] {
        let traces = [trace(
            "github_selection",
            &[
                ("outcome", json!(outcome)),
                ("account", json!("private-org")),
            ],
        )];
        assert!(github_verbose(false, &traces).is_empty());
        assert_eq!(
            github_verbose(true, &traces),
            [format!("[GitHub] \"{outcome}\"")]
        );
        assert!(!github_verbose(true, &traces)
            .join(" ")
            .contains("private-org"));
    }
}

#[test]
fn generic_transport_timing_is_not_rendered_or_allowed_to_leak_fields() {
    let traces = [trace(
        "http_request",
        &[
            ("method", json!("GET")),
            ("status", json!(200)),
            ("url", json!("https://secret.example/private?id=secret")),
        ],
    )];
    assert!(github_verbose(false, &traces).is_empty());
    assert!(github_verbose(true, &traces).is_empty());
}
