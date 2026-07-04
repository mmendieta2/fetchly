from fetchly.parser import parse_page


def test_title_and_links():
    html = """<html><head><title> My Page </title></head>
    <body><a href="/a">A</a><a href="b.html">B</a><a href="https://x.com/">X</a></body></html>"""
    title, links = parse_page("https://site.com/dir/page.html", html)
    assert title == "My Page"
    assert links == ["https://site.com/a", "https://site.com/dir/b.html", "https://x.com/"]


def test_base_href_changes_resolution():
    html = """<html><head><base href="https://cdn.site.com/root/"></head>
    <body><a href="rel.html">r</a></body></html>"""
    _, links = parse_page("https://site.com/page", html)
    assert links == ["https://cdn.site.com/root/rel.html"]


def test_missing_title_and_hrefless_anchors():
    html = "<html><body><a name='anchor'>no href</a><a href=''>empty</a></body></html>"
    title, links = parse_page("https://site.com/", html)
    assert title == ""
    assert links == []


def test_malformed_html_does_not_raise():
    title, links = parse_page("https://site.com/", "<a href='/x'>unclosed <b><title>T")
    assert links == ["https://site.com/x"]
