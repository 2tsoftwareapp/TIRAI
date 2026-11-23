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


PG_WRITE_CHECK = """
SELECT current_setting('default_transaction_read_only') = 'on',
       r.rolsuper,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
           AND (has_table_privilege(c.oid, 'INSERT') OR has_table_privilege(c.oid, 'UPDATE')
                OR has_table_privilege(c.oid, 'DELETE')))
  FROM pg_roles r WHERE r.rolname = current_user
"""


def write_access(dsn: str):
    """(read_only, detail) for the DSN's user; read_only is None when it cannot be determined."""
    scheme = urlparse(dsn).scheme.split("+")[0]
    if scheme == "sqlite":
        return True, "opened read-only (mode=ro)"
    if scheme in ("postgres", "postgresql"):
        import psycopg

        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
            ro, superuser, writable = conn.execute(PG_WRITE_CHECK).fetchone()
        if ro and not superuser:
            return True, "default_transaction_read_only=on"
        if superuser:
            return False, "user is a superuser"
        if writable:
            return False, f"user can INSERT/UPDATE/DELETE on {writable} table(s)"
        return True, "no write privilege on any table"
    if scheme == "mysql":
        import pymysql

        u = urlparse(dsn)
        conn = pymysql.connect(
            host=u.hostname,
            port=u.port or 3306,
            user=unquote(u.username or ""),
            password=unquote(u.password or ""),
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = " ".join(str(r[0]).upper() for r in cur.fetchall())
        finally:
            conn.close()
        bad = [g for g in ("ALL PRIVILEGES", "INSERT", "UPDATE", "DELETE") if g in grants]
        return (False, f"user has {', '.join(bad)}") if bad else (True, "no write grants")
    return None, f"unsupported scheme {scheme!r}"
