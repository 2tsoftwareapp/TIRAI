"""Demo web app with a login form used by the example scenario (stdlib only)."""

import html
import http.server
import os
import urllib.parse

USERS = {
    "alice@demo.local": ("Passw0rd!", "ACTIVE", "Alice Nguyen"),
    "bob@demo.local": ("Passw0rd!", "LOCKED", "Bob Tran"),
}

STYLE = """
body{font-family:system-ui,sans-serif;background:#f3f5f9;margin:0}
header{background:#1f3a68;color:#fff;padding:14px 32px;font-size:20px;font-weight:600}
main{max-width:420px;margin:60px auto;background:#fff;padding:32px;border-radius:10px;box-shadow:0 2px 12px #0002}
label{display:block;margin:14px 0 6px;font-weight:600}
input{width:100%;padding:10px;font-size:15px;box-sizing:border-box;border:1px solid #bbb;border-radius:6px}
button{margin-top:22px;width:100%;padding:12px;font-size:16px;background:#1f6feb;color:#fff;border:0;border-radius:6px;cursor:pointer}
.error{margin-top:16px;padding:10px;background:#fde8e8;color:#b42318;border-radius:6px}
.ok{font-size:18px}
"""


def page(body):
    return (
        "<!doctype html><html><head><meta charset=utf-8><title>Demo Shop</title>"
        f"<style>{STYLE}</style></head><body><header>Demo Shop Admin</header><main>{body}</main></body></html>"
    )


def login_form(error="", email=""):
    err = f'<div class="error" id="login-error">{html.escape(error)}</div>' if error else ""
    return page(f"""<h2>Sign in</h2><form method=post action=/login>
<label for=email>Email</label><input id=email name=email value="{html.escape(email)}" autocomplete=off>
<label for=password>Password</label><input id=password name=password type=password>
<button id=submit type=submit>Sign in</button>{err}</form>""")


class H(http.server.BaseHTTPRequestHandler):
    def send(self, code, body):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/dashboard"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = html.escape(q.get("name", ["user"])[0])
            welcome = f"<h2 id=welcome>Welcome, {name}</h2>"
            return self.send(200, page(welcome + "<p class=ok>Login successful. Status: <b id=status>ACTIVE</b></p>"))
        self.send(200, login_form())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        f = urllib.parse.parse_qs(self.rfile.read(n).decode())
        email, pw = f.get("email", [""])[0].strip(), f.get("password", [""])[0]
        if "@" not in email:
            return self.send(200, login_form("Email format is invalid.", email))
        u = USERS.get(email)
        if not u or u[0] != pw:
            return self.send(200, login_form("Email or password is incorrect.", email))
        if u[1] == "LOCKED":
            return self.send(200, login_form("This account is locked. Contact the administrator.", email))
        self.send_response(303)
        self.send_header("Location", "/dashboard?name=" + urllib.parse.quote(u[2]))
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))
    http.server.ThreadingHTTPServer((host, port), H).serve_forever()
