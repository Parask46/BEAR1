import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Project layout:
# C:\BEAR\Web\webserver.py
# C:\BEAR\Agent\Bear\agent.py
BEAR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AGENT_DIR = os.path.join(BEAR_ROOT, "Agent", "Bear")
WEB_DIR = os.path.join(BEAR_ROOT, "Web")

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from agent import (
    ALL_FUNCTIONS,
    ALL_SCHEMAS,
    chat_with_bear_agent,
    get_installed_ollama_models,
    load_effort_config,
)

HOST = "127.0.0.1"
PORT = 8765


def tool_descriptions():
    descriptions = {}
    for schema in ALL_SCHEMAS:
        function = schema.get("function", {})
        name = function.get("name")
        if name:
            descriptions[name] = function.get(
                "description", "Available Bear tool"
            )

    return [
        {
            "name": name,
            "description": descriptions.get(name, "Available Bear tool"),
        }
        for name in ALL_FUNCTIONS
    ]


class BearHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/config":
            self.send_json(200, load_effort_config())
            return

        if path == "/api/models":
            models = get_installed_ollama_models()
            if not models:
                self.send_json(503, {
                    "models": [],
                    "error": (
                        "No Ollama models were found. Start Ollama and install "
                        "a model, for example: ollama pull qwen3:8b"
                    ),
                })
                return
            self.send_json(200, {"models": models})
            return

        if path == "/api/tools":
            self.send_json(200, tool_descriptions())
            return

        if path == "/":
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_json(404, {"error": "Endpoint not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body)

            message = str(payload.get("message", "")).strip()
            effort = str(payload.get("effort", "Low")).strip().title()
            model = str(payload.get("model", "")).strip() or None
            selected_tool = payload.get("tool")

            if not message:
                self.send_json(400, {"error": "Message cannot be empty"})
                return

            if selected_tool:
                if selected_tool not in ALL_FUNCTIONS:
                    self.send_json(400, {"error": "Unknown tool selected"})
                    return
                message = (
                    f"[The user selected the {selected_tool} tool. "
                    f"Use it when appropriate.]\n\n{message}"
                )

            reply = chat_with_bear_agent(
                message,
                effort=effort,
                model=model,
            )

            self.send_json(200, {
                "reply": reply,
                "effort": effort,
                "model": model,
            })
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON request"})
        except Exception as error:
            self.send_json(500, {"error": str(error)})


if __name__ == "__main__":
    print(f"Bear web interface: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server = ThreadingHTTPServer((HOST, PORT), BearHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Bear web server...")
    finally:
        server.server_close()