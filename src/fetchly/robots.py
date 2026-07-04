"""Per-host robots.txt cache built on the stdlib parser."""

import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsCache:
    def __init__(self, user_agent: str, timeout: float = 10.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
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
