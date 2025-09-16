from __future__ import annotations

import datetime as dt
import io
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

# Support running as package (app.*) or script (local modules)
try:
    from app.db import fetch_production  # type: ignore
    from app.i18n import t, TRANSLATIONS  # type: ignore
except ModuleNotFoundError:
    from db import fetch_production  # type: ignore
    from i18n import t, TRANSLATIONS  # type: ignore


# Page config
st.set_page_config(page_title="Production Dashboard", layout="wide")


MOBILE_STYLE = """
<style>
:root {
    --card-radius: 12px;
    --shadow-soft: 0 2px 12px rgba(15, 23, 42, 0.08);
}
[data-testid="stAppViewContainer"] {
    background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
    color: #0f172a;
}
header[data-testid="stHeader"] {
    background: transparent;
    border-bottom: none;
    box-shadow: none;
    display: none;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2.5rem;
}
.block-container h1 {
    font-size: clamp(1.85rem, 2vw + 1.25rem, 3rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #0f172a;
    margin-bottom: 1.2rem;
}
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.95);
    border-radius: var(--card-radius);
    box-shadow: var(--shadow-soft);
    padding: 0.9rem 1.1rem;
}
div[data-testid="stMetricValue"] {
    font-size: 1.5rem;
    font-weight: 600;
    color: #0f172a;
}
div[data-testid="stMetricLabel"] {
    font-size: 0.85rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: #475569;
}
[data-testid="stDataFrame"] {
    background: rgba(255, 255, 255, 0.96);
    border-radius: var(--card-radius);
    box-shadow: var(--shadow-soft);
}
[data-testid="stDataFrame"] > div:first-child {
    border-radius: var(--card-radius);
}
[data-testid="stDataFrame"] > div {
    overflow-x: auto;
}
[data-testid="stDataFrame"] div[role="grid"] {
    border: none;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 0.75rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.65);
    box-shadow: var(--shadow-soft);
    color: #1e293b;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: #2563eb;
    color: #ffffff;
}
@media (max-width: 768px) {
    .block-container {
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    section[data-testid="stHorizontalBlock"] > div {
        flex-direction: column !important;
        gap: 0.75rem !important;
    }
    div[data-testid="metric-container"] {
        width: 100%;
    }
    [data-testid="stMetric"] {
        width: 100%;
    }
    [data-testid="stDataFrame"] {
        font-size: 0.95rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        flex-wrap: wrap;
        gap: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        flex: 1 1 45%;
        justify-content: center;
    }
}
</style>
"""


def apply_responsive_styles():
    st.markdown(MOBILE_STYLE, unsafe_allow_html=True)


def get_locale() -> str:
    app_cfg = st.secrets.get("app", {}) if hasattr(st, "secrets") else {}
    default_locale = app_cfg.get("default_locale", "KO")
    return st.session_state.get("locale", default_locale)


def set_locale(loc: str):
    st.session_state["locale"] = loc


@st.cache_data(ttl=60)
def load_data(date_from: str, date_to: Optional[str] = None) -> pd.DataFrame:
    # 서버 쿼리는 기간만 필터링하고, 라인/카테고리/스타일은 클라이언트에서 필터링
    rows = fetch_production(date_from, date_to, line=None, category=None, style_like=None)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


def melt_hourly(df: pd.DataFrame) -> pd.DataFrame:
    hour_cols = [
        "t_0830", "t_0930", "t_1000", "t_1130", "t_1330", "t_1430", "t_1530", "t_1630", "t_1730", "t_1800", "overtime",
    ]
    present = [c for c in hour_cols if c in df.columns]
    if not present:
        return pd.DataFrame()
    m = df.melt(id_vars=["production_date", "line", "style_number"], value_vars=present, var_name="time", value_name="qty")
    # Map t_0830 -> 08:30 etc.
    def to_label(x: str) -> str:
        if x == "overtime":
            return "OT"
        t = x.replace("t_", "")
        return f"{t[:2]}:{t[2:]}"

    m["time_label"] = m["time"].map(to_label)
    agg = m.groupby(["production_date", "time_label"], as_index=False)["qty"].sum()
    return agg


def kpi_cards(locale: str, df: pd.DataFrame):
    total_output = int(df["daily_production_total"].fillna(0).sum()) if "daily_production_total" in df else 0
    avg_hourly = float(df["average_hourly"].dropna().mean()) if "average_hourly" in df else 0.0

    c1, c2 = st.columns(2)
    c1.metric(t(locale, "kpi_total_output"), f"{total_output:,}")
    c2.metric(t(locale, "kpi_avg_hourly"), f"{avg_hourly:,.2f}")


