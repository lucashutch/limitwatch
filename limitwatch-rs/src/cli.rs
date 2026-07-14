use crate::{
    auth::AuthManager,
    completions,
    config::Config,
    display,
    export::{ExportFilter, Exporter},
    history::HistoryManager,
    model::{Account, Quota, Timing},
    providers::base::{HttpClient, ProcessRunner, RequestContext},
    quota_client::QuotaClient,
};
use anyhow::{bail, Result};
use clap::{Args, CommandFactory, Parser, Subcommand, ValueEnum};
use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{self, IsTerminal, Write},
    path::PathBuf,
    process::Command,
    sync::mpsc,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[derive(Parser)]
#[command(
    name = "limitwatch",
    version,
    about = "Monitor API quota usage and reset times across all accounts",
    args_conflicts_with_subcommands = true
)]
pub struct Cli {
    #[command(flatten)]
    show: ShowArgs,
    #[command(subcommand)]
    command: Option<Commands>,
}
#[derive(Subcommand)]
enum Commands {
    Show(ShowArgs),
    History(HistoryArgs),
    Export(ExportArgs),
    Completion {
        #[arg(value_parser=["bash","zsh","fish"])]
        shell: String,
    },
    #[command(hide = true)]
    Complete {
        kind: String,
        prefix: String,
    },
}
#[derive(Args, Clone, Default)]
pub struct ShowArgs {
    #[arg(short, long)]
    account: Vec<String>,
    #[arg(long)]
    alias: Option<String>,
    #[arg(short, long)]
    group: Option<String>,
    #[arg(short, long)]
    provider: Vec<String>,
    #[arg(short, long)]
    query: Vec<String>,
    #[arg(short, long)]
    refresh: bool,
    #[arg(short = 's', long)]
    show_all: bool,
    #[arg(short, long)]
    compact: bool,
    #[arg(short = 'j', long = "json")]
    json_output: bool,
    #[arg(short, long)]
    login: bool,
    #[arg(long)]
    project_id: Option<String>,
    #[arg(long)]
    logout: bool,
    #[arg(long)]
    logout_all: bool,
    /// List supported accounts without fetching quotas
    #[arg(long)]
    list_accounts: bool,
    /// Make the identified supported account active
    #[arg(long)]
    select_account: Option<String>,
    #[arg(long)]
    no_record: bool,
    #[arg(long)]
    verbose: bool,
    #[arg(long)]
    timings: bool,
    #[arg(long, default_value_t = 4000)]
    max_age_ms: u64,
    #[arg(long)]
    cache_ttl: Option<u64>,
}
#[derive(Args)]
struct HistoryArgs {
    #[arg(long,value_parser=["24h","7d","30d","90d"])]
    preset: Option<String>,
    #[arg(long)]
    since: Option<String>,
    #[arg(long)]
    until: Option<String>,
    #[arg(short, long)]
    account: Option<String>,
    #[arg(short, long)]
    provider: Option<String>,
    #[arg(short = 'q', long)]
    quota: Option<String>,
    #[arg(long)]
    table: bool,
    #[arg(long)]
    summary: bool,
    #[arg(long, value_enum)]
    view: Option<View>,
}
#[derive(Clone, Debug, ValueEnum)]
enum View {
    Heatmap,
    Chart,
    Calendar,
    Bars,
    Stats,
}
#[derive(Args)]
struct ExportArgs {
    #[arg(long, value_enum, default_value = "csv")]
    format: Format,
    #[arg(short, long)]
    output: Option<PathBuf>,
    #[arg(long,value_parser=["24h","7d","30d","90d"])]
    preset: Option<String>,
    #[arg(long)]
    since: Option<String>,
    #[arg(long)]
    until: Option<String>,
    #[arg(short, long)]
    account: Option<String>,
    #[arg(short, long)]
    provider: Option<String>,
    #[arg(short = 'q', long)]
    quota: Option<String>,
}
#[derive(Clone, ValueEnum)]
enum Format {
    Csv,
    Markdown,
}
struct Proc;
impl ProcessRunner for Proc {
    fn run(
        &self,
        p: &str,
        args: &[&str],
        _timeout: Duration,
    ) -> Result<crate::providers::base::ProcessOutput> {
        let o = Command::new(p).args(args).output()?;
        Ok(crate::providers::base::ProcessOutput {
            success: o.status.success(),
            stdout: String::from_utf8_lossy(&o.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&o.stderr).into_owned(),
        })
    }
}
#[derive(Serialize)]
struct JsonResult {
    email: String,
    alias: String,
    group: String,
    quotas: Vec<Quota>,
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    timings: Option<Vec<Timing>>,
}
struct Fetch {
    index: usize,
    account: Account,
    quotas: Vec<Quota>,
    error: Option<String>,
    timings: Vec<Timing>,
    client: Option<QuotaClient>,
}
pub fn run() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        None => show(cli.show),
        Some(Commands::Show(x)) => show(x),
        Some(Commands::History(x)) => history(x),
        Some(Commands::Export(x)) => export(x),
        Some(Commands::Completion { shell }) => {
            completions::generate_script(&shell, Cli::command())
        }
        Some(Commands::Complete { kind, prefix }) => {
            for x in completions::candidates(&kind, &prefix) {
                println!("{x}")
            }
            Ok(())
        }
    }
}
fn show(a: ShowArgs) -> Result<()> {
    let config = Config::new(None);
    let mut auth = AuthManager::new(config.auth_path());
    if a.login {
        return login(&mut auth, &a);
    }
    if a.logout_all {
        auth.logout_all()?;
        return status(&a, "success", "Successfully logged out from all accounts.");
    }
    if a.list_accounts {
        let rows = auth
            .supported_accounts()
            .map(|(i, x)| {
                json!({
                    "email": x.email, "alias": x.alias, "group": x.group,
                    "provider": x.provider_type, "active": i == auth.active_index
                })
            })
            .collect::<Vec<_>>();
        if a.json_output {
            println!("{}", serde_json::to_string_pretty(&rows)?);
        } else if rows.is_empty() {
            println!("No supported accounts found.");
        } else {
            for row in rows {
                println!("{}", row);
            }
        }
        return Ok(());
    }
    if let Some(id) = &a.select_account {
        let matches = auth
            .supported_accounts()
            .filter(|(_, x)| x.email == *id || x.identity() == id || x.alias.as_deref() == Some(id))
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return status(&a, "error", "Account not found or ambiguous");
        }
        auth.active_index = matches[0];
        auth.save_accounts()?;
        return status(&a, "success", &format!("Selected account {id}"));
    }
    if a.logout {
        if let Some(id) = a.account.first() {
            if !auth.logout(id)? {
                return status(&a, "error", "Account not found or ambiguous");
            }
            return status(&a, "success", &format!("Successfully logged out {id}"));
        }
        if a.json_output || !io::stdin().is_terminal() {
            return status(
                &a,
                "error",
                "--logout requires --account in non-interactive mode",
            );
        }
        return interactive_logout(&mut auth);
    }
    if !auth.auth_path.exists() {
        return status(&a, "error", "Accounts file not found");
    }
    if auth.accounts.is_empty() {
        return status(&a, "error", "No accounts found");
    }
    if (!a.alias.is_none() || !a.group.is_none() || !a.project_id.is_none())
        && !a.account.is_empty()
    {
        if a.account.len() != 1 {
            return status(&a, "error", "Metadata update requires a single account");
        }
        let target = auth
            .accounts
            .iter()
            .find(|x| x.email == a.account[0] || x.alias.as_deref() == Some(&a.account[0]))
            .map(|x| x.email.clone());
        let Some(email) = target else {
            return status(&a, "error", "Account not found");
        };
        let mut m = BTreeMap::new();
        if a.alias.is_some() {
            m.insert("alias".into(), a.alias.clone());
        }
        if a.group.is_some() {
            m.insert("group".into(), a.group.clone());
        }
        if let Some(p) = &a.project_id {
            m.insert("projectId".into(), Some(p.clone()));
            m.insert("managedProjectId".into(), Some(p.clone()));
        }
        auth.update_account_metadata(&email, &m)?;
        return status(&a, "success", &format!("Updated metadata for {email}"));
    }
    let selected = auth
        .supported_accounts()
        .map(|(i, x)| (i, x.clone()))
        .filter(|(_, x)| {
            (a.account.is_empty()
                || a.account
                    .iter()
                    .any(|v| v == &x.email || Some(v.as_str()) == x.alias.as_deref()))
                && (a.provider.is_empty() || a.provider.contains(&x.provider_type))
                && (a.group.is_none() || !a.account.is_empty() || x.group == a.group)
        })
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return status(&a, "error", "No accounts matching filters");
    }
    let deadline = Instant::now() + Duration::from_millis(a.max_age_ms);
    let http = crate::quota_client::SharedHttp::new()?;
    let (tx, rx) = mpsc::channel();
    for (index, account) in selected.clone() {
        let tx = tx.clone();
        let http = http.clone();
        thread::spawn(move || {
            let mut client = match QuotaClient::new(account.clone()) {
                Ok(x) => x,
                Err(e) => {
                    let _ = tx.send(Fetch {
                        index,
                        account,
                        quotas: vec![],
                        error: Some(e.to_string()),
                        timings: vec![],
                        client: None,
                    });
                    return;
                }
            };
            let start = Instant::now();
            let ctx = RequestContext {
                deadline: Some(deadline),
                ..Default::default()
            };
            let result = futures::executor::block_on(client.fetch(&http, &Proc, &ctx));
            let mut timings = vec![Timing {
                name: "account_total".into(),
                elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                extra: BTreeMap::new(),
            }];
            timings.extend(client.provider().timings());
            timings.extend(http.timings());
            let (q, e) = match result {
                Ok(q) => (q, None),
                Err(e) => (vec![], Some(e.to_string())),
            };
            let _ = tx.send(Fetch {
                index,
                account,
                quotas: q,
                error: e,
                timings,
                client: Some(client),
            });
        });
    }
    drop(tx);
    let mut fetched = Vec::new();
    while fetched.len() < selected.len() {
        let left = deadline.saturating_duration_since(Instant::now());
        match rx.recv_timeout(left) {
            Ok(x) => fetched.push(x),
            Err(_) => break,
        }
    }
    for (index, account) in selected {
        if !fetched.iter().any(|x| x.index == index) {
            fetched.push(Fetch {
                index,
                account: account.clone(),
                quotas: if a.refresh {
                    vec![]
                } else {
                    cached(&account, a.cache_ttl.unwrap_or(config.cache_ttl()))
                },
                error: Some("Timed out (no cached data available)".into()),
                timings: vec![],
                client: QuotaClient::new(account).ok(),
            });
        }
    }
    fetched.sort_by_key(|x| x.index);
    if a.verbose {
        for f in &fetched {
            eprintln!(
                "provider={} quotas={} status={} elapsed_ms={:.1}",
                f.account.provider_type,
                f.quotas.len(),
                if f.error.is_some() { "error" } else { "ok" },
                f.timings.first().map(|t| t.elapsed_ms).unwrap_or(0.0)
            );
            for line in github_verbose(a.verbose, &f.timings) {
                eprintln!("{line}");
            }
        }
    }
    let mut cache_changed = false;
    for f in &mut fetched {
        if let Some(client) = &f.client {
            auth.accounts[f.index] = client.account().clone();
            cache_changed = true;
        }
        if f.error.is_none() && !f.quotas.is_empty() {
            auth.accounts[f.index]
                .extra
                .insert("cachedQuotas".into(), serde_json::to_value(&f.quotas)?);
            auth.accounts[f.index]
                .extra
                .insert("cachedAt".into(), json!(now()));
            cache_changed = true;
        }
    }
    if cache_changed {
        auth.save_accounts()?;
    }
    if !a.no_record && config.history_enabled() {
        let h = HistoryManager::new(Some(config.history_db_path()))?;
        for f in &fetched {
            if f.error.is_none() && !f.quotas.is_empty() {
                let _ =
                    h.record_quotas(&f.account.email, &f.account.provider_type, &f.quotas, None);
            }
        }
    }
    let mut matched = false;
    if a.json_output {
        let mut out = Vec::new();
        for mut f in fetched {
            if let Some(c) = &f.client {
                f.quotas = c.filter(f.quotas, a.show_all)
            }
            f.quotas = display::query_filter(f.quotas, &a.query);
            matched |= !f.quotas.is_empty();
            out.push(JsonResult {
                email: f.account.email,
                alias: f.account.alias.unwrap_or_default(),
                group: f.account.group.unwrap_or_default(),
                quotas: f.quotas,
                error: f.error,
                timings: a.timings.then_some(f.timings),
            });
        }
        println!("{}", serde_json::to_string_pretty(&out)?)
    } else {
        if a.query.is_empty() && !a.compact {
            println!("\nQuota Status")
        }
        for mut f in fetched {
            if let Some(e) = f.error {
                println!(
                    "{}: Warning: {e}",
                    f.account.alias.as_deref().unwrap_or(&f.account.email)
                );
                continue;
            }
            let Some(c) = f.client else { continue };
            f.quotas = c.filter(f.quotas, a.show_all);
            f.quotas = display::query_filter(f.quotas, &a.query);
            matched |= !f.quotas.is_empty();
            if !f.quotas.is_empty() {
                print!(
                    "{}",
                    display::render_quotas(
                        &f.account.email,
                        f.account.alias.as_deref(),
                        f.account.group.as_deref(),
                        c.provider(),
                        f.quotas,
                        a.compact,
                        display::color_enabled(
                            io::stdout().is_terminal(),
                            std::env::var_os("NO_COLOR").is_some()
                        )
                    )
                );
                if !a.compact {
                    let separator = "━".repeat(50);
                    if display::color_enabled(
                        io::stdout().is_terminal(),
                        std::env::var_os("NO_COLOR").is_some(),
                    ) {
                        println!("\x1b[2m{separator}\x1b[0m")
                    } else {
                        println!("{separator}")
                    }
                }
            }
        }
    }
    if !a.query.is_empty() && !matched {
        bail!("No quotas matched query")
    }
    Ok(())
}

