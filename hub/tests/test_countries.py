"""Test countries handler logic."""
import json
import pytest
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "bot" / "data"


@pytest.fixture
def countries():
    with open(DATA_DIR / "countries.json", "r", encoding="utf-8") as f:
        return json.load(f)["countries"]


def test_search_by_name(countries):
    query = "germany"
    results = [c for c in countries if query.lower() in c["name"].lower()]
    assert len(results) == 1
    assert results[0]["code"] == "DE"


def test_search_by_code(countries):
    codes = {c["code"]: c for c in countries}
    assert "US" in codes
    assert "GB" in codes
    assert "RU" in codes


def test_search_by_russian_name(countries):
    query = "герман"
    results = [c for c in countries if query.lower() in c.get("name_ru", "").lower()]
    assert len(results) >= 1


def test_filter_by_region(countries):
    regions = {}
    for c in countries:
        r = c["region"]
        regions[r] = regions.get(r, 0) + 1
    assert "Europe" in regions
    assert "CIS" in regions
    assert regions["Europe"] >= 20


def test_filter_by_vertical(countries):
    gambling_allowed = [c for c in countries
                        if c.get("gambling", {}).get("status") == "allowed"]
    assert len(gambling_allowed) >= 5, "Should have countries where gambling is allowed"


def test_free_tier_limit(countries):
    free_limit = 3
    assert len(countries) > free_limit
    free_codes = {c["code"] for c in countries[:free_limit]}
    assert len(free_codes) == free_limit
