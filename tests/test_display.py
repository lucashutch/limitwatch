from unittest.mock import MagicMock, patch
from gemini_quota.display import DisplayManager


def test_display_manager_filter_quotas():
    display = DisplayManager()
    client = MagicMock()

    quotas = [
        {"display_name": "Gemini 3 Pro (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.5 Pro (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.0 Flash (AG)", "source_type": "Antigravity"},
        {"display_name": "Claude (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.5 Flash (CLI)", "source_type": "Gemini CLI"},
    ]

    # Mock client filtering (delegate to real GoogleProvider for realistic test or just mock)
    # Let's mock it to return what we expect for Google
    client.filter_quotas.side_effect = lambda qs, show_all: [
        q
        for q in qs
        if show_all
        or (
            "2.0" not in q["display_name"]
            and (
                "3" in q["display_name"]
                or "Claude" in q["display_name"]
                or "CLI" in q["source_type"]
            )
        )
    ]

    # Test default filtering (no show_all)
    filtered = display.filter_quotas(quotas, client, show_all=False)

    assert not any("2.0" in q["display_name"] for q in filtered)
    assert not any("2.5 Pro (AG)" == q["display_name"] for q in filtered)
    assert any("Gemini 2.5 Flash (CLI)" == q["display_name"] for q in filtered)
    assert any("Claude (AG)" == q["display_name"] for q in filtered)
    assert any("Gemini 3 Pro (AG)" == q["display_name"] for q in filtered)


def test_display_manager_show_all():
    display = DisplayManager()
    client = MagicMock()

    quotas = [
        {"display_name": "Gemini 2.0 Flash (CLI)", "source_type": "Gemini CLI"},
    ]

    client.filter_quotas.side_effect = lambda qs, show_all: [
        q for q in qs if show_all or "2.0" not in q["display_name"]
    ]

    # Should be empty by default
    assert len(display.filter_quotas(quotas, client, show_all=False)) == 0

    # Should be shown with show_all
    assert len(display.filter_quotas(quotas, client, show_all=True)) == 1


def test_display_manager_headers():
    display = DisplayManager()
    display.console = MagicMock()

    display.print_main_header()
    display.console.print.assert_called_with("\n[bold blue]Quota Status[/bold blue]")

    display.print_account_header("test@example.com")
    display.console.print.assert_called_with("[dim]📧 test@example.com[/dim]")

    display.print_account_header("test@example.com", provider="Google")
    display.console.print.assert_called_with("[dim]📧 Google: test@example.com[/dim]")


def test_draw_quota_bars_no_quotas():
    display = DisplayManager()
    display.console = MagicMock()
    client = MagicMock()

    display.draw_quota_bars([], client)
    display.console.print.assert_called_with(
        "[yellow]No active quota information found.[/yellow]"
    )


def test_draw_quota_bars_with_quotas():
    display = DisplayManager()
    display.console = MagicMock()
    display.console.width = 80
    client = MagicMock()

    quotas = [
        {
            "display_name": "Model A",
            "remaining_pct": 85,
            "reset": "2026-02-19T20:00:00Z",
        },
        {"display_name": "Model B", "remaining_pct": 45, "reset": 1739999999000},
        {"display_name": "Model C", "remaining_pct": 10},
    ]

    client.filter_quotas.return_value = quotas
    client.get_sort_key.side_effect = lambda q: q["display_name"]
    client.get_color.return_value = "blue"

    display.draw_quota_bars(quotas, client)

    # Verify print was called for each quota
    assert display.console.print.call_count == len(quotas)


def test_draw_quota_bars_timestamp_parsing():
    display = DisplayManager()
    display.console = MagicMock()
    display.console.width = 80
    client = MagicMock()

    # Test ISO timestamp
    quotas = [
        {"display_name": "Model", "remaining_pct": 50, "reset": "2026-02-19T20:00:00Z"}
    ]
    client.filter_quotas.return_value = quotas
    client.get_sort_key.return_value = (0, 0, "")
    client.get_color.return_value = "blue"

    display.draw_quota_bars(quotas, client)
    assert display.console.print.called

    # Test epoch timestamp
    quotas[0]["reset"] = 1739999999
    display.draw_quota_bars(quotas, client)
    assert display.console.print.called


def test_draw_quota_bars_no_client():
    display = DisplayManager()
    display.console = MagicMock()
    display.console.width = 80

    quotas = [{"display_name": "Model", "remaining_pct": 50}]
    display.draw_quota_bars(quotas, None)
    display.console.print.assert_called()
