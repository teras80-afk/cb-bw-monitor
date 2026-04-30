"""
페이지 1 — 종목별 CB/BW 상세 조회
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from lib import (
    get_ticker_name_map, resolve_ticker, require_dart_or_stop,
    fetch_cb_bw_disclosures, fetch_debt_securities_latest,
    filter_cb_bw_outstanding, extract_balance_and_price,
    fetch_cb_conversion_periods, find_imminent_conversions,
    get_full_conversion_schedule,
    get_listed_shares, get_company_name,
)

st.set_page_config(page_title="종목별 조회", page_icon="🎯", layout="wide")
st.title("🎯 종목별 CB/BW 조회")
st.caption("발행 이력, 미상환 잔액, 잠재 희석률, 전환청구 D-Day까지 한눈에")

require_dart_or_stop()
name_map = get_ticker_name_map()
if not name_map:
    st.info("ℹ️ 종목명 자동 변환 기능은 비활성 상태입니다. **6자리 종목코드를 직접 입력**하세요. (예: 005930)")

st.markdown("---")

col_in, col_yrs = st.columns([3, 1])
with col_in:
    user_input = st.text_input("종목코드 6자리 또는 종목명",
                                value="", placeholder="예: 005930 또는 삼성전자")
with col_yrs:
    years_back = st.selectbox("발행 공시 조회 기간", [3, 5, 7, 10], index=1)

if not user_input.strip():
    st.info("종목을 입력하세요.")
    st.stop()

ticker = resolve_ticker(user_input, name_map)
if not ticker:
    st.error("종목을 찾지 못했습니다.")
    st.stop()

name = get_company_name(ticker, name_map)
st.markdown(f"### 📍 {name} ({ticker})")

# ─── 섹션 1: 핵심 지표 (잠재주식수 / 희석률) ───
st.markdown("#### 📊 핵심 지표")

with st.spinner("미상환 잔액 및 핵심 지표 계산 중..."):
    df_debt, report_label = fetch_debt_securities_latest(ticker)
    listed_shares = get_listed_shares(ticker)

if df_debt.empty:
    metric_cb_total = 0
    metric_potential_shares = 0
    metric_dilution = 0.0
    has_data = False
else:
    df_outstanding = filter_cb_bw_outstanding(df_debt)
    if df_outstanding.empty:
        metric_cb_total = 0
        metric_potential_shares = 0
        metric_dilution = 0.0
        has_data = False
    else:
        df_calc = extract_balance_and_price(df_outstanding)
        metric_cb_total = (df_calc["_미상환잔액(원)"].sum()
                           if "_미상환잔액(원)" in df_calc.columns else 0)
        metric_potential_shares = (df_calc["_잠재출회주식수"].sum()
                                    if "_잠재출회주식수" in df_calc.columns else 0)
        metric_dilution = (metric_potential_shares / listed_shares * 100
                           if listed_shares > 0 and metric_potential_shares > 0
                           else 0.0)
        has_data = True

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("미상환 잔액 합계",
              f"{metric_cb_total/1e8:,.1f}억원" if metric_cb_total > 0 else "—")
with m2:
    st.metric("잠재 출회주식수",
              f"{metric_potential_shares:,.0f}주"
              if metric_potential_shares > 0 else "—")
with m3:
    st.metric("상장주식수",
              f"{listed_shares:,.0f}주" if listed_shares > 0 else "—")
with m4:
    st.metric("잠재 희석률",
              f"{metric_dilution:.2f}%" if metric_dilution > 0 else "—",
              help="잠재 출회주식수 ÷ 현재 상장주식수")

st.caption(f"기준: {report_label}" if has_data else "미상환 CB/BW 없음 또는 데이터 없음")

st.markdown("---")

# ─── 섹션 2: 미상환 CB/BW 상세 ───
st.markdown("#### 💰 미상환 CB/BW 상세")
if not has_data:
    if df_debt.empty:
        st.info(f"ℹ️ {report_label}")
    else:
        st.success(f"✅ 미상환 CB/BW 없음 (기준: {report_label})")
        with st.expander("전체 채무증권 발행실적 (참고)"):
            st.dataframe(df_debt, use_container_width=True, hide_index=True)
else:
    # 계산용 컬럼은 숨김
    show_df = df_calc.drop(
        columns=[c for c in df_calc.columns
                 if str(c).startswith("_") and c != "_잠재출회주식수"],
        errors="ignore"
    )
    if "_잠재출회주식수" in show_df.columns:
        show_df = show_df.rename(columns={"_잠재출회주식수": "잠재출회주식수(계산)"})
    st.dataframe(show_df, use_container_width=True, hide_index=True)
    st.caption("'잠재출회주식수(계산)' = 미상환잔액 ÷ 전환(행사)가액 (자체 계산)")

st.markdown("---")

# ─── 섹션 3: 전환청구 일정표 ───
st.markdown("#### 🗓️ 전환청구 가능 일정")
st.caption("발행된 모든 CB/BW의 전환청구 시작일과 D-Day를 한눈에. "
           "🔴 행사중 / 🟡 D-180 임박 / 🟢 대기 / ⚪ 종료")

with st.spinner("전환청구기간 조회 중..."):
    schedule = get_full_conversion_schedule(ticker)

if schedule.empty:
    st.info("ℹ️ 전환청구기간 정보 없음 (발행 공시가 없거나 데이터 누락)")
else:
    # 임박/행사중만 카운트
    n_active = (schedule["상태"] == "🔴 행사중").sum()
    n_imminent = (schedule["상태"] == "🟡 임박").sum()
    n_waiting = (schedule["상태"] == "🟢 대기").sum()
    n_ended = (schedule["상태"] == "⚪ 종료").sum()

    msgs = []
    if n_active > 0:
        msgs.append(f"🔴 행사중 **{n_active}건**")
    if n_imminent > 0:
        msgs.append(f"🟡 D-180 임박 **{n_imminent}건**")
    if n_waiting > 0:
        msgs.append(f"🟢 대기 {n_waiting}건")
    if n_ended > 0:
        msgs.append(f"⚪ 종료 {n_ended}건")

    if n_active > 0:
        st.error(" / ".join(msgs))
    elif n_imminent > 0:
        st.warning(" / ".join(msgs))
    else:
        st.success(" / ".join(msgs) if msgs else "현재 활성 CB/BW 없음")

    st.dataframe(schedule, use_container_width=True, hide_index=True)
    st.caption("💡 D-Day가 음수(=시작일 지남)인 건은 '행사중'으로 표시됩니다. "
               "행사중·임박 건은 단기 매물 출회 가능성이 높으니 주의.")

st.markdown("---")

# ─── 섹션 4: 발행 공시 이력 ───
st.markdown(f"#### 📋 최근 {years_back}년 발행 공시 이력")
with st.spinner("발행 공시 조회 중..."):
    df_disc = fetch_cb_bw_disclosures(ticker, years_back)

if df_disc.empty:
    st.info(f"최근 {years_back}년 내 CB/BW 발행 공시 없음")
else:
    show_cols = []
    for c in ["rcept_dt", "report_nm", "사채종류", "rcept_no"]:
        if c in df_disc.columns:
            show_cols.append(c)
    rename_map = {"rcept_dt": "접수일", "report_nm": "공시명", "rcept_no": "접수번호"}
    df_show = df_disc[show_cols].rename(columns=rename_map)
    st.caption(f"총 **{len(df_disc)}건**")
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    with st.expander("🔗 DART 원문 링크"):
        for _, row in df_disc.iterrows():
            rd = row.get("rcept_dt", "—")
            rn = row.get("report_nm", "—")
            url = row.get("원문URL", "#")
            st.markdown(f"- [{rd}] {rn} → [DART 원문]({url})")

st.markdown("---")
with st.expander("ℹ️ 데이터 정확성 주의"):
    st.markdown(
        "- **발행 공시**: DART 주요사항보고서, 실시간 반영\n"
        "- **미상환 잔액**: 최근 정기보고서 기준, 최대 ~3개월 지연 가능\n"
        "- **잠재 출회주식수**: 보고서 기준일 시점 전환가액으로 계산. "
        "이후 리픽싱은 미반영\n"
        "- **희석률**: 분모는 현재 상장주식수. 우선주·자사주 미차감"
    )
