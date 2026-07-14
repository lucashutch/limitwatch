use crate::{
    history::{DatabaseInfo, WeeklyActivity},
    model::Quota,
    providers::base::Provider,
    storage::Snapshot,
};
use chrono::{DateTime, TimeZone, Utc};

pub fn query_filter(mut quotas: Vec<Quota>, queries: &[String]) -> Vec<Quota> {
    for query in queries {
        let q = query.to_lowercase();
        quotas.retain(|x| {
            x.name.to_lowercase().contains(&q) || x.display_name.to_lowercase().contains(&q)
        });
    }
    quotas
}
fn pct(q: &Quota) -> (f64, bool) {
    q.used_pct
        .map(|value| (value, true))
        .unwrap_or((q.remaining_pct.unwrap_or(100.0), false))
}
fn reset(q: &Quota, now: DateTime<Utc>) -> String {
    if q.remaining_pct.unwrap_or(100.0) >= 100.0 {
        return String::new();
    }
    let Some(value) = q.reset_time.as_deref() else {
        return String::new();
    };
    let dt = DateTime::parse_from_rfc3339(&value.replace('Z', "+00:00"))
        .map(|x| x.with_timezone(&Utc))
        .ok()
        .or_else(|| {
            value.parse::<i64>().ok().and_then(|mut x| {
                if x.abs() > 10_000_000_000 {
                    x /= 1000;
                }
                Utc.timestamp_opt(x, 0).single()
            })
        });
    let Some(dt) = dt else {
        return String::new();
    };
    let seconds = (dt - now).num_seconds();
    if seconds <= 0 {
        return String::new();
    }
    format_countdown(seconds)
}
fn format_countdown(seconds: i64) -> String {
    if seconds <= 0 {
        return String::new();
    }
    let (d, r) = (seconds / 86400, seconds % 86400);
    let (h, r) = (r / 3600, r % 3600);
    let m = r / 60;
    let mut p = Vec::new();
    if d > 0 {
        p.push(format!("{d}d"))
    }
    if h > 0 {
        p.push(format!("{h}h"))
    }
    if m > 0 || p.is_empty() {
        p.push(format!("{m}m"))
    }
    format!(" ({})", p.join(" "))
}
fn normal_bar_width() -> usize {
    std::env::var("COLUMNS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(80)
        .saturating_sub(50)
        .clamp(10, 60)
}
fn bar(value: f64, width: usize, compact: bool) -> String {
    let value = value.clamp(0.0, 100.0);
    let n = (value * width as f64 / 100.0) as usize;
    let remainder = value * width as f64 / 100.0 - n as f64;
    let fractions = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"];
    let fraction = if compact || n >= width {
        ""
    } else {
        fractions[(remainder * 8.0) as usize]
    };
    format!(
        "{}{}{}",
        "█".repeat(n),
        fraction,
        " ".repeat(width - n - usize::from(!fraction.is_empty()))
    )
}
fn color_code(color: &str) -> &'static str {
    match color {
        "red" => "31",
        "green" => "32",
        "yellow" => "33",
        "cyan" => "36",
        _ => "37",
    }
}
fn styled(value: &str, code: &str, color: bool) -> String {
    if color && !value.is_empty() {
        format!("\x1b[{code}m{value}\x1b[0m")
    } else {
        value.to_owned()
    }
}
pub fn color_enabled(is_terminal: bool, no_color: bool) -> bool {
    is_terminal && !no_color
}
pub fn account_header(
    email: &str,
    provider: &str,
    alias: Option<&str>,
    group: Option<&str>,
) -> String {
    let name = alias.unwrap_or(email);
    let meta = match (alias, group) {
        (Some(_), Some(g)) => format!(" ({email}|{g})"),
        (Some(_), None) => format!(" ({email})"),
        (None, Some(g)) => format!(" ({g})"),
        _ => String::new(),
    };
    format!("📧 {provider}: {name}{meta}")
}
pub fn render_quotas(
    email: &str,
    alias: Option<&str>,
    group: Option<&str>,
    provider: &dyn Provider,
    quotas: Vec<Quota>,
    compact: bool,
    color: bool,
) -> String {
    render_quotas_at(
        email,
        alias,
        group,
        provider,
        quotas,
        compact,
        color,
        Utc::now(),
    )
}

