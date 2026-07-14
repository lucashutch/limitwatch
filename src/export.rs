use crate::history::HistoryManager;
use anyhow::Result;
use chrono::Local;
use std::fmt::Write as _;
use std::path::Path;

#[derive(Default)]
pub struct ExportFilter<'a> {
    pub preset: Option<&'a str>,
    pub since: Option<&'a str>,
    pub until: Option<&'a str>,
    pub account_email: Option<&'a str>,
    pub provider_type: Option<&'a str>,
    pub quota_name: Option<&'a str>,
}
pub struct ExportInfo {
    pub record_count: usize,
    pub date_range: Option<(String, String)>,
}
pub struct Exporter<'a> {
    pub history: &'a HistoryManager,
}
impl Exporter<'_> {
    fn data(&self, f: &ExportFilter<'_>) -> Result<Vec<crate::storage::Snapshot>> {
        self.history.get_history(
            f.preset,
            f.since,
            f.until,
            f.account_email,
            f.provider_type,
            f.quota_name,
        )
    }
    fn finish(content: String, path: Option<&Path>) -> Result<String> {
        if let Some(p) = path {
            if let Some(parent) = p.parent() {
                std::fs::create_dir_all(parent)?
            }
            std::fs::write(p, content)?;
            Ok(String::new())
        } else {
            Ok(content)
        }
    }
    fn info(data: &[crate::storage::Snapshot]) -> ExportInfo {
        let date_range = if data.is_empty() {
            None
        } else {
            let mut timestamps = data
                .iter()
                .map(|snapshot| snapshot.timestamp.clone())
                .collect::<Vec<_>>();
            timestamps.sort();
            Some((
                timestamps[0].clone(),
                timestamps[timestamps.len() - 1].clone(),
            ))
        };
        ExportInfo {
            record_count: data.len(),
            date_range,
        }
    }
    pub fn export_csv(&self, path: Option<&Path>, f: &ExportFilter<'_>) -> Result<String> {
        let data = self.data(f)?;
        self.export_csv_data(path, data)
    }
    pub(crate) fn export_csv_with_info(
        &self,
        path: Option<&Path>,
        f: &ExportFilter<'_>,
    ) -> Result<(String, ExportInfo)> {
        let data = self.data(f)?;
        let info = Self::info(&data);
        Ok((self.export_csv_data(path, data)?, info))
    }
    fn export_csv_data(
        &self,
        path: Option<&Path>,
        data: Vec<crate::storage::Snapshot>,
    ) -> Result<String> {
        if data.is_empty() {
            return Ok(String::new());
        }
        let mut out="timestamp,account_email,provider_type,quota_name,display_name,remaining_pct,used,limit,reset_time\r\n".to_owned();
        for x in data {
            let fields = [
                x.timestamp,
                x.account_email,
                x.provider_type,
                x.quota_name,
                x.display_name.unwrap_or_default(),
                x.remaining_pct.map(csv_float).unwrap_or_default(),
                x.used.map(csv_float).unwrap_or_default(),
                x.limit_val.map(csv_float).unwrap_or_default(),
                x.reset_time.unwrap_or_default(),
            ];
            out.push_str(
                &fields
                    .iter()
                    .map(|v| csv_field(v))
                    .collect::<Vec<_>>()
                    .join(","),
            );
            out.push_str("\r\n")
        }
        Self::finish(out, path)
    }
    pub fn export_markdown(&self, path: Option<&Path>, f: &ExportFilter<'_>) -> Result<String> {
        let data = self.data(f)?;
        self.export_markdown_data(path, f, data)
    }
    pub(crate) fn export_markdown_with_info(
        &self,
        path: Option<&Path>,
        f: &ExportFilter<'_>,
    ) -> Result<(String, ExportInfo)> {
        let data = self.data(f)?;
        let info = Self::info(&data);
        Ok((self.export_markdown_data(path, f, data)?, info))
    }
    fn export_markdown_data(
        &self,
        path: Option<&Path>,
        f: &ExportFilter<'_>,
        data: Vec<crate::storage::Snapshot>,
    ) -> Result<String> {
        if data.is_empty() {
            return Ok(String::new());
        }
        let mut o = format!(
            "# Quota History Export\n\nGenerated: {}\n\n",
            Local::now().format("%Y-%m-%dT%H:%M:%S%.f")
        );
        if [
            f.preset,
            f.since,
            f.account_email,
            f.provider_type,
            f.quota_name,
        ]
        .iter()
        .any(|x| x.is_some())
        {
            o.push_str("## Filters\n");
            for (label, v) in [
                ("Time Range", f.preset),
                ("Since", f.since),
                ("Until", f.until),
                ("Account", f.account_email),
                ("Provider", f.provider_type),
                ("Quota", f.quota_name),
            ] {
                if let Some(v) = v {
                    writeln!(o, "- {label}: {v}")?
                }
            }
            o.push('\n')
        }
        o.push_str("## Data\n\n| Timestamp | Account | Provider | Quota | Remaining % | Used | Limit |\n|-----------|---------|----------|-------|-------------|------|-------|\n");
        let n = data.len();
        for x in data {
            let ts = &x.timestamp[..x.timestamp.len().min(16)];
            let account = x.account_email.split('@').next().unwrap_or("");
            let quota = x
                .display_name
                .as_deref()
                .filter(|x| !x.is_empty())
                .unwrap_or(&x.quota_name);
            let r = x
                .remaining_pct
                .map(|v| format!("{v:.1}%"))
                .unwrap_or_else(|| "N/A".into());
            let u = x
                .used
                .map(|v| format!("{v:.0}"))
                .unwrap_or_else(|| "N/A".into());
            let l = x
                .limit_val
                .map(|v| format!("{v:.0}"))
                .unwrap_or_else(|| "N/A".into());
            writeln!(
                o,
                "| {ts} | {account} | {} | {quota} | {r} | {u} | {l} |",
                x.provider_type
            )?
        }
        write!(o, "\n*Total records: {n}*\n")?;
        Self::finish(o, path)
    }
    pub fn get_export_info(&self, f: &ExportFilter<'_>) -> Result<ExportInfo> {
        Ok(Self::info(&self.data(f)?))
    }
}
fn csv_field(v: &str) -> String {
    if v.chars().any(|c| matches!(c, ',' | '"' | '\n' | '\r')) {
        format!("\"{}\"", v.replace('"', "\"\""))
    } else {
        v.to_owned()
    }
}

fn csv_float(value: f64) -> String {
    if value.is_finite() && value.fract() == 0.0 {
        format!("{value:.1}")
    } else {
        value.to_string()
    }
}
