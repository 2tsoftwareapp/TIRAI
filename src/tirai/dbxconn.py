"""Create (or update) a DBX web connection from a DSN, so a database tab needs no manual setup.

Uses DBX web's own HTTP API: `POST /api/auth/login` (when a password is set), `GET /api/connection/list`,
`POST /api/connection/mcp/add` for a new connection and `POST /api/connection/save` to update one by name.
"""

import http.cookiejar
import json
import urllib.error
import urllib.request
import uuid
from urllib.parse import unquote, urljoin, urlsplit

DB_TYPES = {"postgres": "postgres", "postgresql": "postgres", "mysql": "mysql", "mariadb": "mysql"}
DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306}


class DbxError(Exception):
    pass


def dsn_config(dsn, name, host=None):
    """DBX connection fields from `postgresql://user:pw@host:port/db` (host may be overridden, e.g. for Docker)."""
    u = urlsplit(dsn)
    scheme = u.scheme.split("+", 1)[0].lower()
    if scheme not in DB_TYPES:
        raise DbxError(f"unsupported DSN scheme {u.scheme!r} (postgresql, mysql)")
    db_type = DB_TYPES[scheme]
    return {
        "name": name,
        "db_type": db_type,
        "driver_profile": db_type,
        "host": host or u.hostname or "127.0.0.1",
        "port": u.port or DEFAULT_PORTS[db_type],
        "username": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": (u.path or "/").lstrip("/") or None,
        "save_password": True,
    }


class DbxClient:
    def __init__(self, base_url, password=None, timeout=30):
        self.base = base_url if base_url.endswith("/") else base_url + "/"
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        if password:
            self.post("api/auth/login", {"password": password})

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(urljoin(self.base, path), data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:  # noqa: S310 - user-supplied DBX URL
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            hint = " (set the DBX password)" if e.code == 401 else ""
            raise DbxError(f"DBX {path}: HTTP {e.code} {detail}{hint}") from None
        except OSError as e:
            raise DbxError(f"DBX {path}: {e}") from None
        return json.loads(raw) if raw.strip() else None

    def post(self, path, body):
        return self.request(path, body)

    def connections(self):
        return self.request("api/connection/list") or []

    def test(self, cfg):
        """Ask DBX to open a throwaway connection with `cfg`; raises DbxError when it cannot."""
        self.post("api/connection/test", {"config": {"id": str(uuid.uuid4()), **cfg}})

    def ensure(self, cfg):
        """Add the connection, or update the one with the same name. Returns ("added"|"updated", id)."""
        existing = next((c for c in self.connections() if c.get("name") == cfg["name"]), None)
        if existing:
            merged = {**existing, **cfg, "id": existing["id"]}
            merged.pop("database_info", None)
            self.post("api/connection/save", {"configs": [merged], "removedIds": []})
            return "updated", existing["id"]
        saved = self.post("api/connection/mcp/add", {"config": {"id": str(uuid.uuid4()), **cfg}})
        return "added", (saved or {}).get("id")

    def remove(self, connection_id):
        self.post("api/connection/mcp/remove", {"connectionId": connection_id})


def connect(url, dsn, name, password=None, host=None, test=True):
    client = DbxClient(url, password)
    cfg = dsn_config(dsn, name, host)
    if test:
        client.test(cfg)
    return client.ensure(cfg)