/// Render the deliberately narrow GitHub diagnostic contract. Unknown trace
/// fields are ignored so credentials and response data can never be emitted.
pub fn github_verbose(verbose: bool, timings: &[crate::model::Timing]) -> Vec<String> {
    if !verbose {
        return vec![];
    }
    timings
        .iter()
        .filter_map(|trace| match trace.name.as_str() {
            "github_request" => Some(format!(
                "[GitHub] {} {} status={}",
                trace.extra.get("method")?,
                trace.extra.get("path")?,
                trace.extra.get("status")?
            )),
            "github_selection" => trace
                .extra
                .get("outcome")
                .map(|outcome| format!("[GitHub] {outcome}")),
            _ => None,
        })
        .collect()
}

fn interactive_logout(auth: &mut AuthManager) -> Result<()> {
    let accounts = auth
        .supported_accounts()
        .map(|(_, a)| a.clone())
        .collect::<Vec<_>>();
    if accounts.is_empty() {
        println!("No accounts found to log out from.");
        return Ok(());
    }
    let mut providers = Vec::new();
    for provider in ["github_copilot", "openai", "chutes", "openrouter"] {
        if accounts.iter().any(|a| a.provider_type == provider) {
            providers.push(provider);
        }
    }
    println!("Select Provider to log out from:");
    for (index, provider) in providers.iter().enumerate() {
        let count = accounts
            .iter()
            .filter(|a| a.provider_type == *provider)
            .count();
        let label = match *provider {
            "github_copilot" => "GitHub Copilot",
            "openai" => "OpenAI",
            "chutes" => "Chutes",
            "openrouter" => "OpenRouter",
            _ => provider,
        };
        println!(
            "{}) {label} ({count} account{})",
            index + 1,
            if count == 1 { "" } else { "s" }
        );
    }
    let provider_choice = prompt("Enter choice [1]: ")?;
    let index = choice_index(&provider_choice, providers.len());
    let Some(provider) = index.and_then(|i| providers.get(i)) else {
        println!("Invalid choice.");
        return Ok(());
    };
    let provider_accounts = accounts
        .iter()
        .filter(|a| a.provider_type == *provider)
        .collect::<Vec<_>>();
    let account = if provider_accounts.len() == 1 {
        provider_accounts[0]
    } else {
        println!("Select Account to log out:");
        for (index, account) in provider_accounts.iter().enumerate() {
            println!(
                "{}) {}",
                index + 1,
                account.alias.as_deref().unwrap_or(&account.email)
            );
        }
        let account_choice = prompt("Enter choice [1]: ")?;
        let Some(account) = choice_index(&account_choice, provider_accounts.len())
            .and_then(|i| provider_accounts.get(i))
        else {
            println!("Invalid choice.");
            return Ok(());
        };
        account
    };
    let label = account
        .alias
        .as_deref()
        .unwrap_or(&account.email)
        .to_owned();
    let answer = prompt(&format!("Log out {label}? [y/N]: "))?;
    if !matches!(answer.to_ascii_lowercase().as_str(), "y" | "yes") {
        println!("Logout cancelled.");
        return Ok(());
    }
    auth.logout(&account.email)?;
    println!("Successfully logged out {label}");
    Ok(())
}

