"""HTML parsing: extract audit data, outgoing links, and custom data."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def simhash64(words: "list[str]") -> int:
    """64-bit SimHash over word 3-grams for near-duplicate detection."""
    if not words:
        return 0
    votes = [0] * 64
    for i in range(max(1, len(words) - 2)):
        shingle = " ".join(words[i:i + 3])
        h = int(hashlib.md5(shingle.encode("utf-8")).hexdigest()[:16], 16)
        for bit in range(64):
            votes[bit] += 1 if (h >> bit) & 1 else -1
    return sum(1 << bit for bit in range(64) if votes[bit] > 0)


def _jsonld_types(data) -> "list[str]":
    types = []
    if isinstance(data, dict):
        t = data.get("@type")
        if isinstance(t, str):
            types.append(t)
        elif isinstance(t, list):
            types.extend(x for x in t if isinstance(x, str))
        types.extend(_jsonld_types(data.get("@graph", [])))
    elif isinstance(data, list):
        for item in data:
            types.extend(_jsonld_types(item))
    return types

_MAX_EXTRACT_MATCHES = 5


def parse_extract_rules(specs: "list[str]") -> "list[tuple[str, str, str]]":
    """Parse 'name=css:selector' / 'name=re:pattern' specs into (name, kind, pattern).

    Raises ValueError on a malformed spec so front ends can reject it early.
    """
    rules = []
    for spec in specs:
        name, sep, rest = spec.partition("=")
        kind, sep2, pattern = rest.partition(":")
        if not sep or not sep2 or not name.strip() or kind not in ("css", "re") or not pattern:
            raise ValueError(
                f"bad extract rule {spec!r} (expected name=css:selector or name=re:pattern)")
        if kind == "re":
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"bad regex in extract rule {spec!r}: {exc}")
        rules.append((name.strip(), kind, pattern))
    return rules


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
    meta_robots: str = ""       # content of <meta name="robots">, lowercased
    content_hash: str = ""      # md5 of normalized visible text, for duplicate detection
    simhash: int = 0            # near-duplicate fingerprint (simhash64)
    hreflang: "list[tuple]" = field(default_factory=list)  # (lang, absolute url)
    schema_types: "list[str]" = field(default_factory=list)  # JSON-LD @type values
    schema_errors: int = 0      # unparseable JSON-LD blocks
    amp_url: str = ""           # <link rel="amphtml"> target, absolute
    is_amp: bool = False        # <html amp> / <html ⚡>
    extracted: dict = field(default_factory=dict)  # rule name -> " | "-joined matches
    misspellings: "list[str]" = field(default_factory=list)  # unknown words (spellcheck)


_MAX_MISSPELLINGS = 10
_WORD_EDGE = re.compile(r"^[^\w]+|[^\w]+$")


def find_misspellings(words: "list[str]", dictionary: "set[str]") -> "list[str]":
    """Conservative spellcheck: only plain lowercase ASCII words are judged,
    so names, acronyms, code, and non-English text don't false-positive."""
    unknown, seen = [], set()
    for raw in words:
        word = _WORD_EDGE.sub("", raw)
        if (len(word) < 4 or not word.isascii() or not word.isalpha()
                or word != word.lower() or word in seen):
            continue
        seen.add(word)
        if word not in dictionary:
            unknown.append(word)
            if len(unknown) >= _MAX_MISSPELLINGS:
                break
    return unknown


# Tags whose fetched resources cause mixed-content warnings on https pages.
_RESOURCE_TAGS = (
    ("img", "src"), ("script", "src"), ("iframe", "src"),
    ("source", "src"), ("audio", "src"), ("video", "src"),
    ("embed", "src"), ("object", "data"),
)


def parse_page(base_url: str, html: str, extract_rules=(), spell_dictionary=None) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    page = ParsedPage()

    for name, kind, pattern in extract_rules:
        if kind == "css":
            matches = [el.get_text(" ", strip=True) for el in soup.select(pattern)]
        else:
            matches = ["".join(m) if isinstance(m, tuple) else m
                       for m in re.findall(pattern, html)]
        page.extracted[name] = " | ".join(matches[:_MAX_EXTRACT_MATCHES])

    if soup.title and soup.title.string:
        page.title = soup.title.string.strip()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        page.meta_description = meta["content"].strip()

    robots = soup.find("meta", attrs={"name": "robots"})
    if robots and robots.get("content"):
        page.meta_robots = robots["content"].strip().lower()

    canonical = soup.find("link", rel="canonical", href=True)
    if canonical:
        page.canonical_url = urljoin(base_url, canonical["href"].strip())

    html_tag = soup.find("html")
    if html_tag and (html_tag.has_attr("amp") or html_tag.has_attr("⚡")):
        page.is_amp = True

    for link_tag in soup.find_all("link", href=True):
        rel = link_tag.get("rel") or []
        if "alternate" in rel and link_tag.get("hreflang"):
            page.hreflang.append((link_tag["hreflang"].strip(),
                                  urljoin(base_url, link_tag["href"].strip())))
        elif "amphtml" in rel:
            page.amp_url = urljoin(base_url, link_tag["href"].strip())

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            page.schema_types.extend(_jsonld_types(json.loads(script.string or "")))
        except (json.JSONDecodeError, TypeError):
            page.schema_errors += 1

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
    words = body.get_text(separator=" ").split()
    page.word_count = len(words)
    if words:
        normalized = " ".join(words).lower()
        page.content_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        page.simhash = simhash64(normalized.split())
        if spell_dictionary is not None:
            page.misspellings = find_misspellings(words, spell_dictionary)

    # <base href> changes how relative links resolve.
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = urljoin(base_url, base_tag["href"])

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href:
            page.links.append(urljoin(base_url, href))
    return page
