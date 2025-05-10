import re
import socketserver
import http.server
import urllib.parse
import html
import random
import sqlite3

class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status = status
        self.headers = headers or {}

class Redirect(Response):
    def __init__(self, location, status=302):
        super().__init__("", status, {"Location": location})

class Error(Response):
    def __init__(self, message="Error", status=500):
        super().__init__(f"<h1>{status}</h1><p>{message}</p>", status)

class Context:
    def __init__(self, handler):
        self.method = handler.command
        self.raw_path = handler.path
        self.path, self.query = self._parse_path(self.raw_path)
        self.headers = handler.headers
        self.cookies = self._parse_cookies()
        self.form = {}
        self.raw_body = b""
        self._parse_body(handler)

    def _parse_path(self, raw_path):
        parsed = urllib.parse.urlparse(raw_path)
        return parsed.path, dict(urllib.parse.parse_qsl(parsed.query))

    def _parse_cookies(self):
        cookies = {}
        if "Cookie" in self.headers:
            for part in self.headers["Cookie"].split("; "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k] = v
        return cookies

    def _parse_body(self, handler):
        if self.method in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", 0))
            self.raw_body = handler.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" in ctype:
                body = self.raw_body.decode(errors="ignore")
                self.form = dict(urllib.parse.parse_qsl(body))

class App:
    def __init__(self, docs=False):
        self.urls = {}
        self.middlewares = []
        self.debug = False
        self.docs_enabled = docs
        self.limits = {}
        self.pin = None
        self.commands = []
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)

    def _dispatch(self, ctx):
        for pattern, func in self.urls.items():
            match = re.fullmatch(pattern, ctx.path)
            if match:
                return func(ctx, **match.groupdict())
        return Error("Not Found", 404)

    def _send_response(self, handler, response):
        handler.send_response(response.status)
        for k, v in response.headers.items():
            handler.send_header(k, v)
        handler.end_headers()
        handler.wfile.write(response.body)

    def run(self, host="127.0.0.1", port=8000, debug=False, limits=None):
        self.debug = debug
        self.limits = limits or {}
        self.pin = str(random.randint(100000, 999999))
        self.admin_commands = []

        app = self

        class FrameletHandler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self): self.handle_request()
            def do_GET(self): self.handle_request()
            def do_POST(self): self.handle_request()
            def do_PUT(self): self.handle_request()
            def do_PATCH(self): self.handle_request()
            def do_DELETE(self): self.handle_request()
            def do_OPTIONS(self): self.handle_request()

            def handle_request(self):
                ctx = Context(self)

                def execute_middlewares(index=0):
                    if index < len(app.middlewares):
                        return app.middlewares[index](ctx, lambda: execute_middlewares(index + 1))
                    return app._dispatch(ctx)

                try:
                    response = execute_middlewares()
                    app._send_response(self, response)
                except Exception as e:
                    if debug:
                        body = f"<h1>Exception:</h1><pre>{html.escape(str(e))}</pre>"
                        app._send_response(self, Error(body, status=500))
                    else:
                        app._send_response(self, Error("Internal Server Error", status=500))

            def log_message(self, format, *args):
                if debug:
                    super().log_message(format, *args)

        print(f" * Running on http://{host}:{port}/ (Press CTRL+C to quit)")
        if debug:
            print(f" * Admin PIN: {self.pin}")

        with socketserver.ThreadingTCPServer((host, port), FrameletHandler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nShutting down...")
