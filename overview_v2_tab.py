"""Overview v2: a consistent Overall -> By merchant category -> By merchant drill
hierarchy, applied identically to three breakdown dimensions (status, hour of day,
amount range). Deposit only for now, to validate the concept before Withdrawal.

Every table (Overall, By merchant category, By merchant) shows the same six
metrics: Count, Txn usage (%), Amount (NPR), Amount (USD), Amount usage (%),
Success rate (%).

"Success" here means status in {success, approved} (they are distinct literal
status values in the data that both count as approved), matching the definition
used in the Overview tab's "By merchant category" chart.
"""

import pandas as pd
import streamlit as st

from latest_status_tab import (
    NPR_TO_USD_RATE, CATEGORY_ORDER, SUCCESS_STATUS, AMOUNT_BUCKET_ORDER, _sort_order,
    load_latest_status, load_merchant_hour_data, load_amount_range_data,
)

GOOD_STATUSES = {SUCCESS_STATUS, "approved", "success"}
DEPOSIT_TYPE = "deposit"


def _label_common(frame):
    frame = frame.copy()
    if "transaction_type" in frame.columns:
        frame["type_label"] = frame["transaction_type"].astype("string").fillna("(Missing)").str.title()
    if "merchant_category" in frame.columns:
        frame["category"] = frame["merchant_category"].astype("string").fillna("(Missing)")
    if "merchant_code" in frame.columns:
        frame["merchant_code"] = frame["merchant_code"].astype("string").fillna("(Missing)")
    if "status" in frame.columns:
        frame["status"] = frame["status"].astype("string").fillna("(Missing)")
    if "amount_bucket" in frame.columns:
        frame["amount_bucket"] = frame["amount_bucket"].astype("string").fillna("(Missing)")
    return frame


def _add_rate_columns(frame, type_total, type_amount, with_usage):
    frame = frame.copy()
    frame["success_rate"] = (frame["success_rows"] / frame["row_count"] * 100).where(frame["row_count"] > 0)
    frame["total_amount_usd"] = frame["total_amount"] * NPR_TO_USD_RATE
    if with_usage:
        frame["usage"] = frame["row_count"] / type_total * 100 if type_total else 0.0
        frame["amount_usage"] = (
            frame["total_amount"] / type_amount * 100
            if pd.notna(type_amount) and type_amount != 0 else float("nan")
        )
    return frame


def _dimension_order(values, preferred):
    if preferred:
        return _sort_order(values, preferred)
    return sorted(values)


def _overall_table(leaf, dimension_col, dimension_label, order, type_total, type_amount):
    overall = leaf.groupby(dimension_col, as_index=False).agg(
        row_count=("row_count", "sum"), success_rows=("success_rows", "sum"),
        total_amount=("total_amount", lambda v: v.sum(min_count=1)),
    )
    overall = _add_rate_columns(overall, type_total, type_amount, with_usage=True)
    overall = overall.set_index(dimension_col).loc[order].reset_index()
    st.markdown("**Overall**")
    st.dataframe(
        overall[[dimension_col, "row_count", "usage", "total_amount", "total_amount_usd",
                 "amount_usage", "success_rate"]],
        hide_index=True, width="stretch",
        column_config={
            dimension_col: st.column_config.TextColumn(dimension_label),
            "row_count": st.column_config.NumberColumn("Count", format="localized"),
            "usage": st.column_config.NumberColumn("Txn usage (%)", format="%.1f%%"),
            "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
            "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
            "amount_usage": st.column_config.NumberColumn("Amount usage (%)", format="%.1f%%"),
            "success_rate": st.column_config.NumberColumn("Success rate (%)", format="%.1f%%"),
        },
    )


