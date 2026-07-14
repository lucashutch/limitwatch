use super::base::*;
use crate::model::{Account, Quota, Timing};
use anyhow::{bail, Context};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs,
    path::PathBuf,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
const USAGE: &str = "https://chatgpt.com/backend-api/wham/usage";
const USER_INFO: &str = "https://chatgpt.com/backend-api/me";
const CLIENT_ID: &str = "app_EMoamEEZ73f0CkXaXp7hrann";

fn number(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
        .filter(|value| value.is_finite())
}

fn capitalize(value: &str) -> String {
    let mut chars = value.chars();
    chars
        .next()
        .map(|first| first.to_uppercase().collect::<String>() + chars.as_str())
        .unwrap_or_default()
}

fn identity_from_value(value: &Value) -> Option<String> {
    const PREFERRED: [&str; 7] = [
        "email",
        "preferred_username",
        "username",
        "user_name",
        "login",
        "name",
        "nickname",
    ];
    const FALLBACK: [&str; 2] = ["id", "sub"];
    fn usable(value: &str) -> bool {
        let value = value.trim();
        if value.is_empty()
            || ["openai user", "unknown", "none", "null"]
                .contains(&value.to_ascii_lowercase().as_str())
        {
            return false;
        }
        if value.contains('|')
            && [
                "google-oauth2",
                "auth0",
                "oauth",
                "samlp",
                "github",
                "microsoft",
            ]
            .iter()
            .any(|prefix| {
                value
                    .split('|')
                    .next()
                    .unwrap_or_default()
                    .eq_ignore_ascii_case(prefix)
            })
        {
            return false;
        }
        !(value.len() >= 8 && value.chars().all(|c| c.is_ascii_digit()))
    }
    fn walk(value: &Value, keys: &[&str]) -> Option<String> {
        match value {
            Value::Object(object) => {
                for key in keys {
                    if let Some(text) = object.get(*key).and_then(Value::as_str) {
                        if usable(text) {
                            return Some(text.trim().to_owned());
                        }
                    }
                }
                object.values().find_map(|child| walk(child, keys))
            }
            Value::Array(values) => values.iter().find_map(|child| walk(child, keys)),
            _ => None,
        }
    }
    walk(value, &PREFERRED).or_else(|| walk(value, &FALLBACK))
}
pub struct OpenAiProvider {
    a: Account,
    t: Vec<Timing>,
}
impl OpenAiProvider {
    pub fn new(a: Account) -> Self {
        Self { a, t: vec![] }
    }
    pub fn parse_usage(v: &Value) -> Vec<Quota> {
        let plan = v["plan_type"].as_str().unwrap_or("unknown");
        let mut out = vec![];
        for (k, label) in [
            ("primary_window", "Primary"),
            ("secondary_window", "Secondary"),
        ] {
            if let Some(w) = v["rate_limit"].get(k).and_then(Value::as_object) {
                out.push(Self::parse_window(w, plan, label));
            }
        }
        if let Some(additional) = v.get("additional_rate_limits").and_then(Value::as_array) {
            for entry in additional {
                let Some(object) = entry.as_object() else {
                    continue;
                };
                let label = object
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("Additional");
                let window = object
                    .get("primary_window")
                    .and_then(Value::as_object)
                    .unwrap_or(object);
                out.push(Self::parse_window(window, plan, label));
            }
        }
        if let Some(credits) = v.get("credits").and_then(Value::as_object) {
            if credits.get("has_credits").and_then(Value::as_bool) == Some(true) {
                let unlimited = credits
                    .get("unlimited")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let balance = number(credits.get("balance").unwrap_or(&Value::Null)).unwrap_or(0.);
                let mut q = quota(
                    &format!("OpenAI Credits ({plan})"),
                    "Credits",
                    "OpenAI Codex",
                );
                q.remaining_pct = Some(if unlimited {
                    100.
                } else {
                    balance.clamp(0., 100.)
                });
                q.used_pct = Some(if unlimited {
                    0.
                } else {
                    (100. - balance).max(0.)
                });
                extra(&mut q, "plan_type", plan);
                extra(&mut q, "unlimited", unlimited);
                extra(&mut q, "balance", balance);
                out.push(q);
            }
        }
        if out.is_empty() {
            let mut q = quota(
                &format!("OpenAI Codex ({plan})"),
                &format!("Plan: {}", capitalize(plan)),
                "OpenAI Codex",
            );
            q.remaining_pct = Some(100.);
            extra(&mut q, "plan_type", plan);
            q.reset_time = Some("No quota limits".into());
            out.push(q);
        }
        out
    }

