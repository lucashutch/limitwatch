use crate::model::Quota;
use crate::storage::{
    Aggregation, CreditConsumption, DailyActivity, HistoryFilter, Snapshot, Storage,
};
use anyhow::{anyhow, Result};
use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, TimeZone, Utc};
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
        if value.is_empty() {
            return None;
        }
        DateTime::parse_from_rfc3339(&value.replace('Z', "+00:00"))
            .ok()
            .map(|x| x.with_timezone(&Utc))
            .or_else(|| {
                let (n, s) = value.split_at(value.len().checked_sub(1)?);
                if n.is_empty() || !n.chars().all(|x| x.is_ascii_digit()) {
                    return None;
                }
                let n = n.parse::<i64>().ok()?;
                match s {
                    "d" => Some(Utc::now() - Duration::days(n)),
                    "h" => Some(Utc::now() - Duration::hours(n)),
                    _ => None,
                }
            })
            .or_else(|| {
                let naive = NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
                    .or_else(|_| NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f"))
                    .ok()?;
                Some(Utc.from_utc_datetime(&naive))
            })
            .or_else(|| {
                NaiveDate::parse_from_str(value, "%Y-%m-%d")
                    .ok()
                    .map(|date| Utc.from_utc_datetime(&date.and_hms_opt(0, 0, 0).unwrap()))
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
            .chain(totals.iter().map(|x| x.date.clone()))
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

fn short_account(email: &str) -> &str {
    email.split('@').next().unwrap_or(email)
}

fn quota_label(snapshot: &Snapshot) -> &str {
    snapshot
        .display_name
        .as_deref()
        .filter(|name| !name.is_empty())
        .unwrap_or(&snapshot.quota_name)
}

fn pct(value: Option<f64>, decimals: usize) -> String {
    value
        .map(|value| format!("{value:.decimals$}%"))
        .unwrap_or_else(|| "N/A".into())
}

fn number(value: Option<f64>) -> String {
    value
        .map(|value| {
            let raw = format!("{value:.0}");
            let (sign, whole) = if let Some(whole) = raw.strip_prefix('-') {
                ("-", whole)
            } else {
                ("", raw.as_str())
            };
            let grouped = whole
                .chars()
                .rev()
                .enumerate()
                .fold(String::new(), |mut output, (index, digit)| {
                    if index > 0 && index % 3 == 0 {
                        output.push(',');
                    }
                    output.push(digit);
                    output
                })
                .chars()
                .rev()
                .collect::<String>();
            format!("{sign}{grouped}")
        })
        .unwrap_or_else(|| "N/A".into())
}

fn sparkline(values: &[f64], width: usize) -> String {
    if values.len() < 2 {
        return "─".repeat(width);
    }
    let blocks = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
    (0..width)
        .map(|i| {
            let index =
                ((i as f64 * values.len() as f64 / width as f64) as usize).min(values.len() - 1);
            let value = values[index].clamp(0.0, 100.0);
            blocks[(value / 100.0 * 8.0) as usize]
        })
        .collect()
}

fn trend(values: &[f64]) -> &'static str {
    if values.len() < 2 {
        return "--";
    }
    let third = values.len() / 3;
    let first = values.iter().take(third).sum::<f64>() / third.max(1) as f64;
    let last_values = if third == 0 {
        values
    } else {
        &values[values.len() - third..]
    };
    let last = last_values.iter().sum::<f64>() / third.max(1) as f64;
    let diff = last - first;
    if diff.abs() < 1.0 {
        "= stable"
    } else if diff > 0.0 {
        "^ rising"
    } else {
        "v falling"
    }
}

/// Plain-text equivalent of the Rich history sparkline table.
pub fn render_history_sparklines(data: &[Snapshot]) -> String {
    if data.is_empty() {
        return "No historical data found.\n".into();
    }
    let mut groups = std::collections::BTreeMap::<(String, String, String), Vec<f64>>::new();
    for row in data {
        if let Some(value) = row.remaining_pct {
            groups
                .entry((
                    row.account_email.clone(),
                    row.provider_type.clone(),
                    row.quota_name.clone(),
                ))
                .or_default()
                .push(value);
        }
    }
    let mut out = String::from(
        "Quota History\nAccount | Provider | Quota | Trend                 | Current | Min | Max\n",
    );
    for ((account, provider, quota), values) in groups {
        if values.is_empty() {
            continue;
        }
        let current = values.last().copied();
        let min = values.iter().copied().reduce(f64::min);
        let max = values.iter().copied().reduce(f64::max);
        out.push_str(&format!(
            "{} | {} | {} | {} {} | {} | {} | {}\n",
            short_account(&account),
            provider,
            quota,
            sparkline(&values, 20),
            trend(&values),
            pct(current, 1),
            pct(min, 0),
            pct(max, 0)
        ));
    }
    out.push_str(&format!(
        "{} quotas tracked across {} snapshots\n",
        data.iter()
            .map(|row| (&row.account_email, &row.provider_type, &row.quota_name))
            .collect::<BTreeSet<_>>()
            .len(),
        data.len()
    ));
    out
}

/// Plain-text equivalent of the Rich time-series table.
pub fn render_history_table(data: &[Snapshot]) -> String {
    if data.is_empty() {
        return "No historical data found.\n".into();
    }
    let shown = data.len().min(100);
    let mut out = format!("Quota History ({shown} of {} records)\n", data.len());
    out.push_str("Time             Account          Provider        Quota                    Remaining   Bar          Used      Limit\n");
    for row in data.iter().take(100) {
        let time = DateTime::parse_from_rfc3339(&row.timestamp)
            .map(|time| time.format("%b %d %H:%M").to_string())
            .unwrap_or_else(|_| row.timestamp.chars().take(16).collect());
        let bar = row
            .remaining_pct
            .map(|value| {
                let filled = ((value / 10.0) as usize).min(10);
                format!("{}{}", "█".repeat(filled), "░".repeat(10 - filled))
            })
            .unwrap_or_else(|| "░".repeat(10));
        out.push_str(&format!(
            "{time:<16} {:<16} {:<15} {:<24} {:>9} {bar} {:>9} {:>9}\n",
            short_account(&row.account_email),
            row.provider_type,
            quota_label(row),
            pct(row.remaining_pct, 1),
            number(row.used),
            number(row.limit_val)
        ));
    }
    if data.len() > 100 {
        out.push_str(&format!("... {} more records\n", data.len() - 100));
    }
    out
}

pub fn render_history_summary(info: &DatabaseInfo) -> String {
    let providers = info.providers.join(", ");
    let mut out = format!(
        "History Database Summary\nDatabase: {}\nOldest Record: {}\nNewest Record: {}\nAccounts: {}\nProviders: {}\n",
        info.path,
        info.oldest_record.as_deref().unwrap_or("None"),
        info.newest_record.as_deref().unwrap_or("None"),
        info.accounts.len(),
        if providers.is_empty() { "None" } else { &providers },
    );
    if !info.accounts.is_empty() {
        out.push_str(&format!("Account List: {}\n", info.accounts.join(", ")));
    }
    out
}

fn no_activity(view: &str, w: &WeeklyActivity) -> bool {
    match view {
        "bars" => w.daily_totals.is_empty(),
        "calendar" => {
            w.dates.is_empty() || (w.daily_per_account.is_empty() && w.daily_totals.is_empty())
        }
        _ => w.daily_per_account.is_empty() || w.accounts.is_empty() || w.dates.is_empty(),
    }
}

/// Render all weekly views without requiring Rich or terminal capabilities.
pub fn render_weekly(view: &str, w: &WeeklyActivity) -> String {
    if no_activity(view, w) {
        return "No activity data found for the past week.\n".into();
    }
    let mut out = String::new();
    match view {
        "heatmap" => {
            out.push_str("Activity Heatmap (Last 7 Days)\nAccount | ");
            out.push_str(&w.days.join(" | "));
            out.push_str(" | Total\n");
            for account in &w.accounts {
                let mut total = 0;
                out.push_str(short_account(account));
                for date in &w.dates {
                    let count = w
                        .daily_per_account
                        .iter()
                        .find(|row| &row.account_email == account && &row.date == date)
                        .map(|row| row.record_count)
                        .unwrap_or(0);
                    total += count;
                    out.push_str(&format!(" | {count}"));
                }
                out.push_str(&format!(" | {total}\n"));
            }
            out.push_str("Total | ");
            for date in &w.dates {
                out.push_str(&format!(
                    "{} |",
                    w.daily_per_account
                        .iter()
                        .filter(|row| &row.date == date)
                        .map(|row| row.record_count)
                        .sum::<i64>()
                ));
            }
            out.push_str("\nLegend: counts are activity intensity (plain-text equivalent)\n");
        }
        "chart" => {
            out.push_str("Remaining % Chart\n");
            for account in &w.accounts {
                out.push_str(&format!("{}\n", short_account(account)));
                for threshold in [100, 80, 60, 40, 20, 0] {
                    out.push_str(&format!("{threshold:>3}% |"));
                    for date in &w.dates {
                        let value = w
                            .daily_per_account
                            .iter()
                            .find(|row| &row.account_email == account && &row.date == date)
                            .map(|row| row.avg_remaining_pct);
                        out.push_str(if value.is_some_and(|value| value >= threshold as f64) {
                            " ███ "
                        } else {
                            "     "
                        });
                    }
                    out.push('\n');
                }
                out.push_str("     +");
                out.push_str(&"─────".repeat(w.dates.len()));
                out.push('\n');
                out.push_str(&format!("       {}\n", w.days.join("   ")));
            }
        }
        "calendar" => {
            out.push_str("Weekly Activity Calendar\n");
            let totals = w
                .daily_totals
                .iter()
                .map(|row| (&row.date, row))
                .collect::<std::collections::BTreeMap<_, _>>();
            for (index, date) in w.dates.iter().enumerate() {
                if let Some(total) = totals.get(date) {
                    out.push_str(&format!(
                        "{} ({date}): {} snapshots, {} accounts, {} credits\n",
                        w.days.get(index).map(String::as_str).unwrap_or(""),
                        total.record_count,
                        total.account_count,
                        total.total_used.round()
                    ));
                } else {
                    out.push_str(&format!(
                        "{} ({date}): no activity\n",
                        w.days.get(index).map(String::as_str).unwrap_or("")
                    ));
                }
            }
        }
        "bars" => {
            out.push_str("Daily Credit Consumption (Last 7 Days)\nDay | Usage | Credits | Accounts | % of Peak\n");
            let peak = w
                .daily_totals
                .iter()
                .map(|row| row.total_used)
                .fold(0.0, f64::max);
            let mut total = 0.0;
            for (index, row) in w.daily_totals.iter().enumerate() {
                let percent = if peak > 0.0 {
                    row.total_used / peak * 100.0
                } else {
                    0.0
                };
                total += row.total_used;
                out.push_str(&format!(
                    "{} | {} | {:.0} | {} | {:.0}%\n",
                    w.days.get(index).map(String::as_str).unwrap_or(&row.date),
                    "█".repeat((percent / 10.0) as usize),
                    row.total_used,
                    row.account_count,
                    percent
                ));
            }
            let average = if w.daily_totals.is_empty() {
                0.0
            } else {
                total / w.daily_totals.len() as f64
            };
            out.push_str(&format!(
                "Total: {:.0} credits | Avg: {:.0}/day\n",
                total, average
            ));
        }
        _ => out.push_str("Quota Statistics Dashboard\n"),
    }
    out
}

pub fn render_stats(
    history: &[Snapshot],
    weekly: &WeeklyActivity,
    aggregation: &[Aggregation],
) -> String {
    let span = history
        .iter()
        .filter_map(|row| DateTime::parse_from_rfc3339(&row.timestamp).ok())
        .fold(
            None,
            |range: Option<(DateTime<chrono::FixedOffset>, DateTime<chrono::FixedOffset>)>,
             value| {
                Some(match range {
                    Some((min, max)) => (min.min(value), max.max(value)),
                    None => (value, value),
                })
            },
        )
        .map(|(min, max)| max - min);
    let mut out = format!(
        "Quota Statistics Dashboard\nData Volume: {} snapshots (spanning {})\nCoverage: {} accounts, {} providers, {} quotas tracked\n",
        history.len(),
        span.map(|value| {
            if value.num_days() > 0 {
                format!("{}d {}h", value.num_days(), value.num_hours() % 24)
            } else {
                format!("{}h", value.num_hours())
            }
        }).unwrap_or_else(|| "N/A".into()),
        history.iter().map(|x| &x.account_email).collect::<BTreeSet<_>>().len(),
        history.iter().map(|x| &x.provider_type).collect::<BTreeSet<_>>().len(),
        history.iter().map(|x| &x.quota_name).collect::<BTreeSet<_>>().len(),
    );
    let pcts = aggregation
        .iter()
        .filter_map(|x| x.avg_remaining)
        .collect::<Vec<_>>();
    if pcts.is_empty() {
        out.push_str("Health: No percentage data\n");
    } else {
        let average = pcts.iter().sum::<f64>() / pcts.len() as f64;
        out.push_str(&format!(
            "Health: {:.1}% avg remaining ({} healthy, {} warning, {} critical)\n",
            average,
            pcts.iter().filter(|x| **x >= 50.0).count(),
            pcts.iter().filter(|x| **x >= 20.0 && **x < 50.0).count(),
            pcts.iter().filter(|x| **x < 20.0).count()
        ));
    }
    if !aggregation.is_empty() {
        out.push_str("\nPer-Quota Statistics\nAccount | Provider | Quota | Avg % | Min % | Max % | Volatility | Samples\n");
        for row in aggregation {
            let volatility = match (row.min_remaining, row.max_remaining, row.avg_remaining) {
                (Some(min), Some(max), Some(avg)) if avg > 0.0 => format!(
                    "{} ({:.0}pp)",
                    if (max - min) / avg * 100.0 < 5.0 {
                        "low"
                    } else if (max - min) / avg * 100.0 < 20.0 {
                        "moderate"
                    } else {
                        "high"
                    },
                    max - min
                ),
                _ => "--".into(),
            };
            out.push_str(&format!(
                "{} | {} | {} | {} | {} | {} | {} | {}\n",
                short_account(&row.account_email),
                row.provider_type,
                row.display_name.as_deref().unwrap_or(&row.quota_name),
                pct(row.avg_remaining, 1),
                pct(row.min_remaining, 1),
                pct(row.max_remaining, 1),
                volatility,
                row.data_points
            ));
        }
    }
    if !weekly.daily_totals.is_empty() {
        let credits: f64 = weekly.daily_totals.iter().map(|row| row.total_used).sum();
        let active = weekly
            .daily_totals
            .iter()
            .filter(|row| row.total_used > 0.0)
            .count();
        out.push_str(&format!(
            "\n7-Day Summary: {:.0} total credits | {active}/{} active days\n",
            credits,
            weekly.daily_totals.len()
        ));
    }
    out
}