def _category_table(leaf, dimension_col, dimension_label, order, type_total, type_amount, category_order):
    by_cat = leaf.groupby([dimension_col, "category"], as_index=False).agg(
        row_count=("row_count", "sum"), success_rows=("success_rows", "sum"),
        total_amount=("total_amount", lambda v: v.sum(min_count=1)),
    )
    by_cat = _add_rate_columns(by_cat, type_total, type_amount, with_usage=True)
    dim_rank = {value: index for index, value in enumerate(order)}
    cat_rank = {value: index for index, value in enumerate(category_order)}
    by_cat = by_cat.assign(
        _dim_sort=by_cat[dimension_col].map(dim_rank), _cat_sort=by_cat["category"].map(cat_rank),
    ).sort_values(["_dim_sort", "_cat_sort"]).drop(columns=["_dim_sort", "_cat_sort"])
    st.markdown("**By merchant category**")
    st.dataframe(
        by_cat[[dimension_col, "category", "row_count", "usage", "total_amount", "total_amount_usd",
                "amount_usage", "success_rate"]],
        hide_index=True, width="stretch",
        column_config={
            dimension_col: st.column_config.TextColumn(dimension_label),
            "category": st.column_config.TextColumn("Merchant category"),
            "row_count": st.column_config.NumberColumn("Count", format="localized"),
            "usage": st.column_config.NumberColumn("Txn usage (%)", format="%.1f%%"),
            "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
            "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
            "amount_usage": st.column_config.NumberColumn("Amount usage (%)", format="%.1f%%"),
            "success_rate": st.column_config.NumberColumn("Success rate (%)", format="%.1f%%"),
        },
    )


def _merchant_tables(leaf, dimension_col, dimension_label, order, type_total, type_amount, category_order):
    by_merchant = leaf.groupby([dimension_col, "category", "merchant_code"], as_index=False).agg(
        row_count=("row_count", "sum"), success_rows=("success_rows", "sum"),
        total_amount=("total_amount", lambda v: v.sum(min_count=1)),
    )
    by_merchant = _add_rate_columns(by_merchant, type_total, type_amount, with_usage=True)
    dim_rank = {value: index for index, value in enumerate(order)}
    by_merchant = by_merchant.assign(_dim_sort=by_merchant[dimension_col].map(dim_rank))

    st.markdown("**By merchant**")
    present_categories = _sort_order(by_merchant["category"].unique(), category_order)
    for category_label in present_categories:
        st.caption(f"{category_label} merchants")
        subset = (
            by_merchant.loc[by_merchant["category"] == category_label]
            .sort_values(["_dim_sort", "merchant_code"])
            .drop(columns="_dim_sort")
        )
        st.dataframe(
            subset[[dimension_col, "merchant_code", "row_count", "usage", "total_amount", "total_amount_usd",
                    "amount_usage", "success_rate"]],
            hide_index=True, width="stretch",
            column_config={
                dimension_col: st.column_config.TextColumn(dimension_label),
                "merchant_code": st.column_config.TextColumn("Merchant"),
                "row_count": st.column_config.NumberColumn("Count", format="localized"),
                "usage": st.column_config.NumberColumn("Txn usage (%)", format="%.1f%%"),
                "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
                "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
                "amount_usage": st.column_config.NumberColumn("Amount usage (%)", format="%.1f%%"),
                "success_rate": st.column_config.NumberColumn("Success rate (%)", format="%.1f%%"),
            },
        )


def _render_flow(leaf, dimension_col, dimension_label, preferred_order, type_total, type_amount, category_order):
    if leaf.empty:
        st.info("No data is available for this breakdown.")
        return
    order = _dimension_order(leaf[dimension_col].unique(), preferred_order)
    _overall_table(leaf, dimension_col, dimension_label, order, type_total, type_amount)
    _category_table(leaf, dimension_col, dimension_label, order, type_total, type_amount, category_order)
    _merchant_tables(leaf, dimension_col, dimension_label, order, type_total, type_amount, category_order)


