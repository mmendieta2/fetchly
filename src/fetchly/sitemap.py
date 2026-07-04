"""Fetch, parse, and generate sitemap.xml (sitemap index files supported)."""

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from urllib.parse import urljoin, urlparse

_MAX_SITEMAPS = 20  # cap recursion through sitemap index files


def _extract(xml_text: str) -> "tuple[list[str], list[str]]":
    """Return (page_urls, child_sitemap_urls) from one sitemap document."""
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return [], []
    # Ignore namespaces: match on local tag names.
    pages, children = [], []
    tag = root.tag.rsplit("}", 1)[-1]
    for loc in root.iter():
        if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text:
            url = loc.text.strip()
            (children if tag == "sitemapindex" else pages).append(url)
    return pages, children


def fetch_sitemap_urls(session, start_url: str, timeout: float = 10.0) -> "list[str]":
    """Fetch /sitemap.xml for start_url's origin; return page URLs (may be [])."""
    parts = urlparse(start_url)
    seed = urljoin(f"{parts.scheme}://{parts.netloc}", "/sitemap.xml")
    queue, urls, fetched = [seed], [], 0
    while queue and fetched < _MAX_SITEMAPS:
        sitemap_url = queue.pop(0)
        fetched += 1
        try:
            response = session.get(sitemap_url, timeout=timeout)
        except Exception:
            continue
        if response.status_code != 200:
            continue
        pages, children = _extract(response.text)
        urls.extend(pages)
        queue.extend(children)
    return urls


def write_sitemap(path: str, results) -> int:
    """Generate a sitemap.xml from crawl results; returns number of URLs written.

    Includes indexable HTML pages only: status 200, no noindex directive,
    and not a redirect (the final URL is what belongs in a sitemap).
    """
    urls = []
    for r in results:
        if r.status_code != 200 or r.error or r.redirected_to:
            continue
        if r.content_type not in ("text/html", "application/xhtml+xml", ""):
            continue
        if "noindex" in f"{r.meta_robots} {r.x_robots_tag}":
            continue
        urls.append(r.url)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for url in sorted(urls):
            fh.write(f"  <url><loc>{escape(url)}</loc></url>\n")
        fh.write("</urlset>\n")
    return len(urls)
