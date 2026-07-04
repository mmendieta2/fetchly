from fetchly.config import CrawlConfig
from fetchly.frontier import Frontier, normalize


def make_frontier(**overrides):
    config = CrawlConfig(start_url="https://example.com/", **overrides)
    return Frontier(config)


class TestNormalize:
    def test_strips_fragment(self):
        assert normalize("https://a.com/page#top") == "https://a.com/page"

    def test_drops_default_ports(self):
        assert normalize("http://a.com:80/x") == "http://a.com/x"
        assert normalize("https://a.com:443/x") == "https://a.com/x"

    def test_keeps_custom_port(self):
        assert normalize("https://a.com:8443/x") == "https://a.com:8443/x"

    def test_lowercases_scheme_and_host_only(self):
        assert normalize("HTTPS://A.com/PaTh") == "https://a.com/PaTh"

    def test_empty_path_becomes_slash(self):
        assert normalize("https://a.com") == "https://a.com/"

    def test_keeps_query(self):
        assert normalize("https://a.com/p?q=1#f") == "https://a.com/p?q=1"


class TestScope:
    def test_same_domain_allowed(self):
        f = make_frontier()
        assert f.in_scope("https://example.com/about")

    def test_other_domain_rejected(self):
        f = make_frontier()
        assert not f.in_scope("https://other.com/")

    def test_subdomain_rejected_by_default(self):
        f = make_frontier()
        assert not f.in_scope("https://blog.example.com/")

    def test_subdomain_allowed_when_enabled(self):
        f = make_frontier(include_subdomains=True)
        assert f.in_scope("https://blog.example.com/")
        assert not f.in_scope("https://notexample.com/")

    def test_all_domains(self):
        f = make_frontier(same_domain_only=False)
        assert f.in_scope("https://anything.net/")

    def test_non_http_schemes_rejected(self):
        f = make_frontier()
        for url in ("mailto:x@y.z", "javascript:void(0)", "tel:+123", "ftp://example.com/f"):
            assert not f.in_scope(url), url

    def test_binary_extensions_rejected(self):
        f = make_frontier()
        for url in ("https://example.com/a.png", "https://example.com/b.PDF",
                    "https://example.com/c.zip"):
            assert not f.in_scope(url), url

    def test_exclude_patterns(self):
        f = make_frontier(exclude_patterns=["/wp-admin/", "?replytocom="])
        assert not f.in_scope("https://example.com/wp-admin/edit.php")
        assert not f.in_scope("https://example.com/post?replytocom=5")
        assert f.in_scope("https://example.com/blog")


class TestAdmit:
    def test_admits_new_url_normalized(self):
        f = make_frontier()
        assert f.admit("https://example.com/page#x") == "https://example.com/page"

    def test_dedupes(self):
        f = make_frontier()
        assert f.admit("https://example.com/page")
        assert f.admit("https://example.com/page") == ""
        assert f.admit("https://example.com/page#other") == ""

    def test_out_of_scope_returns_empty(self):
        f = make_frontier()
        assert f.admit("https://other.com/") == ""
