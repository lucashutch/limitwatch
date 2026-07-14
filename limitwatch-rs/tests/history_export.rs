use chrono::{TimeZone, Utc};
use limitwatch::export::{ExportFilter, Exporter};
use limitwatch::history::HistoryManager;
use limitwatch::model::Quota;

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
    mgr.record_quotas("a@example.com", "google", &[q.clone()], Some(t))
        .unwrap();
    q.remaining_pct = Some(70.0);
    mgr.record_quotas(
        "a@example.com",
        "google",
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
    assert!(csv.contains("a@example.com,google,quota,Quota,70"));
    let md = ex.export_markdown(None, &ExportFilter::default()).unwrap();
    assert!(md.contains("| a | google | Quota | 70.0% | 20 | 100 |"));
    assert_eq!(mgr.purge_data("2024-01-16T00:00:00Z").unwrap(), 1);
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
