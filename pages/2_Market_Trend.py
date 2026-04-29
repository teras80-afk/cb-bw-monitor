"""
페이지 2 — 시장 전체 CB/BW 신규 발행 동향
"""
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from lib import require_dart_or_stop, fetch_market_cb_bw_recent

st.set_page_config(page_title="시장 동향", page_icon="📈", layout="wide")
st.title("📈 시장 CB/BW 발행 동향")
st.caption("최근 시장 전체 CB/BW 신규 발행 공시 (어떤 회사가 자금 조달을 시작했나)")

require_dart_or_stop()

st.markdown("---")

col_d, col_btn = st.columns([3, 1])
with col_d:
    days_back = st.selectbox("조회 기간",
                              [7, 14, 30, 60, 90],
                              index=2,
                              format_func=lambda d: f"최근 {d}일")
with col_btn:
    st.write("")  # spacer
    refresh = st.button("🔄 새로고침", use_container_width=True)

if refresh:
    st.cache_data.clear()
    st.rerun()

with st.spinner(f"최근 {days_back}일 시장 전체 CB/BW 공시 조회 중..."):
    df = fetch_market_cb_bw_recent(days_back)

if df.empty:
    st.info("해당 기간 내 CB/BW 발행 공시 없음 (또는 DART API 응답 오류)")
    st.stop()

# 핵심 지표
n_total = len(df)
n_cb = (df["사채종류"] == "CB").sum() if "사채종류" in df.columns else 0
n_bw = (df["사채종류"] == "BW").sum() if "사채종류" in df.columns else 0
n_companies = (df["corp_name"].nunique()
               if "corp_name" in df.columns else 0)

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("총 공시 건수", f"{n_total}건")
with m2:
    st.metric("CB 발행", f"{n_cb}건")
with m3:
    st.metric("BW 발행", f"{n_bw}건")
with m4:
    st.metric("발행 회사 수", f"{n_companies}개사")

st.markdown("---")

# 일자별 추이 차트
if "rcept_dt" in df.columns:
    df_chart = df.copy()
    df_chart["접수일"] = pd.to_datetime(df_chart["rcept_dt"].astype(str),
                                       format="%Y%m%d", errors="coerce")
    df_chart = df_chart.dropna(subset=["접수일"])
    if len(df_chart) > 0:
        st.markdown("#### 📊 일자별 발행 공시 추이")
        daily = (df_chart.groupby([df_chart["접수일"].dt.date, "사채종류"])
                 .size().reset_index(name="건수"))
        daily.columns = ["접수일", "사채종류", "건수"]
        daily["접수일"] = pd.to_datetime(daily["접수일"])

        chart = alt.Chart(daily).mark_bar().encode(
            x=alt.X("접수일:T", title=""),
            y=alt.Y("건수:Q", title="공시 건수"),
            color=alt.Color("사채종류:N",
                            scale=alt.Scale(domain=["CB", "BW"],
                                            range=["#3498db", "#e67e22"])),
            tooltip=["접수일:T", "사채종류:N", "건수:Q"],
        ).properties(height=280)
        st.altair_chart(chart, use_container_width=True)

st.markdown("---")

# 공시 리스트
st.markdown("#### 📋 발행 공시 리스트")

# 시장 필터
filter_kind = st.radio("사채종류 필터", ["전체", "CB만", "BW만"],
                       horizontal=True, index=0)
df_show = df.copy()
if filter_kind == "CB만":
    df_show = df_show[df_show["사채종류"] == "CB"]
elif filter_kind == "BW만":
    df_show = df_show[df_show["사채종류"] == "BW"]

if df_show.empty:
    st.info("해당 조건에 맞는 공시 없음")
else:
    show_cols = []
    for c in ["rcept_dt", "corp_name", "stock_code", "사채종류", "report_nm"]:
        if c in df_show.columns:
            show_cols.append(c)
    rename_map = {
        "rcept_dt": "접수일",
        "corp_name": "회사명",
        "stock_code": "종목코드",
        "report_nm": "공시명",
    }
    df_view = (df_show[show_cols].rename(columns=rename_map)
               .sort_values("접수일", ascending=False)
               .reset_index(drop=True))
    st.caption(f"표시: **{len(df_view)}건**")
    st.dataframe(df_view, use_container_width=True, hide_index=True)

    # DART 원문 링크
    with st.expander("🔗 DART 원문 바로가기"):
        for _, row in df_show.iterrows():
            rd = row.get("rcept_dt", "—")
            cn = row.get("corp_name", "—")
            rn = row.get("report_nm", "—")
            url = row.get("원문URL", "#")
            st.markdown(f"- [{rd}] **{cn}** — {rn} → [DART 원문]({url})")

st.markdown("---")
st.caption(
    "📌 DART 주요사항보고(kind='B') 중 'CB/BW 발행결정'만 필터링한 결과입니다. "
    "정정공시·취소공시는 별도 표시되지 않으니 DART 원문에서 최종 확인하세요."
)