fn choice_index(value: &str, len: usize) -> Option<usize> {
    let choice = if value.is_empty() {
        1
    } else {
        value.parse().ok()?
    };
    (choice > 0 && choice <= len).then_some(choice - 1)
}
fn cached(a: &Account, ttl: u64) -> Vec<Quota> {
    let at = a
        .extra
        .get("cachedAt")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    if ttl == 0 || now() - at > ttl as f64 {
        return vec![];
    }
    a.extra
        .get("cachedQuotas")
        .cloned()
        .and_then(|x| serde_json::from_value(x).ok())
        .unwrap_or_default()
}
fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
fn status(a: &ShowArgs, status: &str, message: &str) -> Result<()> {
    if a.json_output {
        println!("{}", json!({"status":status,"message":message}))
    } else {
        println!("{message}")
    }
    Ok(())
}
fn login(auth: &mut AuthManager, a: &ShowArgs) -> Result<()> {
    let p = if let Some(p) = a.provider.first() {
        p.as_str()
    } else if io::stdin().is_terminal() && io::stdout().is_terminal() && !a.json_output {
        eprint!(
            "Select provider [1] GitHub Copilot [2] OpenAI [3] Chutes [4] OpenRouter (default 1): "
        );
        io::stderr().flush()?;
        let mut value = String::new();
        io::stdin().read_line(&mut value)?;
        match value.trim() {
            "2" | "openai" => "openai",
            "3" | "chutes" => "chutes",
            "4" | "openrouter" => "openrouter",
            _ => "github_copilot",
        }
    } else {
        "github_copilot"
    };
    let mut client = QuotaClient::new(Account {
        provider_type: p.into(),
        email: "pending".into(),
        ..Default::default()
    })?;
    let mut input = std::env::var("LIMITWATCH_LOGIN_JSON")
        .ok()
        .and_then(|x| serde_json::from_str(&x).ok())
        .unwrap_or(Value::Null);
    if p == "github_copilot" && input.is_null() {
        input = github_login_input(
            &crate::quota_client::SharedHttp::new()?,
            &Proc,
            &RequestContext::default(),
        )?;
    }
    let account = futures::executor::block_on(client.login(
        input,
        &crate::quota_client::SharedHttp::new()?,
        &Proc,
        &RequestContext::default(),
    ))?;
    let email = auth.login(account)?;
    status(a, "success", &format!("Successfully logged in as {email}"))
}
fn prompt(message: &str) -> Result<String> {
    eprint!("{message}");
    io::stderr().flush()?;
    let mut value = String::new();
    io::stdin().read_line(&mut value)?;
    Ok(value.trim().to_owned())
}
fn github_login_input(
    http: &dyn HttpClient,
    proc: &dyn ProcessRunner,
    ctx: &RequestContext,
) -> Result<Value> {
    use crate::providers::github_copilot::GitHubCopilotProvider as G;
    let accounts = G::discover_gh_accounts(proc, ctx);
    let mut selected = accounts.first().cloned();
    if accounts.len() > 1 {
        eprintln!("\nSelect a GitHub account:");
        for (i, user) in accounts.iter().enumerate() {
            eprintln!("{}) {user}", i + 1);
        }
        let choice = prompt("Enter choice [1]: ")?;
        let index: usize = if choice.is_empty() {
            1
        } else {
            choice.parse().unwrap_or(0)
        };
        selected = accounts.get(index.saturating_sub(1)).cloned();
        if selected.is_none() {
            bail!("A GitHub account selection is required")
        }
    }
    let mut source = "gh_cli";
    let token_user = (accounts.len() > 1)
        .then_some(selected.as_deref())
        .flatten();
    let token = if let Some(token) = G::gh_token(proc, token_user, ctx)? {
        eprintln!("✓ GitHub CLI token found");
        token
    } else {
        eprintln!("⚠ Could not load GitHub CLI token");
        source = "manual";
        let token = prompt("Enter GitHub token (or press Enter to skip): ")?;
        if token.is_empty() {
            bail!("GitHub token is required")
        }
        token
    };
    let include = prompt("Include work/organization Copilot credits? [y/N]: ")?;
    let mut organization = None;
    if matches!(include.to_lowercase().as_str(), "y" | "yes") {
        eprintln!("Discovering organizations...");
        let orgs = G::discover_organizations(http, &token, ctx).unwrap_or_default();
        if orgs.is_empty() {
            organization = Some(prompt(
                "Enter organization name (optional, for work quotas): ",
            )?)
            .filter(|s| !s.is_empty());
        } else {
            eprintln!(
                "Found {} organization(s)\n\nSelect an organization (or press Enter to skip):",
                orgs.len()
            );
            for (i, org) in orgs.iter().enumerate() {
                eprintln!("{}) {org}", i + 1);
            }
            eprintln!("0) Skip (personal only)");
            let choice = prompt("Enter choice [0]: ")?.parse::<usize>().unwrap_or(0);
            organization = choice.checked_sub(1).and_then(|i| orgs.get(i)).cloned();
        }
    }
    Ok(
        json!({"githubToken":token,"token_source":source,"github_account":selected,"organization":organization}),
    )
}
fn history(a: HistoryArgs) -> Result<()> {
    let c = Config::new(None);
    let h = HistoryManager::new(Some(c.history_db_path()))?;
    if a.summary {
        return print_ok(display::history_summary(&h.get_database_info()?));
    }
    if let Some(v) = a.view {
        let name = format!("{v:?}").to_lowercase();
        return print_ok(display::weekly(
            &name,
            &h.get_weekly_activity(a.account.as_deref(), a.provider.as_deref())?,
        ));
    }
    let preset = a
        .preset
        .as_deref()
        .or(if a.since.is_none() { Some("24h") } else { None });
    let d = h.get_history(
        preset,
        a.since.as_deref(),
        a.until.as_deref(),
        a.account.as_deref(),
        a.provider.as_deref(),
        a.quota.as_deref(),
    )?;
    print_ok(if a.table {
        display::history_table(&d)
    } else {
        display::history_sparklines(&d)
    })
}
fn export(a: ExportArgs) -> Result<()> {
    let c = Config::new(None);
    let h = HistoryManager::new(Some(c.history_db_path()))?;
    let e = Exporter { history: &h };
    let f = ExportFilter {
        preset: a
            .preset
            .as_deref()
            .or(if a.since.is_none() { Some("7d") } else { None }),
        since: a.since.as_deref(),
        until: a.until.as_deref(),
        account_email: a.account.as_deref(),
        provider_type: a.provider.as_deref(),
        quota_name: a.quota.as_deref(),
    };
    let s = match a.format {
        Format::Csv => e.export_csv(a.output.as_deref(), &f)?,
        Format::Markdown => e.export_markdown(a.output.as_deref(), &f)?,
    };
    if let Some(p) = a.output {
        println!("Exported to {}", p.display())
    } else {
        print!("{s}")
    }
    Ok(())
}
fn print_ok(s: String) -> Result<()> {
    print!("{s}");
    Ok(())
}
