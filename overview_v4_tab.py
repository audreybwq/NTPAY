"""Overview v4: one merchant scope for all metrics, charts and tables."""

import altair as alt
import pandas as pd
import streamlit as st
from datetime import timedelta

from newduck import connect_ducklake

from latest_status_tab import (
    NPR_TO_USD_RATE, CATEGORY_ORDER, SUCCESS_STATUS, AMOUNT_BUCKET_ORDER, _sort_order,
    load_merchant_hour_data, load_amount_range_data,
)

GOOD_STATUSES = {SUCCESS_STATUS, "approved", "success"}
CATEGORY_COLORS = {"Internal": "#1769aa", "External": "#e09627"}

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
        **_latency_aggregation(leaf),
    )
    if "latency_rows" in grouped:
        grouped["avg_latency"] = grouped["latency_sum"] / grouped["latency_rows"].where(grouped["latency_rows"] > 0)
    return _add_rate_columns(grouped, type_total, type_amount)


def _latency_aggregation(frame):
    return {name: (name, "sum") for name in ("latency_sum", "latency_rows") if name in frame}


def _format_latency(value):
    if pd.isna(value):
        return "N/A"
    seconds = int(float(value) + 0.5)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:,}m {seconds}s" if minutes else f"{seconds}s"


def _latency_expression(value):
    rounded = f"round({value})"
    return (
        f"isValid({value}) ? ({rounded} >= 60 ? "
        f"format(floor({rounded} / 60), ',.0f') + 'm ' + ({rounded} % 60) + 's' "
        f": {rounded} + 's') : 'N/A'"
    )


def _visible_metrics(dimension_col, frame=None):
    metrics = [metric for metric in TOOLTIP_FIELDS
            if dimension_col not in ("status", "amount_bucket") or metric[0] != "success_rate"]
    if frame is not None and "avg_latency" in frame:
        metrics.append(("avg_latency", "Avg latency", ",.1f"))
    return metrics


def _metric_table(frame, dimensions, dimension_col, dimension_label):
    """Omit success rate from status and approved-only amount-range views."""
    display = frame[dimensions + [field for field, _, _ in _visible_metrics(dimension_col, frame)]].copy()
    if "avg_latency" in display:
        display["avg_latency"] = display["avg_latency"].map(_format_latency)
    st.dataframe(
        display,
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
            "avg_latency": st.column_config.TextColumn("Avg latency"),
        },
    )


