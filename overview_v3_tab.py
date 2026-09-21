"""Overview v3: a concise operations layout preserving v4 metrics and scope."""

import altair as alt
import pandas as pd
import streamlit as st

from latest_status_tab import (
    NPR_TO_USD_RATE, CATEGORY_ORDER, SUCCESS_STATUS, AMOUNT_BUCKET_ORDER, _sort_order,
    load_latest_status, load_merchant_hour_data, load_amount_range_data,
)

GOOD_STATUSES = {SUCCESS_STATUS, "approved", "success"}
DEPOSIT_TYPE = "deposit"

TOOLTIP_FIELDS = [
    ("row_count", "Count", ","),
    ("usage", "Txn usage (%)", ",.1f"),
    ("total_amount", "Amount (NPR)", ",.2f"),
    ("total_amount_usd", "Amount (USD)", ",.2f"),
    ("amount_usage", "Amount usage (%)", ",.1f"),
    ("success_rate", "Success rate (%)", ",.1f"),
]


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


def _add_rate_columns(frame, type_total, type_amount):
    frame = frame.copy()
    frame["success_rate"] = (frame["success_rows"] / frame["row_count"] * 100).where(frame["row_count"] > 0)
    frame["total_amount_usd"] = frame["total_amount"] * NPR_TO_USD_RATE
    frame["usage"] = frame["row_count"] / type_total * 100 if type_total else 0.0
    frame["amount_usage"] = (
        frame["total_amount"] / type_amount * 100 if pd.notna(type_amount) and type_amount != 0 else float("nan")
    )
    return frame


def _dimension_order(values, preferred):
    if preferred:
        return _sort_order(values, preferred)
    return sorted(values)


def _fmt(value, kind):
    if pd.isna(value):
        return "N/A"
    if kind == "count":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{value:.1f}%"
    if kind == "npr":
        return f"{value:,.2f}"
    if kind == "usd":
        return f"${value:,.2f}"
    return str(value)


def _summary(leaf, dimensions, type_total, type_amount):
    grouped = leaf.groupby(dimensions, as_index=False, dropna=False).agg(
        row_count=("row_count", "sum"),
        success_rows=("success_rows", "sum"),
        total_amount=("total_amount", lambda values: values.sum(min_count=1)),
    )
    return _add_rate_columns(grouped, type_total, type_amount)


def _visible_metrics(dimension_col):
    return [metric for metric in TOOLTIP_FIELDS
            if dimension_col not in ("status", "amount_bucket") or metric[0] != "success_rate"]


def _metric_table(frame, dimensions, dimension_col, dimension_label):
    """Omit success rate from status and approved-only amount-range views."""
    st.dataframe(
        frame[dimensions + [field for field, _, _ in _visible_metrics(dimension_col)]],
        hide_index=True, width="stretch",
        height=min(650, 36 * (len(frame) + 1) + 4),
        column_config={
            dimension_col: st.column_config.TextColumn(dimension_label),
            "category": st.column_config.TextColumn("Merchant category"),
            "merchant_code": st.column_config.TextColumn("Merchant"),
            "row_count": st.column_config.NumberColumn("Count", format="%,d"),
            "usage": st.column_config.NumberColumn("Txn usage (%)", format="%,.1f%%"),
            "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%,.2f"),
            "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%,.2f"),
            "amount_usage": st.column_config.NumberColumn("Amount usage (%)", format="%,.1f%%"),
            "success_rate": st.column_config.ProgressColumn(
                "Success rate (%)", min_value=0, max_value=100, format="%,.1f%%",
            ),
        },
    )


def _breakdown_chart(frame, dimension_col, dimension_label, order, category_order=None):
    # Only the displayed dimensions and six reviewed measures enter the chart.
    dimensions = [dimension_col] + (["category"] if category_order else [])
    chart_frame = frame[dimensions + [field for field, _, _ in _visible_metrics(dimension_col)]]
    hourly = dimension_col == "hour_of_day"
    field = "success_rate" if hourly else "row_count"
    y_title = "Success rate (%)" if hourly else "Transaction count"
    scale = alt.Scale(domain=[0, 100]) if hourly else alt.Scale(zero=True)
    chart_frame = chart_frame.copy()
    chart_frame["bar_label"] = chart_frame[field].map(
        lambda value: "" if pd.isna(value) else (f"{value:,.1f}%" if hourly else f"{value:,.0f}")
    )
    tips = [alt.Tooltip(f"{dimension_col}:N", title=dimension_label)]
    if category_order:
        tips.append(alt.Tooltip("category:N", title="Merchant category"))
    tips += [alt.Tooltip(f"{field}:Q", title=title, format=fmt)
             for field, title, fmt in _visible_metrics(dimension_col)]
    base = alt.Chart(chart_frame).encode(
        x=alt.X(f"{dimension_col}:N", title=dimension_label, sort=order,
                axis=alt.Axis(labelAngle=0, labelOverlap=False)),
        y=alt.Y(f"{field}:Q", title=y_title, axis=alt.Axis(format=",.0f"), scale=scale),
        tooltip=tips,
    )
    if category_order:
        base = base.encode(
            xOffset=alt.XOffset("category:N", sort=category_order),
            color=alt.Color("category:N", title="Merchant category",
                            scale=alt.Scale(domain=category_order,
                                            range=["#1769aa", "#e09627", "#7b6cb0"][:len(category_order)])),
        )
        bars = base.mark_bar()
    else:
        bars = base.mark_bar(color="#1769aa")
    # Label each category's bar, not a combined total.
    labels = base.mark_text(dy=-8, fontSize=10).encode(
        text=alt.Text("bar_label:N"), color=alt.value("#333333"),
    )
    st.altair_chart((bars + labels).properties(height=240), width="stretch")