    fn parse_window(w: &serde_json::Map<String, Value>, plan: &str, label: &str) -> Quota {
        let used = number(w.get("used_percent").unwrap_or(&Value::Null))
            .unwrap_or(0.)
            .clamp(0., 100.);
        let secs = number(w.get("limit_window_seconds").unwrap_or(&Value::Null))
            .unwrap_or(0.)
            .max(0.) as u64;
        let wl = if secs >= 86400 {
            let days = secs as f64 / 86400.;
            if days.fract() == 0. {
                format!("{days:.0}d")
            } else {
                format!("{days:.1}d")
            }
        } else if secs >= 3600 {
            let hours = secs as f64 / 3600.;
            if hours.fract() == 0. {
                format!("{hours:.0}h")
            } else {
                format!("{hours:.1}h")
            }
        } else if secs > 0 {
            format!("{}m", secs / 60)
        } else {
            String::new()
        };
        let display = if wl.is_empty() {
            label.to_owned()
        } else {
            format!("{label} ({wl})")
        };
        let mut q = quota(
            &format!("OpenAI Codex {label} ({plan})"),
            &display,
            "OpenAI Codex",
        );
        q.used_pct = Some(used);
        q.remaining_pct = Some(100. - used);
        q.reset_time = w.get("reset_at").and_then(normalize_reset);
        extra(&mut q, "plan_type", plan);
        extra(&mut q, "window_seconds", secs);
        q
    }
    fn jwt(token: &str) -> Option<Value> {
        let part = token.split('.').nth(1)?;
        let part = part.trim_end_matches('=');
        serde_json::from_slice(&URL_SAFE_NO_PAD.decode(part).ok()?).ok()
    }
    fn expired(token: &str) -> bool {
        Self::jwt(token)
            .and_then(|v| v["exp"].as_u64())
            .is_some_and(|e| {
                e <= SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs()
                    + 30
            })
    }
    fn credentials(i: &Value, a: &Account) -> Value {
        if i.get("accessToken").and_then(Value::as_str).is_some()
            || i.get("access_token").and_then(Value::as_str).is_some()
        {
            return i.clone();
        }
        if a.extra
            .get("accessToken")
            .or_else(|| a.extra.get("access_token"))
            .and_then(Value::as_str)
            .is_some()
        {
            return Value::Object(a.extra.clone().into_iter().collect());
        }
        let mut paths = Vec::new();
        if let Some(path) = i.get("authFile").and_then(Value::as_str) {
            paths.push(PathBuf::from(path));
        }
        if let Some(home) = dirs::home_dir() {
            paths.push(home.join(".local/share/opencode/auth.json"));
        }
        if let Some(home) = std::env::var_os("CODEX_HOME").map(PathBuf::from) {
            paths.push(home.join("auth.json"));
        }
        if let Some(home) = dirs::home_dir() {
            paths.push(home.join(".codex/auth.json"));
        }
        paths
            .into_iter()
            .filter_map(|path| fs::read_to_string(path).ok())
            .filter_map(|contents| serde_json::from_str::<Value>(&contents).ok())
            .find(|value| Self::token(value).is_some())
            .unwrap_or(Value::Null)
    }

