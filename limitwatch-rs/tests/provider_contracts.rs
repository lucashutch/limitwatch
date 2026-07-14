use anyhow::Result;
use limitwatch::{
    model::Account,
    providers::{self, base::*},
};
use serde_json::{json, Value};
use std::{
    sync::Mutex,
    time::{Duration, Instant},
};
struct Http {
    responses: Mutex<Vec<HttpResponse>>,
    requests: Mutex<Vec<HttpRequest>>,
}
impl HttpClient for Http {
    fn execute(&self, r: HttpRequest) -> Result<HttpResponse> {
        self.requests.lock().unwrap().push(r);
        Ok(self.responses.lock().unwrap().remove(0))
    }
}
struct Proc;
impl ProcessRunner for Proc {
    fn run(&self, _: &str, _: &[&str], _: Duration) -> Result<ProcessOutput> {
        Ok(ProcessOutput {
            success: true,
            ..Default::default()
        })
    }
}
fn account(kind: &str) -> Account {
    Account {
        provider_type: kind.into(),
        email: "user@example.com".into(),
        api_key: Some("SECRET_KEY".into()),
        refresh_token: Some("SECRET_REFRESH".into()),
        ..Default::default()
    }
}
#[test]
fn every_provider_has_stable_metadata() {
    for kind in ["chutes", "github_copilot", "openai", "openrouter"] {
        let p = providers::create(account(kind)).unwrap();
        assert_eq!(p.provider_type(), kind);
        assert!(!p.provider_name().is_empty());
        assert!(!p.primary_color().is_empty());
        assert!(p.short_indicator().is_ascii_uppercase());
    }
}
#[test]
fn request_context_bounds_and_cancels() {
    let ctx = RequestContext {
        deadline: Some(Instant::now() + Duration::from_millis(20)),
        ..Default::default()
    };
    assert!(ctx.remaining(Duration::from_secs(5)).unwrap() <= Duration::from_millis(20));
    ctx.cancellation.cancel();
    assert!(ctx
        .remaining(Duration::from_secs(1))
        .unwrap_err()
        .to_string()
        .contains("cancelled"));
}
#[test]
fn provider_errors_do_not_expose_credentials() {
    let secret = "SECRET_KEY";
    let http = Http {
        responses: Mutex::new(vec![
            HttpResponse {
                status: 401,
                body: Value::Null,
                headers: Default::default(),
            },
            HttpResponse {
                status: 401,
                body: Value::Null,
                headers: Default::default(),
            },
        ]),
        requests: Mutex::new(vec![]),
    };
    let mut p = providers::create(account("openrouter")).unwrap();
    let error = futures::executor::block_on(p.fetch(&http, &Proc, &RequestContext::default()))
        .unwrap_err()
        .to_string();
    assert!(!error.contains(secret));
    assert!(!error.contains("Authorization"));
    assert_eq!(
        http.requests.lock().unwrap()[0].headers["Authorization"],
        format!("Bearer {secret}")
    );
}
#[test]
fn parsers_accept_representative_payloads() {
    use limitwatch::providers::{
        chutes::ChutesProvider, openai::OpenAiProvider, openrouter::OpenRouterProvider,
    };
    assert!(ChutesProvider::parse_usage(&json!({"quota":100,"used":25}), "Daily").is_some());
    assert_eq!(OpenAiProvider::parse_usage(&json!({"rate_limit":{"primary_window":{"used_percent":10,"limit_window_seconds":3600}}})).len(),1);
    assert_eq!(
        OpenRouterProvider::parse_credits(&json!({"data":{"total_credits":10,"total_usage":2}}))
            .remaining,
        Some(8.0)
    );
}

#[test]
fn python_reference_reset_and_failure_fixture_matches() {
    let f: Value = serde_json::from_str(include_str!("fixtures/parity/reference.json")).unwrap();
    for c in f["resets"].as_array().unwrap() {
        assert_eq!(normalize_reset(&c["input"]).unwrap(), c["canonical"]);
    }
    for c in f["failures"].as_array().unwrap() {
        let error = require_success(
            HttpResponse {
                status: c["status"].as_u64().unwrap() as u16,
                body: Value::Null,
                headers: Default::default(),
            },
            "fetch",
        )
        .unwrap_err();
        assert_eq!(error.to_string(), c["message"]);
    }
}