def _breakdown_chart(frame, dimension_col, dimension_label, order, category_order=None, *, latency=False):
    # Only the displayed dimensions and six reviewed measures enter the chart.
    dimensions = [dimension_col] + (["category"] if category_order else [])
    chart_frame = frame[dimensions + [field for field, _, _ in _visible_metrics(dimension_col, frame)]].copy()
    # Fixed display strings also preserve trailing .0 in Streamlit's Show data.
    # Quantitative chart encodings still interpret these values as numbers.
    for percentage in ("usage", "amount_usage", "success_rate"):
        if percentage in chart_frame:
            chart_frame[percentage] = chart_frame[percentage].map(
                lambda value: None if pd.isna(value) else f"{value:.1f}"
            )
    percentage_names = {
        "usage": "Txn usage (%)",
        "amount_usage": "Amount usage (%)",
        "success_rate": "Success rate (%)",
    }
    chart_frame = chart_frame.rename(columns=percentage_names)
    hourly = dimension_col == "hour_of_day"
    rate_chart = hourly and not latency
    field = "avg_latency" if latency else (percentage_names["success_rate"] if hourly else "row_count")
    y_title = "Avg latency" if latency else ("Success rate (%)" if hourly else "Transaction count")
    scale = alt.Scale(domain=[0, 100]) if rate_chart else alt.Scale(zero=True)
    # Source rows contain only business fields; label helpers are computed by Vega.
    chart_max = 100 if rate_chart else chart_frame[field].max()
    chart_max = float(chart_max) if pd.notna(chart_max) and chart_max > 0 else 0.0
    value_expression = f"datum[{field!r}]"
    label_expression = (
        _latency_expression(value_expression) if latency else
        f"format({value_expression}, ',.1f') + '%'" if rate_chart
        else f"format({value_expression}, ',.0f')"
    )
    missing_label = "N/A" if latency else ""
    label_expression = f"isValid({value_expression}) ? ({label_expression}) : '{missing_label}'"
    tips = [alt.Tooltip(f"{dimension_col}:N", title=dimension_label)]
    if category_order:
        tips.append(alt.Tooltip("category:N", title="Merchant category"))
    tips += [alt.Tooltip("latency_display:N", title="Avg latency") if field == "avg_latency" else
             alt.Tooltip(f"{percentage_names.get(field, field)}:Q", title=title, format=fmt)
             for field, title, fmt in _visible_metrics(dimension_col, frame)]
    base = alt.Chart(chart_frame)
    if "avg_latency" in chart_frame:
        base = base.transform_calculate(latency_display=_latency_expression("datum.avg_latency"))
    value_axis = alt.Axis(labelExpr=_latency_expression("datum.value")) if latency else alt.Axis(format=",.0f")
    base = base.encode(
        x=alt.X(f"{dimension_col}:N", title=dimension_label, sort=order,
                axis=alt.Axis(labelAngle=0, labelOverlap=False)),
        y=alt.Y(f"{field}:Q", title=y_title, axis=value_axis, scale=scale),
        tooltip=tips,
    )
    if category_order:
        offset = {"xOffset": alt.XOffset("category:N", sort=category_order)}
        base = base.encode(
            **offset,
            color=alt.Color("category:N", title="Merchant category", legend=None,
                            scale=alt.Scale(domain=category_order,
                                            range=[CATEGORY_COLORS.get(category, "#7b6cb0") for category in category_order])),
        )
        bars = base.mark_bar()
    else:
        bars = base.mark_bar(color="#1769aa")
    label_base = base.transform_calculate(raw_label=label_expression)
    required_height = "length(datum.raw_label) * 7 + 12"
    label_base = label_base.transform_calculate(
        bar_label="datum.raw_label",
        label_midpoint=f"{value_expression} / 2",
        label_anchor=f"isValid({value_expression}) ? {value_expression} : 0",
        label_inside=(
            f"isValid({value_expression}) && {value_expression} / {chart_max} * 240 >= ({required_height})"
            if chart_max else "false"
        ),
    )
    # Values read vertically along each bar, without splitting the text.
    labels = label_base.transform_filter(alt.datum.label_inside).mark_text(
        angle=270, baseline="middle", align="center",
        fontSize=10 if hourly else 12, fontWeight="bold", lineBreak="\n", lineHeight=14,
    ).encode(
        y=alt.Y("label_midpoint:Q", title=y_title, scale=scale),
        text=alt.Text("bar_label:N"), color=alt.value("white"),
    )
    small_labels = label_base.transform_filter(~alt.datum.label_inside).mark_text(
        dx=8, dy=0,
        fontSize=10 if hourly else 12, baseline="middle",
        angle=270, align="left",
    ).encode(
        y=alt.Y("label_anchor:Q", title=y_title, scale=scale),
        text=alt.Text("bar_label:N"), color=alt.value("#333333"),
    )
    chart = (
        (bars + labels + small_labels).properties(
            height=240,
        )
        .configure_axis(labelFontSize=14, titleFontSize=16, titleFontWeight="normal")
        .configure_legend(labelFontSize=14, titleFontSize=16, titleFontWeight="normal")
    )
    st.altair_chart(chart, width="stretch")


def _ordered(frame, dimension_col, order):
    ranks = {value: index for index, value in enumerate(order)}
    return frame.assign(_rank=frame[dimension_col].map(ranks)).sort_values("_rank").drop(columns="_rank")


def _render_flow(leaf, dimension_col, dimension_label, preferred_order, type_total, type_amount):
    if leaf.empty:
        st.info("No data is available for this breakdown.")
        return
    order = _dimension_order(leaf[dimension_col].unique(), preferred_order)
    overall = _ordered(_summary(leaf, [dimension_col], type_total, type_amount), dimension_col, order)
    by_category = _ordered(
        _summary(leaf, [dimension_col, "category"], type_total, type_amount), dimension_col, order,
    )
    category_order = _sort_order(leaf["category"].unique(), CATEGORY_ORDER)
    st.markdown("#### By merchant category")
    if "avg_latency" in by_category and dimension_col == "hour_of_day":
        st.markdown("**Success rate (%)**")
        _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order)
        st.markdown("**Avg latency**")
        _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order, latency=True)
    elif "avg_latency" in by_category:
        metric_column, latency_column = st.columns(2)
        with metric_column:
            st.markdown("**Success rate (%)**" if dimension_col == "hour_of_day" else "**Transaction count**")
            _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order)
        with latency_column:
            st.markdown("**Avg latency**")
            _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order, latency=True)
    else:
        _breakdown_chart(by_category, dimension_col, dimension_label, order, category_order)
    st.markdown("#### Overall")
    _metric_table(overall, [dimension_col], dimension_col, dimension_label)


