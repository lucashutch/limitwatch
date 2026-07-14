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
    time::{Duration, SystemTime, UNIX_EPOCH},
};
const USAGE: &str = "https://chatgpt.com/backend-api/wham/usage";
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
                let used = w.get("used_percent").and_then(Value::as_f64).unwrap_or(0.);
                let secs = w
                    .get("limit_window_seconds")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                let wl = if secs >= 86400 {
                    format!("{}d", secs / 86400)
                } else if secs >= 3600 {
                    format!("{}h", secs / 3600)
                } else {
                    format!("{}m", secs / 60)
                };
                let mut q = quota(
                    &format!("OpenAI Codex {label} ({plan})"),
                    &format!("{label} ({wl})"),
                    "OpenAI Codex",
                );
                q.used_pct = Some(used);
                q.remaining_pct = Some((100. - used).clamp(0., 100.));
                q.reset_time = w.get("reset_at").and_then(normalize_reset);
                out.push(q)
            }
        }
        if out.is_empty() {
            let mut q = quota(
                &format!("OpenAI Codex ({plan})"),
                &format!("Plan: {plan}"),
                "OpenAI Codex",
            );
            q.remaining_pct = Some(100.);
            out.push(q)
        }
        out
    }
    fn jwt(token: &str) -> Option<Value> {
        let part = token.split('.').nth(1)?;
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
        if i.get("accessToken").is_some() {
            return i.clone();
        }
        if a.extra.contains_key("accessToken") {
            return Value::Object(a.extra.clone().into_iter().collect());
        }
        let path = i
            .get("authFile")
            .and_then(Value::as_str)
            .map(PathBuf::from)
            .or_else(|| {
                std::env::var_os("CODEX_HOME")
                    .map(PathBuf::from)
                    .map(|p| p.join("auth.json"))
            })
            .or_else(|| dirs::home_dir().map(|p| p.join(".codex/auth.json")));
        path.and_then(|p| fs::read_to_string(p).ok())
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or(Value::Null)
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
                json!({"grant_type":"refresh_token","refresh_token":refresh,"client_id":"app_EMoamEEZ73f0CkXaXp7hrann"}),
            )?,
            "OpenAI token refresh",
        )?;
        Ok(r.body)
    }
    fn identity(token: &str) -> String {
        Self::jwt(token)
            .and_then(|v| {
                v.get("email")
                    .or_else(|| v.get("sub"))
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            })
            .unwrap_or_else(|| "OpenAI User".into())
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
                        json!({"client_id":"app_EMoamEEZ73f0CkXaXp7hrann"}),
                    )?,
                    "OpenAI device authorization",
                )?
                .body;
                let code = start["device_auth_id"]
                    .as_str()
                    .context("device authorization omitted id")?;
                let interval = start["interval"].as_u64().unwrap_or(1);
                loop {
                    x.remaining(Duration::from_secs(10))?;
                    let r = Self::post(
                        c,
                        x,
                        "https://auth.openai.com/api/accounts/deviceauth/token",
                        json!({"device_auth_id":code,"user_code":start["user_code"]}),
                    )?;
                    if r.status == 200 {
                        creds = r.body;
                        break;
                    }
                    if r.status != 400 && r.status != 404 {
                        bail!("OpenAI device login failed (HTTP {})", r.status)
                    }
                    thread::sleep(Duration::from_secs(interval.min(2)));
                }
            }
            let mut token = creds
                .get("accessToken")
                .or_else(|| creds.get("access_token"))
                .and_then(Value::as_str)
                .context("OpenAI credentials omitted access token")?
                .to_owned();
            if Self::expired(&token) {
                let refresh = creds
                    .get("refreshToken")
                    .or_else(|| creds.get("refresh_token"))
                    .and_then(Value::as_str)
                    .context("expired OpenAI token has no refresh token")?;
                let fresh = Self::refresh(c, x, refresh)?;
                token = fresh
                    .get("access_token")
                    .and_then(Value::as_str)
                    .context("refresh response omitted access token")?
                    .into();
                creds = fresh;
            }
            require_success(Self::usage(c, x, &token)?, "OpenAI token validation")?;
            let mut a = self.a.clone();
            a.email = Self::identity(&token);
            a.extra.insert("accessToken".into(), Value::String(token));
            if let Some(r) = creds
                .get("refresh_token")
                .or_else(|| creds.get("refreshToken"))
                .cloned()
            {
                a.extra.insert("refreshToken".into(), r);
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
            let mut token = self
                .a
                .extra
                .get("accessToken")
                .and_then(Value::as_str)
                .context("OpenAI credentials missing; log in to Codex")?
                .to_owned();
            let mut r = Self::usage(c, x, &token)?;
            if r.status == 401 {
                let refresh = self
                    .a
                    .extra
                    .get("refreshToken")
                    .and_then(Value::as_str)
                    .context("OpenAI session expired and no refresh token is stored")?;
                let fresh = Self::refresh(c, x, refresh)?;
                token = fresh["access_token"]
                    .as_str()
                    .context("refresh response omitted access token")?
                    .into();
                self.a
                    .extra
                    .insert("accessToken".into(), Value::String(token.clone()));
                if let Some(rotated) = fresh.get("refresh_token").cloned() {
                    self.a.extra.insert("refreshToken".into(), rotated);
                }
                r = Self::usage(c, x, &token)?;
            }
            let r = require_success(r, "OpenAI usage")?;
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
