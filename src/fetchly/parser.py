"""HTML parsing: extract audit data and outgoing links from a page."""

from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class ParsedPage:
    title: str = ""
    links: "list[str]" = field(default_factory=list)
    meta_description: str = ""
    canonical_url: str = ""
    h1_count: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    word_count: int = 0
    missing_alt_srcs: "list[str]" = field(default_factory=list)
    mixed_content: "list[str]" = field(default_factory=list)  # http:// resources on an https page


# Tags whose fetched resources cause mixed-content warnings on https pages.
_RESOURCE_TAGS = (
    ("img", "src"), ("script", "src"), ("iframe", "src"),
    ("source", "src"), ("audio", "src"), ("video", "src"),
    ("embed", "src"), ("object", "data"),
)


def parse_page(base_url: str, html: str) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    page = ParsedPage()

    if soup.title and soup.title.string:
        page.title = soup.title.string.strip()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        page.meta_description = meta["content"].strip()

    canonical = soup.find("link", rel="canonical", href=True)
    if canonical:
        page.canonical_url = urljoin(base_url, canonical["href"].strip())

    page.h1_count = len(soup.find_all("h1"))

    images = soup.find_all("img")
    page.image_count = len(images)
    for img in images:
        if not img.get("alt", "").strip():
            page.missing_alt_srcs.append(img.get("src", "(no src)"))
    page.images_missing_alt = len(page.missing_alt_srcs)

    if base_url.startswith("https://"):
        for tag_name, attr in _RESOURCE_TAGS:
            for tag in soup.find_all(tag_name):
                value = (tag.get(attr) or "").strip()
                if value.startswith("http://"):
                    page.mixed_content.append(value)
        for link_tag in soup.find_all("link", href=True):
            rel = " ".join(link_tag.get("rel") or [])
            if rel in ("stylesheet", "preload", "icon") and link_tag["href"].strip().startswith("http://"):
                page.mixed_content.append(link_tag["href"].strip())

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    page.word_count = len(body.get_text(separator=" ").split())

    # <base href> changes how relative links resolve.
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = urljoin(base_url, base_tag["href"])

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href:
            page.links.append(urljoin(base_url, href))
    return page
