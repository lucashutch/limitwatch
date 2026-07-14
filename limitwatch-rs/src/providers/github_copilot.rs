use super::base::*;
use crate::model::{Account, Quota, Timing};
use anyhow::Context;
use chrono::{Datelike, Months, TimeZone, Utc};
use serde_json::Value;
use std::time::{Duration, Instant};

type BillingResult = (Option<(Value, &'static str, bool)>, Option<String>);

pub struct GitHubCopilotProvider {
    a: Account,
    t: Vec<Timing>,
}
impl GitHubCopilotProvider {
    pub fn new(a: Account) -> Self {
        Self { a, t: vec![] }
    }
    pub fn parse_billing(v: &Value, allowance: Option<f64>) -> Option<Quota> {
        fn walk(v: &Value, used: &mut f64, found: &mut bool) {
            match v {
                Value::Array(a) => a.iter().for_each(|x| walk(x, used, found)),
                Value::Object(o) => {
                    let text = [
                        "product",
                        "productName",
                        "sku",
                        "skuName",
                        "meter",
                        "description",
                        "usageType",
                    ]
                    .iter()
                    .filter_map(|k| o.get(*k).and_then(Value::as_str))
                    .collect::<Vec<_>>()
                    .join(" ")
                    .to_lowercase();
                    if text.contains("copilot")
                        && (text.contains("premium request") || text.contains("ai credit"))
                    {
                        *found = true;
                        let quantity = [
                            "grossQuantity",
                            "gross_quantity",
                            "netQuantity",
                            "net_quantity",
                        ]
                        .iter()
                        .find_map(|k| o.get(*k).and_then(Value::as_f64));
                        let amount = ["netAmount", "net_amount"]
                            .iter()
                            .find_map(|k| o.get(*k).and_then(Value::as_f64))
                            .map(|n| n / 0.01);
                        let fallback = ["quantity", "usageQuantity", "amount"]
                            .iter()
                            .find_map(|k| o.get(*k).and_then(Value::as_f64));
                        *used += quantity.or(amount).or(fallback).unwrap_or(0.);
                    }
                    for key in [
                        "usageItems",
                        "items",
                        "usage",
                        "summary",
                        "products",
                        "lineItems",
                    ] {
                        if let Some(child) = o.get(key) {
                            walk(child, used, found);
                        }
                    }
                }
                _ => {}
            }
        }
        let (mut used, mut found) = (0., false);
        walk(v, &mut used, &mut found);
        if !found {
            return None;
        }
        let allowance = allowance.or_else(|| {
            v.pointer("/copilot/premium_requests/entitlement")
                .and_then(Value::as_f64)
        });
        let mut q = quota(
            "GitHub Copilot AI Credits",
            "Personal AI Credits",
            "GitHub Copilot",
        );
        q.used = Some(used);
        if let Some(limit) = allowance.filter(|x| *x > 0.) {
            q.limit = Some(limit);
            q.remaining = Some(limit - used);
            q.used_pct = Some(used / limit * 100.);
            q.remaining_pct = Some(100. - q.used_pct.unwrap());
        } else {
            q.remaining_pct = Some(100.);
            extra(&mut q, "show_progress", false);
        }
        if let Some(r) = v
            .get("reset_at")
            .or_else(|| v.get("resetDate"))
            .and_then(normalize_reset)
        {
            q.reset_time = Some(r);
        }
        Some(q)
    }
    pub fn discover_gh_accounts(p: &dyn ProcessRunner, x: &RequestContext) -> Vec<String> {
        let Ok(output) = p.run(
            "gh",
            &["auth", "status"],
            x.remaining(Duration::from_secs(6)).unwrap_or_default(),
        ) else {
            return vec![];
        };
        output
            .stdout
            .lines()
            .filter_map(|line| {
                let (_, tail) = line.split_once("Logged in to github.com account ")?;
                tail.split_whitespace()
                    .next()
                    .map(|s| s.trim_end_matches('(').to_owned())
            })
            .collect()
    }
    fn month() -> (i32, u32) {
        let n = Utc::now();
        (n.year(), n.month())
    }
    fn reset() -> String {
        let n = Utc::now();
        Utc.with_ymd_and_hms(n.year(), n.month(), 1, 0, 0, 0)
            .unwrap()
            .checked_add_months(Months::new(1))
            .unwrap()
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    }
    fn plan_allowance(v: Option<&Value>) -> Option<f64> {
        let p = v
            .and_then(|v| {
                ["copilot_plan", "plan", "plan_type", "sku", "subscription"]
                    .iter()
                    .find_map(|k| v.get(*k).and_then(Value::as_str))
            })?
            .to_lowercase()
            .replace(' ', "_");
        Some(if p.contains("max") {
            20000.
        } else if p.contains("pro+") || p.contains("pro_plus") {
            7000.
        } else if p.contains("pro") || p == "individual" {
            1500.
        } else {
            return None;
        })
    }
    fn org_allowance(seats: Option<i64>, plan: Option<&str>) -> Option<f64> {
        let s = seats.filter(|x| *x > 0)? as f64;
        let p = plan?.to_lowercase();
        let promo = Utc::now() >= Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap()
            && Utc::now() < Utc.with_ymd_and_hms(2026, 9, 1, 0, 0, 0).unwrap();
        Some(
            s * if p.contains("enterprise") {
                if promo {
                    7000.
                } else {
                    3900.
                }
            } else if p.contains("business") {
                if promo {
                    3000.
                } else {
                    1900.
                }
            } else {
                return None;
            },
        )
    }
    fn parse_internal_org(v: &Value, organization: &str) -> Option<Quota> {
        let matches_org = v
            .get("organization_login_list")?
            .as_array()?
            .iter()
            .filter_map(Value::as_str)
            .any(|org| org.eq_ignore_ascii_case(organization));
        if !matches_org {
            return None;
        }
        let premium = v.pointer("/quota_snapshots/premium_interactions")?;
        let entitlement = premium.get("entitlement")?.as_f64()?;
        let remaining = premium.get("remaining")?.as_f64()?;
        if !entitlement.is_finite() || !remaining.is_finite() || entitlement <= 0.0 {
            return None;
        }
        let used = premium
            .get("used")
            .and_then(Value::as_f64)
            .filter(|n| n.is_finite())
            .unwrap_or_else(|| (entitlement - remaining).max(0.0));
        let mut q = quota(
            &format!("GitHub Copilot Org ({organization})"),
            organization,
            "GitHub Copilot",
        );
        q.limit = Some(entitlement);
        q.remaining = Some(remaining);
        q.used = Some(used);
        q.used_pct = Some(used / entitlement * 100.0);
        q.remaining_pct = Some(100.0 - q.used_pct.unwrap());
        q.reset_time = Some(v.get("quota_reset_date")?.as_str()?.into());
        extra(&mut q, "billing_model", "ai_credits");
        Some(q)
    }
    fn billing(
        c: &dyn HttpClient,
        x: &RequestContext,
        token: &str,
        owner: &str,
        org: bool,
        traces: &mut Vec<Timing>,
    ) -> anyhow::Result<BillingResult> {
        let (y, m) = Self::month();
        let root = if org {
            format!("organizations/{owner}")
        } else {
            format!("users/{owner}")
        };
        let base = format!("https://api.github.com/{root}/settings/billing/usage");
        let (mut usage, mut empty, mut diagnostic) = (None, None, None);
        for (url, source) in [(format!("{base}/summary"), "summary"), (base, "usage")] {
            for filtered in [true, false] {
                let q = if filtered {
                    format!("year={y}&month={m}&product=copilot&sku=copilot_ai_credits")
                } else {
                    format!("year={y}&month={m}")
                };
                let r = Self::traced_request(c, x, format!("{url}?{q}"), token, traces)?;
                if r.status != 200 {
                    diagnostic.get_or_insert_with(|| {
                        Self::billing_diagnostic(
                            r.status,
                            r.body.get("message").and_then(Value::as_str),
                        )
                    });
                    continue;
                }
                if Self::parse_billing(&r.body, None).is_some() {
                    usage = Some((r.body, source, filtered));
                } else {
                    empty = Some((r.body, source, filtered));
                }
            }
        }
        let result = usage.or(empty);
        if result.is_some() {
            diagnostic = None;
        }
        Ok((result, diagnostic))
    }
    fn billing_diagnostic(status: u16, detail: Option<&str>) -> String {
        let detail = detail
            .map(|s| s.split_whitespace().collect::<Vec<_>>().join(" "))
            .filter(|s| !s.is_empty())
            .map(|s| s.chars().take(160).collect::<String>());
        format!(
            "GitHub billing unavailable (HTTP {status}): {}. Check billing access, rate limits, and organization SSO authorization.",
            detail.as_deref().unwrap_or("GitHub returned no usable error details")
        )
    }
    pub fn gh_token(
        p: &dyn ProcessRunner,
        user: Option<&str>,
        x: &RequestContext,
    ) -> anyhow::Result<Option<String>> {
        let args = user.map_or_else(
            || vec!["auth", "token"],
            |u| vec!["auth", "token", "--user", u],
        );
        let output = p.run("gh", &args, x.remaining(Duration::from_secs(6))?)?;
        if !output.success {
            let diagnostic = output.stderr.lines().next().unwrap_or("unknown error");
            let diagnostic: String = diagnostic.chars().take(200).collect();
            anyhow::bail!("`gh auth token` failed: {diagnostic}")
        }
        Ok(Some(output.stdout.trim().to_owned()).filter(|s| !s.is_empty()))
    }
    pub fn discover_organizations(
        c: &dyn HttpClient,
        token: &str,
        x: &RequestContext,
    ) -> anyhow::Result<Vec<String>> {
        let response = Self::request(
            c,
            x,
            "https://api.github.com/user/orgs?per_page=100".into(),
            token,
        )?;
        if response.status != 200 {
            return Ok(vec![]);
        }
        let mut orgs = response
            .body
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|o| o.get("login").and_then(Value::as_str).map(str::to_owned))
            .collect::<Vec<_>>();
        orgs.sort();
        Ok(orgs)
    }
    fn request(
        c: &dyn HttpClient,
        x: &RequestContext,
        url: String,
        token: &str,
    ) -> anyhow::Result<HttpResponse> {
        let mut headers = bearer(token);
        headers.insert("Accept".into(), "application/vnd.github+json".into());
        headers.insert("X-GitHub-Api-Version".into(), "2026-03-10".into());
        headers.insert("User-Agent".into(), "limitwatch".into());
        checked(
            c,
            x,
            HttpRequest {
                method: "GET",
                url,
                headers,
                body: None,
                timeout: Duration::from_secs(10),
            },
        )
    }
    fn traced_request(
        c: &dyn HttpClient,
        x: &RequestContext,
        url: String,
        token: &str,
        traces: &mut Vec<Timing>,
    ) -> anyhow::Result<HttpResponse> {
        let raw = url
            .split('?')
            .next()
            .unwrap_or(&url)
            .strip_prefix("https://api.github.com")
            .unwrap_or("/<redacted>");
        let parts = raw.split('/').collect::<Vec<_>>();
        let path = if parts.len() > 3 && matches!(parts[1], "users" | "organizations" | "orgs") {
            format!("/{}/<redacted>/{}", parts[1], parts[3..].join("/"))
        } else {
            raw.into()
        };
        let start = Instant::now();
        let response = Self::request(c, x, url, token);
        let mut extra = std::collections::BTreeMap::new();
        extra.insert("method".into(), Value::String("GET".into()));
        extra.insert("path".into(), Value::String(path));
        match &response {
            Ok(response) => {
                extra.insert("status".into(), Value::from(response.status));
                extra.insert("outcome".into(), Value::String("response".into()));
            }
            Err(_) => {
                // Do not copy transport errors: they can contain URLs and proxy details.
                extra.insert("outcome".into(), Value::String("transport_error".into()));
            }
        }
        traces.push(Timing {
            name: "github_request".into(),
            elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
            extra,
        });
        response
    }
}
impl Provider for GitHubCopilotProvider {
    fn account(&self) -> &Account {
        &self.a
    }
    fn provider_type(&self) -> &'static str {
        "github_copilot"
    }
    fn provider_name(&self) -> &'static str {
        "GitHub Copilot"
    }
    fn source_priority(&self) -> u8 {
        2
    }
    fn primary_color(&self) -> &'static str {
        "white"
    }
    fn short_indicator(&self) -> char {
        'H'
    }
    fn login<'a>(
        &'a mut self,
        i: Value,
        c: &'a dyn HttpClient,
        p: &'a dyn ProcessRunner,
        x: &'a RequestContext,
    ) -> ProviderFuture<'a, Account> {
        Box::pin(async move {
            let requested_account = i.get("github_account").and_then(Value::as_str);
            let supplied = i
                .get("githubToken")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_owned);
            let token = match supplied {
                Some(token) => token,
                None => Self::gh_token(p, requested_account, x)?
                    .context("GitHub token required: pass githubToken or run `gh auth login`")?,
            };
            let start = Instant::now();
            let r = Self::request(c, x, "https://api.github.com/user".into(), &token)?;
            if !(200..300).contains(&r.status) {
                let message = r
                    .body
                    .get("message")
                    .and_then(Value::as_str)
                    .map(|s| s.chars().take(200).collect::<String>());
                let hint = if r.status == 403 {
                    " Check token scopes, rate limits, and organization SSO authorization."
                } else {
                    ""
                };
                anyhow::bail!(
                    "GitHub token validation failed (HTTP {}): {}{}",
                    r.status,
                    message
                        .as_deref()
                        .unwrap_or("GitHub returned no usable error details"),
                    hint
                );
            }
            let login = r
                .body
                .get("login")
                .and_then(Value::as_str)
                .context("GitHub user response omitted login")?;
            if let Some(selected) = requested_account {
                if !login.eq_ignore_ascii_case(selected) {
                    anyhow::bail!("GitHub token identity mismatch: selected account `{selected}` but token belongs to `{login}`");
                }
            }
            let mut a = self.a.clone();
            a.email = login.into();
            a.extra
                .insert("github_account".into(), Value::String(login.into()));
            a.extra.insert("githubToken".into(), Value::String(token));
            if let Some(user) = requested_account {
                a.extra
                    .insert("github_selected_account".into(), Value::String(user.into()));
            }
            if i.get("token_source").and_then(Value::as_str) == Some("gh_cli") {
                a.extra
                    .insert("githubAuthSource".into(), Value::String("gh_cli".into()));
            }
            if let Some(org) = i
                .get("organization")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
            {
                a.extra
                    .insert("organization".into(), Value::String(org.into()));
            }
            self.t.push(Timing {
                name: "github_identity".into(),
                elapsed_ms: start.elapsed().as_secs_f64() * 1000.,
                extra: Default::default(),
            });
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
            let token = self
                .a
                .extra
                .get("githubToken")
                .and_then(Value::as_str)
                .context("GitHub token missing; log in with GitHub Copilot")?;
            let owner = self.a.identity();
            let mut out = vec![];
            // This endpoint is independent of billing and is intentionally fetched once.
            let internal = Self::traced_request(
                c,
                x,
                "https://api.github.com/copilot_internal/user".into(),
                token,
                &mut self.t,
            )
            .ok()
            .filter(|r| r.status == 200);
            if let Some(org) = self.a.extra.get("organization").and_then(Value::as_str) {
                if let Some(q) = internal
                    .as_ref()
                    .and_then(|response| Self::parse_internal_org(&response.body, org))
                {
                    let mut extra = std::collections::BTreeMap::new();
                    extra.insert(
                        "outcome".into(),
                        Value::String("internal snapshot selected".into()),
                    );
                    self.t.push(Timing {
                        name: "github_selection".into(),
                        elapsed_ms: 0.0,
                        extra,
                    });
                    return Ok(vec![q]);
                }
            }
            let (personal_usage, _) = Self::billing(c, x, token, owner, false, &mut self.t)?;
            if let Some((body, source, filtered)) = personal_usage {
                let mut q = Self::parse_billing(&body, None).unwrap_or_else(|| {
                    let mut q = quota("GitHub Copilot Personal", "Personal", "GitHub Copilot");
                    q.used = Some(0.);
                    q.remaining_pct = Some(100.);
                    q.used_pct = Some(0.);
                    extra(&mut q, "show_progress", false);
                    q
                });
                if let Some(limit) = Self::plan_allowance(internal.as_ref().map(|r| &r.body).or(
                    Some(&Value::Object(self.a.extra.clone().into_iter().collect())),
                )) {
                    q.limit = Some(limit);
                    q.remaining = Some(limit - q.used.unwrap_or(0.));
                    q.used_pct = Some(q.used.unwrap_or(0.) / limit * 100.);
                    q.remaining_pct = Some(100. - q.used_pct.unwrap());
                }
                q.reset_time = Some(Self::reset());
                extra(&mut q, "billing_source", source);
                extra(&mut q, "billing_filtered", filtered);
                extra(&mut q, "billing_model", "ai_credits");
                out.push(q);
            } else if !self.a.extra.contains_key("organization") {
                let mut q = quota("GitHub Copilot Personal", "Personal", "GitHub Copilot");
                q.remaining_pct = Some(100.);
                q.used_pct = Some(0.);
                q.reset_time = Some("Monthly".into());
                out.push(q);
            }
            if let Some(org) = self.a.extra.get("organization").and_then(Value::as_str) {
                let mut trace_extra = std::collections::BTreeMap::new();
                trace_extra.insert(
                    "outcome".into(),
                    Value::String("internal unavailable; billing fallback".into()),
                );
                self.t.push(Timing {
                    name: "github_selection".into(),
                    elapsed_ms: 0.0,
                    extra: trace_extra,
                });
                let (usage, billing_error) = Self::billing(c, x, token, org, true, &mut self.t)?;
                if let Some((body, source, filtered)) = usage {
                    let bill = Self::request(
                        c,
                        x,
                        format!("https://api.github.com/orgs/{org}/copilot/billing"),
                        token,
                    )
                    .ok()
                    .filter(|response| response.status == 200);
                    let seats = bill
                        .as_ref()
                        .and_then(|response| response.body.pointer("/seat_breakdown/total"))
                        .and_then(Value::as_i64);
                    let plan = bill
                        .as_ref()
                        .and_then(|response| {
                            response
                                .body
                                .get("plan_type")
                                .or_else(|| response.body.get("plan"))
                        })
                        .and_then(Value::as_str);
                    let allowance = Self::org_allowance(seats, plan);
                    let mut q = Self::parse_billing(&body, allowance).unwrap_or_else(|| {
                        let mut q = quota("", "", "GitHub Copilot");
                        q.used = Some(0.);
                        q
                    });
                    q.name = format!("GitHub Copilot Org ({org})");
                    q.display_name = org.into();
                    q.reset_time = Some(Self::reset());
                    extra(&mut q, "billing_source", source);
                    extra(&mut q, "billing_filtered", filtered);
                    extra(&mut q, "billing_model", "ai_credits");
                    out.push(q);
                } else {
                    let mut q = quota(
                        &format!("GitHub Copilot Org ({org})"),
                        org,
                        "GitHub Copilot",
                    );
                    extra(&mut q, "is_error", true);
                    extra(
                        &mut q,
                        "message",
                        billing_error
                            .as_deref()
                            .unwrap_or("Could not fetch AI credits billing usage for this org"),
                    );
                    out.push(q);
                }
            }
            Ok(out)
        })
    }
    fn sort_key(&self, q: &Quota) -> (u8, u8, String) {
        (
            0,
            u8::from(!q.display_name.contains("Personal")),
            q.display_name.clone(),
        )
    }
    fn color(&self, _: &Quota) -> &'static str {
        "white"
    }
    fn timings(&self) -> Vec<Timing> {
        self.t.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::Result;
    use serde_json::json;
    use std::sync::Mutex;

    struct Http(Mutex<Vec<HttpRequest>>);
    impl HttpClient for Http {
        fn execute(&self, request: HttpRequest) -> Result<HttpResponse> {
            let body = if request.url == "https://api.github.com/user" {
                json!({"login":"work"})
            } else {
                json!([])
            };
            self.0.lock().unwrap().push(request);
            Ok(HttpResponse {
                status: 200,
                body,
                headers: Default::default(),
            })
        }
    }

    #[test]
    fn traced_request_records_sanitized_success_and_failure_elapsed_time() {
        struct Failing;
        impl HttpClient for Failing {
            fn execute(&self, _: HttpRequest) -> Result<HttpResponse> {
                std::thread::sleep(Duration::from_millis(2));
                anyhow::bail!("secret proxy URL https://user:password@example.test")
            }
        }
        let mut traces = vec![];
        let result = GitHubCopilotProvider::traced_request(
            &Failing,
            &RequestContext::default(),
            "https://api.github.com/organizations/private-org/settings/billing/usage?token=secret"
                .into(),
            "secret-token",
            &mut traces,
        );
        assert!(result.is_err());
        assert_eq!(traces.len(), 1);
        assert!(traces[0].elapsed_ms >= 1.0);
        assert_eq!(
            traces[0].extra["path"],
            "/organizations/<redacted>/settings/billing/usage"
        );
        assert_eq!(traces[0].extra["outcome"], "transport_error");
        let serialized = serde_json::to_string(&traces[0].extra).unwrap();
        for secret in ["private-org", "secret", "password", "example.test"] {
            assert!(!serialized.contains(secret));
        }
    }

    #[test]
    fn billing_uses_exact_month_urls_and_github_headers() {
        let http = Http(Mutex::new(vec![]));
        let ctx = RequestContext::default();
        GitHubCopilotProvider::billing(&http, &ctx, "secret", "octo", false, &mut vec![]).unwrap();
        let requests = http.0.lock().unwrap();
        let (year, month) = GitHubCopilotProvider::month();
        assert_eq!(requests.len(), 4);
        assert_eq!(requests[0].url, format!("https://api.github.com/users/octo/settings/billing/usage/summary?year={year}&month={month}&product=copilot&sku=copilot_ai_credits"));
        assert_eq!(requests[1].url, format!("https://api.github.com/users/octo/settings/billing/usage/summary?year={year}&month={month}"));
        assert_eq!(requests[0].headers["Accept"], "application/vnd.github+json");
        assert_eq!(requests[0].headers["X-GitHub-Api-Version"], "2026-03-10");
        assert_eq!(requests[0].headers["Authorization"], "Bearer secret");
    }

    #[test]
    fn login_persists_selected_user_and_organization() {
        struct Proc;
        impl ProcessRunner for Proc {
            fn run(&self, _: &str, _: &[&str], _: Duration) -> Result<ProcessOutput> {
                unreachable!()
            }
        }
        let http = Http(Mutex::new(vec![]));
        let mut provider = GitHubCopilotProvider::new(Account::default());
        let account = futures::executor::block_on(provider.login(
            json!({"githubToken":"secret","github_account":"work","organization":"acme"}),
            &http,
            &Proc,
            &RequestContext::default(),
        ))
        .unwrap();
        assert_eq!(account.extra["github_account"], "work");
        assert_eq!(account.extra["organization"], "acme");
        assert_eq!(account.extra["githubToken"], "secret");
    }

    #[test]
    fn gh_token_reports_failure_and_empty_output_deterministically() {
        struct Proc(ProcessOutput);
        impl ProcessRunner for Proc {
            fn run(&self, _: &str, _: &[&str], _: Duration) -> Result<ProcessOutput> {
                Ok(self.0.clone())
            }
        }
        let ctx = RequestContext::default();
        let error = GitHubCopilotProvider::gh_token(
            &Proc(ProcessOutput {
                success: false,
                stdout: String::new(),
                stderr: "SSO required\nsecret detail".into(),
            }),
            Some("work"),
            &ctx,
        )
        .unwrap_err();
        assert_eq!(error.to_string(), "`gh auth token` failed: SSO required");
        assert_eq!(
            GitHubCopilotProvider::gh_token(
                &Proc(ProcessOutput {
                    success: true,
                    stdout: String::new(),
                    stderr: "warning only".into()
                }),
                None,
                &ctx
            )
            .unwrap(),
            None
        );
    }

    #[test]
    fn billing_diagnostic_is_actionable_bounded_and_handles_non_json() {
        let message = "x".repeat(300);
        let diagnostic = GitHubCopilotProvider::billing_diagnostic(403, Some(&message));
        assert!(diagnostic.contains(&"x".repeat(160)));
        assert!(!diagnostic.contains(&"x".repeat(161)));
        assert!(diagnostic.contains("rate limits"));
        assert!(GitHubCopilotProvider::billing_diagnostic(403, None)
            .contains("no usable error details"));
    }
}