def _apply_scope(frame, category, merchant):
    selected = frame
    if category is not None:
        selected = selected.loc[selected["category"] == category]
    if merchant is not None:
        selected = selected.loc[selected["merchant_code"] == merchant]
    return selected.copy()


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_withdrawal_overview(sql, start=None, end=None):
    """Keep latency sums and valid-row counts for weighted rollups at every level."""
    source = sql.strip().rstrip(";")
    dates = ""
    params = []
    if start is not None and end is not None:
        dates = "AND created_at >= ? AND created_at < ?"
        params = [start, end + timedelta(days=1)]
    query = f"""
        WITH source AS ({source}), measured AS (
            SELECT *,
                CASE WHEN LOWER(status) IN ('approved', 'success')
                          AND end_time >= created_at
                    THEN date_diff('millisecond', created_at, end_time) / 1000.0
                END AS valid_latency,
                EXTRACT(HOUR FROM converted_created_at) AS hour_of_day,
                CASE
                    WHEN amount IS NULL THEN '(Missing)'
                    WHEN amount < 500 THEN '< 500'
                    WHEN amount < 1000 THEN '500 - 1,000'
                    WHEN amount < 10000 THEN '1,000 - 10,000'
                    WHEN amount < 20000 THEN '10,000 - 20,000'
                    ELSE '> 20,000'
                END AS amount_bucket
            FROM source
            WHERE LOWER(transaction_type) = 'withdrawal' {dates}
        )
        SELECT transaction_type, merchant_category, merchant_code, status,
            hour_of_day, amount_bucket,
            COUNT(*) AS row_count, SUM(amount) AS total_amount,
            SUM(valid_latency) AS latency_sum, COUNT(valid_latency) AS latency_rows
        FROM measured
        GROUP BY transaction_type, merchant_category, merchant_code, status,
            hour_of_day, amount_bucket
    """
    con = connect_ducklake()
    try:
        leaf = con.execute(query, params).fetch_df()
    finally:
        con.close()
    keys = ["transaction_type", "merchant_category", "merchant_code", "status"]
    def rollup(dimension):
        return leaf.groupby(keys + [dimension], as_index=False, dropna=False).agg(
            row_count=("row_count", "sum"),
            total_amount=("total_amount", lambda values: values.sum(min_count=1)),
            **_latency_aggregation(leaf),
        )
    return rollup("hour_of_day"), rollup("amount_bucket")


@st.cache_data(ttl=300, max_entries=2, show_spinner=False)
def load_withdrawal_details(sql, start=None, end=None, category=None, merchant=None):
    source = sql.strip().rstrip(";")
    filters = ["LOWER(transaction_type) = 'withdrawal'"]
    params = []
    if start is not None and end is not None:
        filters.append("created_at >= ? AND created_at < ?")
        params.extend([start, end + timedelta(days=1)])
    if category is not None:
        filters.append("COALESCE(merchant_category, '(Missing)') = ?")
        params.append(category)
    if merchant is not None:
        filters.append("COALESCE(merchant_code, '(Missing)') = ?")
        params.append(merchant)
    query = f"""SELECT *, CASE WHEN end_time >= created_at
        THEN date_diff('millisecond', created_at, end_time) / 1000.0
        END AS latency_seconds,
        EXTRACT(HOUR FROM converted_created_at) AS created_hour,
        EXTRACT(MINUTE FROM converted_created_at) AS created_minute
        FROM ({source}) AS source
        WHERE {' AND '.join(filters)} ORDER BY created_at DESC NULLS LAST"""
    con = connect_ducklake()
    try:
        return con.execute(query, params).fetch_df()
    finally:
        con.close()


