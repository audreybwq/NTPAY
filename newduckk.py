"""Run newduckk.sql using the connection configured in newduck.py.

Run from PowerShell: python newduckk.py
Edit newduckk.sql to change the query, then run this script again.
"""

from pathlib import Path

from newduck import connect_ducklake


SQL_PATH = Path(__file__).resolve().with_suffix(".sql")


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    print(f"Running query from: {SQL_PATH}")
    con = connect_ducklake()
    try:
        result = con.execute(sql).fetch_df()
        print(f"\nMatching rows: {len(result):,}")
        if result.empty:
            print("No rows match the query filters.")
        else:
            print("Showing the first 20 rows (duration is in seconds):\n")
            print(result.head(20).to_string(index=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