#[test]
fn github_selected_identity_and_explicit_org_survive_optional_403s() {
    struct Gh(Mutex<Vec<Vec<String>>>);
    impl ProcessRunner for Gh {
        fn run(&self, command: &str, args: &[&str], _: Duration) -> Result<ProcessOutput> {
            assert_eq!(command, "gh");
            self.0
                .lock()
                .unwrap()
                .push(args.iter().map(|arg| (*arg).to_owned()).collect());
            Ok(ProcessOutput {
                success: true,
                stdout: "selected-token\n".into(),
                stderr: "diagnostic".into(),
            })
        }
    }
    let http = Http {
        responses: Mutex::new(vec![HttpResponse {
            status: 200,
            body: json!({"login":"Selected-User"}),
            headers: Default::default(),
        }]),
        requests: Mutex::new(vec![]),
    };
    let gh = Gh(Mutex::new(vec![]));
    let mut provider = providers::create(account("github_copilot")).unwrap();
    let logged_in = futures::executor::block_on(provider.login(
        json!({"github_account":"selected-user", "organization":"Myriota", "token_source":"gh_cli"}),
        &http,
        &gh,
        &RequestContext::default(),
    ))
    .unwrap();

    assert_eq!(
        gh.0.lock().unwrap()[0],
        ["auth", "token", "--user", "selected-user"]
    );
    let request = &http.requests.lock().unwrap()[0];
    assert_eq!(request.url, "https://api.github.com/user");
    assert_eq!(request.headers["Authorization"], "Bearer selected-token");
    assert_eq!(request.headers["Accept"], "application/vnd.github+json");
    assert_eq!(request.headers["X-GitHub-Api-Version"], "2026-03-10");
    assert_eq!(request.headers["User-Agent"], "limitwatch");
    assert_eq!(logged_in.email, "Selected-User");
    assert_eq!(logged_in.extra["github_account"], "Selected-User");
    assert_eq!(logged_in.extra["github_selected_account"], "selected-user");
    assert_eq!(logged_in.extra["githubAuthSource"], "gh_cli");
    assert_eq!(logged_in.extra["githubToken"], "selected-token");
    assert_eq!(logged_in.extra["organization"], "Myriota");
}

#[test]
fn github_internal_user_is_first_single_call_and_selects_configured_org() {
    let fixture: Value = serde_json::from_str(include_str!(
        "fixtures/github_copilot/myriota_internal_user.json"
    ))
    .unwrap();
    let responses = vec![HttpResponse {
        status: 200,
        body: fixture,
        headers: Default::default(),
    }];
    let http = Http {
        responses: Mutex::new(responses),
        requests: Mutex::new(vec![]),
    };
    let mut saved = account("github_copilot");
    saved.email = "user".into();
    saved
        .extra
        .insert("githubToken".into(), json!("sanitized-token"));
    saved.extra.insert("organization".into(), json!("myriota"));
    let mut provider = providers::create(saved).unwrap();
    let quotas =
        futures::executor::block_on(provider.fetch(&http, &Proc, &RequestContext::default()))
            .unwrap();
    let org = quotas.iter().find(|q| q.display_name == "myriota").unwrap();
    assert_eq!(org.name, "GitHub Copilot Org (myriota)");
    assert_eq!(org.limit, Some(26000.0));
    assert_eq!(org.used, Some(231.3));
    assert_eq!(org.remaining, Some(25768.7));
    assert!((org.used_pct.unwrap() - 0.8896153846153846).abs() < f64::EPSILON);
    assert!((org.remaining_pct.unwrap() - 99.11038461538462).abs() < f64::EPSILON);
    assert_eq!(org.reset_time.as_deref(), Some("2026-08-01T00:00:00Z"));
    let requests = http.requests.lock().unwrap();
    assert_eq!(
        requests[0].url,
        "https://api.github.com/copilot_internal/user"
    );
    assert_eq!(
        requests
            .iter()
            .filter(|r| r.url.ends_with("/copilot_internal/user"))
            .count(),
        1
    );
    assert!(!requests.iter().any(|r| r.url.contains("/organizations/")));
    assert_eq!(requests.len(), 1);
}

#[test]
fn github_internal_user_malformed_or_no_match_falls_back_to_billing() {
    for body in [
        json!({"quota_snapshots":null}),
        json!({
            "organization_login_list":["OtherOrg"],
            "quota_snapshots":{"premium_interactions":{"entitlement":300,"remaining":68.7}}
        }),
    ] {
        let missing = || HttpResponse {
            status: 404,
            body: json!({"message":"Not Found"}),
            headers: Default::default(),
        };
        let mut responses = vec![HttpResponse {
            status: 200,
            body,
            headers: Default::default(),
        }];
        responses.extend((0..8).map(|_| missing()));
        let http = Http {
            responses: Mutex::new(responses),
            requests: Mutex::new(vec![]),
        };
        let mut saved = account("github_copilot");
        saved.email = "user".into();
        saved.extra.insert("githubToken".into(), json!("token"));
        saved.extra.insert("organization".into(), json!("Myriota"));
        let mut provider = providers::create(saved).unwrap();
        let quotas =
            futures::executor::block_on(provider.fetch(&http, &Proc, &RequestContext::default()))
                .unwrap();
        assert_eq!(
            quotas
                .iter()
                .find(|q| q.display_name == "Myriota")
                .unwrap()
                .extra["is_error"],
            true
        );
        let requests = http.requests.lock().unwrap();
        assert_eq!(
            requests
                .iter()
                .filter(|r| r.url.ends_with("/copilot_internal/user"))
                .count(),
            1
        );
        assert_eq!(
            requests
                .iter()
                .filter(|r| r.url.contains("/organizations/"))
                .count(),
            4
        );
    }
}

