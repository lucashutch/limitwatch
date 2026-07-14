use super::base::*;
use crate::model::{Account, Quota, Timing};
use anyhow::bail;
use serde_json::Value;
use std::time::Duration;
pub struct ChutesProvider {
    account: Account,
    t: Vec<Timing>,
}
impl ChutesProvider {
    pub fn new(account: Account) -> Self {
        Self { account, t: vec![] }
    }
    pub fn parse_usage(v: &Value, reset: &str) -> Option<Quota> {
        let limit = v.get("quota").or_else(|| v.get("limit"))?.as_f64()?;
        if limit <= 0. {
            return None;
        }
        let used = v["used"].as_f64().unwrap_or(0.);
        let id = v["chute_id"].as_str().unwrap_or("*");
        let mut q = quota(
            &format!("Chutes Quota ({id})"),
            &format!("Quota ({}/{})", limit - used, limit),
            "Chutes",
        );
        q.limit = Some(limit);
        q.used = Some(used);
        q.remaining = Some(limit - used);
        q.remaining_pct = Some(((limit - used) / limit * 100.).max(0.));
        q.reset_time = Some(reset.into());
        Some(q)
    }
}
impl Provider for ChutesProvider {
    fn account(&self) -> &Account {
        &self.account
    }
    fn provider_type(&self) -> &'static str {
        "chutes"
    }
    fn provider_name(&self) -> &'static str {
        "Chutes"
    }
    fn source_priority(&self) -> u8 {
        0
    }
    fn primary_color(&self) -> &'static str {
        "yellow"
    }
    fn short_indicator(&self) -> char {
        'C'
    }
    fn login<'a>(
        &'a mut self,
        i: Value,
        c: &'a dyn HttpClient,
        _: &'a dyn ProcessRunner,
        x: &'a RequestContext,
    ) -> ProviderFuture<'a, Account> {
        Box::pin(async move {
            let key = i["apiKey"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("API key is required for Chutes.ai login"))?;
            let r = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://api.chutes.ai/users/me".into(),
                    headers: std::collections::BTreeMap::from([(
                        "Authorization".into(),
                        key.into(),
                    )]),
                    body: None,
                    timeout: Duration::from_secs(10),
                },
            )?;
            if r.status != 200 {
                bail!("Failed to authenticate with Chutes.ai (HTTP {})", r.status)
            }
            let mut a = self.account.clone();
            a.api_key = Some(key.into());
            a.email = r
                .body
                .get("email")
                .or_else(|| r.body.get("username"))
                .and_then(Value::as_str)
                .unwrap_or("Chutes User")
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
            let Some(k) = &self.account.api_key else {
                return Ok(vec![]);
            };
            let h = std::collections::BTreeMap::from([("Authorization".into(), k.clone())]);
            let me = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://api.chutes.ai/users/me".into(),
                    headers: h.clone(),
                    body: None,
                    timeout: Duration::from_secs(3),
                },
            )?;
            if matches!(me.status, 401 | 403) {
                bail!("Unauthorized: Invalid Chutes.ai API key")
            }
            let mut out = vec![];
            if let Some(b) = me.body["balance"].as_f64().filter(|b| *b > 0.) {
                let mut q = quota("Chutes Credits", &format!("Credits: ${b:.2}"), "Chutes");
                q.remaining_pct = Some(100.);
                extra(&mut q, "show_progress", false);
                out.push(q)
            }
            let u = checked(
                c,
                x,
                HttpRequest {
                    method: "GET",
                    url: "https://api.chutes.ai/users/me/quota_usage/me".into(),
                    headers: h,
                    body: None,
                    timeout: Duration::from_secs(3),
                },
            )?;
            if u.status == 200 {
                if let Some(q) = Self::parse_usage(&u.body, "Daily") {
                    out.push(q)
                }
            }
            Ok(out)
        })
    }
    fn sort_key(&self, q: &Quota) -> (u8, u8, String) {
        (u8::from(!q.name.contains("Credits")), 0, q.name.clone())
    }
    fn color(&self, _: &Quota) -> &'static str {
        "yellow"
    }
    fn timings(&self) -> Vec<Timing> {
        self.t.clone()
    }
}
