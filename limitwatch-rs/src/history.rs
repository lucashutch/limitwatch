use crate::model::Quota;
use crate::storage::{
    Aggregation, CreditConsumption, DailyActivity, HistoryFilter, Snapshot, Storage,
};
use anyhow::{anyhow, Result};
use chrono::{DateTime, Duration, Utc};
use std::collections::BTreeSet;
use std::path::Path;

pub struct HistoryManager {
    pub storage: Storage,
}
pub struct DatabaseInfo {
    pub path: String,
    pub oldest_record: Option<String>,
    pub newest_record: Option<String>,
    pub accounts: Vec<String>,
    pub providers: Vec<String>,
}
pub struct WeeklyActivity {
    pub daily_per_account: Vec<DailyActivity>,
    pub daily_totals: Vec<CreditConsumption>,
    pub accounts: Vec<String>,
    pub days: Vec<String>,
    pub dates: Vec<String>,
    pub date_range: (Option<String>, Option<String>),
}
impl HistoryManager {
    pub fn new(path: Option<impl AsRef<Path>>) -> Result<Self> {
        Ok(Self {
            storage: Storage::new(path)?,
        })
    }
    pub fn record_quotas(
        &self,
        a: &str,
        p: &str,
        q: &[Quota],
        t: Option<DateTime<Utc>>,
    ) -> Result<usize> {
        self.storage.record_quotas(a, p, q, t)
    }
    pub fn parse_time_preset(value: &str) -> Option<DateTime<Utc>> {
        let d = match value {
            "24h" => Duration::hours(24),
            "7d" => Duration::days(7),
            "30d" => Duration::days(30),
            "90d" => Duration::days(90),
            _ => return None,
        };
        Some(Utc::now() - d)
    }
    pub fn parse_datetime(value: &str) -> Option<DateTime<Utc>> {
        DateTime::parse_from_rfc3339(&value.replace('Z', "+00:00"))
            .ok()
            .map(|x| x.with_timezone(&Utc))
            .or_else(|| {
                let (n, s) = value.split_at(value.len().checked_sub(1)?);
                let n = n.parse::<i64>().ok()?;
                match s {
                    "d" => Some(Utc::now() - Duration::days(n)),
                    "h" => Some(Utc::now() - Duration::hours(n)),
                    _ => None,
                }
            })
    }
    fn filter(
        preset: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
        account: Option<&str>,
        provider: Option<&str>,
        quota: Option<&str>,
    ) -> HistoryFilter {
        HistoryFilter {
            since: preset
                .and_then(Self::parse_time_preset)
                .or_else(|| since.and_then(Self::parse_datetime)),
            until: until.and_then(Self::parse_datetime),
            account_email: account.map(str::to_owned),
            provider_type: provider.map(str::to_owned),
            quota_name: quota.map(str::to_owned),
        }
    }
    pub fn get_history(
        &self,
        p: Option<&str>,
        s: Option<&str>,
        u: Option<&str>,
        a: Option<&str>,
        provider: Option<&str>,
        q: Option<&str>,
    ) -> Result<Vec<Snapshot>> {
        self.storage
            .query_history(&Self::filter(p, s, u, a, provider, q))
    }
    pub fn get_aggregation(
        &self,
        p: Option<&str>,
        s: Option<&str>,
        u: Option<&str>,
        a: Option<&str>,
        provider: Option<&str>,
    ) -> Result<Vec<Aggregation>> {
        self.storage
            .get_aggregation(&Self::filter(p, s, u, a, provider, None))
    }
    pub fn get_time_series(
        &self,
        q: &str,
        a: Option<&str>,
        p: Option<&str>,
        s: Option<&str>,
    ) -> Result<Vec<(DateTime<Utc>, f64)>> {
        let mut v = self
            .get_history(p, s, None, a, None, Some(q))?
            .into_iter()
            .filter_map(|x| {
                Some((
                    DateTime::parse_from_rfc3339(&x.timestamp)
                        .ok()?
                        .with_timezone(&Utc),
                    x.remaining_pct?,
                ))
            })
            .collect::<Vec<_>>();
        v.sort_by_key(|x| x.0);
        Ok(v)
    }
    pub fn get_available_filters(&self) -> Result<(Vec<String>, Vec<String>)> {
        let providers = self
            .storage
            .get_distinct_providers()?
            .into_iter()
            .filter(|p| p != "google")
            .collect();
        Ok((self.storage.get_distinct_accounts()?, providers))
    }
    pub fn get_database_info(&self) -> Result<DatabaseInfo> {
        let (a, b) = self.storage.get_time_range()?;
        Ok(DatabaseInfo {
            path: self.storage.db_path.display().to_string(),
            oldest_record: a,
            newest_record: b,
            accounts: self.storage.get_distinct_accounts()?,
            providers: self
                .storage
                .get_distinct_providers()?
                .into_iter()
                .filter(|p| p != "google")
                .collect(),
        })
    }
    pub fn purge_data(&self, before: &str) -> Result<usize> {
        self.storage.purge_old_data(
            Self::parse_datetime(before).ok_or_else(|| anyhow!("Invalid date format: {before}"))?,
        )
    }
    pub fn get_weekly_activity(&self, a: Option<&str>, p: Option<&str>) -> Result<WeeklyActivity> {
        let since = Utc::now() - Duration::days(7);
        let f = HistoryFilter {
            since: Some(since),
            account_email: a.map(str::to_owned),
            provider_type: p.map(str::to_owned),
            ..Default::default()
        };
        let daily = self.storage.get_daily_activity(&f)?;
        let totals = self.storage.get_credit_consumption(Some(since), None)?;
        let accounts = daily
            .iter()
            .map(|x| x.account_email.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let dates = daily
            .iter()
            .map(|x| x.date.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        let days = dates
            .iter()
            .filter_map(|d| {
                chrono::NaiveDate::parse_from_str(d, "%Y-%m-%d")
                    .ok()
                    .map(|x| x.format("%a %-d").to_string())
            })
            .collect();
        Ok(WeeklyActivity {
            daily_per_account: daily,
            daily_totals: totals,
            accounts,
            days,
            date_range: (dates.first().cloned(), dates.last().cloned()),
            dates,
        })
    }
}
