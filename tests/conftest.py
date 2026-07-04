import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

SITE = {
    "index.html": """<html><head><title>Home</title></head><body>
        <a href="/page1.html">1</a> <a href="/sub/page2.html">2</a>
        <a href="/missing.html">404</a> <a href="mailto:x@y.z">m</a>
        <a href="/pic.png">img</a></body></html>""",
    "page1.html": """<html><head><title>Page One</title></head><body>
        <a href="/">home</a> <a href="/page1.html#frag">self</a>
        <a href="/page3.html">3</a></body></html>""",
    "sub/page2.html": """<html><head><title>Page Two</title></head><body>
        <a href="/page1.html">one</a></body></html>""",
    "page3.html": "<html><head><title>Page Three</title></head><body>end</body></html>",
    "robots.txt": "User-agent: *\nDisallow: /private/\n",
    "private/secret.html": "<html><head><title>Secret</title></head><body></body></html>",
}


@pytest.fixture(scope="session")
def test_site(tmp_path_factory):
    """Serve a small fixed site on an ephemeral localhost port; yield base URL."""
    root = tmp_path_factory.mktemp("site")
    for name, content in SITE.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
