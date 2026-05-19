from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


LOG_PATH = Path(os.environ.get("ACCOUNTPILOT_SMOKE_LOG", "connector-smoke.log"))
HOST = os.environ.get("ACCOUNTPILOT_SMOKE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ACCOUNTPILOT_SMOKE_PORT", "18080"))


class SmokeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{self.command} {self.path} token={self.headers.get('X-AccountPilot-Agent-Token')} body={body}\n")

        if self.path == "/connector/poll":
            self._json_response({"job": None})
            return
        self._json_response({"status": "ok"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json_response(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), SmokeHandler)
    print(f"AccountPilot smoke backend listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
