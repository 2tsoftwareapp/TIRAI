"""Read-only database queries used by `expect: db` checks.

DSN schemes: postgresql:// (psycopg), mysql:// (PyMySQL), sqlite:///path (stdlib).
"""

import sqlite3
from urllib.parse import unquote, urlparse


def query(dsn: str, sql: str) -> list[tuple]:
    scheme = urlparse(dsn).scheme.split("+")[0]
    if scheme in ("postgres", "postgresql"):
        return _postgres(dsn, sql)
    if scheme == "mysql":
        return _mysql(dsn, sql)
    if scheme == "sqlite":
        return _sqlite(dsn, sql)
    raise ValueError(f"unsupported database scheme: {scheme or dsn!r}")


def _postgres(dsn, sql):
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError("PostgreSQL checks need: pip install 'tirai[postgres]'") from e
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.read_only = True
        return [tuple(r) for r in conn.execute(sql).fetchall()]


def _mysql(dsn, sql):
    try:
        import pymysql
    except ImportError as e:
        raise RuntimeError("MySQL checks need: pip install 'tirai[mysql]'") from e
    u = urlparse(dsn)
    conn = pymysql.connect(
        host=u.hostname,
        port=u.port or 3306,
        user=unquote(u.username or ""),
        password=unquote(u.password or ""),
        database=u.path.lstrip("/"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(sql)
            return [tuple(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _sqlite(dsn, sql):
    path = dsn.split("sqlite:///", 1)[-1]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()
