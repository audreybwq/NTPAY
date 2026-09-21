from __future__ import annotations
from pathlib import Path
import duckdb
import pandas as pd

DUCKDB_PATH = ":memory:"
DUCKLAKE_ATTACH = "ducklake:lakehouse"
DUCKLAKE_ALIAS = "ducklake"


def _literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _configure_cloud_secrets(con, settings) -> None:
    """Create connection-scoped secrets; never persist Cloud credentials to disk."""
    options = {
        "postgres": ("supabase_pg_secret", {"host", "port", "dbname", "user", "password"}),
        "s3": ("my_secret", {"key_id", "secret", "region", "endpoint", "url_style", "use_ssl", "session_token", "scope"}),
    }
    for kind, (name, allowed) in options.items():
        values = settings[kind]
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported options in ducklake.{kind}.")
        fields = [f"TYPE {kind}"]
        for key, value in values.items():
            fields.append(f"{key.upper()} {_literal(value)}")
        con.execute(f"CREATE OR REPLACE SECRET {name} ({', '.join(fields)})")

    lake = settings["catalog"]
    con.execute(
        "CREATE OR REPLACE SECRET lakehouse (TYPE ducklake, "
        f"METADATA_PATH {_literal(lake.get('metadata_path', ''))}, "
        f"METADATA_SCHEMA {_literal(lake.get('metadata_schema', 'main'))}, "
        f"DATA_PATH {_literal(lake['data_path'])}, "
        "METADATA_PARAMETERS MAP {'TYPE': 'postgres', 'SECRET': 'supabase_pg_secret'})"
    )


def _cloud_settings():
    import streamlit as st
    from streamlit.errors import StreamlitSecretNotFoundError

    try:
        return st.secrets.get("ducklake")
    except StreamlitSecretNotFoundError:
        return None


def connect_ducklake(
    duckdb_path: str | Path = DUCKDB_PATH,
) -> duckdb.DuckDBPyConnection:

    con = duckdb.connect(str(duckdb_path))
    try:
        settings = _cloud_settings()
        extensions = ("ducklake", "postgres", "httpfs") if settings is not None else ("ducklake",)
        for extension in extensions:
            con.execute(f"INSTALL {extension};")
            con.execute(f"LOAD {extension};")
        if settings is not None:
            _configure_cloud_secrets(con, settings)
        con.execute(
            f"ATTACH IF NOT EXISTS '{DUCKLAKE_ATTACH}' AS {DUCKLAKE_ALIAS} (READ_ONLY);"
        )
        return con
    except Exception:
        con.close()
        # Driver errors can contain connection strings; the UI displays this exception.
        raise RuntimeError(
            "Could not connect to DuckLake. Check the ducklake PostgreSQL, S3, and "
            "catalog settings in Streamlit secrets and network access to both services. "
            "For local use without Streamlit secrets, install the lakehouse and its "
            "PostgreSQL/S3 secrets in DuckDB."
        ) from None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Cached DuckLake connection, reused across reruns/queries in a session.

    Opening a connection installs extensions and re-attaches the Postgres/S3
    catalog, which is cheap locally but slow in cloud deployments — caching it
    avoids paying that cost on every query.
    """
    import streamlit as st

    @st.cache_resource(show_spinner=False)
    def _cached():
        return connect_ducklake()

    return _cached()


def list_ducklake_tables(schema: str = "ingest_ntpay") -> pd.DataFrame:
    """List tables in the selected DuckLake schema."""
    con = connect_ducklake()
    return con.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_catalog = ? AND table_schema = ?
        ORDER BY table_name
        """,
        [DUCKLAKE_ALIAS, schema],
    ).fetch_df()


def preview_table(table_name: str, schema: str = "ingest_ntpay", limit: int = 10) -> pd.DataFrame:
    """Preview rows from a DuckLake table."""
    con = connect_ducklake()
    sql = f"""
        SELECT *
        FROM {DUCKLAKE_ALIAS}.{schema}.{table_name}
        LIMIT ?
    """
    return con.execute(sql, [limit]).fetch_df()


def sample_ducklake() -> pd.DataFrame:
    con = connect_ducklake()
    return con.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_catalog = ? AND table_schema = 'ingest_ntpay'
        ORDER BY table_name
        LIMIT 20
        """,
        [DUCKLAKE_ALIAS],
    ).fetch_df()


def main() -> None:
    pd.set_option("display.max_columns", None)
    

    print("=== DUCKLAKE CONNECTION TEST ===")
    print(f"DuckDB file: {DUCKDB_PATH}")
    print(f"DuckLake alias: {DUCKLAKE_ALIAS}")

    print("\n=== DUCKLAKE TABLES ===")
    print(sample_ducklake().to_string(index=False))

    print("\n=== SAMPLE PREVIEW ===")
    try:
        df = preview_table("bank_accounts", limit=5)
        print(df.head().to_string(index=False))
    except Exception as exc:
        print(f"Preview failed: {exc}\n")
        print("Try a different table name from the list above.")


if __name__ == "__main__":
    main()
