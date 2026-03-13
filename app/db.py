"""
Database layer backed by SQLAlchemy engine (connection pooling)
with psycopg2 as the DBAPI driver.

Neon-specific considerations:
  - SSL required (sslmode=require)
  - Pooler endpoint uses PgBouncer in transaction mode
  - Fully qualified table names (job_module.*) everywhere
  - pool_pre_ping=True handles cold-start / dropped connections
  - pool_recycle keeps connections fresh
"""

import logging
from contextlib import contextmanager
from urllib.parse import quote_plus

import psycopg2.extras
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

_engine = None


def _build_url(settings) -> str:
    password = quote_plus(settings.db_password)
    return (
        f"postgresql+psycopg2://{settings.db_user}:{password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        f"?sslmode={settings.db_sslmode}"
    )


# Schema used for all job_module tables (same as DDL script)
DB_SCHEMA = "job_module"


def _mask_password(s: str) -> str:
    """Return connection URL with password replaced by ****."""
    if not s or "@" not in s:
        return "****"
    try:
        pre, rest = s.split("@", 1)
        if ":" in pre:
            user, _ = pre.rsplit(":", 1)
            return f"{user}:****@{rest}"
    except Exception:
        pass
    return "****"


def init_pool(settings) -> None:
    """Create the SQLAlchemy engine. Call once at application startup."""
    global _engine
    if _engine is not None:
        return

    url = _build_url(settings)
    _engine = create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_timeout=30,
    )

    # ── Cross-verify: print credentials and validate connection ─────────────
    logger.info(
        "DB connection config | host=%s port=%s database=%s user=%s sslmode=%s schema=%s",
        settings.db_host, settings.db_port, settings.db_name, settings.db_user,
        settings.db_sslmode, DB_SCHEMA,
    )
    logger.info("DB URL (masked) | %s", _mask_password(url))

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT current_database(), version()")
        db, ver = cur.fetchone()
        cur.close()
        logger.info("SQLAlchemy pool ready | database=%s engine=%s", db, ver[:50] if ver else "")

        # Validate schema and table state (so you can cross-check with DBeaver)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    current_database() AS connected_database,
                    current_schema()  AS current_schema,
                    (SELECT COUNT(*) FROM job_module.job_profiles) AS job_profiles_count,
                    (SELECT COALESCE(MAX(id), 0) FROM job_module.job_profiles) AS job_profiles_max_id
                """
            )
            row = cur.fetchone()
            cur.close()
            conn.commit()
            logger.info(
                "DB validation | connected_database=%s current_schema=%s "
                "job_module.job_profiles count=%s max_id=%s",
                row[0], row[1], row[2], row[3],
            )
        except Exception as e:
            logger.warning("DB validation query failed (schema/table may not exist yet): %s", e)


def get_db_verify(settings) -> dict:
    """
    Return connection config and live validation so you can cross-check with DBeaver.
    Use GET /db-verify to see exactly which database and schema the app is using.
    """
    url = _build_url(settings)
    out = {
        "credentials": {
            "host": settings.db_host,
            "port": settings.db_port,
            "database": settings.db_name,
            "user": settings.db_user,
            "url_masked": _mask_password(url),
            "schema": DB_SCHEMA,
        },
        "validation": None,
        "expected_url": f"postgresql://{settings.db_user}:****@{settings.db_host}:{settings.db_port}/{settings.db_name}?sslmode=require",
    }
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    current_database() AS connected_database,
                    current_schema()  AS current_schema,
                    (SELECT COUNT(*) FROM job_module.job_profiles) AS job_profiles_count,
                    (SELECT COALESCE(MAX(id), 0) FROM job_module.job_profiles) AS job_profiles_max_id
                """
            )
            row = cur.fetchone()
            cur.close()
            conn.commit()
            out["validation"] = {
                "connected_database": row[0],
                "current_schema": row[1],
                "job_module.job_profiles_count": row[2],
                "job_module.job_profiles_max_id": row[3],
            }
    except Exception as e:
        out["validation_error"] = str(e)
    return out


def close_pool() -> None:
    """Dispose the engine and close all pooled connections."""
    global _engine
    if _engine:
        _engine.dispose()
        _engine = None
        logger.info("SQLAlchemy pool disposed")


@contextmanager
def get_connection():
    """
    Yield a raw DBAPI (psycopg2) connection from the SQLAlchemy pool.
    Auto-commits on success, rolls back on error.
    Connection is returned to the pool on exit.
    """
    if _engine is None:
        raise RuntimeError("Database engine not initialised – call init_pool() first")

    raw_conn = _engine.raw_connection()
    try:
        yield raw_conn
        raw_conn.commit()
        logger.debug("Transaction committed")
    except Exception:
        raw_conn.rollback()
        logger.debug("Transaction rolled back due to exception")
        raise
    finally:
        raw_conn.close()


def fetch_all(sql, params=None, *, conn=None):
    """Execute SELECT and return list[dict]."""
    def _run(c):
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()] if cur.description else []

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        result = _run(c)
        c.commit()
        logger.debug("db fetch_all | rows=%s", len(result))
        return result


def fetch_one(sql, params=None, *, conn=None):
    """Execute query and return first row as dict, or None."""
    def _run(c):
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            r = cur.fetchone()
            return dict(r) if r else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        result = _run(c)
        c.commit()
        logger.debug("db fetch_one | found=%s", result is not None)
        return result


def execute(sql, params=None, *, conn=None):
    """Execute INSERT/UPDATE/DELETE and return rowcount."""
    def _run(c):
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        result = _run(c)
        c.commit()
        logger.info("db execute | rowcount=%s", result)
        return result