#[allow(clippy::too_many_arguments)]
pub fn render_quotas_at(
    email: &str,
    alias: Option<&str>,
    group: Option<&str>,
    provider: &dyn Provider,
    mut quotas: Vec<Quota>,
    compact: bool,
    color: bool,
    now: DateTime<Utc>,
) -> String {
    quotas.sort_by_key(|q| provider.sort_key(q));
    let mut out = format!(
        "{}\n",
        styled(
            &account_header(email, provider.provider_name(), alias, group),
            "2",
            color
        )
    );
    for q in quotas {
        let name = if q.display_name.is_empty() {
            &q.name
        } else {
            &q.display_name
        };
        if q.extra.get("is_error").and_then(|v| v.as_bool()) == Some(true) {
            let m = q
                .extra
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("Validation Required");
            out += &format!("{name}: ⚠ {m}\n");
            continue;
        }
        if q.extra.get("show_progress").and_then(|v| v.as_bool()) == Some(false) {
            out += &format!("{name}\n");
            continue;
        }
        let (p, used) = pct(&q);
        let bar_color = if p <= 20.0 {
            if used {
                "green"
            } else {
                "red"
            }
        } else if p <= 50.0 {
            "yellow"
        } else if used {
            "red"
        } else {
            "green"
        };
        let raw = bar(p, if compact { 10 } else { normal_bar_width() }, compact);
        let filled_chars = raw.trim_end().chars().count();
        let split = raw
            .char_indices()
            .nth(filled_chars)
            .map_or(raw.len(), |x| x.0);
        let progress = format!(
            "{}{}",
            styled(&raw[..split], color_code(bar_color), color),
            styled(&raw[split..], "2", color)
        );
        let suffix = if used { " used" } else { "" };
        let percentage_text =
            if q.extra.get("billing_model").and_then(|v| v.as_str()) == Some("ai_credits") {
                format!("{:.1} cr ({p:.1}%)", q.used.unwrap_or(0.0))
            } else {
                format!("{p:5.1}%{suffix}")
            };
        let percentage = styled(&percentage_text, color_code(bar_color), color);
        let countdown = styled(&reset(&q, now), "2", color);
        if compact {
            out += &format!(
                "{} {:10}: {:18} {} {:5.1}%{}{}\n",
                provider.short_indicator(),
                alias.unwrap_or(email).chars().take(10).collect::<String>(),
                name.chars().take(18).collect::<String>(),
                progress,
                percentage,
                "",
                countdown
            );
        } else {
            out += &format!(
                "{} {} {}{}\n",
                styled(&format!("{name:22}"), color_code(provider.color(&q)), color),
                progress,
                percentage,
                countdown
            );
        }
    }
    out
}
pub fn history_table(data: &[Snapshot]) -> String {
    if data.is_empty() {
        return "No historical data found.\n".into();
    }
    let mut o="Quota History\nTime             Account          Provider        Quota                    Remaining\n".to_owned();
    for x in data.iter().take(100) {
        o += &format!(
            "{:<16} {:<16} {:<15} {:<24} {}\n",
            x.timestamp.chars().take(16).collect::<String>(),
            x.account_email
                .split('@')
                .next()
                .unwrap_or(&x.account_email),
            x.provider_type,
            x.display_name.as_deref().unwrap_or(&x.quota_name),
            x.remaining_pct
                .map(|v| format!("{v:.1}%"))
                .unwrap_or_else(|| "N/A".into())
        );
    }
    o
}
pub fn history_sparklines(data: &[Snapshot]) -> String {
    if data.is_empty() {
        return "No historical data found.\n".into();
    }
    let mut o = "Quota History\n".to_owned();
    for x in data {
        o += &format!(
            "{} {} {} {:5.1}%\n",
            x.account_email,
            x.provider_type,
            x.display_name.as_deref().unwrap_or(&x.quota_name),
            x.remaining_pct.unwrap_or(0.0)
        );
    }
    o
}
pub fn history_summary(i: &DatabaseInfo) -> String {
    format!("History Database Summary\nDatabase: {}\nOldest Record: {}\nNewest Record: {}\nAccounts: {}\nProviders: {}\n",i.path,i.oldest_record.as_deref().unwrap_or("None"),i.newest_record.as_deref().unwrap_or("None"),i.accounts.len(),i.providers.join(", "))
}
pub fn weekly(view: &str, w: &WeeklyActivity) -> String {
    if w.daily_per_account.is_empty() {
        return "No activity data found for the past week.\n".into();
    }
    let title = match view {
        "heatmap" => "Activity Heatmap (Last 7 Days)",
        "chart" => "Remaining % Chart",
        "calendar" => "Weekly Activity Calendar",
        "bars" => "Daily Credit Consumption (Last 7 Days)",
        _ => "Quota Statistics Dashboard",
    };
    let mut o = format!("{title}\n");
    for row in &w.daily_per_account {
        o += &format!(
            "{} {} {} snapshots\n",
            row.date, row.account_email, row.record_count
        )
    }
    o
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{model::Account, providers};
    use serde_json::json;

    fn provider(kind: &str) -> Box<dyn Provider> {
        providers::create(Account {
            provider_type: kind.into(),
            email: "octo".into(),
            ..Default::default()
        })
        .unwrap()
    }

    #[test]
    fn standard_output_matches_used_percent_and_copilot_org_rows() {
        let openai = Quota {
            display_name: "Five hour".into(),
            used_pct: Some(25.0),
            ..Default::default()
        };
        let text = render_quotas(
            "me@example.com",
            None,
            None,
            &*provider("openai"),
            vec![openai],
            false,
            false,
        );
        assert!(text.contains("📧 OpenAI Codex: me@example.com\n"));
        assert!(text.contains(" 25.0% used\n"));

        let org = Quota {
            display_name: "acme".into(),
            remaining_pct: Some(80.0),
            ..Default::default()
        };
        let text = render_quotas(
            "octo",
            None,
            None,
            &*provider("github_copilot"),
            vec![org],
            false,
            false,
        );
        assert!(text.contains("📧 GitHub Copilot: octo\n"));
        assert!(text.contains("acme"));
        assert!(text.contains(" 80.0%"));
    }

    #[test]
    fn ansi_only_decorates_bar_and_errors_have_no_separator_or_countdown() {
        let quota = Quota {
            display_name: "Personal".into(),
            remaining_pct: Some(50.0),
            ..Default::default()
        };
        let plain = render_quotas(
            "octo",
            None,
            None,
            &*provider("github_copilot"),
            vec![quota.clone()],
            false,
            false,
        );
        let ansi = render_quotas(
            "octo",
            None,
            None,
            &*provider("github_copilot"),
            vec![quota],
            false,
            true,
        );
        let mut stripped = ansi;
        for code in ["\x1b[0m", "\x1b[2m", "\x1b[32m", "\x1b[33m", "\x1b[37m"] {
            stripped = stripped.replace(code, "");
        }
        assert_eq!(stripped, plain);

        let mut error = Quota {
            display_name: "acme".into(),
            ..Default::default()
        };
        error.extra.insert("is_error".into(), json!(true));
        error
            .extra
            .insert("message".into(), json!("billing unavailable"));
        assert_eq!(
            render_quotas(
                "octo",
                None,
                None,
                &*provider("github_copilot"),
                vec![error],
                false,
                false
            ),
            "📧 GitHub Copilot: octo\nacme: ⚠ billing unavailable\n"
        );
    }

    #[test]
    fn countdown_uses_python_shapes_without_absolute_time() {
        assert_eq!(format_countdown(19 * 60), " (19m)");
        assert_eq!(
            format_countdown(5 * 86_400 + 19 * 3_600 + 43 * 60),
            " (5d 19h 43m)"
        );
    }

    #[test]
    fn normal_bar_fraction_and_standard_row_match_python_spacing() {
        assert_eq!(bar(25.5, 30, false), "███████▋                      ");
        let quota = Quota {
            display_name: "Five hour".into(),
            used_pct: Some(25.5),
            ..Default::default()
        };
        let text = render_quotas(
            "me@example.com",
            None,
            None,
            &*provider("openai"),
            vec![quota],
            false,
            false,
        );
        assert_eq!(
            text,
            "📧 OpenAI Codex: me@example.com\nFive hour              ███████▋                        25.5% used\n"
        );
    }

    #[test]
    fn normal_color_and_plain_goldens() {
        std::env::set_var("COLUMNS", "80");
        let quotas = vec![
            Quota {
                display_name: "Remaining".into(),
                remaining_pct: Some(75.0),
                ..Default::default()
            },
            Quota {
                display_name: "Used".into(),
                used_pct: Some(25.0),
                ..Default::default()
            },
        ];
        let plain = render_quotas(
            "me@example.com",
            Some("work"),
            Some("team"),
            &*provider("openai"),
            quotas.clone(),
            false,
            false,
        );
        let ansi = render_quotas(
            "me@example.com",
            Some("work"),
            Some("team"),
            &*provider("openai"),
            quotas,
            false,
            true,
        );
        assert_eq!(
            plain,
            include_str!("../tests/fixtures/golden/normal_quota_plain.txt")
        );
        assert_eq!(
            ansi,
            include_str!("../tests/fixtures/golden/normal_quota_ansi.txt")
        );
    }
}
