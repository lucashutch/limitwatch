use crate::{
    model::{Account, Quota},
    providers::{self, base::*},
};
use anyhow::Result;
use serde_json::Value;
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// Blocking transport whose clones share reqwest's thread-safe connection pool.
pub struct SharedHttp {
    client: Arc<reqwest::blocking::Client>,
    timings: Arc<Mutex<Vec<crate::model::Timing>>>,
}

impl Clone for SharedHttp {
    fn clone(&self) -> Self {
        Self {
            client: Arc::clone(&self.client),
            timings: Arc::new(Mutex::new(Vec::new())),
        }
    }
}

impl SharedHttp {
    pub fn new() -> Result<Self> {
        Ok(Self {
            client: Arc::new(reqwest::blocking::Client::builder().build()?),
            timings: Arc::new(Mutex::new(Vec::new())),
        })
    }

    pub fn timings(&self) -> Vec<crate::model::Timing> {
        self.timings.lock().expect("timing lock poisoned").clone()
    }

    #[doc(hidden)]
    pub fn pool_id(&self) -> usize {
        Arc::as_ptr(&self.client) as usize
    }
}

impl HttpClient for SharedHttp {
    fn execute(&self, r: HttpRequest) -> Result<HttpResponse> {
        let start = Instant::now();
        let method = r.method.to_owned();
        let mut q = self
            .client
            .request(r.method.parse()?, &r.url)
            .timeout(r.timeout);
        for (k, v) in r.headers {
            q = q.header(k, v);
        }
        if let Some(v) = r.body {
            q = q.json(&v);
        }
        let x = q.send()?;
        let status = x.status().as_u16();
        let headers = x
            .headers()
            .iter()
            .filter_map(|(k, v)| Some((k.as_str().to_owned(), v.to_str().ok()?.to_owned())))
            .collect();
        let body = x.json().unwrap_or(Value::Null);
        self.timings
            .lock()
            .expect("timing lock poisoned")
            .push(crate::model::Timing {
                name: "http_request".into(),
                elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                extra: [
                    ("method".into(), Value::String(method)),
                    ("status".into(), Value::from(status)),
                ]
                .into_iter()
                .collect(),
            });
        Ok(HttpResponse {
            status,
            headers,
            body,
        })
    }
}
pub struct QuotaClient {
    provider: Box<dyn Provider>,
}
impl QuotaClient {
    pub fn new(account: Account) -> Result<Self> {
        anyhow::ensure!(
            account.is_supported(),
            "unsupported provider: {}",
            account.provider_type
        );
        Ok(Self {
            provider: providers::create(account)?,
        })
    }
    pub async fn fetch(
        &mut self,
        http: &dyn HttpClient,
        process: &dyn ProcessRunner,
        ctx: &RequestContext,
    ) -> Result<Vec<Quota>> {
        self.provider.fetch(http, process, ctx).await
    }
    pub async fn login(
        &mut self,
        input: Value,
        http: &dyn HttpClient,
        process: &dyn ProcessRunner,
        ctx: &RequestContext,
    ) -> Result<Account> {
        self.provider.login(input, http, process, ctx).await
    }
    pub fn filter(&self, q: Vec<Quota>, all: bool) -> Vec<Quota> {
        self.provider.filter_quotas(q, all)
    }
    pub fn provider(&self) -> &dyn Provider {
        &*self.provider
    }
    pub fn account(&self) -> &Account {
        self.provider.account()
    }
}
