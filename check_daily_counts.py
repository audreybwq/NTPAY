"""Count newduckk.sql results by Nepal date and transaction type."""

from pathlib import Path

from newduck import connect_ducklake


def main() -> None:
    directory = Path(__file__).resolve().parent
    sql = (directory / "newduckk.sql").read_text(encoding="utf-8").strip().rstrip(";")
    con = connect_ducklake()
    try:
        # Match the SQL's UTC-to-Nepal offset even for timezone-aware columns.
        con.execute("SET TimeZone = 'UTC'")
        daily = con.execute(f"""
            WITH filtered AS ({sql})
            SELECT
                CAST(converted_created_at AS DATE) AS nepal_date,
                transaction_type,
                COUNT(*) AS cnt
            FROM filtered
            GROUP BY 1, 2
            ORDER BY 1 DESC NULLS LAST, 2
        """).fetch_df()
        print(daily.to_string(index=False))
        print(f"\nTotal count: {int(daily['cnt'].sum()):,}")
        output = directory / "newduckk_daily_counts_by_type.csv"
        daily.to_csv(output, index=False)
        print(f"Saved: {output}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
