use chrono::{TimeZone, Utc};
use limitwatch::export::{ExportFilter, Exporter};
use limitwatch::history::HistoryManager;
use limitwatch::model::Quota;
use limitwatch::storage::Storage;

#[test]
fn replacement_queries_stats_purge_and_exports() {
    let dir = tempfile::tempdir().unwrap();
    let mgr = HistoryManager::new(Some(dir.path().join("history.db"))).unwrap();
    let mut q = Quota {
        name: "quota".into(),
        display_name: "Quota".into(),
        remaining_pct: Some(80.0),
        used: Some(20.0),
        limit: Some(100.0),
        ..Default::default()
    };
    let t = Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap();
    mgr.record_quotas("a@example.com", "openai", &[q.clone()], Some(t))
        .unwrap();
    q.remaining_pct = Some(70.0);
    mgr.record_quotas(
        "a@example.com",
        "openai",
        &[q],
        Some(t + chrono::Duration::minutes(15)),
    )
    .unwrap();
    assert_eq!(
        mgr.get_history(None, None, None, None, None, None)
            .unwrap()
            .len(),
        1
    );
    let agg = mgr.get_aggregation(None, None, None, None, None).unwrap();
    assert_eq!(agg[0].avg_remaining, Some(70.0));
    let ex = Exporter { history: &mgr };
    let csv = ex.export_csv(None, &ExportFilter::default()).unwrap();
    assert_eq!(
        csv,
        "timestamp,account_email,provider_type,quota_name,display_name,remaining_pct,used,limit,reset_time\r\n2024-01-15T10:45:00+00:00,a@example.com,openai,quota,Quota,70.0,20.0,100.0,\r\n"
    );
    let md = ex.export_markdown(None, &ExportFilter::default()).unwrap();
    assert!(md.contains("# Quota History Export\n\nGenerated: "));
    assert!(md.contains("| a | openai | Quota | 70.0% | 20 | 100 |"));
    assert_eq!(mgr.purge_data("2024-01-16T00:00:00Z").unwrap(), 1);
}

#[test]
fn google_records_are_stored_but_ignored_by_history_views() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("history.db");
    let storage = Storage::new(Some(&path)).unwrap();
    let quota = Quota {
        name: "quota".into(),
        remaining_pct: Some(80.0),
        used: Some(20.0),
        limit: Some(100.0),
        ..Default::default()
    };
    assert_eq!(
        storage
            .record_quotas(
                "google@example.com",
                "google",
                &[quota],
                Some(Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap()),
            )
            .unwrap(),
        1
    );
    let connection = rusqlite::Connection::open(&path).unwrap();
    assert_eq!(
        connection
            .query_row("SELECT COUNT(*) FROM quota_snapshots", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        1
    );

    let mgr = HistoryManager::new(Some(&path)).unwrap();
    assert!(mgr
        .get_history(None, None, None, None, None, None)
        .unwrap()
        .is_empty());
    assert!(mgr
        .get_aggregation(None, None, None, None, None)
        .unwrap()
        .is_empty());
    assert!(Exporter { history: &mgr }
        .export_csv(None, &ExportFilter::default())
        .unwrap()
        .is_empty());
    assert!(!mgr
        .get_available_filters()
        .unwrap()
        .1
        .contains(&"google".to_owned()));
}

#[test]
fn skips_error_and_filters() {
    let dir = tempfile::tempdir().unwrap();
    let mgr = HistoryManager::new(Some(dir.path().join("h.db"))).unwrap();
    let mut q = Quota {
        name: "bad".into(),
        ..Default::default()
    };
    q.extra.insert("is_error".into(), serde_json::json!(true));
    assert_eq!(mgr.record_quotas("a", "google", &[q], None).unwrap(), 0);
    assert!(mgr
        .get_history(None, None, None, Some("a"), None, None)
        .unwrap()
        .is_empty());
}
