import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BEAR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BEAR_ROOT not in sys.path:
    sys.path.insert(0, BEAR_ROOT)

from agent import ALL_FUNCTIONS, ALL_SCHEMAS, chat_with_bear_agent

WEB_DIR = os.path.join(BEAR_ROOT, "Web")
HOST = "127.0.0.1"
PORT = 8765


def tool_descriptions():
    descriptions = {}
    for schema in ALL_SCHEMAS:
        function = schema.get("function", {})
        name = function.get("name")
        if name:
            descriptions[name] = function.get("description", "Available Bear tool")

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
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            user_message = str(payload.get("message", "")).strip()
            selected_tool = payload.get("tool")

            if not user_message:
                self.send_json(400, {"error": "Message cannot be empty"})
                return

            if selected_tool:
                if selected_tool not in ALL_FUNCTIONS:
                    self.send_json(400, {"error": "Unknown tool selected"})
                    return
                user_message = (
                    f"[The user selected the {selected_tool} tool. Use this tool when "
                    f"appropriate for the request.]\n\n{user_message}"
                )

            reply = chat_with_bear_agent(user_message)
            self.send_json(200, {"reply": reply})
        except Exception as error:
            self.send_json(500, {"error": str(error)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), BearHandler)
    print(f"Bear web interface: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()