    fn token(value: &Value) -> Option<String> {
        fn walk(value: &Value) -> Option<(String, Option<String>)> {
            match value {
                Value::Object(object) => {
                    for container_key in ["accounts", "providers"] {
                        if let Some(container) =
                            object.get(container_key).and_then(Value::as_object)
                        {
                            for provider_key in ["openai", "OpenAI", "chatgpt"] {
                                if let Some(entry) = container.get(provider_key) {
                                    if let Some(result) = walk(entry) {
                                        return Some(result);
                                    }
                                }
                            }
                        }
                    }
                    let access = object
                        .get("accessToken")
                        .or_else(|| object.get("access_token"))
                        .and_then(Value::as_str)
                        .filter(|token| !token.is_empty())
                        .map(str::to_owned);
                    if let Some(access) = access {
                        let refresh = object
                            .get("refreshToken")
                            .or_else(|| object.get("refresh_token"))
                            .and_then(Value::as_str)
                            .map(str::to_owned);
                        return Some((access, refresh));
                    }
                    object.values().find_map(walk)
                }
                Value::Array(values) => values.iter().find_map(walk),
                _ => None,
            }
        }
        walk(value).map(|(access, _)| access)
    }

    fn refresh_token(value: &Value) -> Option<String> {
        fn walk(value: &Value) -> Option<String> {
            match value {
                Value::Object(object) => object
                    .get("refreshToken")
                    .or_else(|| object.get("refresh_token"))
                    .and_then(Value::as_str)
                    .filter(|token| !token.is_empty())
                    .map(str::to_owned)
                    .or_else(|| object.values().find_map(walk)),
                Value::Array(values) => values.iter().find_map(walk),
                _ => None,
            }
        }
        walk(value)
    }
    fn post(
        c: &dyn HttpClient,
        x: &RequestContext,
        url: &str,
        body: Value,
    ) -> anyhow::Result<HttpResponse> {
        checked(
            c,
            x,
            HttpRequest {
                method: "POST",
                url: url.into(),
                headers: BTreeMap::from([("Content-Type".into(), "application/json".into())]),
                body: Some(body),
                timeout: Duration::from_secs(10),
            },
        )
    }
    fn refresh(c: &dyn HttpClient, x: &RequestContext, refresh: &str) -> anyhow::Result<Value> {
        let r = require_success(
            Self::post(
                c,
                x,
                "https://auth.openai.com/oauth/token",
                json!({"grant_type":"refresh_token","refresh_token":refresh,"client_id":CLIENT_ID,"scope":"openid profile email"}),
            )?,
            "OpenAI token refresh",
        )?;
        Ok(r.body)
    }
    fn exchange_device_code(
        c: &dyn HttpClient,
        x: &RequestContext,
        code: &str,
        verifier: &str,
    ) -> anyhow::Result<Value> {
        require_success(
            Self::post(
                c,
                x,
                "https://auth.openai.com/oauth/token",
                json!({
                    "grant_type":"authorization_code",
                    "client_id":CLIENT_ID,
                    "code":code,
                    "code_verifier":verifier,
                    "redirect_uri":"https://auth.openai.com/deviceauth/callback"
                }),
            )?,
            "OpenAI device token exchange",
        )
        .map(|response| response.body)
    }
    fn identity(token: &str) -> String {
        Self::jwt(token)
            .and_then(|claims| identity_from_value(&claims))
            .unwrap_or_else(|| "OpenAI User".into())
    }
    fn identity_from_api(c: &dyn HttpClient, x: &RequestContext, token: &str) -> Option<String> {
        let response = checked(
            c,
            x,
            HttpRequest {
                method: "GET",
                url: USER_INFO.into(),
                headers: bearer(token),
                body: None,
                timeout: Duration::from_secs(10),
            },
        )
        .ok()?;
        (response.status == 200)
            .then(|| identity_from_value(&response.body))
            .flatten()
    }
    fn usage(c: &dyn HttpClient, x: &RequestContext, t: &str) -> anyhow::Result<HttpResponse> {
        checked(
            c,
            x,
            HttpRequest {
                method: "GET",
                url: USAGE.into(),
                headers: bearer(t),
                body: None,
                timeout: Duration::from_secs(10),
            },
        )
    }
    fn error_quota(message: impl Into<String>) -> Quota {
        let mut q = quota("OpenAI Codex", "Codex", "OpenAI Codex");
        extra(&mut q, "is_error", true);
        extra(&mut q, "message", message.into());
        q
    }
}
impl Provider for OpenAiProvider {
    fn account(&self) -> &Account {
        &self.a
    }
    fn provider_type(&self) -> &'static str {
        "openai"
    }
    fn provider_name(&self) -> &'static str {
        "OpenAI Codex"
    }
    fn source_priority(&self) -> u8 {
        3
    }
    fn primary_color(&self) -> &'static str {
        "green"
    }
    fn short_indicator(&self) -> char {
        'O'
    }
    fn login<'a>(
        &'a mut self,
        i: Value,
        c: &'a dyn HttpClient,
        _: &'a dyn ProcessRunner,
        x: &'a RequestContext,
    ) -> ProviderFuture<'a, Account> {
        Box::pin(async move {
            let mut creds = Self::credentials(&i, &self.a);
            if creds.is_null() {
                let start = require_success(
                    Self::post(
                        c,
                        x,
                        "https://auth.openai.com/api/accounts/deviceauth/usercode",
                        json!({"client_id":CLIENT_ID}),
                    )?,
                    "OpenAI device authorization",
                )?
                .body;
                let code = start["device_auth_id"]
                    .as_str()
                    .context("device authorization omitted id")?;
                let interval = number(&start["interval"]).unwrap_or(1.).max(0.) as u64;
                let user_code = start
                    .get("user_code")
                    .or_else(|| start.get("usercode"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                eprintln!(
                    "OpenAI Device Authorization\nOpen: https://auth.openai.com/codex/device\nEnter code: {user_code}"
                );
                let polling_started = Instant::now();
                loop {
                    if polling_started.elapsed() >= Duration::from_secs(900) {
                        bail!("OpenAI device code auth timed out (15 minutes)")
                    }
                    x.remaining(Duration::from_secs(10))?;
                    let r = Self::post(
                        c,
                        x,
                        "https://auth.openai.com/api/accounts/deviceauth/token",
                        json!({
                            "device_auth_id":code,
                            "user_code":user_code
                        }),
                    )?;
                    if r.status == 200 {
                        if r.body
                            .get("authorization_code")
                            .and_then(Value::as_str)
                            .is_some()
                            && r.body
                                .get("code_verifier")
                                .and_then(Value::as_str)
                                .is_some()
                        {
                            creds = Self::exchange_device_code(
                                c,
                                x,
                                r.body["authorization_code"].as_str().unwrap(),
                                r.body["code_verifier"].as_str().unwrap(),
                            )?;
                        } else {
                            creds = r.body;
                        }
                        break;
                    }
                    if r.status != 403 && r.status != 404 {
                        bail!("OpenAI device login failed (HTTP {})", r.status)
                    }
                    thread::sleep(Duration::from_secs(interval.clamp(1, 30)));
                }
            }
            let mut token = Self::token(&creds)
                .context("OpenAI credentials omitted access token")?
                .to_owned();
            if Self::expired(&token) {
                let refresh = Self::refresh_token(&creds)
                    .context("expired OpenAI token has no refresh token")?;
                let fresh = Self::refresh(c, x, &refresh)?;
                token = Self::token(&fresh).context("refresh response omitted access token")?;
                creds = if Self::refresh_token(&fresh).is_some() {
                    fresh
                } else {
                    let mut object = fresh.as_object().cloned().unwrap_or_default();
                    object.insert("refresh_token".into(), Value::String(refresh));
                    Value::Object(object)
                };
            }
            let mut validation = Self::usage(c, x, &token)?;
            if validation.status == 401 {
                if let Some(refresh) = Self::refresh_token(&creds) {
                    let fresh = Self::refresh(c, x, &refresh)?;
                    token = Self::token(&fresh).context("refresh response omitted access token")?;
                    creds = if Self::refresh_token(&fresh).is_some() {
                        fresh
                    } else {
                        let mut object = fresh.as_object().cloned().unwrap_or_default();
                        object.insert("refresh_token".into(), Value::String(refresh));
                        Value::Object(object)
                    };
                    validation = Self::usage(c, x, &token)?;
                }
            }
            require_success(validation, "OpenAI token validation")?;
            let mut a = self.a.clone();
            a.email = Self::identity_from_api(c, x, &token)
                .or_else(|| identity_from_value(&creds))
                .unwrap_or_else(|| Self::identity(&token));
            a.extra.insert("accessToken".into(), Value::String(token));
            if let Some(refresh) = Self::refresh_token(&creds) {
                a.extra
                    .insert("refreshToken".into(), Value::String(refresh));
            }
            Ok(a)
        })
    }
    fn fetch<'a>(
        &'a mut self,
        c: &'a dyn HttpClient,
        _: &'a dyn ProcessRunner,
        x: &'a RequestContext,
    ) -> ProviderFuture<'a, Vec<Quota>> {
        Box::pin(async move {
            let started = Instant::now();
            let mut token = self
                .a
                .extra
                .get("accessToken")
                .or_else(|| self.a.extra.get("access_token"))
                .and_then(Value::as_str)
                .context("OpenAI credentials missing; log in to Codex")?
                .to_owned();
            let force_refresh = self
                .a
                .extra
                .get("_limitwatch_force_refresh")
                .and_then(Value::as_bool)
                == Some(true);
            if force_refresh {
                if let Some(refresh) = self
                    .a
                    .extra
                    .get("refreshToken")
                    .or_else(|| self.a.extra.get("refresh_token"))
                    .and_then(Value::as_str)
                    .or(self.a.refresh_token.as_deref())
                    .map(str::to_owned)
                {
                    let fresh = Self::refresh(c, x, &refresh)?;
                    token = Self::token(&fresh).context("refresh response omitted access token")?;
                    self.a
                        .extra
                        .insert("accessToken".into(), Value::String(token.clone()));
                    self.a.refresh_token = Some(Self::refresh_token(&fresh).unwrap_or(refresh));
                    self.a.extra.remove("refreshToken");
                    self.a.extra.remove("refresh_token");
                    self.t.push(Timing {
                        name: "openai_refresh".into(),
                        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                        extra: BTreeMap::new(),
                    });
                }
            }
            let mut r = match Self::usage(c, x, &token) {
                Ok(response) => response,
                Err(error) => {
                    self.t.push(Timing {
                        name: "openai_total".into(),
                        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                        extra: BTreeMap::new(),
                    });
                    return Ok(vec![Self::error_quota(sanitize_diagnostic(
                        &error.to_string(),
                    ))]);
                }
            };
            if r.status == 401 {
                let refresh = self
                    .a
                    .extra
                    .get("refreshToken")
                    .or_else(|| self.a.extra.get("refresh_token"))
                    .and_then(Value::as_str)
                    .or(self.a.refresh_token.as_deref())
                    .context("OpenAI session expired and no refresh token is stored")?;
                let fresh = Self::refresh(c, x, refresh)?;
                token = Self::token(&fresh).context("refresh response omitted access token")?;
                self.a
                    .extra
                    .insert("accessToken".into(), Value::String(token.clone()));
                if let Some(rotated) = Self::refresh_token(&fresh) {
                    self.a.refresh_token = Some(rotated);
                    self.a.extra.remove("refreshToken");
                    self.a.extra.remove("refresh_token");
                }
                r = match Self::usage(c, x, &token) {
                    Ok(response) => response,
                    Err(error) => {
                        self.t.push(Timing {
                            name: "openai_total".into(),
                            elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                            extra: BTreeMap::new(),
                        });
                        return Ok(vec![Self::error_quota(sanitize_diagnostic(
                            &error.to_string(),
                        ))]);
                    }
                };
            }
            if !(200..300).contains(&r.status) {
                self.t.push(Timing {
                    name: "openai_total".into(),
                    elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                    extra: BTreeMap::new(),
                });
                return Ok(vec![Self::error_quota(format!("HTTP {}", r.status))]);
            }
            self.t.push(Timing {
                name: "openai_usage".into(),
                elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                extra: BTreeMap::new(),
            });
            self.t.push(Timing {
                name: "openai_total".into(),
                elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                extra: BTreeMap::new(),
            });
            Ok(Self::parse_usage(&r.body))
        })
    }
    fn sort_key(&self, q: &Quota) -> (u8, u8, String) {
        (
            0,
            if q.display_name.contains("Primary") {
                0
            } else if q.display_name.contains("Secondary") {
                1
            } else {
                2
            },
            q.display_name.clone(),
        )
    }
    fn color(&self, _: &Quota) -> &'static str {
        "green"
    }
    fn timings(&self) -> Vec<Timing> {
        self.t.clone()
    }
}
