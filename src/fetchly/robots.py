"""Per-host robots.txt cache built on the stdlib parser."""

import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsCache:
    def __init__(self, user_agent: str, timeout: float = 10.0, override_text: str = ""):
        """override_text: a local robots.txt applied to every host instead of
        fetching — lets users test rule changes before deploying them."""
        self.user_agent = user_agent
        self.timeout = timeout
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
            parser = RobotFileParser(origin + "/robots.txt")
            try:
                parser.read()
            except Exception:
                # Unreachable/broken robots.txt: fail open.
                parser.allow_all = True
            with self._lock:
                self._parsers[origin] = parser
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True
