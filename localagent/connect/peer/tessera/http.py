"""Tessera binding 1: HTTP. POST /tessera carries one envelope each way; GET /tessera/card. Always status 200."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from localagent.protocol.tessera.envelope import MAX_BYTES


def _handler(endpoint):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/tessera":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(length, MAX_BYTES + 1))  # one byte over is enough for `too_large`
            self._reply(endpoint.handle(raw))

        def do_GET(self):
            if self.path != "/tessera/card":
                self.send_error(404)
                return
            self._reply(endpoint.card())

        def _reply(self, data: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # audit.log records what matters; no request lines on the console
            pass

    return Handler


class TesseraServer:
    def __init__(self, endpoint, host: str, port: int):
        self._httpd = ThreadingHTTPServer((host, port), _handler(endpoint))
        self._httpd.daemon_threads = True
        self.host, self.port = host, self._httpd.server_address[1]
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="tessera-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def post(address: str, raw: bytes, timeout: float = 300) -> bytes:
    """Sends one envelope; returns the reply bytes. Raises OSError when the other side can't be reached."""
    request = Request(address.rstrip("/") + "/tessera", data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()