def _withdrawal_details(sql, start, end, category, merchant):
    details_panel = st.expander(
        "Transaction details", expanded=False,
        key="withdrawal_status_details", on_change="rerun",
    )
    if details_panel.open:
        with details_panel:
            try:
                with st.spinner("Loading withdrawal details..."):
                    details = load_withdrawal_details(sql, start, end, category, merchant)
            except Exception as exc:
                st.error("Could not load withdrawal details.")
                st.code(str(exc))
                return
            if details.empty:
                st.info("No withdrawal transactions match these filters.")
                return
            order_column, status_column, hour_column = st.columns([2, 1, 1])
            order_search = order_column.text_input(
                "Merchant order ID contains", key="withdrawal_details_order_id",
            ).strip()
            status_values = details["status"].astype("string").fillna("(Missing)")
            status_options = sorted(status_values.unique().tolist())
            status_key = "withdrawal_details_status"
            if status_key in st.session_state:
                valid_selection = [value for value in st.session_state[status_key] if value in status_options]
                if valid_selection != st.session_state[status_key]:
                    st.session_state[status_key] = valid_selection
            selected_statuses = status_column.multiselect(
                "Status", status_options, key=status_key, placeholder="All statuses",
            )
            hour_options = sorted(int(hour) for hour in details["created_hour"].dropna().unique())
            hour_key = "withdrawal_details_created_hour"
            if hour_key in st.session_state:
                valid_hours = [hour for hour in st.session_state[hour_key] if hour in hour_options]
                if valid_hours != st.session_state[hour_key]:
                    st.session_state[hour_key] = valid_hours
            selected_hours = hour_column.multiselect(
                "Created hour (MYR)", hour_options, key=hour_key,
                placeholder="All hours", format_func=lambda hour: f"{hour:02d}:00–{hour:02d}:59",
            )
            mask = pd.Series(True, index=details.index)
            if order_search:
                mask &= details["merchant_order_id"].astype("string").str.contains(
                    order_search, case=False, regex=False, na=False,
                )
            if selected_statuses:
                mask &= status_values.isin(selected_statuses)
            if selected_hours:
                mask &= details["created_hour"].isin(selected_hours)
            filtered_details = details.loc[mask]
            st.caption(f"{len(filtered_details):,} of {len(details):,} withdrawal transactions")
            if filtered_details.empty:
                st.info("No transactions match the merchant order ID, status and created-hour filters.")
                return
            detail_columns = [column for column in filtered_details.columns
                              if column not in ("created_hour", "created_minute")]
            time_position = detail_columns.index("converted_created_at") + 1
            detail_columns[time_position:time_position] = ["created_hour", "created_minute"]
            st.dataframe(
                filtered_details[detail_columns], hide_index=True, width="stretch",
                column_config={
                    "amount": st.column_config.NumberColumn("Amount (NPR)", format="%,.2f"),
                    "latency_seconds": st.column_config.NumberColumn("Latency (s)", format="%,.1f"),
                    "converted_created_at": st.column_config.DatetimeColumn("Converted created at (MYR)"),
                    "created_hour": st.column_config.NumberColumn("Created hour (MYR)", format="%02d"),
                    "created_minute": st.column_config.NumberColumn("Created minute (MYR)", format="%02d"),
                },
            )


def render_overview_v4_tab(sql, start=None, end=None, *, category=None, merchant=None):
    render_transaction_overview(sql, start, end, transaction_type="deposit", category=category, merchant=merchant)


def render_withdrawal_tab(sql, start=None, end=None, *, category=None, merchant=None):
    render_transaction_overview(sql, start, end, transaction_type="withdrawal", category=category, merchant=merchant)


