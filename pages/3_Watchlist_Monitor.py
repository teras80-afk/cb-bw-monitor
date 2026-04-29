"""
페이지 3 — 관심종목 CB/BW 모니터
별도 watchlist (cb_watchlist.txt) 운영
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from lib import (
    require_dart_or_stop, get_ticker_name_map, resolve_ticker,
    github_get_watchlist, github_put_watchlist, parse_watchlist,
    _github_config,
    fetch_debt_securities_latest, filter_cb_bw_outstanding,
    extract_balance_and_price, find_imminent_conversions,
    get_listed_shares,
)

st.set_page_config(page_title="관심종목 모니터", page_icon="📋", layout="wide")
st.title("📋 관심종목 CB/BW 모니터")
st.caption("등록한 관심종목들의 미상환 CB/BW와 전환청구 임박 여부를 한 번에 스캔")

require_dart_or_stop()
name_map = get_ticker_name_map()

st.markdown("---")

# ─── watchlist 로드 ───
if "cb_wl_text" not in st.session_state:
    content, sha = github_get_watchlist()
    st.session_state.cb_wl_text = content or ""
    st.session_state.cb_wl_sha = sha

if not _github_config():
    st.warning("⚠️ GitHub 연동 미설정 — 관심종목을 저장할 수 없습니다. "
               "Streamlit Secrets에 `GITHUB_TOKEN`, `GITHUB_REPO`, "
               "`CB_WATCHLIST_PATH` 설정이 필요합니다.")

# ─── 편집 영역 ───
col_mode, col_reload = st.columns([3, 1])
with col_mode:
    edit_mode = st.toggle("✏️ 편집 모드", value=False)
with col_reload:
    if st.button("🔄 GitHub 새로고침", use_container_width=True):
        content, sha = github_get_watchlist()
        st.session_state.cb_wl_text = content or ""
        st.session_state.cb_wl_sha = sha
        st.success("갱신됨")
        st.rerun()

if edit_mode:
    new_text = st.text_area(
        "관심종목 (1줄에 1종목, 종목명 또는 6자리 코드)",
        value=st.session_state.cb_wl_text,
        height=240,
    )
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 GitHub에 저장", type="primary",
                     use_container_width=True):
            if not _github_config():
                st.error("GitHub 연동 미설정")
            else:
                ok, msg = github_put_watchlist(
                    new_text, st.session_state.cb_wl_sha)
                if ok:
                    st.session_state.cb_wl_text = new_text
                    _, new_sha = github_get_watchlist()
                    st.session_state.cb_wl_sha = new_sha
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
    with col_cancel:
        if st.button("↩️ 변경 취소", use_container_width=True):
            st.rerun()
    st.stop()

# ─── 일괄 스캔 ───
lines = parse_watchlist(st.session_state.cb_wl_text)
if not lines:
    st.info("관심종목이 없습니다. 위 '편집 모드'를 켜고 등록하세요.")
    st.stop()

st.caption(f"등록된 관심종목: **{len(lines)}개**")

if not st.button("🔍 전체 스캔", type="primary"):
    st.stop()

# 스캔 시작
rows = []
prog = st.progress(0, text="스캔 시작...")
for i, line in enumerate(lines):
    prog.progress((i + 1) / len(lines), text=f"조회 중... {line}")
    ticker = resolve_ticker(line, name_map)
    if not ticker:
        rows.append({
            "종목명": line, "코드": "—",
            "미상환잔액(억원)": "—", "잠재주식수": "—",
            "희석률": "—", "D-30 임박": "❓ 매핑실패",
        })
        continue

    nm = name_map.get(ticker, ticker)

    # 미상환 잔액 / 희석률
    try:
        df_debt, _ = fetch_debt_securities_latest(ticker)
        df_outstanding = filter_cb_bw_outstanding(df_debt)
        if df_outstanding.empty:
            balance_eok = 0
            potential = 0
            dilution = 0.0
        else:
            df_calc = extract_balance_and_price(df_outstanding)
            balance_won = (df_calc["_미상환잔액(원)"].sum()
                           if "_미상환잔액(원)" in df_calc.columns else 0)
            potential = (df_calc["_잠재출회주식수"].sum()
                         if "_잠재출회주식수" in df_calc.columns else 0)
            balance_eok = balance_won / 1e8
            shares = get_listed_shares(ticker)
            dilution = (potential / shares * 100
                        if shares > 0 and potential > 0 else 0.0)
    except Exception:
        balance_eok = 0
        potential = 0
        dilution = 0.0

    # D-30 임박
    try:
        imminent = find_imminent_conversions(ticker, days_threshold=30)
    except Exception:
        imminent = []

    if imminent:
        # 가장 가까운 D-Day
        nearest = min(h["D_days"] for h in imminent)
        d30_label = (f"⚠️ {len(imminent)}건 (최근 D-{nearest})"
                     if nearest > 0 else f"🚨 {len(imminent)}건 (D-Day)")
    else:
        d30_label = "✅ 없음"

    rows.append({
        "종목명": nm,
        "코드": ticker,
        "미상환잔액(억원)": (f"{balance_eok:,.1f}"
                            if balance_eok > 0 else "—"),
        "잠재주식수": (f"{potential:,.0f}주" if potential > 0 else "—"),
        "희석률": f"{dilution:.2f}%" if dilution > 0 else "—",
        "D-30 임박": d30_label,
    })
prog.empty()

df_summary = pd.DataFrame(rows)

# 요약 메시지
n_outstanding = sum(1 for r in rows
                    if r["미상환잔액(억원)"] != "—")
n_imminent = sum(1 for r in rows if "건" in r["D-30 임박"])

msg_parts = []
if n_imminent > 0:
    msg_parts.append(f"🚨 D-30 임박 **{n_imminent}건**")
if n_outstanding > 0:
    msg_parts.append(f"💰 미상환 보유 **{n_outstanding}건**")

if msg_parts:
    if n_imminent > 0:
        st.warning(" / ".join(msg_parts))
    else:
        st.info(" / ".join(msg_parts))
else:
    st.success("✅ 모든 관심종목 — 미상환 CB/BW 없음, 임박 건 없음")

st.dataframe(df_summary, use_container_width=True, hide_index=True)
st.caption(f"기준일: {datetime.now():%Y-%m-%d %H:%M} | {len(lines)}개 종목 스캔")
