"""NTPAY dashboard using newduckk.sql and the existing DuckLake connection.

Install: python -m pip install streamlit duckdb pandas
Run:     python -m streamlit run streamlit_ntpay.py
"""

from pathlib import Path
from datetime import timedelta

import streamlit as st

from newduck import get_connection
from latest_status_tab import render_latest_status_tab
from overview_v2_tab import render_overview_v2_tab
from overview_v3_tab import render_overview_v3_tab
from overview_v4_tab import render_overview_v4_tab, render_withdrawal_tab


SQL_PATH = Path(__file__).resolve().with_name("newduckk.sql")


@st.cache_data(ttl=300, show_spinner=False)
def get_latest_date(sql):
    """Return the most recent created_at date in the source data, or None."""
    source = sql.strip().rstrip(";")
    con = get_connection()
    latest = con.execute(f"SELECT MAX(created_at) FROM ({source}) AS source").fetchone()[0]
    if latest is None:
        return None
    return latest.date() if hasattr(latest, "date") else latest


@st.cache_data(ttl=300, show_spinner=False)
def get_merchant_options(sql, start, end):
    source = sql.strip().rstrip(";")
    date_where = ""
    params = []
    if start is not None and end is not None:
        date_where = "WHERE created_at >= ? AND created_at < ?"
        params = [start, end + timedelta(days=1)]
    con = get_connection()
    return con.execute(f"""
        SELECT DISTINCT COALESCE(merchant_category, '(Missing)') AS category,
            COALESCE(merchant_code, '(Missing)') AS merchant
        FROM ({source}) AS source {date_where}
        ORDER BY 1, 2
    """, params).fetch_df()


def merchant_scope_sql(sql, category, merchant):
    conditions = []
    for column, value in (("merchant_category", category), ("merchant_code", merchant)):
        if value is not None:
            literal = value.replace("'", "''")
            conditions.append(f"COALESCE({column}, '(Missing)') = '{literal}'")
    if not conditions:
        return sql
    source = sql.strip().rstrip(";")
    return f"SELECT * FROM ({source}) AS shared_source WHERE {' AND '.join(conditions)}"


def render_shared_filters():
    sql = SQL_PATH.read_text(encoding="utf-8-sig")
    applied = st.session_state.get("snapshot", {})
    try:
        if applied.get("start"):
            initial_range = (applied["start"], applied["end"])
        elif "start" in applied:
            initial_range = ()
        else:
            latest_date = get_latest_date(sql)
            initial_range = (latest_date, latest_date) if latest_date else ()

        with st.container(border=True):
            st.subheader("Shared filter")
            date_column, category_column, merchant_column = st.columns([2, 1, 1])
            date_range = date_column.date_input(
                "Date range", value=initial_range, key="shared_date_range",
            )
            if len(date_range) == 1:
                st.info("Select an end date to complete the date range.")
                return None
            start, end = date_range if len(date_range) == 2 else (None, None)
            if start is not None and start > end:
                st.error("The start date must be on or before the end date.")
                return None
            options = get_merchant_options(sql, start, end)
            categories = sorted(options["category"].unique())
            categories = [c for c in ["Internal", "External"] if c in categories] + [c for c in categories if c not in ("Internal", "External")]
            category_options = [None] + categories
            if st.session_state.get("shared_category") not in category_options:
                st.session_state.pop("shared_category", None)
            category = category_column.selectbox(
                "Merchant category", category_options, key="shared_category",
                format_func=lambda value: "All" if value is None else value,
            )
            available = options if category is None else options.loc[options["category"] == category]
            merchants = [None] + sorted(available["merchant"].unique())
            if st.session_state.get("shared_merchant") not in merchants:
                st.session_state.pop("shared_merchant", None)
            merchant = merchant_column.selectbox(
                "Merchant", merchants, key="shared_merchant",
                format_func=lambda value: "All" if value is None else value,
            )
            if st.button("Load / refresh", type="primary"):
                st.cache_data.clear()

        snapshot = {
            "sql": merchant_scope_sql(sql, category, merchant), "start": start, "end": end,
            "category": category, "merchant": merchant,
        }
        st.session_state["snapshot"] = snapshot
        return snapshot
    except Exception as exc:
        st.error("Could not load shared filters. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        return None


def main():
    st.set_page_config(page_title="NTPAY transactions", layout="wide")
    st.title("NTPAY transactions")
    snapshot = render_shared_filters()
    if snapshot is None:
        return

    tab_names = ["Deposit", "Withdrawal", "Overview", "Overview v2", "Overview v3"]
    selected = st.radio(
        "View", tab_names, key="active_tab", horizontal=True, label_visibility="collapsed",
    )

    # Render only the selected view so hidden tabs don't run their (expensive,
    # DuckLake-backed) queries on every rerun.
    if selected == "Deposit":
        render_overview_v4_tab(snapshot["sql"], snapshot.get("start"), snapshot.get("end"),
                            category=snapshot.get("category"), merchant=snapshot.get("merchant"))
    elif selected == "Withdrawal":
        render_withdrawal_tab(snapshot["sql"], snapshot.get("start"), snapshot.get("end"),
                            category=snapshot.get("category"), merchant=snapshot.get("merchant"))
    elif selected == "Overview":
        render_latest_status_tab(snapshot["sql"], snapshot.get("start"), snapshot.get("end"))
    elif selected == "Overview v2":
        render_overview_v2_tab(snapshot["sql"], snapshot.get("start"), snapshot.get("end"))
    elif selected == "Overview v3":
        render_overview_v3_tab(snapshot["sql"], snapshot.get("start"), snapshot.get("end"))


if __name__ == "__main__":
    main()


 
