from src.display import DisplayManager


def test_display_manager_filter_quotas():
    display = DisplayManager()

    quotas = [
        {"display_name": "Gemini 3 Pro (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.5 Pro (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.0 Flash (AG)", "source_type": "Antigravity"},
        {"display_name": "Claude (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.5 Flash (CLI)", "source_type": "Gemini CLI"},
    ]

    # Test default filtering (no show_all)
    filtered = display.filter_quotas(quotas, show_all=False)

    # 2.0 Flash should ALWAYS be hidden

    assert not any("2.0" in q["display_name"] for q in filtered)

    # AG has premium (Gemini 3, Claude), so 2.5 should be hidden for AG
    assert not any("2.5 Pro (AG)" == q["display_name"] for q in filtered)

    # CLI has NO premium, so 2.5 should be shown for CLI
    assert any("Gemini 2.5 Flash (CLI)" == q["display_name"] for q in filtered)

    # Claude and Gemini 3 should always be shown
    assert any("Claude (AG)" == q["display_name"] for q in filtered)
    assert any("Gemini 3 Pro (AG)" == q["display_name"] for q in filtered)


def test_display_manager_show_all():
    display = DisplayManager()

    quotas = [
        {"display_name": "Gemini 2.0 Flash (CLI)", "source_type": "Gemini CLI"},
    ]

    # Should be empty by default
    assert len(display.filter_quotas(quotas, show_all=False)) == 0

    # Should be shown with show_all
    assert len(display.filter_quotas(quotas, show_all=True)) == 1
