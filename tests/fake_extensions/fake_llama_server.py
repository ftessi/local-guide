"""Stands in for llama-server in tests: same flags, /health and a streaming /v1/chat/completions.
Replies "hello there friend" in three chunks. A user message of "ECHO" gets the request's settings back as JSON;
"TOO LONG" gets the error llama-server sends for a prompt over the context size."""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEVICES = """\
Available devices:
  Vulkan0: Intel(R) HD Graphics 630 (12230 MiB, 11462 MiB free)
  Vulkan1: NVIDIA GeForce GTX 1050 (4235 MiB, 3631 MiB free)
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        last = body["messages"][-1]["content"]
        if last == "TOO LONG":
            self._json(400, {"error": {"code": 400, "type": "exceed_context_size_error",
                                       "message": "the request exceeds the available context size"}})
            return
        if last == "ECHO":
            chunks = [json.dumps({k: v for k, v in body.items() if k != "messages"} | {"argv": sys.argv[1:]})]
        else:
            chunks = ["hello", " there", " friend"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            event = {"choices": [{"index": 0, "delta": {"content": c}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


def main():
    if "--list-devices" in sys.argv:
        print(DEVICES)
        return 0
    p = argparse.ArgumentParser()
    p.add_argument("-m", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    args, _ = p.parse_known_args()
    if not Path(args.m).is_file():
        print(f"error: failed to load model '{args.m}'", flush=True)
        return 1
    print("server is listening", flush=True)
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
