from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import re
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _build_conn_str() -> str:
    """Build a SQLAlchemy PostgreSQL connection string from environment or Streamlit secrets.

    Expected keys: host, port, dbname, user, password
    """
    # Prefer Streamlit secrets when available
    try:
        import streamlit as st  # type: ignore

        pg = st.secrets.get("postgres", {})
        host = pg.get("host")
        if host:
            user = pg.get("user")
            password = pg.get("password")
            dbname = pg.get("dbname")
            port = int(pg.get("port", 5432))
            return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    except Exception:
        pass

    # Fallback to environment variables
    host = os.getenv("PGHOST")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    dbname = os.getenv("PGDATABASE")
    port = os.getenv("PGPORT", "5432")
    if host and user and password and dbname:
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    raise RuntimeError("Database configuration not found. Provide .streamlit/secrets.toml or PG* env vars.")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(_build_conn_str(), pool_pre_ping=True, pool_recycle=300)


def _get_schema() -> str:
    """Get target schema from secrets or environment, default 'public'.
    Only allow simple schema names (alnum + underscore) for safety.
    """
    schema = None
    try:
        import streamlit as st  # type: ignore

        schema = st.secrets.get("postgres", {}).get("schema")
    except Exception:
        pass
    if not schema:
        schema = os.getenv("PGSCHEMA", "public")

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema):
        schema = "public"
    return schema


def _table_ident() -> str:
    return f"{_get_schema()}.production_data"


def _table_exists(eng: Engine) -> bool:
    sql = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = 'production_data'
        """
    )
    with eng.connect() as conn:
        res = conn.execute(sql, {"schema": _get_schema()}).scalar()
        return bool(res)


def fetch_production(date_from: str, date_to: Optional[str] = None, line: Optional[list[str]] = None,
                     category: Optional[list[str]] = None, style_like: Optional[str] = None):
    """Fetch production rows within date range and optional filters.

    Dates are ISO strings (YYYY-MM-DD). If date_to is None, equals date_from.
    """
    if not date_to:
        date_to = date_from

    filters = ["production_date BETWEEN :dfrom AND :dto"]
    params: dict = {"dfrom": date_from, "dto": date_to}
    if line:
        filters.append("line = ANY(:lines)")
        params["lines"] = line
    if category:
        filters.append("category = ANY(:cats)")
        params["cats"] = category
    if style_like:
        filters.append("style_number ILIKE :style")
        params["style"] = f"%{style_like}%"

    where_clause = " AND ".join(filters)
    table = _table_ident()
    sql = text(
        f"SELECT * FROM {table} WHERE {where_clause} ORDER BY production_date, line, style_number"
    )
    eng = get_engine()
    if not _table_exists(eng):
        raise RuntimeError(
            f"Table not found: {table}. Import Cloud_SQL_sample_DB.sql or set postgres.schema correctly in secrets."
        )
    with eng.connect() as conn:
        res = conn.execute(sql, params)
        rows = res.mappings().all()
    return rows
