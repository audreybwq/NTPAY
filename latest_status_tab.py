"""Overview tab: transactions split by type (deposit/withdrawal), then by
merchant category (internal/external), across the entire applied date range.
"""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from newduck import get_connection

NPR_TO_USD_RATE = 0.0065
SUCCESS_STATUS = "success"
TYPE_ORDER = ["Deposit", "Withdrawal"]
CATEGORY_ORDER = ["Internal", "External"]
PERSPECTIVES = {
    "Transaction count": ("row_count", "Transaction count", ","),
    "Amount (NPR)": ("total_amount", "Sum of amount (NPR)", ",.2f"),
    "Amount (USD)": ("total_amount_usd", "Sum of amount (USD)", ",.2f"),
    "Count usage (%)": ("usage", "Count usage (%)", ".1f"),
    "Amount usage (%)": ("amount_usage", "Amount usage (%)", ".1f"),
}
AMOUNT_BUCKET_ORDER = ["< 500", "500 - 1,000", "1,000 - 10,000", "10,000 - 20,000", "> 20,000", "(Missing)"]


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_latest_status(sql, start=None, end=None):
    """Aggregate all matching rows before returning data to the app."""
    source = sql.strip().rstrip(";")
    date_where = ""
    params = []
    if start is not None and end is not None:
        date_where = "WHERE created_at >= ? AND created_at < ?"
        params = [start, end + timedelta(days=1)]
    query = f"""
        WITH original AS ({source}),
        source AS (SELECT * FROM original {date_where})
        SELECT source.transaction_type, source.status, source.merchant_category,
               COUNT(*) AS row_count, SUM(source.amount) AS total_amount
        FROM source
        GROUP BY source.transaction_type, source.status, source.merchant_category
        ORDER BY row_count DESC
    """
    con = get_connection()
    return con.execute(query, params).fetch_df()


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_merchant_hour_data(sql, start=None, end=None):
    """Per-merchant, per-hour-of-day (Nepal time) counts and amounts."""
    source = sql.strip().rstrip(";")
    date_where = ""
    params = []
    if start is not None and end is not None:
        date_where = "WHERE created_at >= ? AND created_at < ?"
        params = [start, end + timedelta(days=1)]
    query = f"""
        WITH original AS ({source}),
        source AS (SELECT * FROM original {date_where})
        SELECT source.transaction_type, source.merchant_category, source.merchant_code, source.status,
               EXTRACT(HOUR FROM source.converted_created_at) AS hour_of_day,
               COUNT(*) AS row_count, SUM(source.amount) AS total_amount
        FROM source
        GROUP BY source.transaction_type, source.merchant_category, source.merchant_code, source.status, hour_of_day
    """
    con = get_connection()
    return con.execute(query, params).fetch_df()


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_amount_range_data(sql, start=None, end=None):
    """Per-transaction-amount-bucket counts, by transaction type and status."""
    source = sql.strip().rstrip(";")
    date_where = ""
    params = []
    if start is not None and end is not None:
        date_where = "WHERE created_at >= ? AND created_at < ?"
        params = [start, end + timedelta(days=1)]
    query = f"""
        WITH original AS ({source}),
        source AS (SELECT * FROM original {date_where})
        SELECT source.transaction_type, source.status, source.merchant_category, source.merchant_code,
               CASE
                   WHEN source.amount IS NULL THEN '(Missing)'
                   WHEN source.amount < 500 THEN '< 500'
                   WHEN source.amount < 1000 THEN '500 - 1,000'
                   WHEN source.amount < 10000 THEN '1,000 - 10,000'
                   WHEN source.amount < 20000 THEN '10,000 - 20,000'
                   ELSE '> 20,000'
               END AS amount_bucket,
               COUNT(*) AS row_count, SUM(source.amount) AS total_amount
        FROM source
        GROUP BY source.transaction_type, source.status, source.merchant_category, source.merchant_code, amount_bucket
    """
    con = get_connection()
    return con.execute(query, params).fetch_df()


def _money(value, prefix=""):
    return "N/A" if pd.isna(value) else f"{prefix}{value:,.2f}"