def _ordered(frame, dimension_col, order):
    ranks = {value: index for index, value in enumerate(order)}
    return frame.assign(_rank=frame[dimension_col].map(ranks)).sort_values("_rank").drop(columns="_rank")


def _render_flow(leaf, dimension_col, dimension_label, preferred_order, type_total, type_amount, category_order):
    if leaf.empty:
        st.info("No data is available for this breakdown.")
        return
    order = _dimension_order(leaf[dimension_col].unique(), preferred_order)
    overall = _ordered(_summary(leaf, [dimension_col], type_total, type_amount), dimension_col, order)
    by_category = _ordered(
        _summary(leaf, [dimension_col, "category"], type_total, type_amount), dimension_col, order,
    )
    by_merchant = _ordered(
        _summary(leaf, [dimension_col, "category", "merchant_code"], type_total, type_amount), dimension_col, order,
    )

    st.markdown("#### Overall")
    _breakdown_chart(overall, dimension_col, dimension_label, order)
    _metric_table(overall, [dimension_col], dimension_col, dimension_label)

    st.markdown("#### By merchant category")
    _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order)
    _metric_table(by_category, [dimension_col, "category"], dimension_col, dimension_label)

    st.markdown("#### By merchant")
    categories = _sort_order(
        set(CATEGORY_ORDER) | set(by_merchant["category"].unique()), CATEGORY_ORDER,
    )
    columns = st.columns(len(categories))
    for column, category in zip(columns, categories):
        with column:
            st.markdown(f"**{category}**")
            subset = by_merchant.loc[by_merchant["category"] == category]
            if subset.empty:
                st.caption("No matching merchants.")
                continue
            ranks = {value: index for index, value in enumerate(order)}
            subset = subset.assign(_rank=subset[dimension_col].map(ranks)).sort_values(["_rank", "merchant_code"])
            _metric_table(subset, [dimension_col, "merchant_code"], dimension_col, dimension_label)


def render_overview_v3_tab(sql, start=None, end=None):
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

    with st.container(horizontal=True, key="v3_kpis"):
        st.metric("Transaction rows", f"{type_total:,}", border=True)
        st.metric("Approved rows", f"{approved_rows:,}", border=True)
        st.metric("Amount (NPR)", "N/A" if pd.isna(type_amount) else f"{type_amount:,.2f}", border=True)
        st.metric("Amount (USD)", "N/A" if pd.isna(type_amount) else f"${type_amount * NPR_TO_USD_RATE:,.2f}", border=True)
        st.metric("Success rate", "N/A" if pd.isna(overall_rate) else f"{overall_rate:.1f}%", border=True)

    st.caption(
        f"1 NPR = {NPR_TO_USD_RATE} USD."
    )

    # ---- By status ----
    with st.container(border=True):
        st.subheader("1. Status")
        st.caption("All deposit statuses. Count and amount usage use the full deposit total.")
        status_leaf = type_merchant_hour.groupby(
            ["category", "merchant_code", "status"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
        status_leaf["success_rows"] = status_leaf["row_count"].where(
            status_leaf["status"].str.lower().isin(GOOD_STATUSES), 0
        )
        _render_flow(status_leaf, "status", "Status", None, type_total, type_amount, category_order)

    # ---- By hour of day ----
    with st.container(border=True):
        st.subheader("2. Hour of day")
        st.caption(
            "Nepal local time, grouped across the selected dates. Usage uses the full deposit total."
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
        st.subheader("3. Amount range")
        st.caption(
            "Approved/success deposits only. Amount ranges are in NPR; both usage percentages use "
            "the approved deposit totals."
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