def render_overview_v2_tab(sql, start=None, end=None):
    st.info(
        "Overview v2 - proof of concept for a consistent Overall -> By merchant category -> "
        "By merchant drill flow, applied to Status / Hour of day / Amount range. Deposit only "
        "for now; Withdrawal comes after this shape is confirmed."
    )

    try:
        with st.spinner("Loading status totals..."):
            counts = load_latest_status(sql, start, end)
        with st.spinner("Loading merchant / hour-of-day breakdown..."):
            merchant_hour = load_merchant_hour_data(sql, start, end)
        with st.spinner("Loading amount-range breakdown..."):
            amount_range = load_amount_range_data(sql, start, end)
    except Exception as exc:
        st.error("Could not load data. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        return

    if counts.empty:
        st.info("No transactions are available in the applied date range.")
        return

    counts = _label_common(counts)
    merchant_hour = _label_common(merchant_hour)
    amount_range = _label_common(amount_range)

    period = f"{start:%d %b %Y} to {end:%d %b %Y}" if start is not None and end is not None else "All dates"
    st.subheader(f"Deposit - {period}")

    type_counts = counts.loc[counts["transaction_type"].astype("string").str.lower() == DEPOSIT_TYPE]
    type_merchant_hour = merchant_hour.loc[merchant_hour["transaction_type"].astype("string").str.lower() == DEPOSIT_TYPE]
    type_amount_range_all = amount_range.loc[
        amount_range["transaction_type"].astype("string").str.lower() == DEPOSIT_TYPE
    ]

    if type_counts.empty:
        st.info("No deposit transactions are available in the applied date range.")
        return

    type_total = int(type_counts["row_count"].sum())
    type_amount = type_counts["total_amount"].sum(min_count=1)
    category_order = _sort_order(type_counts["category"].unique(), CATEGORY_ORDER)

    is_good = type_counts["status"].str.lower().isin(GOOD_STATUSES)
    approved_rows = int(type_counts.loc[is_good, "row_count"].sum())
    approved_amount = type_counts.loc[is_good, "total_amount"].sum(min_count=1)
    overall_rate = (approved_rows / type_total * 100) if type_total else float("nan")

    with st.container(horizontal=True, key="v2_kpis"):
        st.metric("Transaction rows", f"{type_total:,}", border=True)
        st.metric("Approved rows", f"{approved_rows:,}", border=True)
        st.metric("Amount (NPR)", "N/A" if pd.isna(type_amount) else f"{type_amount:,.2f}", border=True)
        st.metric("Amount (USD)", "N/A" if pd.isna(type_amount) else f"${type_amount * NPR_TO_USD_RATE:,.2f}", border=True)
        st.metric("Success rate", "N/A" if pd.isna(overall_rate) else f"{overall_rate:.1f}%", border=True)

    # ---- By status ----
    with st.container(border=True):
        st.subheader("By status")
        st.caption("Overall -> by merchant category -> by merchant, broken down by status.")
        status_leaf = type_merchant_hour.groupby(
            ["category", "merchant_code", "status"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
        status_leaf["success_rows"] = status_leaf["row_count"].where(
            status_leaf["status"].str.lower().isin(GOOD_STATUSES), 0
        )
        _render_flow(status_leaf, "status", "Status", None, type_total, type_amount, category_order)

    # ---- By hour of day ----
    with st.container(border=True):
        st.subheader("By hour of day")
        st.caption(
            "Overall -> by merchant category -> by merchant, broken down by hour of day "
            "(Nepal local time)."
        )
        hour_leaf = type_merchant_hour.groupby(
            ["category", "merchant_code", "hour_of_day"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
        success_by_hour_leaf = (
            type_merchant_hour.loc[type_merchant_hour["status"].str.lower().isin(GOOD_STATUSES)]
            .groupby(["category", "merchant_code", "hour_of_day"])["row_count"].sum()
        )
        hour_leaf = hour_leaf.set_index(["category", "merchant_code", "hour_of_day"])
        hour_leaf["success_rows"] = success_by_hour_leaf
        hour_leaf = hour_leaf.reset_index()
        hour_leaf["success_rows"] = hour_leaf["success_rows"].fillna(0)
        hour_leaf["hour_of_day"] = hour_leaf["hour_of_day"].astype("string")
        hour_order = [str(h) for h in range(24)]
        _render_flow(hour_leaf, "hour_of_day", "Hour of day", hour_order, type_total, type_amount, category_order)

    # ---- By amount range (approved / success only) ----
    with st.container(border=True):
        st.subheader("By amount range")
        st.caption(
            "Overall -> by merchant category -> by merchant, broken down by transaction amount (NPR). "
            "Restricted to approved/success transactions only - usage and amount shares are relative "
            "to the approved-only total, not the type's full total."
        )
        approved_amount_range = type_amount_range_all.loc[
            type_amount_range_all["status"].str.lower().isin(GOOD_STATUSES)
        ]
        bucket_leaf = approved_amount_range.groupby(
            ["category", "merchant_code", "amount_bucket"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
        bucket_leaf["success_rows"] = bucket_leaf["row_count"]
        bucket_order = _sort_order(bucket_leaf["amount_bucket"].unique(), AMOUNT_BUCKET_ORDER)
        _render_flow(
            bucket_leaf, "amount_bucket", "Amount range (NPR)", bucket_order,
            approved_rows, approved_amount, category_order,
        )
