from __future__ import annotations
from pathlib import Path
import duckdb
import pandas as pd

DUCKDB_PATH = Path(r"C:\Users\User\Desktop\NTPAY\nera_oc.duckdb")
DUCKLAKE_ATTACH = "ducklake:lakehouse"
DUCKLAKE_ALIAS = "ducklake"


def connect_ducklake(
    duckdb_path: str | Path = DUCKDB_PATH,
) -> duckdb.DuckDBPyConnection:

    con = duckdb.connect(str(duckdb_path))
    con.execute("INSTALL ducklake;")
    con.execute("LOAD ducklake;")
    con.execute(
        f"ATTACH IF NOT EXISTS '{DUCKLAKE_ATTACH}' AS {DUCKLAKE_ALIAS} (READ_ONLY);"
    )
    return con


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