def _sort_order(values, preferred):
    values = list(values)
    return [v for v in preferred if v in values] + sorted(v for v in values if v not in preferred)


def _stack_positions(frame, group_col, value_col):
    """Stack segments within each group largest-first, so the biggest value sits at
    the bottom of the bar and the smallest sits at the top."""
    frame = frame.copy()
    frame = frame.sort_values([group_col, value_col], ascending=[True, False])
    frame["_end"] = frame.groupby(group_col)[value_col].cumsum()
    frame["_start"] = frame["_end"] - frame[value_col]
    frame["_mid"] = (frame["_start"] + frame["_end"]) / 2
    return frame


def _kpi_row(frame, key_prefix):
    total_rows = int(frame["row_count"].sum())
    approved = frame.loc[frame["status"].str.lower() == SUCCESS_STATUS]
    total_amount = approved["total_amount"].sum(min_count=1) if not approved.empty else 0.0
    total_amount_usd = total_amount * NPR_TO_USD_RATE if pd.notna(total_amount) else float("nan")
    success_rows = int(approved["row_count"].sum())
    success_rate = (success_rows / total_rows * 100) if total_rows else float("nan")
    with st.container(horizontal=True, key=f"{key_prefix}_kpis"):
        st.metric("Transaction rows", f"{total_rows:,}", border=True)
        st.metric("Approved rows", f"{success_rows:,}", border=True)
        st.metric("Approve Amount (NPR)", _money(total_amount), border=True)
        st.metric("Approve Amount (USD)", _money(total_amount_usd, "$"), border=True)
        st.metric(
            "Success rate",
            "N/A" if pd.isna(success_rate) else f"{success_rate:.1f}%",
            border=True,
        )
    return total_rows


