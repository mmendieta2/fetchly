from fetchly.parser import parse_page


def test_title_and_links():
    html = """<html><head><title> My Page </title></head>
    <body><a href="/a">A</a><a href="b.html">B</a><a href="https://x.com/">X</a></body></html>"""
    page = parse_page("https://site.com/dir/page.html", html)
    assert page.title == "My Page"
    assert page.links == ["https://site.com/a", "https://site.com/dir/b.html", "https://x.com/"]


def test_base_href_changes_resolution():
    html = """<html><head><base href="https://cdn.site.com/root/"></head>
    <body><a href="rel.html">r</a></body></html>"""
    page = parse_page("https://site.com/page", html)
    assert page.links == ["https://cdn.site.com/root/rel.html"]


def test_missing_title_and_hrefless_anchors():
    html = "<html><body><a name='anchor'>no href</a><a href=''>empty</a></body></html>"
    page = parse_page("https://site.com/", html)
    assert page.title == ""
    assert page.links == []


def test_malformed_html_does_not_raise():
    page = parse_page("https://site.com/", "<a href='/x'>unclosed <b><title>T")
    assert page.links == ["https://site.com/x"]


def test_audit_fields():
    html = """<html><head>
      <title>T</title>
      <meta name="description" content=" A fine page. ">
      <link rel="canonical" href="/canon">
    </head><body>
      <h1>One</h1><h1>Two</h1>
      <img src="a.png" alt="ok"><img src="b.png"><img src="c.png" alt="  ">
      <p>five words of body text</p>
      <script>ignored_word_soup();</script>
    </body></html>"""
    page = parse_page("https://site.com/post", html)
    assert page.meta_description == "A fine page."
    assert page.canonical_url == "https://site.com/canon"
    assert page.h1_count == 2
    assert page.image_count == 3
    assert page.images_missing_alt == 2
    # "One Two five words of body text" = 7; script contents excluded
    assert page.word_count == 7


def test_word_count_excludes_scripts():
    html = "<html><body><p>alpha beta</p><script>var x = 'gamma delta';</script></body></html>"
    page = parse_page("https://site.com/", html)
    assert page.word_count == 2
