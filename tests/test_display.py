from unittest.mock import MagicMock
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
