# ====================================================================
# Phase 10 batch 3 tests: weather, stock_crypto, maps
# ====================================================================
from __future__ import annotations

import pytest

from backend.tools import get_registry, RiskTier


def test_phase10_batch3_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.weather.plugin",
        "plugins.stock_crypto.plugin",
        "plugins.maps.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    for required in ["weather.now", "weather.forecast", "finance.quote",
                     "finance.crypto", "finance.trending",
                     "maps.geocode", "maps.search_nearby", "maps.directions"]:
        assert required in names, f"{required} missing"


def test_batch3_all_tools_are_observe_tier():
    """Weather, finance, and maps are read-only — must be Tier 0."""
    reg = get_registry()
    for t in reg.all_tools():
        if t.category in {"weather", "finance", "maps"}:
            assert t.risk_tier is RiskTier.TIER_0_OBSERVE, (
                f"{t.name} should be Tier 0 observe, got {t.risk_tier}"
            )


def test_weather_wmo_code_lookup_table_covers_common_conditions():
    """The WMO code table should include the obvious cases."""
    import plugins.weather.plugin as w
    assert w.WMO_CODES[0] == "Clear sky"
    assert "rain" in w.WMO_CODES[63].lower()
    assert "thunderstorm" in w.WMO_CODES[95].lower()
    assert "snow" in w.WMO_CODES[71].lower()
