"""Tests for custom extraction, crawl comparison, and graph generation."""

import pytest

from fetchly.compare import diff_reports
from fetchly.models import PageResult
from fetchly.parser import parse_extract_rules, parse_page
from fetchly.report import write_report
from fetchly.viz import write_graph


class TestExtractRules:
    def test_parse_specs(self):
        rules = parse_extract_rules(["price=css:.price", "sku=re:SKU-\\d+"])
        assert rules == [("price", "css", ".price"), ("sku", "re", "SKU-\\d+")]

    @pytest.mark.parametrize("bad", ["noequals", "x=badkind:sel", "=css:.a", "x=css:", "x=re:("])
    def test_bad_specs_raise(self, bad):
        with pytest.raises(ValueError):
            parse_extract_rules([bad])

    def test_css_extraction(self):
        html = '<div class="price">$5</div><p>x</p><div class="price">$9</div>'
        page = parse_page("https://s.com/", html, [("price", "css", ".price")])
        assert page.extracted == {"price": "$5 | $9"}

    def test_regex_extraction_and_cap(self):
        html = " ".join(f"SKU-{i}" for i in range(10))
        page = parse_page("https://s.com/", html, [("sku", "re", r"SKU-\d+")])
        assert page.extracted["sku"] == "SKU-0 | SKU-1 | SKU-2 | SKU-3 | SKU-4"

    def test_no_match_gives_empty_string(self):
        page = parse_page("https://s.com/", "<p>hi</p>", [("x", "css", ".missing")])
        assert page.extracted == {"x": ""}

    def test_extracted_lands_in_csv(self, tmp_path):
        r = PageResult(url="https://s.com/", status_code=200, ok=True,
                       extracted={"price": "$5"})
        out = tmp_path / "r.csv"
        write_report(str(out), [r], extra_fields=["price"])
        text = out.read_text()
        assert text.splitlines()[0].endswith(",price")
        assert ",$5" in text


class TestCompare:
    def test_diff(self):
        old = {"https://s.com/a": {"url": "https://s.com/a", "status_code": "200", "title": "A"},
               "https://s.com/b": {"url": "https://s.com/b", "status_code": "200", "title": "B"}}
        new = {"https://s.com/a": {"url": "https://s.com/a", "status_code": "404", "title": "A"},
               "https://s.com/c": {"url": "https://s.com/c", "status_code": "200", "title": "C"}}
        diff = diff_reports(old, new)
        assert diff["added"] == ["https://s.com/c"]
        assert diff["removed"] == ["https://s.com/b"]
        assert diff["changed"] == {"https://s.com/a": {"status_code": ("200", "404")}}

    def test_identical_reports(self):
        rows = {"https://s.com/": {"url": "https://s.com/", "status_code": "200"}}
        diff = diff_reports(rows, dict(rows))
        assert diff["added"] == [] and diff["removed"] == [] and diff["changed"] == {}


class TestGraph:
    def test_writes_selfcontained_html(self, tmp_path):
        results = [
            PageResult(url="https://s.com/", status_code=200, ok=True),
            PageResult(url="https://s.com/a", status_code=200, ok=True, found_on="https://s.com/"),
            PageResult(url="https://s.com/gone", status_code=404, found_on="https://s.com/a"),
        ]
        out = tmp_path / "g.html"
        assert write_graph(str(out), results) == 3
        text = out.read_text()
        assert '"edges": [{"s": 0, "t": 1}, {"s": 1, "t": 2}]' in text
        assert "http://" not in text.replace("http://www.sitemaps", "")  # no external refs
        assert "https://s.com/gone" in text and "#c0392b" in text  # broken node is red