def render_transaction_overview(sql, start=None, end=None, *, transaction_type, category=None, merchant=None):
    if transaction_type not in ("deposit", "withdrawal"):
        raise ValueError("Unsupported transaction type")
    key_prefix = f"overview_{transaction_type}"
    type_plural = f"{transaction_type}s"
    try:
        if transaction_type == "withdrawal":
            with st.spinner("Loading withdrawal totals and latency..."):
                merchant_hour, amount_range = load_withdrawal_overview(sql, start, end)
        else:
            with st.spinner("Loading merchant / hour-of-day breakdown..."):
                merchant_hour = load_merchant_hour_data(sql, start, end)
            with st.spinner("Loading amount-range breakdown..."):
                amount_range = load_amount_range_data(sql, start, end)
    except Exception as exc:
        st.error("Could not load data. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        return

    if merchant_hour.empty:
        st.info("No transactions are available in the applied date range.")
        return

    merchant_hour = _label_common(merchant_hour)
    amount_range = _label_common(amount_range)

    period = f"{start:%d %b %Y} to {end:%d %b %Y}" if start is not None and end is not None else "All dates"

    type_merchant_hour = merchant_hour.loc[merchant_hour["transaction_type"].astype("string").str.lower() == transaction_type]
    type_amount_range_all = amount_range.loc[
        amount_range["transaction_type"].astype("string").str.lower() == transaction_type
    ]

    if type_merchant_hour.empty:
        st.info(f"No {transaction_type} transactions are available in the applied date range.")
        return

    type_merchant_hour = _apply_scope(type_merchant_hour, category, merchant)
    type_amount_range_all = _apply_scope(type_amount_range_all, category, merchant)
    scope = f"Merchant: {merchant}" if merchant is not None else (f"{category} {type_plural}" if category else f"All {type_plural}")
    st.subheader(f"{scope} - {period}")
    st.markdown(":blue[● **Internal**]　　:orange[● **External**]")
    if type_merchant_hour.empty:
        st.info(f"No {type_plural} match the selected merchant filters.")
        return
    # This merchant-level aggregate supports the same scope for KPIs and every breakdown.
    type_counts = type_merchant_hour
    type_total = int(type_counts["row_count"].sum())
    type_amount = type_counts["total_amount"].sum(min_count=1)

    is_good = type_counts["status"].str.lower().isin(GOOD_STATUSES)
    approved_rows = int(type_counts.loc[is_good, "row_count"].sum())
    approved_amount = type_counts.loc[is_good, "total_amount"].sum(min_count=1)
    overall_rate = (approved_rows / type_total * 100) if type_total else float("nan")

    with st.container(horizontal=True, key=f"{key_prefix}_kpis"):
        st.metric("Transaction rows", f"{type_total:,}", border=True)
        st.metric("Approved rows", f"{approved_rows:,}", border=True)
        st.metric("Amount (NPR)", "N/A" if pd.isna(type_amount) else f"{type_amount:,.2f}", border=True)
        st.metric("Amount (USD)", "N/A" if pd.isna(type_amount) else f"${type_amount * NPR_TO_USD_RATE:,.2f}", border=True)
        st.metric("Success rate", "N/A" if pd.isna(overall_rate) else f"{overall_rate:.1f}%", border=True)

    st.caption(
        f"1 NPR = {NPR_TO_USD_RATE} USD."
    )
    if transaction_type == "withdrawal":
        st.caption("Avg latency includes approved + success transactions only; missing or negative durations are excluded. N/A means no eligible durations.")

    # ---- By status ----
    with st.container(border=True):
        st.subheader("1. Status")
        st.caption(f"All {transaction_type} statuses. Count and amount usage use the selected {transaction_type} total.")
        status_leaf = type_merchant_hour.groupby(
            ["category", "merchant_code", "status"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)),
              **_latency_aggregation(type_merchant_hour))
        status_leaf["success_rows"] = status_leaf["row_count"].where(
            status_leaf["status"].str.lower().isin(GOOD_STATUSES), 0
        )
        _render_flow(status_leaf, "status", "Status", None, type_total, type_amount)
        if transaction_type == "withdrawal":
            _withdrawal_details(sql, start, end, category, merchant)

    # ---- By hour of day ----
    with st.container(border=True):
        st.subheader("2. Hour of day")
        st.caption(
            f"Nepal local time, grouped across the selected dates. Usage uses the selected {transaction_type} total."
        )
        hour_leaf = type_merchant_hour.groupby(
            ["category", "merchant_code", "hour_of_day"], as_index=False, dropna=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)),
              **_latency_aggregation(type_merchant_hour))
        success_by_hour_leaf = (
            type_merchant_hour.loc[type_merchant_hour["status"].str.lower().isin(GOOD_STATUSES)]
            .groupby(["category", "merchant_code", "hour_of_day"], dropna=False)["row_count"].sum()
        )
        hour_leaf = hour_leaf.set_index(["category", "merchant_code", "hour_of_day"])
        hour_leaf["success_rows"] = success_by_hour_leaf
        hour_leaf = hour_leaf.reset_index()
        hour_leaf["success_rows"] = hour_leaf["success_rows"].fillna(0)
        hour_leaf["hour_of_day"] = hour_leaf["hour_of_day"].astype("string").fillna("(Missing)")
        hour_order = [str(h) for h in range(24)]
        _render_flow(hour_leaf, "hour_of_day", "Hour of day", hour_order, type_total, type_amount)

    # ---- By amount range (approved / success only) ----
    with st.container(border=True):
        st.subheader("3. Amount range")
        st.caption(
            f"Approved/success {type_plural} only. Amount ranges are in NPR; both usage percentages use "
            f"the selected approved {transaction_type} totals."
        )
        approved_amount_range = type_amount_range_all.loc[
            type_amount_range_all["status"].str.lower().isin(GOOD_STATUSES)
        ]
        bucket_leaf = approved_amount_range.groupby(
            ["category", "merchant_code", "amount_bucket"], as_index=False
        ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)),
              **_latency_aggregation(approved_amount_range))
        bucket_leaf["success_rows"] = bucket_leaf["row_count"]
        bucket_order = _sort_order(bucket_leaf["amount_bucket"].unique(), AMOUNT_BUCKET_ORDER)
        _render_flow(
            bucket_leaf, "amount_bucket", "Amount range (NPR)", bucket_order,
            approved_rows, approved_amount,
        )
