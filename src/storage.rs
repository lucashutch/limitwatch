use std::path::{Path, PathBuf};

use anyhow::Result;
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};

use crate::model::Quota;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS quota_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, account_email TEXT NOT NULL,
 provider_type TEXT NOT NULL, quota_name TEXT NOT NULL, display_name TEXT,
 remaining_pct REAL, used REAL, limit_val REAL, reset_time TEXT,
 timestamp TEXT NOT NULL, hour_bucket TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(account_email, quota_name, hour_bucket));
CREATE INDEX IF NOT EXISTS idx_snapshots_account ON quota_snapshots(account_email);
CREATE INDEX IF NOT EXISTS idx_snapshots_provider ON quota_snapshots(provider_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON quota_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_name ON quota_snapshots(quota_name);
CREATE INDEX IF NOT EXISTS idx_snapshots_hour ON quota_snapshots(hour_bucket);
"#;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HistoryFilter {
    pub since: Option<DateTime<Utc>>,
    pub until: Option<DateTime<Utc>>,
    pub account_email: Option<String>,
    pub provider_type: Option<String>,
    pub quota_name: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Snapshot {
    pub id: i64,
    pub account_email: String,
    pub provider_type: String,
    pub quota_name: String,
    pub display_name: Option<String>,
    pub remaining_pct: Option<f64>,
    pub used: Option<f64>,
    pub limit_val: Option<f64>,
    pub reset_time: Option<String>,
    pub timestamp: String,
    pub hour_bucket: String,
    pub created_at: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Aggregation {
    pub account_email: String,
    pub provider_type: String,
    pub quota_name: String,
    pub display_name: Option<String>,
    pub min_remaining: Option<f64>,
    pub max_remaining: Option<f64>,
    pub avg_remaining: Option<f64>,
    pub min_used: Option<f64>,
    pub max_used: Option<f64>,
    pub avg_used: Option<f64>,
    pub data_points: i64,
    pub first_seen: String,
    pub last_seen: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DailyActivity {
    pub date: String,
    pub account_email: String,
    pub provider_type: String,
    pub record_count: i64,
    pub avg_remaining_pct: f64,
    pub min_remaining_pct: f64,
    pub max_remaining_pct: f64,
    pub total_used: Option<f64>,
    pub first_record: String,
    pub last_record: String,
}
#[derive(Clone, Debug, PartialEq)]
pub struct CreditConsumption {
    pub date: String,
    pub total_used: f64,
    pub account_count: i64,
    pub provider_count: i64,
    pub record_count: i64,
}

pub struct Storage {
    pub db_path: PathBuf,
}

impl Storage {
    pub fn new(path: Option<impl AsRef<Path>>) -> Result<Self> {
        let db_path = path
            .map(|p| p.as_ref().to_path_buf())
            .unwrap_or_else(default_db_path);
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let storage = Self { db_path };
        storage.connection()?.execute_batch(SCHEMA)?;
        Ok(storage)
    }
    fn connection(&self) -> Result<Connection> {
        Ok(Connection::open(&self.db_path)?)
    }
    pub fn record_quotas(
        &self,
        account: &str,
        provider: &str,
        quotas: &[Quota],
        timestamp: Option<DateTime<Utc>>,
    ) -> Result<usize> {
        let now = timestamp.unwrap_or_else(Utc::now);
        let ts = now.to_rfc3339();
        let hour = now.format("%Y-%m-%d %H").to_string();
        let mut conn = self.connection()?;
        let tx = conn.transaction()?;
        let mut count = 0;
        for quota in quotas {
            if quota
                .extra
                .get("is_error")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
            {
                continue;
            }
            let name = if quota.name.is_empty() {
                "unknown"
            } else {
                &quota.name
            };
            let display = (!quota.display_name.is_empty()).then_some(quota.display_name.as_str());
            let reset = quota
                .reset_time
                .as_deref()
                .or_else(|| quota.extra.get("reset").and_then(|v| v.as_str()))
                .unwrap_or("");
            tx.execute("INSERT OR REPLACE INTO quota_snapshots (account_email,provider_type,quota_name,display_name,remaining_pct,used,limit_val,reset_time,timestamp,hour_bucket) VALUES (?,?,?,?,?,?,?,?,?,?)", params![account,provider,name,display,quota.remaining_pct,quota.used,quota.limit,reset,ts,hour])?;
            count += 1;
        }
        tx.commit()?;
        Ok(count)
    }
    pub fn query_history(&self, filter: &HistoryFilter) -> Result<Vec<Snapshot>> {
        let (sql, values) = filtered_sql("SELECT * FROM quota_snapshots WHERE 1=1", filter, true);
        let conn = self.connection()?;
        let mut stmt = conn.prepare(&sql)?;
        let rows = stmt.query_map(rusqlite::params_from_iter(values), |r| {
            Ok(Snapshot {
                id: r.get(0)?,
                account_email: r.get(1)?,
                provider_type: r.get(2)?,
                quota_name: r.get(3)?,
                display_name: r.get(4)?,
                remaining_pct: r.get(5)?,
                used: r.get(6)?,
                limit_val: r.get(7)?,
                reset_time: r.get(8)?,
                timestamp: r.get(9)?,
                hour_bucket: r.get(10)?,
                created_at: r.get(11)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
    pub fn get_aggregation(&self, filter: &HistoryFilter) -> Result<Vec<Aggregation>> {
        let base="SELECT account_email,provider_type,quota_name,display_name,MIN(remaining_pct),MAX(remaining_pct),AVG(remaining_pct),MIN(used),MAX(used),AVG(used),COUNT(*),MIN(timestamp),MAX(timestamp) FROM quota_snapshots WHERE 1=1";
        let (mut sql, values) = filtered_sql(base, filter, false);
        sql.push_str(
            " GROUP BY account_email,provider_type,quota_name ORDER BY account_email,quota_name",
        );
        let conn = self.connection()?;
        let mut s = conn.prepare(&sql)?;
        let rows = s.query_map(rusqlite::params_from_iter(values), |r| {
            Ok(Aggregation {
                account_email: r.get(0)?,
                provider_type: r.get(1)?,
                quota_name: r.get(2)?,
                display_name: r.get(3)?,
                min_remaining: r.get(4)?,
                max_remaining: r.get(5)?,
                avg_remaining: r.get(6)?,
                min_used: r.get(7)?,
                max_used: r.get(8)?,
                avg_used: r.get(9)?,
                data_points: r.get(10)?,
                first_seen: r.get(11)?,
                last_seen: r.get(12)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
    fn distinct(&self, column: &str, account: Option<&str>) -> Result<Vec<String>> {
        let sql = format!(
            "SELECT DISTINCT {column} FROM quota_snapshots WHERE provider_type != 'google'{} ORDER BY {column}",
            if account.is_some() {
                " AND account_email = ?"
            } else {
                ""
            }
        );
        let values = account.into_iter().collect::<Vec<_>>();
        let c = self.connection()?;
        let mut s = c.prepare(&sql)?;
        let rows = s.query_map(rusqlite::params_from_iter(values), |r| r.get(0))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
    pub fn get_distinct_accounts(&self) -> Result<Vec<String>> {
        self.distinct("account_email", None)
    }
    pub fn get_distinct_providers(&self) -> Result<Vec<String>> {
        self.distinct("provider_type", None)
    }
    pub fn get_distinct_quotas(&self, account: Option<&str>) -> Result<Vec<String>> {
        self.distinct("quota_name", account)
    }
    pub fn get_time_range(&self) -> Result<(Option<String>, Option<String>)> {
        Ok(self.connection()?.query_row(
            "SELECT MIN(timestamp),MAX(timestamp) FROM quota_snapshots WHERE provider_type != 'google'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?)
    }
    pub fn purge_old_data(&self, before: DateTime<Utc>) -> Result<usize> {
        Ok(self.connection()?.execute(
            "DELETE FROM quota_snapshots WHERE timestamp < ?",
            [before.to_rfc3339()],
        )?)
    }
    pub fn get_daily_activity(&self, filter: &HistoryFilter) -> Result<Vec<DailyActivity>> {
        let (mut sql,v)=filtered_sql("SELECT date(timestamp),account_email,provider_type,COUNT(*),AVG(remaining_pct),MIN(remaining_pct),MAX(remaining_pct),SUM(used),MIN(timestamp),MAX(timestamp) FROM quota_snapshots WHERE remaining_pct IS NOT NULL",filter,false);
        sql.push_str(" GROUP BY date(timestamp),account_email,provider_type ORDER BY date(timestamp),account_email");
        let c = self.connection()?;
        let mut s = c.prepare(&sql)?;
        let r = s.query_map(rusqlite::params_from_iter(v), |x| {
            Ok(DailyActivity {
                date: x.get(0)?,
                account_email: x.get(1)?,
                provider_type: x.get(2)?,
                record_count: x.get(3)?,
                avg_remaining_pct: x.get(4)?,
                min_remaining_pct: x.get(5)?,
                max_remaining_pct: x.get(6)?,
                total_used: x.get(7)?,
                first_record: x.get(8)?,
                last_record: x.get(9)?,
            })
        })?;
        Ok(r.collect::<rusqlite::Result<_>>()?)
    }
    pub fn get_credit_consumption(
        &self,
        since: Option<DateTime<Utc>>,
        until: Option<DateTime<Utc>>,
    ) -> Result<Vec<CreditConsumption>> {
        let f = HistoryFilter {
            since,
            until,
            ..Default::default()
        };
        let(mut sql,v)=filtered_sql("SELECT date(timestamp),SUM(used),COUNT(DISTINCT account_email),COUNT(DISTINCT provider_type),COUNT(*) FROM quota_snapshots WHERE used IS NOT NULL",&f,false);
        sql.push_str(" GROUP BY date(timestamp) ORDER BY date(timestamp) DESC");
        let c = self.connection()?;
        let mut s = c.prepare(&sql)?;
        let r = s.query_map(rusqlite::params_from_iter(v), |x| {
            Ok(CreditConsumption {
                date: x.get(0)?,
                total_used: x.get(1)?,
                account_count: x.get(2)?,
                provider_count: x.get(3)?,
                record_count: x.get(4)?,
            })
        })?;
        Ok(r.collect::<rusqlite::Result<_>>()?)
    }
}
fn filtered_sql(base: &str, f: &HistoryFilter, order: bool) -> (String, Vec<String>) {
    // Google snapshots remain in the shared database for compatibility, but
    // the Rust rewrite intentionally does not expose the unsupported provider
    // through history or export views.
    let mut q = format!("{base} AND provider_type != 'google'");
    let mut v = vec![];
    for (column, value) in [
        ("timestamp >=", f.since.map(|x| x.to_rfc3339())),
        ("timestamp <=", f.until.map(|x| x.to_rfc3339())),
        ("account_email =", f.account_email.clone()),
        ("provider_type =", f.provider_type.clone()),
        ("quota_name =", f.quota_name.clone()),
    ] {
        if let Some(x) = value {
            q.push_str(&format!(" AND {column} ?"));
            v.push(x)
        }
    }
    if order {
        q.push_str(" ORDER BY timestamp DESC,account_email,quota_name")
    }
    (q, v)
}
pub fn default_db_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_default()
        .join(".config/limitwatch/history.db")
}
