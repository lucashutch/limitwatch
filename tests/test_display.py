from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from limitwatch.display import (
    DisplayManager,
    apply_query_filter,
    extract_percentages,
    get_bar_color,
    format_time_delta,
    parse_reset_datetime,
    get_reset_string,
    render_compact_bar,
    render_normal_bar,
)


# --- Pure helper function tests ---


class TestApplyQueryFilter:
    def test_no_query_returns_as_is(self):
        quotas = [{"name": "a"}]
        assert apply_query_filter(quotas, None) == quotas
        assert apply_query_filter(quotas, []) == quotas

    def test_empty_quotas(self):
        assert apply_query_filter([], "test") == []

    def test_single_string_query(self):
        quotas = [
            {"name": "Gemini Pro", "display_name": "Gemini Pro"},
            {"name": "Claude", "display_name": "Claude"},
        ]
        result = apply_query_filter(quotas, "gemini")
        assert len(result) == 1
        assert result[0]["name"] == "Gemini Pro"

    def test_list_query_and_filter(self):
        quotas = [
            {"name": "Gemini Pro", "display_name": "Gemini Pro (CLI)"},
            {"name": "Gemini Flash", "display_name": "Gemini Flash (CLI)"},
            {"name": "Claude", "display_name": "Claude (AG)"},
        ]
        result = apply_query_filter(quotas, ["gemini", "pro"])
        assert len(result) == 1
        assert result[0]["name"] == "Gemini Pro"

    def test_case_insensitive(self):
        quotas = [{"name": "GEMINI", "display_name": "TEST"}]
        assert len(apply_query_filter(quotas, "gemini")) == 1

    def test_matches_display_name(self):
        quotas = [{"name": "x", "display_name": "Special Model"}]
        assert len(apply_query_filter(quotas, "special")) == 1


class TestExtractPercentages:
    def test_remaining_only(self):
        shown, is_used, remaining = extract_percentages({"remaining_pct": 75})
        assert shown == 75.0
        assert is_used is False
        assert remaining == 75

    def test_used_pct_provided(self):
        shown, is_used, remaining = extract_percentages(
            {"used_pct": 30, "remaining_pct": 70}
        )
        assert shown == 30.0
        assert is_used is True
        assert remaining == 70

    def test_defaults(self):
        shown, is_used, remaining = extract_percentages({})
        assert shown == 100.0
        assert is_used is False
        assert remaining == 100

    def test_used_pct_zero(self):
        shown, is_used, remaining = extract_percentages({"used_pct": 0})
        assert shown == 0.0
        assert is_used is True


class TestGetBarColor:
    def test_used_mode_green(self):
        assert get_bar_color(10, True) == "green"

    def test_used_mode_yellow(self):
        assert get_bar_color(30, True) == "yellow"

    def test_used_mode_red(self):
        assert get_bar_color(80, True) == "red"

    def test_remaining_mode_red(self):
        assert get_bar_color(10, False) == "red"

    def test_remaining_mode_yellow(self):
        assert get_bar_color(30, False) == "yellow"

    def test_remaining_mode_green(self):
        assert get_bar_color(80, False) == "green"

    def test_boundary_20(self):
        assert get_bar_color(20, True) == "green"
        assert get_bar_color(20, False) == "red"

    def test_boundary_50(self):
        assert get_bar_color(50, True) == "yellow"
        assert get_bar_color(50, False) == "yellow"


class TestFormatTimeDelta:
    def test_zero_seconds(self):
        assert format_time_delta(timedelta(seconds=0)) == ""

    def test_negative(self):
        assert format_time_delta(timedelta(seconds=-60)) == ""

    def test_minutes_only(self):
        result = format_time_delta(timedelta(minutes=30))
        assert "30m" in result

    def test_hours_and_minutes(self):
        result = format_time_delta(timedelta(hours=2, minutes=15))
        assert "2h" in result
        assert "15m" in result

    def test_days_hours_minutes(self):
        result = format_time_delta(timedelta(days=1, hours=3, minutes=5))
        assert "1d" in result
        assert "3h" in result
        assert "5m" in result

    def test_zero_minutes_with_hours(self):
        result = format_time_delta(timedelta(hours=1))
        assert "1h" in result

    def test_only_seconds(self):
        result = format_time_delta(timedelta(seconds=30))
        assert "0m" in result


