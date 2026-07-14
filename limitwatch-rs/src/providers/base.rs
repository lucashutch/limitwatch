use crate::model::{Account, Quota, Timing};
use anyhow::{bail, Result};
use chrono::{DateTime, TimeZone, Utc};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

pub type ProviderFuture<'a, T> = Pin<Box<dyn Future<Output = Result<T>> + Send + 'a>>;

#[derive(Clone, Debug)]
pub struct HttpRequest {
    pub method: &'static str,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    pub body: Option<Value>,
    pub timeout: Duration,
}
#[derive(Clone, Debug)]
pub struct HttpResponse {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: Value,
}
pub trait HttpClient: Send + Sync {
    fn execute(&self, request: HttpRequest) -> Result<HttpResponse>;
}
pub trait ProcessRunner: Send + Sync {
    fn run(&self, program: &str, args: &[&str], timeout: Duration) -> Result<ProcessOutput>;
}
#[derive(Clone, Debug, Default)]
pub struct ProcessOutput {
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Clone, Default)]
pub struct CancellationToken(Arc<AtomicBool>);
impl CancellationToken {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::SeqCst)
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
}
#[derive(Clone, Default)]
pub struct RequestContext {
    pub deadline: Option<Instant>,
    pub cancellation: CancellationToken,
}
impl RequestContext {
    pub fn remaining(&self, cap: Duration) -> Result<Duration> {
        if self.cancellation.is_cancelled() {
            bail!("operation cancelled")
        };
        match self.deadline {
            Some(d) => {
                let left = d.checked_duration_since(Instant::now()).unwrap_or_default();
                if left.is_zero() {
                    bail!("deadline exceeded")
                }
                Ok(left.min(cap))
            }
            None => Ok(cap),
        }
    }
}
pub fn quota(name: &str, display: &str, source: &str) -> Quota {
    Quota {
        name: name.into(),
        display_name: display.into(),
        source_type: Some(source.into()),
        ..Default::default()
    }
}
pub fn extra(q: &mut Quota, key: &str, value: impl Into<Value>) {
    q.extra.insert(key.into(), value.into());
}
pub fn bearer(token: &str) -> BTreeMap<String, String> {
    BTreeMap::from([
        ("Authorization".into(), format!("Bearer {token}")),
        ("Content-Type".into(), "application/json".into()),
    ])
}
pub fn checked(
    client: &dyn HttpClient,
    ctx: &RequestContext,
    mut req: HttpRequest,
) -> Result<HttpResponse> {
    req.timeout = ctx.remaining(req.timeout)?;
    client.execute(req)
}

pub fn require_success(response: HttpResponse, operation: &str) -> Result<HttpResponse> {
    if (200..300).contains(&response.status) {
        Ok(response)
    } else if response.status == 429 {
        bail!("{operation} was rate limited; retry later")
    } else {
        bail!("{operation} failed (HTTP {})", response.status)
    }
}

/// Keep provider diagnostics useful without echoing request credentials or URLs.
/// Provider errors are user-facing and may include text returned by an HTTP
/// client or a local helper, so they must not be copied verbatim.
pub fn sanitize_diagnostic(value: &str) -> String {
    let mut words = value.split_whitespace().peekable();
    let mut sanitized = Vec::new();
    while let Some(word) = words.next() {
        let lower = word.to_ascii_lowercase();
        if lower == "bearer" || lower == "token" || lower == "password" {
            sanitized.push(word.to_owned());
            if words.peek().is_some() {
                words.next();
                sanitized.push("<redacted>".into());
            }
        } else if lower.starts_with("http://")
            || lower.starts_with("https://")
            || lower.contains("://")
        {
            sanitized.push("<redacted-url>".into())
        } else if lower.contains("secret") {
            sanitized.push("<redacted>".into())
        } else if [
            "token=",
            "access_token=",
            "refresh_token=",
            "api_key=",
            "apikey=",
            "key=",
            "authorization=",
        ]
        .iter()
        .any(|prefix| lower.starts_with(prefix))
        {
            sanitized.push(format!(
                "{}<redacted>",
                word.split('=').next().unwrap_or("value=")
            ));
        } else {
            sanitized.push(word.to_owned())
        }
    }
    sanitized.join(" ")
}

/// Canonical RFC3339 UTC representation for epoch seconds/milliseconds or RFC3339 input.
pub fn normalize_reset(value: &Value) -> Option<String> {
    let epoch = value
        .as_f64()
        .or_else(|| value.as_str().and_then(|s| s.trim().parse::<f64>().ok()));
    let parsed: DateTime<Utc> = if let Some(mut epoch) = epoch {
        if !epoch.is_finite() {
            return None;
        }
        if epoch.abs() > 10_000_000_000. {
            epoch /= 1000.;
        }
        let seconds = epoch.trunc() as i64;
        let nanos = ((epoch - seconds as f64) * 1_000_000_000.)
            .round()
            .clamp(0., 999_999_999.) as u32;
        Utc.timestamp_opt(seconds, nanos).single()?
    } else {
        DateTime::parse_from_rfc3339(value.as_str()?)
            .ok()?
            .with_timezone(&Utc)
    };
    Some(parsed.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
}

pub trait Provider: Send {
    fn account(&self) -> &Account;
    fn provider_type(&self) -> &'static str;
    fn provider_name(&self) -> &'static str;
    fn source_priority(&self) -> u8;
    fn primary_color(&self) -> &'static str;
    fn short_indicator(&self) -> char;
    fn login<'a>(
        &'a mut self,
        input: Value,
        client: &'a dyn HttpClient,
        process: &'a dyn ProcessRunner,
        ctx: &'a RequestContext,
    ) -> ProviderFuture<'a, Account>;
    fn fetch<'a>(
        &'a mut self,
        client: &'a dyn HttpClient,
        process: &'a dyn ProcessRunner,
        ctx: &'a RequestContext,
    ) -> ProviderFuture<'a, Vec<Quota>>;
    fn filter_quotas(&self, quotas: Vec<Quota>, _show_all: bool) -> Vec<Quota> {
        quotas
    }
    fn sort_key(&self, q: &Quota) -> (u8, u8, String);
    fn color(&self, q: &Quota) -> &'static str;
    fn timings(&self) -> Vec<Timing>;
}