#[test]
fn github_reloaded_account_fetches_personal_and_myriota_endpoints() {
    let usage = json!({"usageItems":[{"product":"Copilot premium requests","grossQuantity":2.0}]});
    let http = Http {
        responses: Mutex::new(vec![
            HttpResponse {
                status: 200,
                body: json!({"copilot_plan":"pro"}),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage.clone(),
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: usage,
                headers: Default::default(),
            },
            HttpResponse {
                status: 200,
                body: json!({"seat_breakdown":{"total":2},"plan_type":"business"}),
                headers: Default::default(),
            },
        ]),
        requests: Mutex::new(vec![]),
    };
    let mut saved = account("github_copilot");
    saved.email = "Lucashutch".into();
    saved
        .extra
        .insert("github_account".into(), json!("Lucashutch"));
    saved
        .extra
        .insert("githubToken".into(), json!("validated-token"));
    saved.extra.insert("organization".into(), json!("Myriota"));
    let reloaded: Account = serde_json::from_value(serde_json::to_value(saved).unwrap()).unwrap();
    let mut provider = providers::create(reloaded).unwrap();
    let quotas =
        futures::executor::block_on(provider.fetch(&http, &Proc, &RequestContext::default()))
            .unwrap();
    assert_eq!(quotas.len(), 2);
    let requests = http.requests.lock().unwrap();
    assert_eq!(
        requests[0].url,
        "https://api.github.com/copilot_internal/user"
    );
    assert!(requests[1]
        .url
        .contains("/users/Lucashutch/settings/billing/usage/summary?"));
    assert!(requests[5]
        .url
        .contains("/organizations/Myriota/settings/billing/usage/summary?"));
    assert_eq!(
        requests[9].url,
        "https://api.github.com/orgs/Myriota/copilot/billing"
    );
    for request in requests.iter() {
        assert!(request.headers["Authorization"].contains("validated-token"));
        assert_eq!(request.headers["Accept"], "application/vnd.github+json");
        assert!(request.headers.contains_key("X-GitHub-Api-Version"));
    }
}

#[test]
fn github_billing_request_sequence() {
    let fixture: Value = serde_json::from_str(include_str!(
        "fixtures/github_copilot/myriota_billing_requests.json"
    ))
    .unwrap();
    let empty = || HttpResponse {
        status: 200,
        body: json!({"usageItems":[]}),
        headers: Default::default(),
    };
    let usage = || HttpResponse {
        status: 200,
        body: json!({"usageItems":[{"product":"Copilot AI credits","grossQuantity":2.0}]}),
        headers: Default::default(),
    };
    let mut responses = vec![HttpResponse {
        status: 200,
        body: json!({"copilot_plan":"pro"}),
        headers: Default::default(),
    }];
    responses.extend([empty(), empty(), usage(), usage()]);
    responses.extend([empty(), empty(), usage(), usage()]);
    responses.push(HttpResponse {
        status: 200,
        body: json!({"seat_breakdown":{"total":2},"plan_type":"business"}),
        headers: Default::default(),
    });
    let http = Http {
        responses: Mutex::new(responses),
        requests: Mutex::new(vec![]),
    };
    let mut saved = account("github_copilot");
    saved.email = "Lucashutch".into();
    saved
        .extra
        .insert("githubToken".into(), json!("validated-token"));
    saved.extra.insert("organization".into(), json!("Myriota"));
    let mut provider = providers::create(saved).unwrap();
    futures::executor::block_on(provider.fetch(&http, &Proc, &RequestContext::default())).unwrap();

    let requests = http.requests.lock().unwrap();
    assert_eq!(
        requests[0].url,
        "https://api.github.com/copilot_internal/user"
    );
    let billing = requests
        .iter()
        .filter(|r| r.url.contains("/settings/billing/usage"))
        .collect::<Vec<_>>();
    for (index, request) in billing.iter().enumerate() {
        let (path, query) = request
            .url
            .strip_prefix("https://api.github.com")
            .unwrap()
            .split_once('?')
            .unwrap();
        assert_eq!(path, fixture["billing_paths"][index]);
        let parts = query.split('&').collect::<Vec<_>>();
        let expected = fixture["queries"][index].as_str().unwrap();
        assert_eq!(
            &parts[..2]
                .iter()
                .map(|p| p.split('=').next().unwrap())
                .collect::<Vec<_>>(),
            &["year", "month"]
        );
        if expected == "filtered" {
            assert_eq!(&parts[2..], &["product=copilot", "sku=copilot_ai_credits"]);
        } else {
            assert_eq!(parts.len(), 2);
        }
        assert_eq!(request.method, "GET");
        assert_eq!(request.headers["Authorization"], "Bearer validated-token");
        assert_eq!(request.headers["Accept"], "application/vnd.github+json");
        assert_eq!(request.headers["X-GitHub-Api-Version"], "2026-03-10");
        assert_eq!(request.headers["User-Agent"], "limitwatch");
    }
    assert_eq!(
        requests[0]
            .url
            .strip_prefix("https://api.github.com")
            .unwrap(),
        fixture["interstitial_paths"][0]
    );
    assert_eq!(
        requests[9]
            .url
            .strip_prefix("https://api.github.com")
            .unwrap(),
        fixture["interstitial_paths"][1]
    );
}

