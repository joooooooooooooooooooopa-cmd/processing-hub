"""Test glossary handler logic."""
import json
import pytest
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "bot" / "data"


@pytest.fixture
def terms():
    with open(DATA_DIR / "glossary.json", "r", encoding="utf-8") as f:
        return json.load(f)["terms"]


def test_search_by_term(terms):
    query = "chargeback"
    results = [t for t in terms if query.lower() in t["term"].lower()]
    assert len(results) >= 1, "Should find 'chargeback'"


def test_search_by_russian(terms):
    query = "возврат"
    results = [t for t in terms if query.lower() in t.get("term_ru", "").lower()
               or query.lower() in t.get("definition", "").lower()]
    assert len(results) >= 1


def test_filter_by_category(terms):
    for cat in ["disputes", "acquiring", "compliance", "finance", "risk", "tech", "traffic", "crypto"]:
        filtered = [t for t in terms if t["category"] == cat]
        assert len(filtered) >= 10, f"Category {cat} has only {len(filtered)} terms"


def test_pagination(terms):
    per_page = 5
    total_pages = (len(terms) + per_page - 1) // per_page
    assert total_pages >= 40  # 200+ terms / 5 per page

    # Check page 0
    page0 = terms[0:5]
    assert len(page0) == 5

    # Check last page
    last_start = (total_pages - 1) * per_page
    last_page = terms[last_start:last_start + per_page]
    assert len(last_page) >= 1


def test_free_tier_limit(terms):
    free_limit = 50
    assert len(terms) > free_limit, "Should have more terms than free limit"
    free_terms = terms[:free_limit]
    assert len(free_terms) == free_limit
