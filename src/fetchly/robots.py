"""Per-host robots.txt cache.

Fetches robots.txt with the crawl's own User-Agent (via the shared requests
session) so sites that vary responses by UA are handled consistently. A
missing, blocked, or errored robots.txt fails open (no restrictions),
matching modern crawler behavior — a 403 on robots.txt is usually
bot-protection, not a real site-wide disallow.
"""

import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


class RobotsCache:
    def __init__(self, user_agent: str, timeout: float = 10.0,
                 override_text: str = "", session=None):
        """override_text: a local robots.txt applied to every host instead of
        fetching — lets users test rule changes before deploying them.
        session: the crawl's requests.Session, so robots.txt is fetched with
        the same User-Agent and connection settings as the pages."""
        self.user_agent = user_agent
        self.timeout = timeout
        self._session = session or requests.Session()
        self._parsers = {}
        self._lock = threading.Lock()
        self._override = None
        if override_text:
            self._override = RobotFileParser()
            self._override.parse(override_text.splitlines())

    def allowed(self, url: str) -> bool:
        if self._override is not None:
            try:
                return self._override.can_fetch(self.user_agent, url)
            except Exception:
                return True
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            parser = self._parsers.get(origin)
        if parser is None:
            parser = self._fetch_parser(origin)
            with self._lock:
                self._parsers[origin] = parser
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _fetch_parser(self, origin: str) -> RobotFileParser:
        parser = RobotFileParser()
        try:
            response = self._session.get(
                origin + "/robots.txt", timeout=self.timeout,
                headers={"User-Agent": self.user_agent})
        except requests.RequestException:
            parser.allow_all = True
            return parser
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
        else:
            # Missing / blocked / errored robots.txt → assume no restrictions.
            parser.allow_all = True
        return parser