#[test]
fn github_billing_404_fallback() {
    let fixture: Value = serde_json::from_str(include_str!(
        "fixtures/github_copilot/myriota_billing_404_fallback.json"
    ))
    .unwrap();
    let empty = || HttpResponse {
        status: 200,
        body: json!({"usageItems":[]}),
        headers: Default::default(),
    };
    let missing = || HttpResponse {
        status: 404,
        body: json!({"message":"Not Found"}),
        headers: Default::default(),
    };
    for all_missing in [false, true] {
        let mut responses = vec![empty(), empty(), empty(), empty()];
        responses.push(HttpResponse {
            status: 200,
            body: json!({"copilot_plan":"pro"}),
            headers: Default::default(),
        });
        responses.extend(if all_missing {
            vec![missing(), missing(), missing(), missing()]
        } else {
            vec![missing(), empty(), missing(), empty()]
        });
        if !all_missing {
            responses.push(HttpResponse {
                status: 200,
                body: json!({"seat_breakdown":{"total":2},"plan_type":"business"}),
                headers: Default::default(),
            });
        }
        let http = Http {
            responses: Mutex::new(responses),
            requests: Mutex::new(vec![]),
        };
        let mut saved = account("github_copilot");
        saved.email = "Lucashutch".into();
        saved
            .extra
            .insert("githubToken".into(), json!("validated-token"));
        saved.extra.insert("organization".into(), json!("Myriota"));
        let mut provider = providers::create(saved).unwrap();
        let quotas =
            futures::executor::block_on(provider.fetch(&http, &Proc, &RequestContext::default()))
                .unwrap();
        let org = quotas.iter().find(|q| q.display_name == "Myriota").unwrap();
        assert_eq!(
            org.extra.get("is_error").and_then(Value::as_bool),
            all_missing.then_some(true)
        );
        if all_missing {
            assert!(org.extra["message"].as_str().unwrap().contains("HTTP 404"));
        }
        let requests = http.requests.lock().unwrap();
        let billing = requests
            .iter()
            .filter(|r| r.url.contains("/organizations/"))
            .collect::<Vec<_>>();
        assert_eq!(billing.len(), 4);
        for (index, request) in billing.iter().enumerate() {
            let (path, query) = request
                .url
                .strip_prefix("https://api.github.com")
                .unwrap()
                .split_once('?')
                .unwrap();
            assert_eq!(path, fixture["billing_paths"][index]);
            let filtered = query.contains("product=copilot");
            assert_eq!(filtered, fixture["queries"][index] == "filtered");
        }
    }
}

#[test]
fn github_identity_validation_failure_is_not_treated_as_optional() {
    let http = Http {
        responses: Mutex::new(vec![HttpResponse {
            status: 403,
            body: json!({"message":"Forbidden"}),
            headers: Default::default(),
        }]),
        requests: Mutex::new(vec![]),
    };
    let mut provider = providers::create(account("github_copilot")).unwrap();
    let error = futures::executor::block_on(provider.login(
        json!({"githubToken":"identity-token", "organization":"Myriota"}),
        &http,
        &Proc,
        &RequestContext::default(),
    ))
    .unwrap_err();
    assert_eq!(
        error.to_string(),
        "GitHub token validation failed (HTTP 403): Forbidden Check token scopes, rate limits, and organization SSO authorization."
    );
}
