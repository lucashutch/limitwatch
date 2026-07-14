use super::base::*;
use crate::model::{Account, Quota, Timing};
use anyhow::bail;
use serde_json::Value;
use std::time::Duration;
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
        let limit = d["total_credits"].as_f64().unwrap_or(0.);
        let used = d["total_usage"].as_f64().unwrap_or(0.);
        Self::build("OpenRouter Credits", limit, used, "credits")
    }
    fn build(name: &str, limit: f64, used: f64, ep: &str) -> Quota {
        let rem = (limit - used).max(0.);
        let mut q = quota(name, &format!("Credits: ${rem:.2} remaining"), "OpenRouter");
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
                .ok_or_else(|| anyhow::anyhow!("API key is required for OpenRouter login"))?;
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
            a.email = i["name"]
                .as_str()
                .or_else(|| r.body["data"]["label"].as_str())
                .unwrap_or("OpenRouter Key")
                .into();
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
            let Some(k) = &self.a.api_key else {
                return Ok(vec![]);
            };
            let h = bearer(k);
            let r = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://openrouter.ai/api/v1/credits".into(),
                    headers: h.clone(),
                    body: None,
                    timeout: Duration::from_secs(4),
                },
            )?;
            if r.status == 200 {
                return Ok(vec![Self::parse_credits(&r.body)]);
            }
            let r = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://openrouter.ai/api/v1/auth/key".into(),
                    headers: h,
                    body: None,
                    timeout: Duration::from_secs(4),
                },
            )?;
            if matches!(r.status, 401 | 403) {
                bail!("Unauthorized: Invalid OpenRouter API key")
            }
            if r.status != 200 {
                return Ok(vec![]);
            }
            let d = &r.body["data"];
            Ok(vec![Self::build(
                "OpenRouter Key",
                d["limit"].as_f64().unwrap_or(0.),
                d["usage"].as_f64().unwrap_or(0.),
                "auth/key",
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
