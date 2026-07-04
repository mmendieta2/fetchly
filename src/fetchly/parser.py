"""HTML parsing: extract the page title and outgoing links."""

from urllib.parse import urljoin

from bs4 import BeautifulSoup


def parse_page(base_url: str, html: str) -> "tuple[str, list[str]]":
    """Return (title, absolute link URLs) for an HTML document."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # <base href> changes how relative links resolve.
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = urljoin(base_url, base_tag["href"])

    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href:
            links.append(urljoin(base_url, href))
    return title, links