def _grouped_bar_chart(frame, x_field, x_title, x_order, field, y_title, label_format):
    base = alt.Chart(frame).encode(
        x=alt.X(f"{x_field}:N", title=x_title, sort=x_order, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("category:N", sort=CATEGORY_ORDER),
        color=alt.Color("category:N", title="Merchant category", sort=CATEGORY_ORDER),
        tooltip=[
            alt.Tooltip(f"{x_field}:N", title=x_title),
            alt.Tooltip("category:N", title="Merchant category"),
            alt.Tooltip("row_count:Q", title="Count", format=","),
            alt.Tooltip("usage:Q", title="Count usage (%)", format=".1f"),
            alt.Tooltip("amount_usage:Q", title="Amount usage (%)", format=".1f"),
            alt.Tooltip("total_amount:Q", title="Amount (NPR)", format=",.2f"),
            alt.Tooltip("total_amount_usd:Q", title="Amount (USD)", format=",.2f"),
        ],
    )
    bars = base.mark_bar().encode(y=alt.Y(f"{field}:Q", title=y_title))
    labels = base.mark_text(dy=-8, color="#555555").encode(
        y=alt.Y(f"{field}:Q"), text=alt.Text(f"{field}:Q", format=label_format),
    )
    st.altair_chart((bars + labels).properties(height=300), width="stretch")


def _breakdown_table(frame, dimensions):
    columns = dimensions + ["total_amount", "total_amount_usd", "row_count", "usage", "amount_usage"]
    column_config = {
        "category": st.column_config.TextColumn("Merchant category"),
        "status": st.column_config.TextColumn("Status"),
        "merchant_code": st.column_config.TextColumn("Merchant"),
        "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
        "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
        "row_count": st.column_config.NumberColumn("Count", format="localized"),
        "usage": st.column_config.NumberColumn("Count usage (%)", format="%.1f%%"),
        "amount_usage": st.column_config.NumberColumn("Amount usage (%)", format="%.1f%%"),
    }
    if "success_rate" in frame.columns:
        columns.append("success_rate")
        column_config["success_rate"] = st.column_config.NumberColumn("Success rate (%)", format="%.1f%%")
    st.dataframe(frame[columns], hide_index=True, width="stretch", column_config=column_config)


def _rate_breakdown_table(frame, dimensions, dimension_labels=None):
    dimension_labels = dimension_labels or {}
    columns = dimensions + ["row_count", "success_rows", "success_rate", "total_amount", "total_amount_usd"]
    column_config = {
        "category": st.column_config.TextColumn("Merchant category"),
        "row_count": st.column_config.NumberColumn("Count", format="localized"),
        "success_rows": st.column_config.NumberColumn("Approved rows", format="localized"),
        "success_rate": st.column_config.NumberColumn("Success rate (%)", format="%.1f%%"),
        "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
        "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
    }
    for dim, label in dimension_labels.items():
        column_config[dim] = st.column_config.TextColumn(label)
    st.dataframe(frame[columns], hide_index=True, width="stretch", column_config=column_config)


def _merchant_table(frame):
    st.dataframe(
        frame[[
            "merchant_code", "row_count", "total_amount", "total_amount_usd",
            "success_rate", "count_share", "amount_share",
        ]],
        hide_index=True, width="stretch",
        column_config={
            "merchant_code": st.column_config.TextColumn("Merchant"),
            "row_count": st.column_config.NumberColumn("Count", format="localized"),
            "total_amount": st.column_config.NumberColumn("Amount (NPR)", format="%.2f"),
            "total_amount_usd": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
            "success_rate": st.column_config.NumberColumn("Success rate (%)", format="%.1f%%"),
            "count_share": st.column_config.NumberColumn("Count share (%)", format="%.1f%%"),
            "amount_share": st.column_config.NumberColumn("Amount share (%)", format="%.1f%%"),
        },
    )


def render_latest_status_tab(sql, start=None, end=None):
    try:
        with st.spinner("Loading status totals..."):
            counts = load_latest_status(sql, start, end)
    except Exception as exc:
        st.error("Could not load status totals. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        return

    if counts.empty:
        st.info("No transactions are available in the applied date range.")
        return

    try:
        with st.spinner("Loading merchant / hour-of-day breakdown..."):
            merchant_hour = load_merchant_hour_data(sql, start, end)
    except Exception as exc:
        st.error("Could not load merchant / hour-of-day breakdown. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        merchant_hour = pd.DataFrame(
            columns=["transaction_type", "merchant_category", "merchant_code", "status", "hour_of_day",
                     "row_count", "total_amount"]
        )

    try:
        with st.spinner("Loading amount-range breakdown..."):
            amount_range = load_amount_range_data(sql, start, end)
    except Exception as exc:
        st.error("Could not load amount-range breakdown. Check the DuckLake connection.")
        with st.expander("Connection / query error"):
            st.code(str(exc))
        amount_range = pd.DataFrame(
            columns=["transaction_type", "status", "merchant_category", "amount_bucket", "row_count", "total_amount"]
        )

    period = f"{start:%d %b %Y} to {end:%d %b %Y}" if start is not None and end is not None else "All dates"
    counts["type_label"] = counts["transaction_type"].astype("string").fillna("(Missing)").str.title()
    counts["status"] = counts["status"].astype("string").fillna("(Missing)")
    counts["category"] = counts["merchant_category"].astype("string").fillna("(Missing)")
    counts["total_amount_usd"] = counts["total_amount"] * NPR_TO_USD_RATE
    type_order = _sort_order(counts["type_label"].unique(), TYPE_ORDER)

    merchant_hour["type_label"] = merchant_hour["transaction_type"].astype("string").fillna("(Missing)").str.title()
    merchant_hour["category"] = merchant_hour["merchant_category"].astype("string").fillna("(Missing)")
    merchant_hour["merchant_code"] = merchant_hour["merchant_code"].astype("string").fillna("(Missing)")
    merchant_hour["status"] = merchant_hour["status"].astype("string").fillna("(Missing)")

    amount_range["type_label"] = amount_range["transaction_type"].astype("string").fillna("(Missing)").str.title()
    amount_range["status"] = amount_range["status"].astype("string").fillna("(Missing)")
    amount_range["amount_bucket"] = amount_range["amount_bucket"].astype("string").fillna("(Missing)")
    amount_range["category"] = amount_range["merchant_category"].astype("string").fillna("(Missing)")

    st.subheader(f"Overview - {period}")
    st.caption(
        f"USD uses a fixed rate of 1 NPR = {NPR_TO_USD_RATE} USD."
    )

    if counts["row_count"].sum() == 0:
        return

    for type_label in type_order:
        type_frame = counts.loc[counts["type_label"] == type_label].copy()
        type_total = type_frame["row_count"].sum()
        type_frame["usage"] = type_frame["row_count"] / type_total * 100 if type_total else 0.0
        type_amount = type_frame["total_amount"].sum(min_count=1)
        type_frame["amount_usage"] = (
            type_frame["total_amount"] / type_amount * 100
            if pd.notna(type_amount) and type_amount != 0 else float("nan")
        )
        st.header(type_label)
        _kpi_row(type_frame, key_prefix=f"overview_{type_label}")

        perspective = st.segmented_control(
            "Perspective", list(PERSPECTIVES), default="Transaction count",
            key=f"overview_perspective_{type_label}",
        ) or "Transaction count"
        field, y_title, label_format = PERSPECTIVES[perspective]

        with st.container(border=True):
            st.subheader("By merchant category")
            st.caption(
                "Transaction count, split out by each individual status. "
                "The dotted line marks the success rate per category."
            )
            category_order = _sort_order(type_frame["category"].unique(), CATEGORY_ORDER)
            status_order_cat = (
                type_frame.groupby("status")["row_count"].sum().sort_values(ascending=False).index.tolist()
            )

            is_success = type_frame["status"].str.lower() == SUCCESS_STATUS
            category_totals = type_frame.groupby("category", sort=False)["row_count"].sum().rename("total_rows")
            success_rows_by_cat = (
                type_frame.loc[is_success].groupby("category")["row_count"].sum().rename("success_rows")
            )
            rate_frame = pd.concat([category_totals, success_rows_by_cat], axis=1).reset_index()
            rate_frame["success_rows"] = rate_frame["success_rows"].fillna(0)
            rate_frame["success_rate"] = (
                rate_frame["success_rows"] / rate_frame["total_rows"] * 100
            ).where(rate_frame["total_rows"] > 0)

            bar_frame = type_frame.groupby(["category", "status"], as_index=False)["row_count"].sum()
            stacked = _stack_positions(bar_frame, "category", "row_count")

            category_chart = alt.Chart(stacked).mark_bar().encode(
                x=alt.X("category:N", title="Merchant category", sort=category_order,
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("_start:Q", title="Transaction count"),
                y2=alt.Y2("_end:Q"),
                color=alt.Color(
                    "status:N", title="Status", sort=status_order_cat,
                ),
                tooltip=[
                    alt.Tooltip("category:N", title="Merchant category"),
                    alt.Tooltip("status:N", title="Status"),
                    alt.Tooltip("row_count:Q", title="Count", format=","),
                ],
            ).properties(height=320)

            # Segments taller than 5% of the chart's shared y-range get their own
            # centered label; thinner slivers would overlap their neighbour, so
            # they're bundled into one callout line above their bar instead.
            chart_top = stacked["_end"].max()
            chart_top = chart_top if pd.notna(chart_top) and chart_top else 1.0
            small_mask = (stacked["row_count"] / chart_top).fillna(0) < 0.05
            big_labels = stacked.loc[~small_mask]
            small_rows = stacked.loc[small_mask]

            layers = category_chart
            if not big_labels.empty:
                segment_labels = alt.Chart(big_labels).mark_text(fontWeight="bold").encode(
                    x=alt.X("category:N", sort=category_order),
                    y=alt.Y("_mid:Q"),
                    text=alt.Text("row_count:Q", format=","),
                )
                layers = layers + segment_labels

            if not small_rows.empty:
                bar_tops = stacked.groupby("category")["_end"].max().rename("_top")
                callouts = (
                    small_rows.groupby("category")
                    .apply(lambda g: " · ".join(
                        f"{s}: {format(v, ',')}" for s, v in zip(g["status"], g["row_count"])
                    ))
                    .rename("_label")
                    .reset_index()
                    .merge(bar_tops, on="category")
                )
                callout_labels = alt.Chart(callouts).mark_text(
                    dy=-10, fontWeight="bold", color="#555555",
                ).encode(
                    x=alt.X("category:N", sort=category_order),
                    y=alt.Y("_top:Q"),
                    text=alt.Text("_label:N"),
                )
                layers = layers + callout_labels

            rate_line = alt.Chart(rate_frame).mark_line(
                color="#1f2937", strokeDash=[4, 3], point=False,
            ).encode(
                x=alt.X("category:N", sort=category_order),
                y=alt.Y("success_rate:Q", title="Success rate (%)", scale=alt.Scale(domain=[0, 100])),
            )
            rate_points = alt.Chart(rate_frame).mark_circle(size=650, color="#1f2937").encode(
                x=alt.X("category:N", sort=category_order),
                y=alt.Y("success_rate:Q"),
                tooltip=[
                    alt.Tooltip("category:N", title="Merchant category"),
                    alt.Tooltip("success_rate:Q", title="Success rate (%)", format=".1f"),
                ],
            )
            rate_labels = alt.Chart(rate_frame).mark_text(
                color="white", fontWeight="bold", fontSize=11,
            ).encode(
                x=alt.X("category:N", sort=category_order),
                y=alt.Y("success_rate:Q"),
                text=alt.Text("success_rate:Q", format=".1f"),
            )
            rate_overlay = rate_line + rate_points + rate_labels

            st.altair_chart(
                alt.layer(layers, rate_overlay).resolve_scale(y="independent"),
                width="stretch",
            )
            category_summary = type_frame.groupby("category", sort=False).agg(
                row_count=("row_count", "sum"),
                total_amount=("total_amount", lambda values: values.sum(min_count=1)),
            ).reset_index()
            category_summary["total_amount_usd"] = category_summary["total_amount"] * NPR_TO_USD_RATE
            category_summary["usage"] = category_summary["row_count"] / type_total * 100 if type_total else 0.0
            category_summary["amount_usage"] = (
                category_summary["total_amount"] / type_amount * 100
                if pd.notna(type_amount) and type_amount != 0 else float("nan")
            )
            success_by_category = (
                type_frame.loc[is_success]
                .groupby("category")["row_count"].sum()
            )
            category_summary["success_rate"] = (
                category_summary["category"].map(success_by_category).fillna(0) / category_summary["row_count"] * 100
            )
            category_summary = category_summary.set_index("category").loc[category_order].reset_index()
            _breakdown_table(category_summary, ["category"])

        with st.container(border=True):
            st.subheader("Status breakdown")
            status_order = (
                type_frame.groupby("status")["row_count"].sum().sort_values(ascending=False).index.tolist()
            )
            _grouped_bar_chart(
                type_frame, "status", "Status", status_order, field, y_title, label_format,
            )
            _breakdown_table(
                type_frame.sort_values(["status", "category"]), ["status", "category"],
            )

        type_merchant_hour = merchant_hour.loc[merchant_hour["type_label"] == type_label]

        with st.container(border=True):
            st.subheader("By hour of day")
            st.caption(
                "Success rate by hour of day (Nepal local time), aggregated across all merchants "
                "and categories."
            )
            if type_merchant_hour.empty:
                st.info("No merchant-level data is available for this transaction type.")
            else:
                overview_hours = type_merchant_hour.groupby("hour_of_day", as_index=False).agg(
                    row_count=("row_count", "sum"),
                    total_amount=("total_amount", lambda values: values.sum(min_count=1)),
                )
                overview_success = (
                    type_merchant_hour.loc[type_merchant_hour["status"].str.lower() == SUCCESS_STATUS]
                    .groupby("hour_of_day")["row_count"].sum()
                )
                overview_hours["success_rows"] = overview_hours["hour_of_day"].map(overview_success).fillna(0)
                overview_hours["success_rate"] = (
                    overview_hours["success_rows"] / overview_hours["row_count"] * 100
                ).where(overview_hours["row_count"] > 0)
                overview_hours = pd.DataFrame({"hour_of_day": range(24)}).merge(
                    overview_hours, on="hour_of_day", how="left"
                )
                overview_hours["row_count"] = overview_hours["row_count"].fillna(0)
                overview_hours["success_rows"] = overview_hours["success_rows"].fillna(0)
                overview_hours["total_amount_usd"] = overview_hours["total_amount"] * NPR_TO_USD_RATE
                overview_hours["_mid"] = overview_hours["success_rate"] / 2

                overview_hour_chart = alt.Chart(overview_hours).mark_bar().encode(
                    x=alt.X("hour_of_day:O", title="Hour of day"),
                    y=alt.Y("success_rate:Q", title="Success rate (%)", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color(
                        "success_rate:Q", title="Success rate (%)", legend=None,
                        scale=alt.Scale(scheme="redyellowgreen", domain=[0, 100]),
                    ),
                    tooltip=[
                        alt.Tooltip("hour_of_day:O", title="Hour"),
                        alt.Tooltip("success_rate:Q", title="Success rate (%)", format=".1f"),
                        alt.Tooltip("row_count:Q", title="Count", format=","),
                    ],
                ).properties(height=320)
                overview_hour_labels = alt.Chart(overview_hours).mark_text(
                    fontWeight="bold", color="black",
                ).encode(
                    x=alt.X("hour_of_day:O"),
                    y=alt.Y("_mid:Q"),
                    text=alt.Text("success_rate:Q", format=".1f"),
                )
                st.altair_chart(overview_hour_chart + overview_hour_labels, width="stretch")

                hour_category = type_merchant_hour.groupby(
                    ["hour_of_day", "category"], as_index=False
                ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
                success_by_hour_cat = (
                    type_merchant_hour.loc[type_merchant_hour["status"].str.lower() == SUCCESS_STATUS]
                    .groupby(["hour_of_day", "category"])["row_count"].sum()
                )
                hour_category = hour_category.set_index(["hour_of_day", "category"])
                hour_category["success_rows"] = success_by_hour_cat
                hour_category = hour_category.reset_index()
                hour_category["success_rows"] = hour_category["success_rows"].fillna(0)
                hour_category["success_rate"] = (
                    hour_category["success_rows"] / hour_category["row_count"] * 100
                ).where(hour_category["row_count"] > 0)
                hour_category["total_amount_usd"] = hour_category["total_amount"] * NPR_TO_USD_RATE
                hour_category["hour_of_day"] = hour_category["hour_of_day"].astype("string")
                hour_category = hour_category.sort_values(["hour_of_day", "category"])
                _rate_breakdown_table(hour_category, ["hour_of_day", "category"], {"hour_of_day": "Hour of day"})

        with st.container(border=True):
            st.subheader("By amount range")
            st.caption(
                "Success rate by transaction amount (NPR), aggregated across all merchants and categories."
            )
            type_amount_range = amount_range.loc[amount_range["type_label"] == type_label]
            if type_amount_range.empty:
                st.info("No amount data is available for this transaction type.")
            else:
                bucket_summary = type_amount_range.groupby("amount_bucket", as_index=False).agg(
                    row_count=("row_count", "sum"),
                    total_amount=("total_amount", lambda values: values.sum(min_count=1)),
                )
                bucket_success = (
                    type_amount_range.loc[type_amount_range["status"].str.lower() == SUCCESS_STATUS]
                    .groupby("amount_bucket")["row_count"].sum()
                )
                bucket_summary["success_rows"] = bucket_summary["amount_bucket"].map(bucket_success).fillna(0)
                bucket_summary["success_rate"] = (
                    bucket_summary["success_rows"] / bucket_summary["row_count"] * 100
                ).where(bucket_summary["row_count"] > 0)
                bucket_summary["total_amount_usd"] = bucket_summary["total_amount"] * NPR_TO_USD_RATE
                bucket_summary["_mid"] = bucket_summary["success_rate"] / 2
                bucket_order = _sort_order(bucket_summary["amount_bucket"].unique(), AMOUNT_BUCKET_ORDER)

                bucket_chart = alt.Chart(bucket_summary).mark_bar().encode(
                    x=alt.X("amount_bucket:N", title="Amount range (NPR)", sort=bucket_order,
                            axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("success_rate:Q", title="Success rate (%)", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color(
                        "success_rate:Q", title="Success rate (%)", legend=None,
                        scale=alt.Scale(scheme="redyellowgreen", domain=[0, 100]),
                    ),
                    tooltip=[
                        alt.Tooltip("amount_bucket:N", title="Amount range (NPR)"),
                        alt.Tooltip("success_rate:Q", title="Success rate (%)", format=".1f"),
                        alt.Tooltip("row_count:Q", title="Count", format=","),
                    ],
                ).properties(height=320)
                bucket_labels = alt.Chart(bucket_summary).mark_text(fontWeight="bold", color="black").encode(
                    x=alt.X("amount_bucket:N", sort=bucket_order),
                    y=alt.Y("_mid:Q"),
                    text=alt.Text("success_rate:Q", format=".1f"),
                )
                st.altair_chart(bucket_chart + bucket_labels, width="stretch")

                bucket_category = type_amount_range.groupby(
                    ["amount_bucket", "category"], as_index=False
                ).agg(row_count=("row_count", "sum"), total_amount=("total_amount", lambda v: v.sum(min_count=1)))
                success_by_bucket_cat = (
                    type_amount_range.loc[type_amount_range["status"].str.lower() == SUCCESS_STATUS]
                    .groupby(["amount_bucket", "category"])["row_count"].sum()
                )
                bucket_category = bucket_category.set_index(["amount_bucket", "category"])
                bucket_category["success_rows"] = success_by_bucket_cat
                bucket_category = bucket_category.reset_index()
                bucket_category["success_rows"] = bucket_category["success_rows"].fillna(0)
                bucket_category["success_rate"] = (
                    bucket_category["success_rows"] / bucket_category["row_count"] * 100
                ).where(bucket_category["row_count"] > 0)
                bucket_category["total_amount_usd"] = bucket_category["total_amount"] * NPR_TO_USD_RATE
                bucket_category["_sort"] = bucket_category["amount_bucket"].map(
                    {bucket: index for index, bucket in enumerate(bucket_order)}
                )
                bucket_category = bucket_category.sort_values(["_sort", "category"]).drop(columns="_sort")
                _rate_breakdown_table(
                    bucket_category, ["amount_bucket", "category"], {"amount_bucket": "Amount range (NPR)"}
                )

        with st.container(border=True):
            st.subheader("By merchant")
            st.caption("Status breakdown per merchant - the next level of detail below the category/status totals above.")
            if type_merchant_hour.empty:
                st.info("No merchant-level data is available for this transaction type.")
            else:
                merchant_status = type_merchant_hour.groupby(
                    ["category", "merchant_code", "status"], sort=False
                ).agg(
                    row_count=("row_count", "sum"),
                    total_amount=("total_amount", lambda values: values.sum(min_count=1)),
                ).reset_index()
                merchant_status["total_amount_usd"] = merchant_status["total_amount"] * NPR_TO_USD_RATE
                merchant_status["usage"] = (
                    merchant_status["row_count"] / type_total * 100 if type_total else 0.0
                )
                merchant_status["amount_usage"] = (
                    merchant_status["total_amount"] / type_amount * 100
                    if pd.notna(type_amount) and type_amount != 0 else float("nan")
                )
                for category_label in _sort_order(merchant_status["category"].unique(), CATEGORY_ORDER):
                    st.markdown(f"**{category_label} merchants**")
                    category_status_table = merchant_status.loc[
                        merchant_status["category"] == category_label
                    ].sort_values(["merchant_code", "status"])
                    _breakdown_table(category_status_table, ["merchant_code", "status"])

        with st.container(border=True):
            st.subheader("By merchant, hour of day")
            st.caption(
                "Success rate by hour of day (Nepal local time), aggregated across the whole selected "
                "date range, split by merchant category."
            )
            if type_merchant_hour.empty:
                st.info("No merchant-level data is available for this transaction type.")
            else:
                hour_by_category = type_merchant_hour.groupby(
                    ["category", "hour_of_day"], as_index=False
                )["row_count"].sum()
                success_by_hour_category = (
                    type_merchant_hour.loc[type_merchant_hour["status"].str.lower() == SUCCESS_STATUS]
                    .groupby(["category", "hour_of_day"])["row_count"].sum()
                )
                hour_by_category = hour_by_category.set_index(["category", "hour_of_day"])
                hour_by_category["success_rows"] = success_by_hour_category
                hour_by_category = hour_by_category.reset_index()
                hour_by_category["success_rows"] = hour_by_category["success_rows"].fillna(0)
                hour_by_category["success_rate"] = (
                    hour_by_category["success_rows"] / hour_by_category["row_count"] * 100
                ).where(hour_by_category["row_count"] > 0)

                hour_category_order = _sort_order(type_merchant_hour["category"].unique(), CATEGORY_ORDER)
                hour_columns = st.columns(len(hour_category_order))
                for hour_column, cat_label in zip(hour_columns, hour_category_order):
                    cat_hours = hour_by_category.loc[hour_by_category["category"] == cat_label]
                    full_hours = pd.DataFrame({"hour_of_day": range(24)}).merge(
                        cat_hours, on="hour_of_day", how="left"
                    )
                    full_hours["_mid"] = full_hours["success_rate"] / 2
                    with hour_column:
                        st.markdown(f"**{cat_label}**")
                        hour_chart = alt.Chart(full_hours).mark_bar().encode(
                            x=alt.X("hour_of_day:O", title="Hour of day"),
                            y=alt.Y("success_rate:Q", title="Success rate (%)", scale=alt.Scale(domain=[0, 100])),
                            color=alt.Color(
                                "success_rate:Q", title="Success rate (%)", legend=None,
                                scale=alt.Scale(scheme="redyellowgreen", domain=[0, 100]),
                            ),
                            tooltip=[
                                alt.Tooltip("hour_of_day:O", title="Hour"),
                                alt.Tooltip("success_rate:Q", title="Success rate (%)", format=".1f"),
                                alt.Tooltip("row_count:Q", title="Count", format=","),
                            ],
                        ).properties(height=320)
                        hour_labels = alt.Chart(full_hours).mark_text(fontWeight="bold", color="black").encode(
                            x=alt.X("hour_of_day:O"),
                            y=alt.Y("_mid:Q"),
                            text=alt.Text("success_rate:Q", format=".1f"),
                        )
                        st.altair_chart(hour_chart + hour_labels, width="stretch")

                merchant_summary = type_merchant_hour.groupby(
                    ["category", "merchant_code"], sort=False
                ).agg(
                    row_count=("row_count", "sum"),
                    total_amount=("total_amount", lambda values: values.sum(min_count=1)),
                ).reset_index()
                success_by_merchant = (
                    type_merchant_hour.loc[type_merchant_hour["status"].str.lower() == SUCCESS_STATUS]
                    .groupby("merchant_code")["row_count"].sum()
                )
                merchant_summary["success_rows"] = (
                    merchant_summary["merchant_code"].map(success_by_merchant).fillna(0)
                )
                merchant_summary["success_rate"] = (
                    merchant_summary["success_rows"] / merchant_summary["row_count"] * 100
                )
                merchant_summary["total_amount_usd"] = merchant_summary["total_amount"] * NPR_TO_USD_RATE
                merchant_summary["count_share"] = (
                    merchant_summary["row_count"] / type_total * 100 if type_total else 0.0
                )
                merchant_summary["amount_share"] = (
                    merchant_summary["total_amount"] / type_amount * 100
                    if pd.notna(type_amount) and type_amount != 0 else float("nan")
                )

                for category_label in _sort_order(merchant_summary["category"].unique(), CATEGORY_ORDER):
                    st.markdown(f"**{category_label} merchants**")
                    category_table = merchant_summary.loc[
                        merchant_summary["category"] == category_label
                    ].sort_values("row_count", ascending=False)
                    _merchant_table(category_table)