def top_styles_table(locale: str, df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    cols = ["style_number", "daily_production_total"]
    present = [c for c in cols if c in df.columns]
    if len(present) < 2:
        return []
    topn = df.groupby("style_number", as_index=False)["daily_production_total"].sum().sort_values("daily_production_total", ascending=False).head(10)
    st.subheader(t(locale, "top_styles"))
    st.dataframe(topn, hide_index=True, use_container_width=True)
    return topn["style_number"].tolist()


def hourly_chart(locale: str, df: pd.DataFrame):
    melted = melt_hourly(df)
    if melted.empty:
        return
    st.subheader(t(locale, "hourly_trend"))
    chart = (
        alt.Chart(melted)
        .mark_line(point=True)
        .encode(x="time_label:N", y="qty:Q")
        .properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)


def hourly_detail_grid(locale: str, df: pd.DataFrame, style_order: Optional[list[str]] = None):
    # Build per-style x time grid including overtime
    hour_cols = [
        "t_0830", "t_0930", "t_1000", "t_1130", "t_1330", "t_1430", "t_1530", "t_1630", "t_1730", "t_1800", "overtime",
    ]
    present = [c for c in hour_cols if c in df.columns]
    if not present or "style_number" not in df:
        return
    m = df.melt(id_vars=["style_number"], value_vars=present, var_name="time", value_name="qty")

    def to_label(x: str) -> str:
        if x == "overtime":
            return "OT"
        t = x.replace("t_", "")
        return f"{t[:2]}:{t[2:]}"

    m["time_label"] = m["time"].map(to_label)
    agg = m.groupby(["style_number", "time_label"], as_index=False)["qty"].sum()
    piv = agg.pivot(index="style_number", columns="time_label", values="qty").fillna(0)

    # Ensure column order
    order = ["08:30", "09:30", "10:00", "11:30", "13:30", "14:30", "15:30", "16:30", "17:30", "18:00", "OT"]
    cols = [c for c in order if c in piv.columns]
    piv = piv.reindex(columns=cols)
    # Add row total
    piv["Total"] = piv.sum(axis=1)

    if style_order:
        top_idx = [s for s in style_order if s in piv.index]
        if top_idx:
            piv_top = piv.loc[top_idx]
            piv_rest = piv.drop(index=top_idx, errors="ignore")
            piv = pd.concat([piv_top, piv_rest])

    st.subheader(t(locale, "hourly_detail_by_style"))
    st.dataframe(piv.reset_index(), use_container_width=True)


def main():
    locale = get_locale()
    st.title(t(locale, "app_title"))
    apply_responsive_styles()

    # Sidebar
    with st.sidebar:
        st.selectbox(t(locale, "locale"), options=list(TRANSLATIONS.keys()), index=list(TRANSLATIONS.keys()).index(locale), key="_locale_select", on_change=lambda: set_locale(st.session_state["_locale_select"]))
        today = dt.date.today()
        # 기본은 오늘~오늘, 기간 선택 가능
        date_val = st.date_input(t(locale, "date"), value=(today, today))

    # Big refresh button centered
    cta = st.button(t(locale, "refresh_today"), use_container_width=True)
    if cta:
        st.cache_data.clear()

    # 단일 날짜 또는 기간 처리
    if isinstance(date_val, tuple) and len(date_val) == 2:
        d_from = date_val[0] or today
        d_to = date_val[1] or d_from
    elif isinstance(date_val, dt.date):
        d_from = d_to = date_val
    else:
        d_from = d_to = today

    try:
        df = load_data(d_from.isoformat(), d_to.isoformat())
    except RuntimeError as e:
        st.error(str(e))
        return

    if df.empty:
        st.info(t(locale, "no_data"))
        return

    # 동적 필터 옵션 및 적용 (클라이언트 필터링)
    with st.sidebar:
        st.markdown("---")
        st.caption(t(locale, "filters"))
        line_opts = sorted(df["line"].dropna().unique().tolist()) if "line" in df else []
        sel_lines = st.multiselect(t(locale, "line"), options=line_opts)
        cat_opts = sorted(df["category"].dropna().unique().tolist()) if "category" in df else []
        sel_cats = st.multiselect(t(locale, "category"), options=cat_opts)

        # 스타일 번호 선택 옵션 추가
        style_opts = sorted(df["style_number"].dropna().unique().tolist()) if "style_number" in df else []
        sel_styles = st.multiselect(t(locale, "style"), options=style_opts)

        # 스타일 텍스트 검색 (기존 기능 유지)
        style_like = st.text_input(t(locale, "style_search"), placeholder="Search style...")

    # 선택된 필터 적용
    if sel_lines:
        df = df[df["line"].isin(sel_lines)]
    if sel_cats and "category" in df:
        df = df[df["category"].isin(sel_cats)]

    # 스타일 필터 적용 (선택 또는 검색)
    if sel_styles:
        df = df[df["style_number"].isin(sel_styles)]
    elif style_like:  # 선택된 스타일이 없을 때만 텍스트 검색 적용
        df = df[df["style_number"].str.contains(style_like, case=False, na=False)]

    kpi_cards(locale, df)
    overview_tab, trend_tab, detail_tab = st.tabs([
        t(locale, "tab_summary"),
        t(locale, "tab_trend"),
        t(locale, "tab_detail"),
    ])

    top_styles: list[str] = []
    with overview_tab:
        top_styles = top_styles_table(locale, df)
    with trend_tab:
        hourly_chart(locale, df)
    with detail_tab:
        hourly_detail_grid(locale, df, style_order=top_styles)

    # CSV Download
    csv = df.to_csv(index=False).encode("utf-8-sig")
    if d_from == d_to:
        fname = f"production_{d_from.isoformat()}.csv"
    else:
        fname = f"production_{d_from.isoformat()}_to_{d_to.isoformat()}.csv"
    st.download_button(t(locale, "download_csv"), data=csv, file_name=fname, mime="text/csv")


if __name__ == "__main__":
    main()
