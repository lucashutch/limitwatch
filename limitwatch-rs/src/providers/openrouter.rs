use super::base::*;
use crate::model::{Account, Quota, Timing};
use anyhow::bail;
use serde_json::Value;
use std::time::{Duration, Instant};

fn number(value: &Value) -> f64 {
    value
        .as_f64()
        .or_else(|| value.as_str().and_then(|s| s.trim().parse().ok()))
        .unwrap_or(0.)
}
pub struct OpenRouterProvider {
    a: Account,
    t: Vec<Timing>,
}
impl OpenRouterProvider {
    pub fn new(a: Account) -> Self {
        Self { a, t: vec![] }
    }
    pub fn parse_credits(v: &Value) -> Quota {
        let d = &v["data"];
        let limit = number(&d["total_credits"]);
        let used = number(&d["total_usage"]);
        Self::build("OpenRouter Credits", limit, used, "credits", None)
    }
    /// OpenRouter uses a redacted key as the label when no dashboard name was
    /// assigned. It is not a useful (or safe) account identifier.
    pub fn is_redacted_key_label(label: &str) -> bool {
        label.trim().to_ascii_lowercase().starts_with("sk-or")
    }
    fn build(name: &str, limit: f64, used: f64, ep: &str, label: Option<&str>) -> Quota {
        let rem = (limit - used).max(0.);
        let display = if limit > 0. || ep == "credits" {
            format!("{}: ${rem:.2} remaining", label.unwrap_or("Credits"))
        } else {
            format!("{}: ${used:.2} spent", label.unwrap_or("Key"))
        };
        let mut q = quota(name, &display, "OpenRouter");
        q.limit = Some(limit);
        q.used = Some(used);
        q.remaining = Some(rem);
        q.remaining_pct = Some(if limit <= 0. {
            100.
        } else {
            rem / limit * 100.
        });
        extra(&mut q, "endpoint", ep);
        extra(&mut q, "show_progress", false);
        q
    }
}
impl Provider for OpenRouterProvider {
    fn account(&self) -> &Account {
        &self.a
    }
    fn provider_type(&self) -> &'static str {
        "openrouter"
    }
    fn provider_name(&self) -> &'static str {
        "OpenRouter"
    }
    fn source_priority(&self) -> u8 {
        0
    }
    fn primary_color(&self) -> &'static str {
        "cyan"
    }
    fn short_indicator(&self) -> char {
        'R'
    }
    fn login<'a>(
        &'a mut self,
        i: Value,
        c: &'a dyn HttpClient,
        _: &'a dyn ProcessRunner,
        x: &'a RequestContext,
    ) -> ProviderFuture<'a, Account> {
        Box::pin(async move {
            let k = i["apiKey"]
                .as_str()
                .or_else(|| i["api_key"].as_str())
                .or(self.a.api_key.as_deref())
                .ok_or_else(|| anyhow::anyhow!("API key is required for OpenRouter login"))?;
            let k = k.trim();
            if k.is_empty() {
                bail!("API key is required for OpenRouter login")
            }
            let r = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://openrouter.ai/api/v1/auth/key".into(),
                    headers: bearer(k),
                    body: None,
                    timeout: Duration::from_secs(10),
                },
            )?;
            if r.status != 200 {
                bail!("Invalid OpenRouter API key (HTTP {})", r.status)
            }
            let mut a = self.a.clone();
            a.api_key = Some(k.into());
            let name = i["name"]
                .as_str()
                .map(str::trim)
                .filter(|name| !name.is_empty());
            let label = r.body["data"]["label"]
                .as_str()
                .or_else(|| r.body["data"]["name"].as_str())
                .unwrap_or("OpenRouter Key");
            if let Some(name) = name {
                a.email = name.into();
            } else if Self::is_redacted_key_label(label) {
                a.email = "OpenRouter Key".into();
                // The CLI consumes this before persistence so that an API
                // label derived from a credential is never stored or printed.
                a.extra.insert(
                    "_limitwatch_openrouter_needs_name".into(),
                    Value::Bool(true),
                );
            } else {
                a.email = label.into();
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
            let Some(k) = self
                .a
                .api_key
                .as_deref()
                .or_else(|| self.a.extra.get("apiKey").and_then(Value::as_str))
                .or_else(|| self.a.extra.get("api_key").and_then(Value::as_str))
            else {
                return Ok(vec![]);
            };
            let h = bearer(k);
            let r = match checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://openrouter.ai/api/v1/credits".into(),
                    headers: h.clone(),
                    body: None,
                    timeout: Duration::from_secs(4),
                },
            ) {
                Ok(response) => response,
                Err(_) => {
                    // A management key can still be valid when the credits
                    // endpoint is unavailable; try the regular key endpoint.
                    HttpResponse {
                        status: 0,
                        headers: Default::default(),
                        body: Value::Null,
                    }
                }
            };
            if r.status == 200 {
                self.t.push(Timing {
                    name: "openrouter_credits".into(),
                    elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                    extra: Default::default(),
                });
                self.t.push(Timing {
                    name: "openrouter_total".into(),
                    elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                    extra: Default::default(),
                });
                return Ok(vec![Self::parse_credits(&r.body)]);
            }
            let r = match checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://openrouter.ai/api/v1/auth/key".into(),
                    headers: h,
                    body: None,
                    timeout: Duration::from_secs(4),
                },
            ) {
                Ok(response) => response,
                Err(_) => {
                    self.t.push(Timing {
                        name: "openrouter_total".into(),
                        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                        extra: Default::default(),
                    });
                    return Ok(vec![]);
                }
            };
            if matches!(r.status, 401 | 403) {
                self.t.push(Timing {
                    name: "openrouter_total".into(),
                    elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                    extra: Default::default(),
                });
                bail!("Unauthorized: Invalid OpenRouter API key")
            }
            if r.status != 200 {
                self.t.push(Timing {
                    name: "openrouter_total".into(),
                    elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                    extra: Default::default(),
                });
                return Ok(vec![]);
            }
            let d = &r.body["data"];
            let limit = d["limit"]
                .as_f64()
                .or_else(|| d["limit"].as_str().and_then(|v| v.parse().ok()));
            let usage = number(&d["usage"]);
            self.t.push(Timing {
                name: "openrouter_key".into(),
                elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                extra: Default::default(),
            });
            self.t.push(Timing {
                name: "openrouter_total".into(),
                elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                extra: Default::default(),
            });
            Ok(vec![Self::build(
                "OpenRouter Key",
                limit.unwrap_or(0.),
                usage,
                "auth/key",
                d["label"].as_str().or_else(|| d["name"].as_str()),
            )])
        })
    }
    fn sort_key(&self, q: &Quota) -> (u8, u8, String) {
        (0, 0, q.name.clone())
    }
    fn color(&self, q: &Quota) -> &'static str {
        match q.remaining_pct.unwrap_or(100.) {
            p if p >= 50. => "cyan",
            p if p >= 20. => "yellow",
            _ => "red",
        }
    }
    fn timings(&self) -> Vec<Timing> {
        self.t.clone()
    }
}