class TestParseResetDatetime:
    def test_iso_string(self):
        dt = parse_reset_datetime("2026-02-19T20:00:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_epoch_seconds(self):
        dt = parse_reset_datetime(1739999999)
        assert dt is not None

    def test_epoch_millis(self):
        dt = parse_reset_datetime(1739999999000)
        assert dt is not None

    def test_non_iso_string(self):
        assert parse_reset_datetime("Monthly") is None

    def test_invalid_string(self):
        assert parse_reset_datetime("not-a-date") is None

    def test_none(self):
        assert parse_reset_datetime(None) is None

    def test_list(self):
        assert parse_reset_datetime([1, 2, 3]) is None


class TestGetResetString:
    def test_unknown_returns_empty(self):
        assert get_reset_string("Unknown", 50) == ""

    def test_100_pct_remaining(self):
        assert get_reset_string("2026-02-19T20:00:00Z", 100) == ""

    def test_valid_future_reset(self):
        future = (
            (datetime.now(timezone.utc) + timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        result = get_reset_string(future, 50)
        assert "h" in result or "m" in result

    def test_invalid_reset_info(self):
        assert get_reset_string("Monthly", 50) == ""

    def test_epoch_reset(self):
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=3)).timestamp()
        result = get_reset_string(future_ts, 50)
        assert "h" in result or "m" in result


class TestRenderCompactBar:
    def test_zero_percent(self):
        bar = render_compact_bar(0, 10, "green")
        assert "[green]" in bar
        assert "[/]" in bar

    def test_100_percent(self):
        bar = render_compact_bar(100, 10, "red")
        assert "█" * 10 in bar

    def test_50_percent(self):
        bar = render_compact_bar(50, 10, "yellow")
        assert "█" * 5 in bar


class TestRenderNormalBar:
    def test_zero_percent(self):
        bar = render_normal_bar(0, 10, "green")
        assert "[green]" in bar

    def test_100_percent(self):
        bar = render_normal_bar(100, 10, "red")
        assert "█" * 10 in bar

    def test_fractional(self):
        bar = render_normal_bar(55, 20, "yellow")
        assert "█" in bar

    def test_full_bar(self):
        bar = render_normal_bar(100, 5, "green")
        assert "█" * 5 in bar


# --- DisplayManager class tests ---


class TestDisplayManagerFilterQuotas:
    def test_filter_quotas_delegates(self):
        display = DisplayManager()
        client = MagicMock()
        quotas = [
            {"display_name": "Gemini 3 Pro (AG)", "source_type": "Antigravity"},
            {"display_name": "Gemini 2.5 Pro (AG)", "source_type": "Antigravity"},
            {"display_name": "Gemini 2.0 Flash (AG)", "source_type": "Antigravity"},
            {"display_name": "Claude (AG)", "source_type": "Antigravity"},
            {"display_name": "Gemini 2.5 Flash (CLI)", "source_type": "Gemini CLI"},
        ]

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

        filtered = display.filter_quotas(quotas, client, show_all=False)
        assert not any("2.0" in q["display_name"] for q in filtered)
        assert any("Claude (AG)" == q["display_name"] for q in filtered)
        assert any("Gemini 3 Pro (AG)" == q["display_name"] for q in filtered)

    def test_filter_quotas_no_client(self):
        display = DisplayManager()
        quotas = [{"name": "test"}]
        assert display.filter_quotas(quotas, None) == quotas

    def test_filter_quotas_no_quotas(self):
        display = DisplayManager()
        assert display.filter_quotas([], MagicMock()) == []


class TestDisplayManagerShowAll:
    def test_show_all(self):
        display = DisplayManager()
        client = MagicMock()
        quotas = [
            {"display_name": "Gemini 2.0 Flash (CLI)", "source_type": "Gemini CLI"}
        ]

        client.filter_quotas.side_effect = lambda qs, show_all: [
            q for q in qs if show_all or "2.0" not in q["display_name"]
        ]

        assert len(display.filter_quotas(quotas, client, show_all=False)) == 0
        assert len(display.filter_quotas(quotas, client, show_all=True)) == 1


class TestDisplayManagerHeaders:
    def test_main_header(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_main_header()
        display.console.print.assert_called_with(
            "\n[bold blue]Quota Status[/bold blue]"
        )

    def test_account_header_email_only(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_account_header("test@example.com")
        display.console.print.assert_called_with("[dim]📧 test@example.com[/dim]")

    def test_account_header_with_provider(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_account_header("test@example.com", provider="Google")
        display.console.print.assert_called_with(
            "[dim]📧 Google: test@example.com[/dim]"
        )

    def test_account_header_with_alias(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_account_header("test@example.com", alias="MyAlias")
        assert "MyAlias" in display.console.print.call_args[0][0]

    def test_account_header_with_alias_and_group(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_account_header("test@example.com", alias="MyAlias", group="work")
        call_arg = display.console.print.call_args[0][0]
        assert "MyAlias" in call_arg
        assert "test@example.com|work" in call_arg

    def test_account_header_with_group_no_alias(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.print_account_header("test@example.com", group="team")
        call_arg = display.console.print.call_args[0][0]
        assert "team" in call_arg


class TestDrawQuotaBars:
    def test_no_quotas(self):
        display = DisplayManager()
        display.console = MagicMock()
        client = MagicMock()
        display.draw_quota_bars([], client)
        display.console.print.assert_called_with(
            "[yellow]No active quota information found.[/yellow]"
        )

    def test_with_quotas(self):
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
        assert display.console.print.call_count == len(quotas)

    def test_compact_mode(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()
        client.short_indicator = "G"
        client.primary_color = "cyan"

        quotas = [{"display_name": "Model A", "remaining_pct": 85}]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")

        display.draw_quota_bars(quotas, client, compact=True, account_name="test")
        assert display.console.print.called

    def test_no_client(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        quotas = [{"display_name": "Model", "remaining_pct": 50}]
        display.draw_quota_bars(quotas, None)
        display.console.print.assert_called()

    def test_empty_message_no_premium(self):
        display = DisplayManager()
        display.console = MagicMock()
        client = MagicMock()
        client.filter_quotas.return_value = []

        # Original quotas exist but filtering removed them
        display.draw_quota_bars([{"display_name": "X"}], client, show_all=False)
        call_arg = display.console.print.call_args[0][0]
        assert "premium" in call_arg or "No active" in call_arg

    def test_empty_message_show_all(self):
        display = DisplayManager()
        display.console = MagicMock()
        client = MagicMock()
        client.filter_quotas.return_value = []

        display.draw_quota_bars([{"display_name": "X"}], client, show_all=True)
        call_arg = display.console.print.call_args[0][0]
        assert "No active" in call_arg

    def test_error_quota_normal(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [
            {
                "display_name": "Error Model",
                "is_error": True,
                "message": "Verify required",
                "url": "https://example.com",
            }
        ]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")
        client.get_color.return_value = "white"

        display.draw_quota_bars(quotas, client)
        call_arg = display.console.print.call_args[0][0]
        assert "Verify required" in call_arg

    def test_error_quota_no_url(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [
            {"display_name": "Error Model", "is_error": True, "message": "Broken"}
        ]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")
        client.get_color.return_value = "white"

        display.draw_quota_bars(quotas, client)
        call_arg = display.console.print.call_args[0][0]
        assert "Broken" in call_arg

    def test_used_pct_display(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [{"display_name": "Copilot", "used_pct": 45, "remaining_pct": 55}]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")
        client.get_color.return_value = "white"

        display.draw_quota_bars(quotas, client)
        call_arg = display.console.print.call_args[0][0]
        assert "used" in call_arg

    def test_compact_error_quota(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()
        client.short_indicator = "G"
        client.primary_color = "cyan"

        quotas = [
            {"display_name": "Error Model", "is_error": True, "message": "Broken"}
        ]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")

        display.draw_quota_bars(quotas, client, compact=True, account_name="test")
        call_arg = display.console.print.call_args[0][0]
        assert "Broken" in call_arg

    def test_query_filter_in_draw(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [
            {"name": "pro", "display_name": "Gemini Pro", "remaining_pct": 80},
            {"name": "flash", "display_name": "Gemini Flash", "remaining_pct": 60},
        ]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "a")
        client.get_color.return_value = "blue"

        display.draw_quota_bars(quotas, client, query="pro")
        # Should only render 1 quota line
        assert display.console.print.call_count == 1

    def test_timestamp_parsing_iso(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [
            {
                "display_name": "Model",
                "remaining_pct": 50,
                "reset": "2026-02-19T20:00:00Z",
            }
        ]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "")
        client.get_color.return_value = "blue"

        display.draw_quota_bars(quotas, client)
        assert display.console.print.called

    def test_timestamp_parsing_epoch(self):
        display = DisplayManager()
        display.console = MagicMock()
        display.console.width = 80
        client = MagicMock()

        quotas = [{"display_name": "Model", "remaining_pct": 50, "reset": 1739999999}]
        client.filter_quotas.return_value = quotas
        client.get_sort_key.return_value = (0, 0, "")
        client.get_color.return_value = "blue"

        display.draw_quota_bars(quotas, client)
        assert display.console.print.called
