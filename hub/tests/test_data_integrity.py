"""Test data integrity for all JSON files."""
import json
import pytest
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "bot" / "data"


def load_json(name: str):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


class TestGlossary:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("glossary.json")
        self.terms = self.data["terms"]

    def test_has_terms_key(self):
        assert "terms" in self.data

    def test_min_200_terms(self):
        assert len(self.terms) >= 200, f"Only {len(self.terms)} terms"

    def test_required_fields(self):
        for i, t in enumerate(self.terms):
            assert t.get("term"), f"Term {i} missing 'term'"
            assert t.get("term_ru"), f"Term {i} missing 'term_ru'"
            assert t.get("category"), f"Term {i} missing 'category'"
            assert t.get("definition"), f"Term {i} missing 'definition'"

    def test_valid_categories(self):
        valid = {"disputes", "acquiring", "compliance", "finance", "risk", "tech", "traffic", "crypto"}
        for t in self.terms:
            assert t["category"] in valid, f"Invalid category: {t['category']}"

    def test_no_duplicate_terms(self):
        names = [t["term"].lower() for t in self.terms]
        dupes = [n for n in names if names.count(n) > 1]
        assert len(dupes) == 0, f"Duplicate terms: {set(dupes)}"


class TestCountries:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("countries.json")
        self.countries = self.data["countries"]

    def test_has_countries_key(self):
        assert "countries" in self.data

    def test_min_100_countries(self):
        assert len(self.countries) >= 100, f"Only {len(self.countries)} countries"

    def test_required_fields(self):
        for c in self.countries:
            assert c.get("code"), f"Missing code: {c}"
            assert c.get("name"), f"Missing name for {c.get('code')}"
            assert c.get("name_ru"), f"Missing name_ru for {c.get('code')}"
            assert c.get("region"), f"Missing region for {c.get('code')}"

    def test_valid_regions(self):
        valid = {"Europe", "Asia", "CIS", "LATAM", "Africa", "Middle East", "North America", "Oceania"}
        for c in self.countries:
            assert c["region"] in valid, f"Invalid region '{c['region']}' for {c['code']}"

    def test_valid_risk_levels(self):
        valid = {"low", "medium", "high"}
        for c in self.countries:
            assert c.get("risk_level") in valid, f"Invalid risk for {c['code']}: {c.get('risk_level')}"

    def test_vertical_structure(self):
        for c in self.countries:
            for vert in ("gambling", "crypto", "forex", "adult", "nutra"):
                v = c.get(vert)
                assert isinstance(v, dict), f"{c['code']}.{vert} should be dict, got {type(v)}"
                assert v.get("status") in ("allowed", "restricted", "prohibited"), \
                    f"{c['code']}.{vert}.status invalid: {v.get('status')}"

    def test_no_duplicate_codes(self):
        codes = [c["code"] for c in self.countries]
        dupes = [c for c in codes if codes.count(c) > 1]
        assert len(dupes) == 0, f"Duplicate codes: {set(dupes)}"


class TestAcquirers:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("acquirers.json")
        self.acquirers = self.data["acquirers"]

    def test_min_50_acquirers(self):
        assert len(self.acquirers) >= 50, f"Only {len(self.acquirers)} acquirers"

    def test_required_fields(self):
        for a in self.acquirers:
            assert a.get("name"), f"Missing name"
            assert a.get("type"), f"Missing type for {a.get('name')}"
            assert isinstance(a.get("rating"), (int, float)), f"Invalid rating for {a.get('name')}"

    def test_no_duplicate_names(self):
        names = [a["name"].lower() for a in self.acquirers]
        dupes = [n for n in names if names.count(n) > 1]
        assert len(dupes) == 0, f"Duplicates: {set(dupes)}"


class TestCalendar:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("calendar.json")
        self.months = self.data["months"]

    def test_12_months(self):
        assert len(self.months) == 12

    def test_month_numbers(self):
        nums = sorted(m["month"] for m in self.months)
        assert nums == list(range(1, 13))

    def test_verticals_present(self):
        for m in self.months:
            verts = m.get("verticals", {})
            assert len(verts) >= 4, f"Month {m['month']} has only {len(verts)} verticals"

    def test_valid_colors(self):
        valid = {"green", "yellow", "red"}
        for m in self.months:
            for vname, vdata in m.get("verticals", {}).items():
                assert vdata.get("color") in valid, \
                    f"Month {m['month']}.{vname}: invalid color '{vdata.get('color')}'"


class TestPlatforms:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("platforms.json")
        self.platforms = self.data["platforms"]

    def test_min_25_platforms(self):
        assert len(self.platforms) >= 25, f"Only {len(self.platforms)} platforms"

    def test_required_fields(self):
        for p in self.platforms:
            assert p.get("name"), f"Missing name"
            assert p.get("type"), f"Missing type for {p.get('name')}"


class TestAML:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("aml.json")
        self.regions = self.data["regions"]

    def test_min_5_regions(self):
        assert len(self.regions) >= 5, f"Only {len(self.regions)} regions"

    def test_has_sanctions_lists(self):
        assert "global_sanctions_lists" in self.data
        assert len(self.data["global_sanctions_lists"]) >= 3


class TestTrafficMap:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("traffic_map.json")
        self.verticals = self.data["verticals"]

    def test_min_5_verticals(self):
        assert len(self.verticals) >= 5

    def test_required_fields(self):
        for v in self.verticals:
            assert v.get("vertical"), f"Missing vertical name"
            assert v.get("name_ru"), f"Missing name_ru for {v.get('vertical')}"
